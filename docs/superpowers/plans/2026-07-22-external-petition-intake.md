# 외부 민원 접수 API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 외부 민원 채널(가상)이 `ieum_backend`에 새 민원을 접수할 수 있는 API를 만들고, 부서는 `ieum_ai`의 기존(현재 미사용) 8도메인 분류기로 자동 분류한다.

**Architecture:** `ieum_ai`에 `POST /api/classify-department`(제목+내용 → 부서코드)를 새로 추가해 죽어있던 `classify_text`를 재사용하고, `ieum_backend`의 `petition.py`에 `POST /petitions/external`(API 키 인증)을 추가해 그 분류 결과로 `PETITION` row를 생성한다.

**Tech Stack:** FastAPI, httpx(동기), SQLAlchemy(ieum_backend), 기존 Qwen2.5-3B 분류기(`handover-classifier`, Ollama).

## Global Constraints

- `ieum_ai` 테스트는 이 저장소의 기존 관례대로 plain script 스타일(`assert` + `print("[통과] ...")`, `python tests/xxx.py`로 직접 실행)로 작성한다.
- `ieum_ai`의 엔드포인트 테스트는 `tests/test_task_draft_endpoints.py` 관례를 따라 **실제로 떠 있는 서버**(`localhost:8100`)에 `requests`로 호출하는 라이브 스크립트로 작성한다 (mock 없음).
- `ieum_backend`에는 테스트 파일이 전혀 없다(확인됨) — 새 테스트 프레임워크를 도입하지 않고 curl로 수동 검증한다.
- 부서코드 매핑은 `DOMAIN_CATEGORIES` 리스트 순서(`["교통", "주택·건축", "환경", "복지", "안전", "경제·산업", "문화·체육·관광", "행정·일반"]`)가 부서코드 `01`~`08` 순서와 동일하다는 사실에 의존한다. 이 순서를 바꾸면 안 된다.
- `ieum_backend`가 `ieum_ai`의 `/api/classify-department`를 호출할 때 타임아웃은 **60초**로 잡는다 (분류기 자체의 내부 Ollama 타임아웃 10초보다 충분히 여유 있게, 콜드스타트/네트워크 지연 대비).
- 부서 자동분류가 실패해도 민원 접수 자체는 절대 막지 않는다 — 실패 시 부서코드 `"08"`(행정·일반)로 폴백하고 계속 진행한다.
- `ieum_backend`의 새 엔드포인트는 내부 직원용 JWT(`get_current_user`)가 아니라 `X-API-Key` 헤더로 인증한다.
- `ieum_backend`가 이 저장소의 기존 라우트 핸들러는 전부 동기 `def`(비동기 아님, threadpool에서 실행)다 — 새 엔드포인트도 이 관례를 따라 동기 `def` + `httpx.post`(AsyncClient 아님)로 작성한다.

---

### Task 1: `domain_name_to_department_code()` 매핑 함수 (`ieum_ai`)

**Files:**
- Modify: `app/classifier/ollama_client.py` (12행 `DOMAIN_CATEGORIES` 정의 바로 다음에 함수 추가)
- Test: `tests/test_domain_department_mapping.py` (신규)

**Interfaces:**
- Produces: `domain_name_to_department_code(domain_name: str) -> str` — Task 2에서 그대로 가져다 쓴다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_domain_department_mapping.py` 생성:

```python
# -*- coding: utf-8 -*-
"""
domain_name_to_department_code()는 순수 함수(네트워크 호출 없음)라 바로 assert로 검증 가능.

실행: python tests/test_domain_department_mapping.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.classifier.ollama_client import domain_name_to_department_code, DOMAIN_CATEGORIES

# 케이스 1: 8개 도메인명이 각각 올바른 부서코드로 매핑되는지 확인
EXPECTED = {
    "교통": "01",
    "주택·건축": "02",
    "환경": "03",
    "복지": "04",
    "안전": "05",
    "경제·산업": "06",
    "문화·체육·관광": "07",
    "행정·일반": "08",
}
for name, expected_code in EXPECTED.items():
    actual = domain_name_to_department_code(name)
    assert actual == expected_code, f"{name} -> {actual} (기대값 {expected_code})"
print("[통과] 8개 도메인명 -> 부서코드 매핑 확인")

# 케이스 2: DOMAIN_CATEGORIES 목록과 EXPECTED가 순서까지 일치하는지 확인
# (매핑 로직이 인덱스 기반이므로, 순서가 어긋나면 이 테스트가 잡아내야 함)
assert list(EXPECTED.keys()) == DOMAIN_CATEGORIES, "DOMAIN_CATEGORIES 순서가 바뀌면 매핑이 깨짐"
print("[통과] DOMAIN_CATEGORIES 순서 확인")

# 케이스 3: 목록에 없는 이름이 들어오면 안전하게 '08'로 폴백
assert domain_name_to_department_code("알수없는도메인") == "08"
print("[통과] 알 수 없는 도메인명은 08로 폴백")

print("\n모든 검증 통과")
```

- [ ] **Step 2: 테스트 실행해서 실패 확인**

Run: `python tests/test_domain_department_mapping.py`
Expected: `ImportError: cannot import name 'domain_name_to_department_code'`

- [ ] **Step 3: 최소 구현 작성**

`app/classifier/ollama_client.py`의 12행(`DOMAIN_CATEGORIES = [...]`) 바로 다음에 추가:

```python
def domain_name_to_department_code(domain_name: str) -> str:
    """DOMAIN_CATEGORIES 순서가 부서 코드 01~08 순서와 동일하다는 점을 이용한 매핑.
    classify_text()의 내부 _extract_category()가 항상 8개 이름 중 하나만 반환하도록
    보장하지만, 이 함수는 그 계약이 깨지는 경우에도 안전하게 '08'(행정·일반)로 열화된다."""
    if domain_name not in DOMAIN_CATEGORIES:
        return "08"
    return f"{DOMAIN_CATEGORIES.index(domain_name) + 1:02d}"
```

- [ ] **Step 4: 테스트 실행해서 통과 확인**

Run: `python tests/test_domain_department_mapping.py`
Expected: 마지막 줄에 `모든 검증 통과` 출력, 예외 없음

- [ ] **Step 5: 커밋**

```bash
git add app/classifier/ollama_client.py tests/test_domain_department_mapping.py
git commit -m "feat: 도메인명 -> 부서코드 매핑 함수 추가"
```

---

### Task 2: `POST /api/classify-department` 엔드포인트 (`ieum_ai`)

**Files:**
- Modify: `app/api/routes.py:4` (import에 `classify_text` 추가), `app/api/routes.py:63-66` 근처(신규 요청/응답 모델 추가), `app/api/routes.py:146-149` 근처(신규 엔드포인트 추가)
- Test: `tests/test_classify_department_endpoint.py` (신규, 라이브 서버 대상)

**Interfaces:**
- Consumes: `classify_text(text: str) -> str` (기존 함수, `app/classifier/ollama_client.py`), `domain_name_to_department_code(domain_name: str) -> str` (Task 1)
- Produces: `POST /api/classify-department` — Request `{"title": str, "content": str}`, Response `{"department_code": str}`. Task 3(`ieum_backend`)가 HTTP로 이 계약을 소비한다.

- [ ] **Step 1: import 및 요청/응답 모델 추가**

`app/api/routes.py:4`를 아래로 교체:

```python
from app.classifier.ollama_client import generate_draft_answer, classify_text, domain_name_to_department_code
```

`app/api/routes.py`의 `DraftRequest` 클래스(63~65행) 바로 다음, `IndexComplaintRequest`(68행) 이전에 추가:

```python
class ClassifyDepartmentRequest(BaseModel):
    title: str
    content: str


class ClassifyDepartmentResponse(BaseModel):
    department_code: str
```

- [ ] **Step 2: 엔드포인트 추가**

`app/api/routes.py`에서 `/draft` 엔드포인트가 끝나는 지점(`return {...}` 뒤 146행)과 `@router.post("/legal-chat")`(149행) 사이에 추가:

```python
@router.post("/classify-department", response_model=ClassifyDepartmentResponse)
async def classify_department(req: ClassifyDepartmentRequest):
    """
    민원 제목+내용으로 부서(01~08)를 자동 분류.
    ieum_backend의 외부 민원 접수 API(POST /petitions/external)가 사용한다.
    """
    domain_name = await classify_text(f"{req.title}\n{req.content}")
    department_code = domain_name_to_department_code(domain_name)
    return ClassifyDepartmentResponse(department_code=department_code)
```

- [ ] **Step 3: 라이브 서버 테스트 작성**

`tests/test_classify_department_endpoint.py` 생성:

```python
# -*- coding: utf-8 -*-
"""
/api/classify-department 엔드포인트 동작 확인 스크립트.

사전 조건:
    1) FastAPI 서버 실행 중: uvicorn app.main:app --reload --port 8100
    2) Ollama 실행 중, 분류 모델(handover-classifier) 로드 가능

실행: python tests/test_classify_department_endpoint.py
"""
import requests

BASE_URL = "http://localhost:8100"

print("=" * 70)
print("[테스트 1] 교통 관련 민원 -> 01")
print("-" * 70)
res = requests.post(f"{BASE_URL}/api/classify-department", json={
    "title": "버스정류장 앞 불법주차 신고",
    "content": "버스정류장 앞에 차량이 계속 불법주차를 해서 승하차가 어렵습니다.",
}, timeout=30.0)
res.raise_for_status()
body = res.json()
print("응답:", body)
assert "department_code" in body, f"department_code 필드 누락: {body}"
assert body["department_code"] in {"01", "02", "03", "04", "05", "06", "07", "08"}, body
print("[통과] department_code가 01~08 중 하나로 반환됨:", body["department_code"])

print("\n모든 테스트 통과")
```

- [ ] **Step 4: 서버 기동 후 테스트 실행**

Run:
```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port 8100 &
sleep 5
python tests/test_classify_department_endpoint.py
```
Expected: `모든 테스트 통과` 출력. (`handover-classifier` 모델이 Ollama에 없으면 500 에러 - 그 경우 `ollama list`로 모델 존재 확인)

- [ ] **Step 5: 커밋**

```bash
git add app/api/routes.py tests/test_classify_department_endpoint.py
git commit -m "feat: /api/classify-department 엔드포인트 추가 (부서 자동분류 부활)"
```

---

### Task 3: `POST /petitions/external` 엔드포인트 (`ieum_backend`)

**Files:**
- Modify: `app/core/config.py:25` 근처 (설정값 추가), `app/api/routers/petition.py:2`(import), `app/api/routers/petition.py:83-86` 근처(요청/응답 모델 추가), `app/api/routers/petition.py:114-116` 근처(엔드포인트 추가)
- 신규 코드 없음(테스트 파일) — 이 저장소는 테스트 파일이 없는 관례이므로 curl로 수동 검증(Step 6)

**Interfaces:**
- Consumes: `POST http://<AI_SERVER>/api/classify-department` (Task 2, HTTP 계약: `{"title": str, "content": str}` → `{"department_code": str}`)

- [ ] **Step 1: 설정값 추가**

`C:\Users\kmj24\gonggong\ieum_backend\app\core\config.py`의 `DEFAULT_PASSWORD: str`(25행) 바로 다음 줄에 추가:

```python
    EXTERNAL_PETITION_API_KEY: str
```

`C:\Users\kmj24\gonggong\ieum_backend\.env.local`(git에 커밋되지 않는 파일)에 값 추가:

```bash
python -c "import secrets; print('EXTERNAL_PETITION_API_KEY=' + secrets.token_urlsafe(32))" >> "C:\Users\kmj24\gonggong\ieum_backend\.env.local"
```

- [ ] **Step 2: import에 `Header` 추가**

`app/api/routers/petition.py:2`를 아래로 교체:

```python
from fastapi import APIRouter, Depends, Query, HTTPException, status, Form, File, UploadFile, BackgroundTasks, Header
```

- [ ] **Step 3: 요청/응답 모델 추가**

`app/api/routers/petition.py`의 `DeleteAttachmentResponse` 클래스(83~85행) 바로 다음, `# --- 라우터 ---`(87행) 이전에 추가:

```python
class ExternalPetitionRequest(BaseModel):
    title: str
    content: str

class ExternalPetitionResponse(BaseModel):
    petitionId: int
    departmentCode: str
```

- [ ] **Step 4: 엔드포인트 추가**

`app/api/routers/petition.py`에서 `_call_ai_to_index_petition` 헬퍼 함수가 끝나는 지점(114행)과 `@router.get("/", ...)`(116행) 사이에 추가:

```python
@router.post(
    "/external",
    response_model=ExternalPetitionResponse,
    summary="외부 시스템 민원 접수",
    responses={
        status.HTTP_401_UNAUTHORIZED: {"description": "API 키 불일치/누락"},
    }
)
def create_external_petition(
    req: ExternalPetitionRequest,
    x_api_key: str = Header(..., alias="X-API-Key"),
    db: Session = Depends(get_db),
):
    """
    국민신문고/정부24 같은 외부 민원 채널이 새 민원을 접수할 때 호출하는 엔드포인트.
    내부 직원용 JWT(get_current_user)가 아니라 API 키로 인증한다.

    ieum_ai의 /api/classify-department로 부서를 자동 분류한다. 분류가 실패해도
    (AI 서버 다운, 타임아웃 등) 민원 접수 자체는 막지 않고 기본 부서(08 행정·일반)로
    접수한다 - 담당자는 이후 temp-save에서 담당자/부서를 재배정할 수 있다.
    """
    if x_api_key != settings.EXTERNAL_PETITION_API_KEY:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="유효하지 않은 API 키입니다.")

    department_code = "08"
    try:
        classify_url = f"{settings.AI_SERVER.rstrip('/')}/api/classify-department"
        response = httpx.post(
            classify_url,
            json={"title": req.title, "content": req.content},
            timeout=60.0,
        )
        response.raise_for_status()
        department_code = response.json()["department_code"]
    except Exception as e:
        print(f"WARN: 부서 자동분류 실패, 기본 부서(08)로 접수: {e}")

    petition = Petition(
        title=req.title,
        content=req.content,
        department_code=department_code,
        status_code="01",
        received_at=datetime.now(),
    )
    db.add(petition)
    db.commit()
    db.refresh(petition)

    return ExternalPetitionResponse(
        petitionId=petition.petition_id,
        departmentCode=department_code,
    )
```

- [ ] **Step 5: `.env.local`의 `AI_SERVER` 값 확인**

`AI_SERVER` 값이 `ieum_ai`가 실제로 떠 있는 포트(`8100`)를 가리키는지 확인:

```bash
grep AI_SERVER "C:\Users\kmj24\gonggong\ieum_backend\.env.local"
```

Expected: `AI_SERVER=http://localhost:8100`. 다른 값(예: `8001`)이면 `8100`으로 고친다 — 안 고치면 이번 신규 엔드포인트도 분류 호출이 항상 실패해서(연결 거부) 매번 기본 부서(08)로만 접수된다.

- [ ] **Step 6: 서버 기동 후 curl로 수동 검증**

```bash
uvicorn app.main:app --reload --port 8000 &
sleep 5
API_KEY=$(grep EXTERNAL_PETITION_API_KEY "C:\Users\kmj24\gonggong\ieum_backend\.env.local" | cut -d= -f2)

# 케이스 1: API 키 없이 호출 -> 401
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://localhost:8000/petitions/external \
  -H "Content-Type: application/json" \
  -d '{"title":"테스트","content":"테스트 내용"}'
# Expected: 401 (또는 422 - Header(...)가 필수라 누락 시 422일 수도 있음, 둘 다 정상 거부로 간주)

# 케이스 2: 올바른 API 키로 호출 -> 200 + petitionId/departmentCode 반환
curl -s -X POST http://localhost:8000/petitions/external \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d '{"title":"불법주차 신고","content":"버스정류장 앞 불법주차 차량이 있습니다."}'
# Expected: {"petitionId": <int>, "departmentCode": "01"} 형태 (ieum_ai가 떠 있으면 실제 분류값, 안 떠 있으면 "08")
```

Expected: 케이스 1은 401(또는 422), 케이스 2는 200과 함께 `petitionId`(정수), `departmentCode`(01~08 중 하나)가 반환됨.

- [ ] **Step 7: 접수된 민원이 기존 목록 API에도 보이는지 확인**

케이스 2에서 만들어진 민원이 기존 조회 API에도 정상적으로 보이는지 (내부 직원 JWT 토큰 필요 - 수동으로 로그인해서 토큰 확보 후):

```bash
curl -s "http://localhost:8000/petitions/?scope=ALL&status=ALL&page=0" \
  -H "Authorization: Bearer <내부 직원 토큰>"
```

Expected: 방금 만든 `title`("불법주차 신고")이 목록에 `statusName: "대기중"`으로 나타남.

- [ ] **Step 8: 커밋**

```bash
git add app/core/config.py app/api/routers/petition.py
git commit -m "feat: 외부 민원 접수 API(POST /petitions/external) 추가"
```

(`.env.local`은 git에 커밋되지 않는 파일이므로 별도 커밋 없음.)

---

## Self-Review 결과

- **스펙 커버리지:** 아키텍처 다이어그램의 3개 구성요소(classify-department 엔드포인트, 매핑 함수, 접수 엔드포인트) 모두 태스크로 매핑됨. 에러 처리 표의 4개 케이스(API 키 오류, 필드 누락, 분류 실패 폴백, DB 오류)는 Task 3에서 코드로 구현되고 Step 6에서 401/폴백 케이스가 검증됨. 범위 밖으로 명시한 3개 항목(task_id 자동배정, 실제 외부 시스템 연동, 제출자 정보)은 태스크로 만들지 않음.
- **플레이스홀더 스캔:** 없음 — 모든 스텝에 실행 가능한 코드/명령 포함.
- **타입/시그니처 일관성:** `domain_name_to_department_code(domain_name: str) -> str`(Task 1)이 Task 2에서 동일 시그니처로 소비됨. `/api/classify-department`의 요청/응답 필드명(`title`, `content`, `department_code`)이 Task 2와 Task 3(curl 페이로드, `response.json()["department_code"]`)에서 정확히 일치.
