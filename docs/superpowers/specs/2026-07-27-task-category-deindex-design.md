# 업무(Task) 삭제 시 AI 서버 벡터DB 색인 제거 설계

- 작성일: 2026-07-27
- 관련 저장소: `ieum_ai`(삭제 엔드포인트 신규), `ieum_backend`(`delete_task` 연결)
- 관련 기존 기능: [담당업무·담당자 자동 배정 설계](./2026-07-23-petition-task-assignee-routing-design.md) — 그 문서의 "범위 밖" 항목("delete_task 시 ieum_ai 벡터DB에서 색인 제거")을 이번에 해소한다.

## 배경 및 목적

부서장이 `DELETE /tasks/{taskId}`로 업무를 삭제하면 `ieum_backend`의 `TASK`/`TASK_ASSIGNEE` 테이블에서는 지워지지만, `ieum_ai`의 ChromaDB `task_categories` 컬렉션에는 그 업무의 색인이 그대로 남는다. 그 결과 `POST /api/classify-task`가 이미 삭제된 업무를 계속 추천할 수 있다 — 이번 세션 초반에 실제로 겪었던 "스테일 벡터 데이터" 문제와 같은 유형이 재발할 수 있는 구조다.

민원(Petition)은 삭제 기능 자체가 프론트/백엔드 어디에도 없음을 확인했다 — 이번 작업은 **업무(Task)에만 해당**한다.

## 아키텍처

```
[부장이 프론트에서 업무 삭제]
        │
        │ DELETE /tasks/{taskId} (기존)
        ▼
[ieum_backend: delete_task] TASK_ASSIGNEE 삭제 → Task 삭제 → commit (기존 로직 그대로)
        │
        │ (신규) DELETE /api/task-category/{department_code}/{task_id}
        ▼
[ieum_ai: 신규 엔드포인트] ChromaDB(task_categories 컬렉션)에서 해당 업무 색인 제거
```

`create_task` → `index-task-category` 연결(2026-07-23 완료)과 정확히 대칭되는 반대 방향 작업이다.

## 컴포넌트

### 1. `ieum_ai` — `DELETE /api/task-category/{department_code}/{task_id}` (신규)

- `app/vectorstore/chroma_client.py`에 `remove_task_category(task_id: int, department_code: str) -> None` 추가 — `add_task_category`와 동일한 ID 규칙(`f"{department_code}_{task_id}"`)으로 `collection.delete(ids=[...])` 호출.
- `app/api/routes.py`에 엔드포인트 추가: 기존 `_validate_lead_department_code`로 `department_code` 검증 후 `remove_task_category` 호출.
- ChromaDB의 `delete(ids=...)`는 존재하지 않는 id를 지워도 에러를 던지지 않는다(멱등) — 이미 삭제됐거나 애초에 색인 안 된 업무를 지우려 해도 안전하다.

### 2. `ieum_backend` — `delete_task` 수정 (`app/api/routers/task.py`)

- 기존 로직(`TASK_ASSIGNEE` 삭제 → `Task` 삭제 → `db.commit()`)은 그대로 둔다.
- `db.delete(task)` 전에 `task_id`/`department_code`를 지역 변수로 저장해둔다 — 삭제된 SQLAlchemy 객체는 커밋 후 속성 접근이 불안정하기 때문.
- `db.commit()` **이후에** `ieum_ai`의 새 삭제 엔드포인트를 호출한다. 실패해도 로그만 남기고 응답은 그대로 200 — Task 삭제 자체는 이미 완료된 뒤라 실패가 사용자에게 영향을 주지 않는다 (`create_task`의 색인 실패 처리와 동일한 패턴).

## 에러 처리

| 상황 | 처리 |
|---|---|
| `ieum_ai` 삭제 엔드포인트 호출 실패(다운/타임아웃) | 로그만 남기고 무시 — Task 삭제는 이미 완료된 상태라 사용자 응답에 영향 없음 |
| 애초에 색인 안 됐던 업무를 삭제 | ChromaDB `delete`가 멱등이라 에러 없이 조용히 통과 |
| `department_code`가 01~08이 아님 | `ieum_ai`가 기존 검증 로직으로 400 반환 (백엔드는 이 실패도 무시하고 진행) |

## 테스트

- `ieum_ai`: 신규 `remove_task_category` 함수를 이 저장소 기존 관례(plain script, `python tests/test_xxx.py`)로 단위 테스트. 색인 후 삭제하면 `classify-task` 검색 결과에서 사라지는지까지 라이브 서버로 확인.
- `ieum_backend`: 테스트 파일 없는 관례 유지, curl/DB 조회로 수동 검증 — 업무 생성 → 색인 확인 → 삭제 → `ieum_ai`에서 색인이 사라졌는지 재확인.

## 범위 밖

- 민원(Petition) 삭제 관련 색인 정리 — 애초에 민원 삭제 기능이 없어 해당 없음
- 업무 수정(이름 변경 등) 시 색인 갱신 — 이번 요청 범위 밖, 필요해지면 별도 설계
