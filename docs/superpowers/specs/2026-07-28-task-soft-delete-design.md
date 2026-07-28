# 업무(Task) 소프트 삭제 전환 설계

- 작성일: 2026-07-28
- 관련 저장소: `ieum_backend`만 해당 (`ieum_ai`는 영향 없음)
- 관련 기존 기능: [담당업무·담당자 자동 배정 설계](./2026-07-23-petition-task-assignee-routing-design.md), [업무 삭제 시 AI 서버 벡터DB 색인 제거 설계](./2026-07-27-task-category-deindex-design.md)

## 배경 및 목적

현재 `delete_task`(`app/api/routers/task.py:158-179`)는 하드 삭제다: `TASK_ASSIGNEE`를 먼저 지우고 `TASK` row를 지운다.

- `TASK_ASSIGNEE`가 먼저 하드 삭제되므로 "누가 언제 이 업무를 맡았었는지" 배정 이력이 완전히 사라진다.
- `PETITION.task_id`는 `TASK`를 가리키는 nullable FK인데(`app/models/petition.py:12`) `delete_task`가 이 테이블은 건드리지 않는다. 그 업무로 분류된 민원이 하나라도 있으면 FK 제약 때문에 삭제가 실패하거나(제약이 걸려 있는 경우), 제약이 느슨하면 민원들이 죽은 `task_id`를 가리키는 고아 레코드가 된다. 지금까지 다뤄진 적 없는 gap이다.

한편 `PETITION.assignee_user_id`(민원의 실제 담당자)는 `TASK_ASSIGNEE`와 완전히 독립된 컬럼이라는 걸 확인했다 — 접수 시점에 자동배정 로직(`app/api/routers/petition.py:187-206`)이 한 번 값을 채운 뒤로는 `TASK_ASSIGNEE`가 바뀌어도 따라 바뀌지 않는다. 즉 이번 변경(Task 삭제 방식)은 이미 배정된 민원의 담당자 정보에는 애초에 영향을 주지 않는다. 이번 설계가 다루는 건 오직 "Task 자체와 그 배정 이력을 어떻게 보존하느냐"다.

## 결정: 소프트 삭제

`KNOWLEDGE`/`KNOWLEDGE_ATTACHMENT`/`KNOWLEDGE_LOG`가 이미 쓰고 있는 소프트 삭제 컨벤션(`is_deleted BOOLEAN`, `deleted_at DATETIME`, `app/models/knowledge.py:20-21`)을 `TASK`에도 그대로 적용한다. 하드 삭제 + FK `ON DELETE CASCADE/SET NULL` 대신 이 방식을 택한 이유:

- 민원 처리 이력은 감사 목적상 "이 민원이 예전엔 어떤 업무였는지"가 보존돼야 한다. `PETITION.task_id`를 SET NULL 하면 그 정보가 영구히 사라진다.
- 배정 이력(`TASK_ASSIGNEE`)도 지금처럼 즉시 지우지 않고 그대로 둔다 — "누가 이 업무를 맡았었는지" 기록이 남는다.
- 실수로 삭제한 업무를 DB에서 직접 복구할 수 있다.
- 이미 이 저장소에 있는 패턴을 재사용하므로 새 개념을 도입하지 않는다.

## 아키텍처

```
[부장이 프론트에서 업무 삭제]
        │
        │ DELETE /tasks/{taskId}
        ▼
[ieum_backend: delete_task]
  - TASK.is_deleted = True, TASK.deleted_at = now() (UPDATE, 더 이상 DELETE 아님)
  - TASK_ASSIGNEE는 그대로 둠 (배정 이력 보존)
  - commit
        │
        │ DELETE /api/task-category/{department_code}/{task_id} (기존 그대로, 2026-07-27 설계)
        ▼
[ieum_ai] ChromaDB에서 색인 제거 → classify-task 추천 후보에서 빠짐
```

`TASK`를 "활성 업무 목록/자동배정 후보/집계"로 사용하는 모든 조회는 `Task.is_deleted == False` 필터를 추가한다. 반대로 `PETITION`/`KNOWLEDGE`가 Task 이름을 **표시용**으로 outerjoin하는 곳(민원 목록/상세, 지식베이스 목록)은 그대로 둔다 — 삭제된 업무라도 과거 기록에는 이름이 계속 보여야 하기 때문이다.

## 컴포넌트

### 1. 스키마 변경 (`ieum_backend`)

- `TASK` 테이블에 `is_deleted TINYINT(1) NOT NULL DEFAULT 0`, `deleted_at DATETIME NULL` 컬럼 추가.
- 이 저장소는 alembic을 쓰지 않으므로(`KNOWLEDGE`의 동일 컬럼 추가 때도 마찬가지, 커밋 `f367512`) 공유 DB(`192.168.4.122:3306/ggieum`)에 직접 `ALTER TABLE`을 실행해야 한다. 팀이 공유하는 운영 DB이므로 실행 전 사용자 확인을 받는다.
- `app/models/task.py`에 두 컬럼을 추가해 모델과 실제 스키마를 맞춘다.

### 2. `delete_task` 하드 삭제 → 소프트 삭제 (`app/api/routers/task.py`)

- `TASK_ASSIGNEE`를 미리 지우는 줄을 제거한다.
- `db.delete(task)` 대신 `task.is_deleted = True; task.deleted_at = func.now()`로 UPDATE.
- 이미 삭제된(`is_deleted == True`) Task를 다시 삭제하려 하면 404("존재하지 않거나 이미 삭제됨")로 응답 — `KNOWLEDGE`의 `delete_knowledge`와 동일한 멱등 실패 패턴.
- AI 서버 색인 삭제 호출은 기존 그대로 유지(2026-07-27 설계, 변경 없음).

### 3. 활성 업무만 노출하도록 조회 쿼리 필터링

아래 6곳에 `Task.is_deleted == False` 조건을 추가한다:

| 파일:함수 | 용도 |
|---|---|
| `task.py:get_my_tasks` | 내 담당 업무 목록 |
| `task.py:get_department_tasks` | 부서 업무 목록(부서관리 페이지) |
| `task.py:add_assignee` | 삭제된 업무에 새 담당자 배정하는 것 방지 |
| `dashboard.py:get_tasks_summary` | 업무 현황 집계(전체/미배정 업무 수, 미배정 인원 수) |
| `admin.py` (담당 Task 정보, 150번째 줄 부근) | 직원 관리 페이지의 "담당 업무" 표시 |
| `petition.py:create_external_petition` (183번째 줄) | AI가 추천한 task_id가 삭제된 업무면 미배정으로 접수 |
| `petition.py:get_petitions` `scope=TASK` (275번째 줄 부근) | "내 담당업무 전체보기"에서 삭제된 업무 제외 |

### 4. 건드리지 않는 곳

- `petition.py`의 `get_petitions`/`get_petition_detail`/`answer_petition`이 `Task.name`을 표시용으로 outerjoin하는 부분, `knowledge.py`의 목록 조회 — 삭제된 업무라도 과거 기록의 이름은 계속 보여야 한다.
- `PETITION.assignee_user_id` 관련 로직(담당자 재배정 등) — `TASK_ASSIGNEE`와 무관하게 이미 독립적으로 동작하므로 이번 변경과 무관.

## 에러 처리

| 상황 | 처리 |
|---|---|
| 이미 삭제된 Task를 다시 삭제 요청 | 404 "존재하지 않거나 이미 삭제됨" |
| 삭제된 Task에 담당자 지정 시도 | 404 (활성 Task 취급 안 함) |
| AI가 추천한 task_id가 삭제된 업무 | 기존 "존재하지 않는 task_id" 처리 경로 그대로 재사용, 미배정으로 접수 |
| ALTER TABLE 실행 중 실패 | 코드 변경 전에 스키마부터 적용하므로, 실패 시 이후 태스크(모델/라우터 수정)를 진행하지 않고 원인 파악 |

## 테스트

이 저장소는 자동 테스트가 없는 관례를 유지 — curl/DB 조회로 수동 검증한다: 업무 생성 → 삭제 → DB에서 `is_deleted=1`이고 row가 남아있는지 확인 → 그 업무가 목록/집계/자동배정 후보에서 빠지는지 확인 → 그 업무에 이미 배정돼 있던 민원(`PETITION.task_id`)과 담당자(`TASK_ASSIGNEE`)는 그대로 남아있는지 확인.

## 범위 밖

- 삭제된 업무를 다시 복구(un-delete)하는 API — 필요해지면 별도 설계.
- 민원을 한 업무에서 다른 업무로 일괄 이관하는 기능 — 현재 요구사항에 없음.
