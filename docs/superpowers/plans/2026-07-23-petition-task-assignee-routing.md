# 민원 접수 시 담당업무·담당자 자동 배정 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `POST /petitions/external`이 부서뿐 아니라 담당업무(task)·담당자까지 자동 분류/배정하게 하고, 새로 만든 task가 그 분류 대상에서 누락되지 않도록 `create_task`가 `ieum_ai`에 색인하게 만든다.

**Architecture:** 둘 다 `ieum_backend` 저장소 안에서만 이루어진다. `ieum_ai`는 이미 필요한 엔드포인트(`/api/classify-task`, `/api/index-task-category`)를 다 갖고 있으므로 변경 없음. `petition.py`의 `create_external_petition`에 `classify-task` 호출 + 담당자 선정 로직을 추가하고, `task.py`의 `create_task`에 색인 호출을 추가한다.

**Tech Stack:** FastAPI, httpx(동기, 기존 파일들과 동일 관례), SQLAlchemy.

## Global Constraints

- `ieum_backend`에는 테스트 파일이 없다 - 새 테스트 프레임워크를 도입하지 않고 curl/DB 조회로 수동 검증한다.
- 이 저장소의 기존 라우트 핸들러는 전부 동기 `def` + 동기 `httpx.post`(`AsyncClient` 아님) - 새로 추가하는 호출도 이 관례를 따른다.
- `ieum_ai` 호출 실패는 절대 원래 동작(민원 접수, task 생성)을 막지 않는다 - 실패하면 로그만 남기고 값은 `None`/생략 상태로 진행한다.
- `classify-task` 호출 타임아웃은 `classify-department`와 동일하게 **60초**로 잡는다.
- 담당자가 여러 명인 task는 **미완료(`status_code != '03'`) 민원이 가장 적은 사람**에게 배정한다. 후보가 0명이면 `assignee_user_id`는 `None`.
- `department_code` 자동분류(기존 로직)는 이번 변경으로 건드리지 않는다 - 그 뒤에 이어서 task 분류만 추가한다.

---

### Task 1: `create_task`가 `ieum_ai`에 새 task를 색인하도록 수정

**Files:**
- Modify: `app/api/routers/task.py:1-10`(import 추가), `app/api/routers/task.py:110-131`(`create_task` 함수)

**Interfaces:**
- 없음 (다른 태스크와 독립적 - Task 2와 파일도 다르고 서로 참조하지 않음)

- [ ] **Step 1: import 추가**

`app/api/routers/task.py`의 최상단 import 블록(1~10행)을 아래로 교체:

```python
from fastapi import APIRouter, Depends, status, HTTPException, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional
import httpx

from app.db.session import get_db
from app.models.user import User
from app.models.task import Task
from app.api.routers.auth import get_current_user
from app.models.task_assignee import TaskAssignee
from app.core.config import settings
```

- [ ] **Step 2: `create_task`에 색인 호출 추가**

`app/api/routers/task.py`의 `create_task` 함수(현재 아래와 같은 형태)를 찾는다:

```python
def create_task(
    body: TaskCreateRequest,
    department_code: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    is_admin = current_user.system_role_code == "02"

    if is_admin and department_code:
        target_dept = department_code
    else:
        target_dept = current_user.department_code

    task = Task(
        name=body.name,
        department_code=target_dept,
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    return TaskCreateResponse(taskId=task.task_id, name=task.name)
```

`db.refresh(task)` 다음 줄, `return` 이전에 아래 블록을 추가:

```python
    try:
        index_url = f"{settings.AI_SERVER.rstrip('/')}/api/index-task-category"
        response = httpx.post(
            index_url,
            json={
                "task_id": task.task_id,
                "name": task.name,
                "department_code": target_dept,
                "description": task.name,
            },
            timeout=30.0,
        )
        response.raise_for_status()
    except Exception as e:
        print(f"WARN: task 색인 실패(task_id={task.task_id}): {e}")
```

(즉 함수 마지막 형태는 `db.refresh(task)` → 새 `try/except` 블록 → `return TaskCreateResponse(...)` 순서가 된다.)

- [ ] **Step 3: 문법 확인**

Run: `python -c "import ast; ast.parse(open('app/api/routers/task.py', encoding='utf-8').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 4: 실제 서버로 검증**

`ieum_ai`(8100번 포트, Ollama 포함)와 `ieum_backend`(8000번 포트)가 떠 있는지 확인 후, 실제 로그인 토큰으로 새 task를 하나 만들고, `ieum_ai`의 `/api/classify-task`로 그 task가 검색되는지 확인한다:

```bash
curl -s -m 5 http://localhost:8100/docs -o /dev/null -w "ieum_ai: %{http_code}\n"
```

`POST /tasks?department_code=01` (관리자 토큰, body `{"name": "테스트업무_고유이름"}`)로 task 생성 후, 반환된 `taskId`를 아래로 확인:

```bash
curl -s -X POST http://localhost:8100/api/classify-task \
  -H "Content-Type: application/json" \
  -d '{"complaint_text": "테스트업무_고유이름 관련 민원입니다", "department_code": "01"}'
```

Expected: 응답의 `task_id`가 방금 만든 task의 `taskId`와 일치 (또는 최소한 다른 후보들보다 유사도가 높게 나오는지 육안 확인 - 정확히 그 task_id가 top1이 안 나올 수도 있으므로, 최소 기준은 "에러 없이 응답이 오고 색인이 실제로 들어갔다"는 것).

- [ ] **Step 5: 커밋**

```bash
git add app/api/routers/task.py
git commit -m "feat: 새 task 생성 시 ieum_ai에 자동 색인"
```

---

### Task 2: `POST /petitions/external`에 담당업무·담당자 자동 배정 추가

**Files:**
- Modify: `app/api/routers/petition.py:4`(import에 `func` 추가), `app/api/routers/petition.py:163-175`(`create_external_petition`의 department_code 확정 이후 ~ Petition 생성 부분)

**Interfaces:**
- 없음 (Task 1과 독립 - 다른 파일, 다른 함수)

- [ ] **Step 1: import에 `func` 추가**

`app/api/routers/petition.py:4`를 아래로 교체:

```python
from sqlalchemy import or_, case, func
```

- [ ] **Step 2: 담당업무·담당자 분류 로직 추가**

`app/api/routers/petition.py`에서 아래 블록(현재 163~175행)을 찾는다:

```python
    if department_code not in VALID_DEPARTMENT_CODES:
        print(f"WARN: ieum_ai가 유효하지 않은 department_code를 반환함({department_code!r}), 기본 부서(08)로 접수")
        department_code = "08"

    petition = Petition(
        title=req.title,
        content=req.content,
        department_code=department_code,
        status_code="01",
        received_at=datetime.now(),
    )
    db.add(petition)
    db.commit()
```

아래 내용으로 교체 (department_code 검증 블록과 `db.commit()` 사이에 task/담당자 로직 삽입 + `Petition(...)`에 `task_id`/`assignee_user_id` 추가):

```python
    if department_code not in VALID_DEPARTMENT_CODES:
        print(f"WARN: ieum_ai가 유효하지 않은 department_code를 반환함({department_code!r}), 기본 부서(08)로 접수")
        department_code = "08"

    task_id = None
    try:
        classify_task_url = f"{settings.AI_SERVER.rstrip('/')}/api/classify-task"
        task_response = httpx.post(
            classify_task_url,
            json={
                "complaint_text": f"{req.title}\n{req.content}",
                "department_code": department_code,
            },
            timeout=60.0,
        )
        task_response.raise_for_status()
        task_id = task_response.json().get("task_id")
    except Exception as e:
        print(f"WARN: 담당업무 자동분류 실패, 미배정으로 접수: {e}")

    assignee_user_id = None
    if task_id is not None:
        candidate_ids = [
            row.user_id for row in
            db.query(TaskAssignee.user_id).filter(TaskAssignee.task_id == task_id).all()
        ]
        if candidate_ids:
            open_counts = {uid: 0 for uid in candidate_ids}
            counted = (
                db.query(Petition.assignee_user_id, func.count(Petition.petition_id))
                .filter(
                    Petition.assignee_user_id.in_(candidate_ids),
                    Petition.status_code != "03",
                )
                .group_by(Petition.assignee_user_id)
                .all()
            )
            for uid, cnt in counted:
                open_counts[uid] = cnt
            assignee_user_id = min(open_counts, key=open_counts.get)

    petition = Petition(
        title=req.title,
        content=req.content,
        department_code=department_code,
        task_id=task_id,
        assignee_user_id=assignee_user_id,
        status_code="01",
        received_at=datetime.now(),
    )
    db.add(petition)
    db.commit()
```

- [ ] **Step 3: 문법 확인**

Run: `python -c "import ast; ast.parse(open('app/api/routers/petition.py', encoding='utf-8').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 4: 실제 서버 + DB로 검증**

서버 기동 확인 후, 교통 관련 민원을 접수:

```bash
curl -s -X POST http://localhost:8000/petitions/external \
  -H "Content-Type: application/json" \
  -H "X-API-Key: <settings.EXTERNAL_PETITION_API_KEY 값>" \
  -d '{"title": "도로 포트홀 신고", "content": "도로에 큰 포트홀이 있어서 위험합니다."}'
```

응답의 `petitionId`로 DB에서 직접 확인:

```python
from app.db.database import engine
from sqlalchemy import text
with engine.connect() as conn:
    rows = conn.execute(text("SELECT petition_id, department_code, task_id, assignee_user_id FROM PETITION ORDER BY petition_id DESC LIMIT 1"))
    for r in rows:
        print(dict(r._mapping))
```

Expected: `department_code`가 `01`(교통)이고, `task_id`가 채워져 있고(교통부는 실제 task 데이터가 있으므로), `assignee_user_id`도 채워져 있어야 함(교통부 task들은 전부 담당자가 1명 이상 있음 - task_id=16 "함정"만 예외).

같은 요청을 3~4번 반복해서, `assignee_user_id`가 매번 같은 사람에게만 몰리지 않고 후보들 사이에서 분산되는지(또는 최소한 미완료 건수가 적은 쪽으로 가는지) 확인.

- [ ] **Step 5: 커밋**

```bash
git add app/api/routers/petition.py
git commit -m "feat: 외부 민원 접수 시 담당업무·담당자 자동 배정"
```

---

## Self-Review 결과

- **스펙 커버리지:** 아키텍처의 두 갈래(create_task 색인 연동, petition 접수 시 task/담당자 배정) 모두 태스크로 매핑됨. "동작 원칙" 4개 항목(부서 하드코딩 안 함, 분류 실패해도 접수 진행, 담당자 0명 처리, 최소 미완료 배정) 모두 Task 2의 로직에 반영됨. "범위 밖"으로 명시한 4개 항목(6개 부서 가짜 데이터, description 프론트 입력, task 삭제 시 색인 제거, 알림)은 태스크로 만들지 않음.
- **플레이스홀더 스캔:** 없음 — 모든 스텝에 실행 가능한 코드/명령 포함.
- **타입/시그니처 일관성:** `task_id`(int|None), `assignee_user_id`(str|None) 타입이 `Petition` 모델 컬럼 타입(`Integer` nullable, `String(50)` nullable)과 일치. `TaskAssignee.user_id`도 `String(50)`이라 `Petition.assignee_user_id`와 타입 일치 확인.
