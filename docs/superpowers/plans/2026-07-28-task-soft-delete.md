# 업무(Task) 소프트 삭제 전환 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `ieum_backend`의 `delete_task`를 하드 삭제에서 소프트 삭제로 바꿔서, 삭제된 업무에 연결된 담당자 배정 이력(`TASK_ASSIGNEE`)과 그 업무로 분류된 민원(`PETITION.task_id`)이 그대로 보존되게 하고, 활성 업무 목록·집계·자동배정·자동분류에서는 삭제된 업무가 제외되게 한다.

**Architecture:** `TASK`에 `KNOWLEDGE`와 동일한 소프트 삭제 컬럼(`is_deleted`, `deleted_at`)을 추가한다. `delete_task`는 실제 `DELETE` 대신 `is_deleted=True` UPDATE로 바뀌고, 기존에 `TASK_ASSIGNEE`를 먼저 지우던 로직은 제거한다. Task를 "활성 업무"로 취급하는 모든 조회(목록/집계/자동배정 후보/자동분류 검증)에 `Task.is_deleted == False` 필터를 추가한다. Task 이름을 표시용으로만 쓰는 곳(민원 목록/상세, 지식베이스 목록)은 건드리지 않는다.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, MySQL(PyMySQL). 상세 설계는 [2026-07-28-task-soft-delete-design.md](../specs/2026-07-28-task-soft-delete-design.md) 참고.

## Global Constraints

- `ieum_backend`에는 자동 테스트가 없다 (기존 관례) - curl/DB 조회로 수동 검증한다.
- alembic 미사용 - 스키마 변경은 직접 `ALTER TABLE` 실행 (`KNOWLEDGE`의 `is_deleted`/`deleted_at` 추가 때도 동일했음, 커밋 `f367512`).
- `TASK`는 이미 데이터가 있는 공유 DB(`192.168.4.122:3306/ggieum`)의 테이블이다 - `ALTER TABLE` 실행 전 사용자에게 명시적으로 확인받는다. 다른 태스크는 이 확인과 무관하게 코드 변경만이라 바로 진행 가능하지만, 실행/검증은 Task 1의 스키마 변경이 끝난 뒤에만 가능하다.
- 소프트 삭제 컬럼명은 기존 `KNOWLEDGE`/`KNOWLEDGE_ATTACHMENT`/`KNOWLEDGE_LOG`와 동일하게 `is_deleted`(Boolean, default False, not null)/`deleted_at`(DateTime, nullable)을 사용한다.
- `TASK_ASSIGNEE`는 더 이상 Task 삭제 시 지우지 않는다 - 활성 업무 여부는 항상 `TASK.is_deleted`로 판단하고, `TASK_ASSIGNEE` 자체는 이력으로 그대로 둔다.
- `PETITION`/`KNOWLEDGE`가 `Task.name`을 표시 목적으로 outerjoin하는 곳(petition.py의 `get_petitions`/`get_petition_detail`/`answer_petition`, knowledge.py 목록 조회)은 이번 변경 범위에서 제외한다.
- 이 저장소의 기존 라우트 핸들러는 전부 동기 `def` - 새 코드도 이 관례를 따른다.

---

### Task 1: TASK 테이블에 소프트 삭제 컬럼 추가 (`ieum_backend`)

**Files:**
- Modify: `app/models/task.py` (전체, 9줄)

**Interfaces:**
- Produces: `Task.is_deleted: bool`, `Task.deleted_at: datetime | None` — Task 2~4가 모든 쿼리에서 이 두 속성을 사용한다.

- [ ] **Step 1: 모델에 컬럼 추가**

`app/models/task.py`를 아래로 교체:

```python
from sqlalchemy import Column, String, Integer, ForeignKey, Boolean, DateTime, func
from app.db.database import Base

class Task(Base):
    __tablename__ = "TASK"

    task_id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    department_code = Column(String(10), ForeignKey("DEPARTMENT.department_code"), nullable=True)
    is_deleted = Column(Boolean, default=False, nullable=False)
    deleted_at = Column(DateTime, nullable=True)
```

- [ ] **Step 2: 공유 DB에 컬럼 추가 (사용자 확인 필요)**

이 단계는 팀이 공유하는 DB(`192.168.4.122`)의 스키마를 바꾸는 되돌리기 번거로운 작업이다. **실행 전 사용자에게 진행 여부를 확인받는다.**

승인받으면 `ieum_backend` 루트에서 실행:

```bash
"C:\Users\kmj24\anaconda3\envs\ieum_backend\python.exe" -c "from app.db.database import engine; from sqlalchemy import text; conn = engine.connect(); conn.execute(text('ALTER TABLE TASK ADD COLUMN is_deleted TINYINT(1) NOT NULL DEFAULT 0, ADD COLUMN deleted_at DATETIME NULL')); conn.commit(); conn.close(); print('OK')"
```

Expected: `OK` 출력, 에러 없음. (MySQL의 `ALTER TABLE ... ADD COLUMN ... DEFAULT 0`은 기존 행에도 자동으로 backfill되므로 별도 UPDATE 불필요.)

- [ ] **Step 3: 컬럼이 실제로 추가됐는지 확인**

```bash
"C:\Users\kmj24\anaconda3\envs\ieum_backend\python.exe" -c "from app.db.database import engine; from sqlalchemy import text; conn = engine.connect(); rows = conn.execute(text('DESCRIBE TASK')).fetchall(); [print(r) for r in rows]; conn.close()"
```

Expected: 출력에 `is_deleted`(tinyint(1), NO, ..., 0)와 `deleted_at`(datetime, YES) 행이 포함됨.

- [ ] **Step 4: 커밋**

```bash
git add app/models/task.py
git commit -m "feat: TASK 테이블에 소프트 삭제 컬럼(is_deleted, deleted_at) 추가"
```

---

### Task 2: `delete_task`를 소프트 삭제로 전환 (`ieum_backend`)

**Files:**
- Modify: `app/api/routers/task.py:1-12`(import), `app/api/routers/task.py:158-179`(`delete_task` 함수)

**Interfaces:**
- Consumes: `Task.is_deleted`, `Task.deleted_at` (Task 1)

- [ ] **Step 1: `func` import 추가**

`app/api/routers/task.py` 상단의 import 블록:

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

아래로 교체(`sqlalchemy import Session` 다음 줄에 `func` import 추가):

```python
from fastapi import APIRouter, Depends, status, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
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

- [ ] **Step 2: `delete_task`를 소프트 삭제로 교체**

현재 함수(158~179행):

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

아래로 교체:

```python
def delete_task(
    taskId: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    task = db.query(Task).filter(
        Task.task_id == taskId,
        Task.is_deleted == False,
    ).first()
    if not task:
        raise HTTPException(status_code=404, detail="존재하지 않는 Task이거나 이미 삭제되었습니다.")

    deleted_task_id = task.task_id
    deleted_department_code = task.department_code

    task.is_deleted = True
    task.deleted_at = func.now()
    db.commit()

    try:
        deindex_url = f"{settings.AI_SERVER.rstrip('/')}/api/task-category/{deleted_department_code}/{deleted_task_id}"
        response = httpx.delete(deindex_url, timeout=30.0)
        response.raise_for_status()
    except Exception as e:
        print(f"WARN: task 색인 삭제 실패(task_id={deleted_task_id}): {e}")
```

(`TASK_ASSIGNEE`를 미리 지우던 줄이 사라진 것에 주의 — 배정 이력을 보존하는 게 이번 변경의 핵심이다.)

- [ ] **Step 3: 문법 확인**

Run: `"C:\Users\kmj24\anaconda3\envs\ieum_backend\python.exe" -c "import ast; ast.parse(open('app/api/routers/task.py', encoding='utf-8').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 4: 서버 기동 후 curl로 수동 검증**

`ieum_backend`가 8000 포트로 떠 있는지 확인 후, 실제 로그인 토큰으로:

```bash
# 1. 테스트용 업무 생성
curl -s -X POST "http://localhost:8000/tasks?department_code=01" \
  -H "Authorization: Bearer <토큰>" -H "Content-Type: application/json" \
  -d '{"name":"소프트삭제테스트업무"}'
# 응답의 taskId를 기록 (예: 999)

# 2. 삭제
curl -s -X DELETE "http://localhost:8000/tasks/999" -H "Authorization: Bearer <토큰>"

# 3. DB에서 row가 남아있고 is_deleted=1인지 확인
"C:\Users\kmj24\anaconda3\envs\ieum_backend\python.exe" -c "from app.db.database import engine; from sqlalchemy import text; conn = engine.connect(); print(conn.execute(text('SELECT task_id, name, is_deleted, deleted_at FROM TASK WHERE task_id = 999')).fetchone()); conn.close()"

# 4. 같은 taskId를 다시 삭제 시도 -> 404가 나와야 함
curl -s -o /dev/null -w "%{http_code}\n" -X DELETE "http://localhost:8000/tasks/999" -H "Authorization: Bearer <토큰>"
```

Expected: 3번 결과가 `(999, '소프트삭제테스트업무', 1, datetime(...))`처럼 row가 실제로 남아있고 `is_deleted=1`. 4번은 `404`.

- [ ] **Step 5: 커밋**

```bash
git add app/api/routers/task.py
git commit -m "feat: delete_task를 하드 삭제에서 소프트 삭제로 전환"
```

---

### Task 3: 활성 업무 목록·집계 조회에서 삭제된 Task 제외 (`ieum_backend`)

**Files:**
- Modify: `app/api/routers/task.py:36-43`(`get_my_tasks`), `app/api/routers/task.py:73-75`(`get_department_tasks`)
- Modify: `app/api/routers/dashboard.py:119-161`(`get_tasks_summary`)
- Modify: `app/api/routers/admin.py:153`

**Interfaces:**
- Consumes: `Task.is_deleted` (Task 1)

- [ ] **Step 1: `get_my_tasks` 필터링**

`app/api/routers/task.py`에서 (36~40행):

```python
    assigned_task_ids_query = db.query(TaskAssignee.task_id)\
        .filter(TaskAssignee.user_id == current_user.user_id)

    my_tasks = db.query(Task).filter(Task.task_id.in_(assigned_task_ids_query)).order_by(Task.name).all()
```

아래로 교체:

```python
    assigned_task_ids_query = db.query(TaskAssignee.task_id)\
        .filter(TaskAssignee.user_id == current_user.user_id)

    my_tasks = db.query(Task).filter(
        Task.task_id.in_(assigned_task_ids_query),
        Task.is_deleted == False,
    ).order_by(Task.name).all()
```

- [ ] **Step 2: `get_department_tasks` 필터링**

같은 파일 (73~75행):

```python
    tasks = db.query(Task).filter(
        Task.department_code == target_dept
    ).all()
```

아래로 교체:

```python
    tasks = db.query(Task).filter(
        Task.department_code == target_dept,
        Task.is_deleted == False,
    ).all()
```

- [ ] **Step 3: `dashboard.py`의 `get_tasks_summary` 필터링**

`app/api/routers/dashboard.py`에서 `get_tasks_summary` 함수(119~161행) 전체를 아래로 교체:

```python
def get_tasks_summary(
    department_code: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    target_dept = department_code or current_user.department_code

    total_tasks = db.query(Task).filter(
        Task.department_code == target_dept,
        Task.is_deleted == False,
    ).count()

    assigned_task_ids = db.query(TaskAssignee.task_id).join(
        Task, TaskAssignee.task_id == Task.task_id
    ).filter(
        Task.department_code == target_dept,
        Task.is_deleted == False,
    ).distinct().subquery()

    unassigned_tasks = db.query(Task).filter(
        Task.department_code == target_dept,
        Task.is_deleted == False,
        Task.task_id.notin_(assigned_task_ids),
    ).count()

    dept_members = db.query(User).filter(
        User.department_code == target_dept
    ).all()

    assigned_user_ids = {
        row.user_id for row in db.query(TaskAssignee.user_id).join(
            Task, TaskAssignee.task_id == Task.task_id
        ).filter(
            Task.department_code == target_dept,
            Task.is_deleted == False,
        ).all()
    }

    members_without_task = sum(
        1 for m in dept_members if m.user_id not in assigned_user_ids
    )

    return TaskSummaryResponse(
        totalTasks=total_tasks,
        unassignedTasks=unassigned_tasks,
        membersWithoutTask=members_without_task,
    )
```

- [ ] **Step 4: `admin.py`의 담당 Task 표시 필터링**

`app/api/routers/admin.py:153`:

```python
        task_assignments = db.query(TaskAssignee.user_id, Task.name).join(Task, TaskAssignee.task_id == Task.task_id).filter(TaskAssignee.user_id.in_(user_ids)).order_by(TaskAssignee.user_id, Task.task_id).all()
```

아래로 교체:

```python
        task_assignments = db.query(TaskAssignee.user_id, Task.name).join(Task, TaskAssignee.task_id == Task.task_id).filter(TaskAssignee.user_id.in_(user_ids), Task.is_deleted == False).order_by(TaskAssignee.user_id, Task.task_id).all()
```

- [ ] **Step 5: 문법 확인**

Run: `"C:\Users\kmj24\anaconda3\envs\ieum_backend\python.exe" -c "import ast; [ast.parse(open(f, encoding='utf-8').read()) for f in ['app/api/routers/task.py','app/api/routers/dashboard.py','app/api/routers/admin.py']]; print('OK')"`
Expected: `OK`

- [ ] **Step 6: 서버 기동 후 curl로 수동 검증**

Task 2에서 만든 `999`(소프트 삭제됨)와 새 활성 업무 하나를 비교:

```bash
# 부서 업무 목록에 999가 더 이상 안 보여야 함
curl -s "http://localhost:8000/tasks?department_code=01" -H "Authorization: Bearer <토큰>" | grep -o '"taskId":999' || echo "999 안 보임 (정상)"

# 업무 현황 집계의 totalTasks가 삭제 전보다 1 줄어야 함 (삭제 전 값과 비교)
curl -s "http://localhost:8000/dashboard/tasks/summary?department_code=01" -H "Authorization: Bearer <토큰>"
```

Expected: 첫 번째 명령이 "999 안 보임 (정상)" 출력, 두 번째 명령의 `totalTasks`가 Task 2 이전에 기록해둔 값보다 1 작음.

- [ ] **Step 7: 커밋**

```bash
git add app/api/routers/task.py app/api/routers/dashboard.py app/api/routers/admin.py
git commit -m "feat: 업무 목록·집계 조회에서 소프트 삭제된 Task 제외"
```

---

### Task 4: 담당자 지정·민원 자동분류/스코프 조회에서 삭제된 Task 제외 (`ieum_backend`)

**Files:**
- Modify: `app/api/routers/task.py:197-199`(`add_assignee`)
- Modify: `app/api/routers/petition.py:183-185`(`create_external_petition`), `app/api/routers/petition.py:275-284`(`get_petitions`의 `scope=TASK`)

**Interfaces:**
- Consumes: `Task.is_deleted` (Task 1)

- [ ] **Step 1: `add_assignee`가 삭제된 Task에 배정하지 못하게 막기**

`app/api/routers/task.py`에서 (197~199행):

```python
    task = db.query(Task).filter(Task.task_id == taskId).first()
    if not task:
        raise HTTPException(status_code=404, detail="존재하지 않는 Task입니다.")
```

(`add_assignee` 함수 안의 것 — `delete_task`의 것과 문구가 같으니 `add_assignee` 함수 본문 안에 있는 인스턴스인지 확인) 아래로 교체:

```python
    task = db.query(Task).filter(
        Task.task_id == taskId,
        Task.is_deleted == False,
    ).first()
    if not task:
        raise HTTPException(status_code=404, detail="존재하지 않는 Task이거나 이미 삭제되었습니다.")
```

- [ ] **Step 2: `create_external_petition`에서 삭제된 task_id를 무효 처리**

`app/api/routers/petition.py`에서 (183~185행):

```python
    if task_id is not None and db.query(Task.task_id).filter(Task.task_id == task_id).first() is None:
        print(f"WARN: ieum_ai가 존재하지 않는 task_id를 반환함({task_id!r}), 미배정으로 접수")
        task_id = None
```

아래로 교체:

```python
    if task_id is not None and db.query(Task.task_id).filter(
        Task.task_id == task_id,
        Task.is_deleted == False,
    ).first() is None:
        print(f"WARN: ieum_ai가 존재하지 않거나 삭제된 task_id를 반환함({task_id!r}), 미배정으로 접수")
        task_id = None
```

- [ ] **Step 3: `get_petitions`의 `scope=TASK`에서 삭제된 업무 제외**

같은 파일 (275~284행):

```python
        elif scope.upper() == "TASK":
            # taskId가 제공된 경우, 해당 업무로 추가 필터링
            if taskId is not None:
                query = query.filter(Petition.task_id == taskId)
            # taskId가 없는 경우, 현재 사용자가 담당하는 모든 업무의 민원을 조회
            else:
                # 1. task_assignee 테이블에서 현재 사용자의 모든 task_id를 조회
                user_task_ids_query = db.query(TaskAssignee.task_id).filter(TaskAssignee.user_id == current_user.user_id)
                # 2. 해당 task_id 목록에 포함되는 민원들만 필터링
                query = query.filter(Petition.task_id.in_(user_task_ids_query))
```

아래로 교체:

```python
        elif scope.upper() == "TASK":
            # taskId가 제공된 경우, 해당 업무로 추가 필터링
            if taskId is not None:
                query = query.filter(Petition.task_id == taskId)
            # taskId가 없는 경우, 현재 사용자가 담당하는 모든 업무(삭제되지 않은 업무만)의 민원을 조회
            else:
                # 1. task_assignee 테이블에서 현재 사용자의 삭제되지 않은 task_id를 조회
                user_task_ids_query = db.query(TaskAssignee.task_id).join(
                    Task, TaskAssignee.task_id == Task.task_id
                ).filter(
                    TaskAssignee.user_id == current_user.user_id,
                    Task.is_deleted == False,
                )
                # 2. 해당 task_id 목록에 포함되는 민원들만 필터링
                query = query.filter(Petition.task_id.in_(user_task_ids_query))
```

(`Task`는 `petition.py` 상단에 이미 import돼 있음 — 새 import 불필요.)

- [ ] **Step 4: 문법 확인**

Run: `"C:\Users\kmj24\anaconda3\envs\ieum_backend\python.exe" -c "import ast; [ast.parse(open(f, encoding='utf-8').read()) for f in ['app/api/routers/task.py','app/api/routers/petition.py']]; print('OK')"`
Expected: `OK`

- [ ] **Step 5: 서버 기동 후 curl로 수동 검증**

```bash
# 1. 999(소프트 삭제됨)에 담당자 지정 시도 -> 404
curl -s -o /dev/null -w "%{http_code}\n" -X POST "http://localhost:8000/tasks/999/assignees" \
  -H "Authorization: Bearer <토큰>" -H "Content-Type: application/json" -d '{"userId": 1}'

# 2. 삭제 전 999에 담당자가 있었다면, scope=TASK(taskId 없이) 조회 시 999로 분류된 민원이 더 이상 안 뜨는지 확인
curl -s "http://localhost:8000/petitions?scope=TASK" -H "Authorization: Bearer <그 담당자 토큰>"
```

Expected: 1번은 `404`. 2번 응답에 999로 분류됐던 민원이 안 보임(또는 애초에 999에 배정된 민원이 없었다면 빈 배열/무관한 결과).

- [ ] **Step 6: 커밋**

```bash
git add app/api/routers/task.py app/api/routers/petition.py
git commit -m "feat: 담당자 지정·민원 자동분류/스코프 조회에서 소프트 삭제된 Task 제외"
```

---

## Self-Review 결과

- **스펙 커버리지:** 설계 문서의 4개 컴포넌트(스키마 변경, delete_task 전환, 활성 업무 필터링 6곳, 건드리지 않는 곳)가 Task 1~4에 모두 매핑됨. "건드리지 않는 곳"(petition.py의 표시용 outerjoin, knowledge.py)은 Global Constraints에 명시하고 별도 태스크로 만들지 않음. "범위 밖"(un-delete API, 민원 일괄 이관)도 태스크로 만들지 않음.
- **플레이스홀더 스캔:** 없음 — 모든 스텝에 실행 가능한 코드/명령 포함. `<토큰>`은 실행 시점에 실제 로그인해서 얻어야 하는 값이라 플레이스홀더가 아니라 수동 검증 절차의 일부.
- **타입/시그니성 일관성:** `Task.is_deleted`(Boolean)/`Task.deleted_at`(DateTime)이 Task 1에서 정의된 그대로 Task 2~4의 모든 쿼리에서 `== False`/`func.now()`로 일관되게 쓰임. `delete_task`의 404 메시지("존재하지 않는 Task이거나 이미 삭제되었습니다")를 `add_assignee`에도 동일하게 맞춤.
