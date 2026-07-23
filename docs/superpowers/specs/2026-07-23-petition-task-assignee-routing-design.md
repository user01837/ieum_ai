# 민원 접수 시 담당업무·담당자 자동 배정 설계

- 작성일: 2026-07-23
- 관련 저장소: `ieum_backend`만 (이번 설계는 `ieum_ai` 변경 없음 — 필요한 엔드포인트가 이미 다 있음)
- 관련 기존 기능: [외부 민원 접수 API 설계](./2026-07-22-external-petition-intake-design.md), `ieum_ai`의 `/api/classify-task`·`/api/index-task-category`(둘 다 기존, 이번 세션 이전부터 존재)

## 배경 및 목적

`POST /petitions/external`(2026-07-22 구현)은 지금 `department_code`만 자동 분류하고, `task_id`/`assignee_user_id`는 항상 `NULL`로 접수된다. 담당자가 부서 큐에서 수동으로 집어가야 하는 구조. 이 문서는 민원 제목/내용을 바탕으로 **부서 내 세부업무(task)까지 자동 분류하고, 그 업무의 여러 담당자 중 한 명에게 직접 배정**하는 기능을 다룬다.

## 실사용 DB 조사 결과 (중요한 제약)

공유 개발 DB(`192.168.4.122`)를 직접 조회해서 확인함:

| 항목 | 교통부(01) | 나머지 7개 부서 |
|---|---|---|
| `TASK` 행 수 | 5건 | **0건** |
| `USER`(직원) 수 | 14명 | **0명** (02만 2명) |

즉 **교통부(01) 외 부서는 세부업무도 직원도 아예 없어서, 이 기능이 실질적으로 동작하는 건 교통부뿐이다.** 다른 6개 부서에 가짜 직원/업무 데이터를 채우는 건 팀 공유 DB에 영향을 주는 별도의 큰 결정이라 이번 범위에서 하지 않는다 (아래 "범위 밖" 참고).

## 아키텍처

```
[부장이 프론트에서 새 task 생성]
        │
        │ POST /tasks (기존, TaskCreateRequest{name})
        ▼
[ieum_backend: create_task] Task INSERT
        │
        │ (신규) POST /api/index-task-category { task_id(실제 DB PK), name, department_code, description=name }
        ▼
[ieum_ai: 기존 엔드포인트] ChromaDB(task_categories 컬렉션)에 색인
        │
        ▼
=====================================================================
[POST /petitions/external] (기존 기능 확장)
        │
        │ (기존) POST /api/classify-department { title, content } → department_code
        │ (신규) POST /api/classify-task { complaint_text, department_code } → task_id (매칭 없으면 null)
        │ (신규, ieum_backend 자체 로직) task_id의 TASK_ASSIGNEE 목록 조회
        │   → 그중 미완료(status_code != '03') 민원이 가장 적은 사람 선택 (담당자 0명이면 null)
        ▼
[PETITION INSERT] department_code + task_id + assignee_user_id 모두 채워서 저장
```

## 동작 원칙 (모두 "실패해도 접수는 막지 않는다"는 기존 철학 유지)

1. **부서를 하드코딩으로 분기하지 않는다.** `classify-task`가 데이터 없는 부서에서는 자연스럽게 `task_id: null`을 반환하므로, 그러면 `assignee_user_id`도 자동으로 `null`이 되어 지금과 동일하게 부서 큐에만 들어간다. 나중에 다른 부서 데이터가 채워지면 코드 수정 없이 그대로 확장된다.
2. **`classify-task` 호출이 실패해도(AI 다운 등) 민원 접수는 그대로 진행**된다 — `task_id`/`assignee_user_id`만 `null`로 남는다.
3. **담당자가 0명인 업무**(예: `task_id=16` "함정" — 현재 `TASK_ASSIGNEE`에 배정된 사람 없음)를 매칭한 경우: `task_id`는 채우고 `assignee_user_id`만 `null`로 둔다 — 담당자 직접 배정은 안 되지만 최소한 어떤 업무인지는 표시된다.
4. **담당자가 여러 명이면 미완료(`status_code != '03'`) 민원을 가장 적게 맡고 있는 사람**에게 배정한다 (동률이면 조회 순서상 먼저 나온 사람, 별도 로직 없음).

## 컴포넌트

### 1. `POST /petitions/external` 확장 (`app/api/routers/petition.py`)

기존 흐름(`department_code` 분류) 뒤에 이어서:

- `httpx.post`로 `ieum_ai`의 `/api/classify-task`를 `{"complaint_text": f"{title}\n{content}", "department_code": department_code}`로 호출 (기존 `classify-department`와 같은 60초 타임아웃, 같은 try/except 패턴 — 실패 시 `task_id=None`으로 폴백)
- 응답의 `task_id`가 `null`이 아니면, `TASK_ASSIGNEE`를 `task_id`로 조회해서 후보 `user_id` 목록을 가져온 뒤, 각 후보의 `PETITION.assignee_user_id == user_id AND status_code != '03'` 개수를 세어 가장 적은 사람을 선택
- 후보가 0명이면 `assignee_user_id = None`
- `Petition` 생성 시 `task_id`, `assignee_user_id`도 함께 채워서 저장

### 2. `create_task` 수정 (`app/api/routers/task.py:110`)

Task INSERT/commit 성공 후:

- `httpx.post`로 `ieum_ai`의 `/api/index-task-category`를 `{"task_id": task.task_id, "name": task.name, "department_code": target_dept, "description": task.name}`로 호출
- 색인 호출이 실패해도 task 생성 자체(이미 커밋됨)는 그대로 유지 — 실패는 로그만 남김 (기존 `_call_ai_to_index_petition` 패턴과 동일)
- `description`은 일단 `name`과 동일한 값을 보낸다. 프론트에 별도 설명 입력 필드를 추가하는 건 이번 범위 밖 — 추후 팀 논의 후 개선

## 에러 처리

| 상황 | 처리 |
|---|---|
| `classify-task` 호출 실패 | `task_id=None`, `assignee_user_id=None`으로 접수 진행 (기존과 동일한 미배정 상태) |
| `classify-task`가 매칭 없음(`task_id: null`) 반환 | 위와 동일 |
| 매칭된 task에 담당자 0명 | `task_id`는 채우고 `assignee_user_id=None` |
| `index-task-category` 호출 실패 (task 생성 시) | task 생성은 그대로 유지, 색인만 실패 (로그만 남김, 사용자에게 에러 노출 안 함) |

## 테스트

이 저장소(`ieum_backend`)는 테스트 파일이 없는 관례를 유지 — curl/Swagger로 수동 검증:

1. 교통 관련 제목/내용으로 `/petitions/external` 호출 → 응답 또는 DB 조회로 `task_id`, `assignee_user_id`가 채워지는지 확인
2. 같은 task에 여러 번 접수해서, 매번 다른(또는 가장 미완료 민원이 적은) 담당자로 배정되는지 확인 — 미완료 민원 수를 수동으로 계산해서 대조
3. `/tasks`로 새 task 생성 후, `ieum_ai`의 `/api/classify-task`를 직접 호출해서 방금 만든 task가 검색되는지 확인 (색인 연동 검증)
4. 무관한 내용(어느 부서에도 안 맞는 텍스트)으로 접수해서 `task_id`/`assignee_user_id`가 `null`로 남는지 확인

## 범위 밖 (이번 설계에 포함하지 않음)

- 직원이 0명인 6개 부서(주택·건축 제외 나머지)용 가짜 직원/업무 데이터 생성 — 팀 공유 DB에 영향 주는 별도 결정 필요
- `create_task`의 `description` 입력을 위한 프론트엔드 변경 — 팀원들과 논의 후 별도 진행
- `delete_task` 시 `ieum_ai` 벡터DB에서 색인 제거 — `ieum_ai`에 삭제 API 자체가 없음(기존 제약), 삭제된 task가 `classify-task` 추천에 계속 나올 수 있는 한계를 그대로 인지하고 넘어감
- 담당자 배정 알림(메일/푸시 등) — 애초에 이 시스템에 알림 기능 자체가 없음
