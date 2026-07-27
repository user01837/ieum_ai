# 업무(Task) 삭제 시 AI 벡터DB 색인 제거 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 업무(task)가 삭제될 때 `ieum_ai`의 ChromaDB 색인도 함께 제거되도록 해서, 이미 삭제된 업무가 `classify-task` 추천에 계속 남는 문제를 없앤다.

**Architecture:** `ieum_ai`에 `DELETE /api/task-category/{department_code}/{task_id}`를 신규 추가하고, `ieum_backend`의 `delete_task`가 DB 삭제를 커밋한 뒤 이 엔드포인트를 호출한다. `create_task` → `index-task-category` 연결과 대칭되는 구조.

**Tech Stack:** FastAPI, ChromaDB(`collection.delete`), httpx(동기, 기존 파일 관례).

## Global Constraints

- `ieum_ai` 테스트는 이 저장소의 기존 관례대로 plain script 스타일(`assert` + `print("[통과] ...")`, `python tests/xxx.py`로 직접 실행)로 작성한다.
- `ieum_backend`에는 테스트 파일이 없다 - curl/DB 조회로 수동 검증한다.
- `ieum_backend`가 `ieum_ai`를 호출할 때 실패해도 절대 원래 동작(Task 삭제)을 막지 않는다 - Task는 이미 DB에서 삭제·커밋된 뒤에 호출하므로, 실패해도 로그만 남기고 응답은 그대로 진행한다.
- 이 저장소의 기존 라우트 핸들러는 전부 동기 `def` + 동기 `httpx`(`AsyncClient` 아님) - `ieum_backend` 쪽 새 호출도 이 관례를 따른다.
- ChromaDB의 `collection.delete(ids=[...])`는 존재하지 않는 id를 지워도 예외를 던지지 않는다(멱등) - 이 특성에 의존해도 된다.
- ID 규칙은 기존 `add_task_category`와 동일하게 `f"{department_code}_{task_id}"`를 그대로 사용한다.

---

### Task 1: `DELETE /api/task-category/{department_code}/{task_id}` 엔드포인트 (`ieum_ai`)

**Files:**
- Modify: `app/vectorstore/chroma_client.py` (189행 `add_task_category` 함수 바로 다음에 `remove_task_category` 추가)
- Modify: `app/api/routes.py:7`(import에 `remove_task_category` 추가), `app/api/routes.py:230` 이후(신규 엔드포인트 추가)
- Test: `tests/test_task_category_deindex.py` (신규, 라이브 서버 대상)

**Interfaces:**
- Produces: `remove_task_category(task_id: int, department_code: str) -> None` (순수 함수형 부수효과, ChromaDB 조작) — Task 2는 이 함수를 직접 쓰지 않고 HTTP로 이 태스크가 만드는 엔드포인트를 호출한다.
- Produces: `DELETE /api/task-category/{department_code}/{task_id}` — Response `{"status": "deleted", "task_id": int, "department_code": str}`. Task 2(다른 저장소 `ieum_backend`)가 HTTP로 이 계약을 소비한다.

- [ ] **Step 1: `remove_task_category` 함수 추가**

`app/vectorstore/chroma_client.py`에서 `add_task_category` 함수(189~202행 부근, `documents=[description],` 다음에 닫는 괄호와 함수가 끝나는 지점)를 찾아, 그 함수가 끝난 직후에 추가:

```python
def remove_task_category(task_id: int, department_code: str) -> None:
    """부서 내 세부업무(TASK) 1건을 ChromaDB(task_categories 컬렉션)에서 삭제.
    add_task_category와 동일한 id 규칙('{department_code}_{task_id}')을 사용한다.
    존재하지 않는 id를 지워도 ChromaDB는 예외를 던지지 않는다(멱등)."""
    collection = get_task_category_collection()
    collection.delete(ids=[f"{department_code}_{task_id}"])
```

- [ ] **Step 2: import 및 엔드포인트 추가**

`app/api/routes.py:7`을 아래로 교체:

```python
from app.vectorstore.chroma_client import search_similar_complaints, add_complaint, search_matching_task_category, add_task_category, remove_task_category
```

`app/api/routes.py`에서 `index_task_category` 함수(219~230행)가 끝나는 지점(`return {"status": "indexed", ...}` 다음) 바로 뒤, `@router.post("/similar-tasks")`(233행) 이전에 추가:

```python
@router.delete("/task-category/{department_code}/{task_id}")
async def delete_task_category(department_code: str, task_id: int):
    """
    세부업무(TASK) 삭제 시 ChromaDB 색인도 함께 제거.
    ieum_backend가 delete_task 처리(DB 삭제 커밋) 이후에 이 엔드포인트를 호출하는 것을
    전제로 함. 색인이 없던 task_id를 지워도 에러 없이 통과한다.
    """
    _validate_lead_department_code(department_code)
    remove_task_category(task_id, department_code)
    return {"status": "deleted", "task_id": task_id, "department_code": department_code}
```

- [ ] **Step 3: 단위 테스트 작성**

`tests/test_task_category_deindex.py` 생성:

```python
# -*- coding: utf-8 -*-
"""
/api/task-category 삭제 엔드포인트 동작 확인 스크립트.

사전 조건:
    1) FastAPI 서버 실행 중: uvicorn app.main:app --reload --port 8100

실행: python tests/test_task_category_deindex.py
"""
import requests

BASE_URL = "http://localhost:8100"
TEST_TASK_ID = 88888
TEST_DEPARTMENT = "01"

print("=" * 70)
print("[준비] 테스트용 업무 색인")
print("-" * 70)
res = requests.post(f"{BASE_URL}/api/index-task-category", json={
    "task_id": TEST_TASK_ID,
    "name": "삭제테스트용업무",
    "department_code": TEST_DEPARTMENT,
    "description": "삭제테스트용업무",
}, timeout=30.0)
res.raise_for_status()
print("색인 완료:", res.json())

print("\n" + "=" * 70)
print("[테스트 1] classify-task로 방금 색인한 업무가 검색되는지 확인")
print("-" * 70)
res = requests.post(f"{BASE_URL}/api/classify-task", json={
    "complaint_text": "삭제테스트용업무 관련 민원입니다",
    "department_code": TEST_DEPARTMENT,
}, timeout=30.0)
res.raise_for_status()
body = res.json()
print("classify-task 응답:", body)
assert body["task_id"] == TEST_TASK_ID, f"방금 색인한 업무가 top1으로 안 나옴: {body}"
print("[통과] 색인 직후 classify-task에서 검색됨")

print("\n" + "=" * 70)
print("[테스트 2] 삭제 엔드포인트 호출")
print("-" * 70)
res = requests.delete(f"{BASE_URL}/api/task-category/{TEST_DEPARTMENT}/{TEST_TASK_ID}", timeout=10.0)
res.raise_for_status()
body = res.json()
print("삭제 응답:", body)
assert body == {"status": "deleted", "task_id": TEST_TASK_ID, "department_code": TEST_DEPARTMENT}, body
print("[통과] 삭제 엔드포인트가 200과 함께 예상된 응답 반환")

print("\n" + "=" * 70)
print("[테스트 3] 삭제 후 classify-task에서 더 이상 top1으로 안 나오는지 확인")
print("-" * 70)
res = requests.post(f"{BASE_URL}/api/classify-task", json={
    "complaint_text": "삭제테스트용업무 관련 민원입니다",
    "department_code": TEST_DEPARTMENT,
}, timeout=30.0)
res.raise_for_status()
body = res.json()
print("classify-task 응답:", body)
assert body["task_id"] != TEST_TASK_ID, f"삭제했는데 여전히 top1으로 나옴: {body}"
print("[통과] 삭제 후에는 더 이상 검색되지 않음")

print("\n" + "=" * 70)
print("[테스트 4] 존재하지 않는 id를 다시 삭제해도 에러 안 나는지 확인(멱등)")
print("-" * 70)
res = requests.delete(f"{BASE_URL}/api/task-category/{TEST_DEPARTMENT}/{TEST_TASK_ID}", timeout=10.0)
res.raise_for_status()
print("[통과] 이미 삭제된 id를 다시 삭제해도 200 반환:", res.json())

print("\n모든 테스트 통과")
```

- [ ] **Step 4: 서버 기동 후 테스트 실행**

Run:
```bash
"C:\Users\kmj24\anaconda3\envs\ieum_ai\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8100 &
sleep 5
"C:\Users\kmj24\anaconda3\envs\ieum_ai\python.exe" tests/test_task_category_deindex.py
```
Expected: `모든 테스트 통과` 출력. (`ieum_ai` 전용 conda 가상환경의 python으로 실행 — 전역 Python 아님)

- [ ] **Step 5: 커밋**

```bash
git add app/vectorstore/chroma_client.py app/api/routes.py tests/test_task_category_deindex.py
git commit -m "feat: 업무 삭제 시 AI 벡터DB 색인 제거 엔드포인트 추가"
```

---

### Task 2: `delete_task`가 `ieum_ai`의 삭제 엔드포인트를 호출하도록 연결 (`ieum_backend`)

**Files:**
- Modify: `app/api/routers/task.py:158-169` (`delete_task` 함수)

**Interfaces:**
- Consumes: `DELETE http://<AI_SERVER>/api/task-category/{department_code}/{task_id}` (Task 1, HTTP 계약)

- [ ] **Step 1: `delete_task`에 삭제 호출 추가**

`app/api/routers/task.py`에서 아래 함수(현재 158~169행)를 찾는다:

```python
def delete_task(
    taskId: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    task = db.query(Task).filter(Task.task_id == taskId).first()
    if not task:
        raise HTTPException(status_code=404, detail="존재하지 않는 Task입니다.")

    db.query(TaskAssignee).filter(TaskAssignee.task_id == taskId).delete(synchronize_session=False)
    db.delete(task)
    db.commit()
```

아래로 교체:

```python
def delete_task(
    taskId: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    task = db.query(Task).filter(Task.task_id == taskId).first()
    if not task:
        raise HTTPException(status_code=404, detail="존재하지 않는 Task입니다.")

    deleted_task_id = task.task_id
    deleted_department_code = task.department_code

    db.query(TaskAssignee).filter(TaskAssignee.task_id == taskId).delete(synchronize_session=False)
    db.delete(task)
    db.commit()

    try:
        deindex_url = f"{settings.AI_SERVER.rstrip('/')}/api/task-category/{deleted_department_code}/{deleted_task_id}"
        response = httpx.delete(deindex_url, timeout=30.0)
        response.raise_for_status()
    except Exception as e:
        print(f"WARN: task 색인 삭제 실패(task_id={deleted_task_id}): {e}")
```

(`httpx`와 `settings`는 이미 이 파일 상단에 import되어 있다 — Task 1 계획(2026-07-23, `create_task` 색인 연결)에서 추가됨. 새 import 불필요.)

- [ ] **Step 2: 문법 확인**

Run: `"C:\Users\kmj24\anaconda3\envs\ieum_backend\python.exe" -c "import ast; ast.parse(open('app/api/routers/task.py', encoding='utf-8').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 3: 서버 기동 후 curl로 수동 검증**

`ieum_ai`(8100)와 `ieum_backend`(8000)가 각자의 conda 환경으로 떠 있는지 확인 후, 실제 로그인 토큰으로:

```bash
# 1. 테스트용 업무 생성
curl -s -X POST "http://localhost:8000/tasks?department_code=01" \
  -H "Authorization: Bearer <토큰>" -H "Content-Type: application/json" \
  -d '{"name":"삭제연동테스트업무"}'
# 응답의 taskId를 기록해둔다 (예: 999)

# 2. ieum_ai에서 색인됐는지 확인
curl -s -X POST http://localhost:8100/api/classify-task \
  -H "Content-Type: application/json" \
  -d '{"complaint_text":"삭제연동테스트업무 관련 민원","department_code":"01"}'
# task_id가 방금 만든 값과 일치하는지 확인

# 3. 업무 삭제
curl -s -X DELETE "http://localhost:8000/tasks/999" -H "Authorization: Bearer <토큰>"

# 4. ieum_ai에서 색인이 사라졌는지 재확인
curl -s -X POST http://localhost:8100/api/classify-task \
  -H "Content-Type: application/json" \
  -d '{"complaint_text":"삭제연동테스트업무 관련 민원","department_code":"01"}'
# task_id가 더 이상 999가 아니어야 함(또는 이 텍스트와 안 맞는 다른 값)
```

Expected: 2번에서 새로 만든 task_id가 나오고, 4번에서는 더 이상 그 task_id가 안 나옴.

- [ ] **Step 4: 커밋**

```bash
git add app/api/routers/task.py
git commit -m "feat: 업무 삭제 시 AI 서버 색인도 함께 제거"
```

---

## Self-Review 결과

- **스펙 커버리지:** 아키텍처의 두 구성요소(ieum_ai 삭제 엔드포인트, ieum_backend delete_task 연결) 모두 태스크로 매핑됨. 에러 처리 표의 3개 케이스(호출 실패 무시, 멱등 삭제, 부서코드 검증) 모두 코드에 반영되고 Task 1의 테스트 케이스 4에서 멱등성 검증됨. "범위 밖"(민원 삭제, 업무 수정 시 색인 갱신)은 태스크로 만들지 않음.
- **플레이스홀더 스캔:** 없음 — 모든 스텝에 실행 가능한 코드/명령 포함.
- **타입/시그니처 일관성:** `remove_task_category(task_id: int, department_code: str) -> None`이 Task 1 안에서 함수 정의와 사용처(엔드포인트)에서 동일하게 쓰임. `DELETE /api/task-category/{department_code}/{task_id}`의 경로 파라미터 순서·타입이 Task 1의 엔드포인트 정의와 Task 2의 호출 URL 구성에서 정확히 일치(`{department_code}/{task_id}` 순서 고정).
