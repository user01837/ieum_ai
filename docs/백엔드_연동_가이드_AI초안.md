# `ieum_backend` 연동 가이드 — AI 기획서 초안 (`/projects/{projectId}/ai-draft`)

- 작성일: 2026-07-22
- 대상: `ieum_backend` 담당자
- 관련 문서: [`API_명세서.md`](./API_명세서.md) (`ieum_ai`의 `/api/task-draft` 전체 계약)

## 지금 뭐가 문제인가

프론트엔드(`ieum_frontend`)에서 "AI 답변 초안 생성"을 누르면 `POST /projects/{projectId}/ai-draft`를 호출하는데, 지금 이 요청은 두 가지 이유로 실패한다.

1. **`ieum_backend`가 안 떠 있으면**: Vite dev 서버(`vite.config.js`의 proxy target `http://localhost:8000`)가 백엔드에 연결하지 못해 `502 Bad Gateway`를 프론트에 그대로 돌려준다.
2. **`ieum_backend`가 떠 있어도**: `app/api/routers/project.py:422-436`의 `get_ai_draft`가 아직 스텁이라 `ieum_ai`를 전혀 호출하지 않고 빈 문자열만 반환한다.

```python
# 현재 코드 (app/api/routers/project.py:427-436)
@router.get("/{projectId}/ai-draft", response_model=AiDraftResponse, summary="AI 기획서 초안 생성")
def get_ai_draft(projectId: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.project_id == projectId).first()
    if not project:
        raise HTTPException(status_code=404, detail="존재하지 않는 프로젝트입니다.")
    return AiDraftResponse(overview="", reportContent="")
```

이 문서는 이 엔드포인트가 실제로 `ieum_ai`의 `/api/task-draft`를 호출하도록 만드는 데 필요한 정보를 정리한 것.

## `ieum_ai` 쪽에서 최근 바뀐 것 (이 작업과 직접 관련)

`/api/task-draft`가 반환하는 `draft`의 9개 필드 값이 **평문에서 HTML로 바뀌었다** (2026-07-22).

- 각 필드는 이제 `<h3>`/`<p>` 태그를 포함한 HTML 문자열이다 (예: `"<p>노후 버스승강장을 저상화...</p>"`).
- `background`(추진 배경 및 필요성) 필드는 특별히 `<h3>추진 배경</h3>` / `<h3>사업 필요성</h3>` 두 소제목으로 나뉘어 온다.
- 이유: 프론트 Tiptap 에디터가 이 내용을 그대로 렌더링/저장하기로 했기 때문 (평문을 넣으면 서식이 다 깨짐).

실제 응답 예시 (`lead_department_code: "01"`로 호출한 실측 결과, 일부 생략):

```json
{
  "draft": {
    "overview": "<p>노후 버스승강장을 저상화하여 교통약자 접근성을 개선하는 사업입니다.</p>",
    "background": "<h3>추진 배경</h3>\n<p>&nbsp;&nbsp;&nbsp;&nbsp;□ 노후 버스승강장이 많아 교통약자 이용이 어려움</p>\n<h3>사업 필요성</h3>\n<p>&nbsp;&nbsp;&nbsp;&nbsp;□ 저상버스 승강장 설치로 이동 편의 향상</p>",
    "goals": "<p>...</p>",
    "detailed_plan": "<p>...</p>",
    "schedule": "<p>...</p>",
    "execution_system": "<p>...</p>",
    "budget": "<p>...</p>",
    "expected_effect": "<p>...</p>",
    "post_management": "<p>...</p>"
  },
  "referenced_tasks": [ { "task_id": 1, "title": "...", "similarity": 89.6, "...": "..." } ],
  "guardrail_triggered": false,
  "needs_review": false,
  "unverified_claims": {}
}
```

## 지금 스키마로 뭘 할 수 있는가 (중요한 제약)

`ieum_backend`의 `Project` 모델(`app/models/project.py:4-19`)에는 9개 섹션을 나눠 저장할 컬럼이 없다 — `overview`, `report_content` 두 개의 `Text` 컬럼뿐이다. 프론트도 섹션별 에디터(`SectionEditor`)가 아니라 `report_content` 하나를 통째로 다루는 Tiptap 에디터 하나만 있다 (`ProjectDetail.jsx`).

즉 **지금 당장은 9개 필드를 섹션별 컬럼에 나눠 저장할 방법이 없다.** 두 가지 선택지가 있다.

### 선택지 A — 9개 필드를 하나로 합쳐서 `report_content`에 채우기 (추천, 지금 스키마로 바로 가능)

`draft`의 9개 필드를 로마숫자 제목(`<h2>`)과 함께 순서대로 이어붙여서 `AiDraftResponse.reportContent` 하나로 반환한다. 프론트는 지금 `report_content` 하나만 다루므로 스키마/프론트 변경 없이 바로 동작한다.

```python
SECTION_TITLES = [
    ("overview", "Ⅰ. 사업 개요"),
    ("background", "Ⅱ. 추진 배경 및 필요성"),
    ("goals", "Ⅲ. 사업 목표"),
    ("detailed_plan", "Ⅳ. 세부 추진 계획"),
    ("schedule", "Ⅴ. 추진 일정"),
    ("execution_system", "Ⅵ. 사업 추진 체계"),
    ("budget", "Ⅶ. 예산 계획"),
    ("expected_effect", "Ⅷ. 기대 효과"),
    ("post_management", "Ⅸ. 사후 관리 계획"),
]

def build_report_content_html(draft: dict) -> str:
    parts = []
    for field, title in SECTION_TITLES:
        parts.append(f"<h2>{title}</h2>")
        parts.append(draft.get(field, ""))
    return "\n".join(parts)
```

### 선택지 B — `Project`에 9개 섹션 컬럼 추가 + `SectionEditor` 컴포넌트 도입

사용자가 초반에 보여준 `SectionEditor.jsx`/`sec_overview` 같은 9섹션 구조를 실제로 만들려면: `Project` 모델에 컬럼 9개 추가(마이그레이션 필요), `AiDraftResponse`도 9개 필드로 확장, 프론트에 `SectionEditor` 컴포넌트 신규 구현까지 필요한 더 큰 작업이다. **이번 문서/작업 범위 밖** — 필요하면 별도로 브레인스토밍부터 다시 시작하는 걸 권장.

## 구현 제안 (선택지 A 기준)

```python
import httpx

AI_SERVER_BASE_URL = "http://localhost:8100"  # 배포 환경에 맞게 설정/환경변수로 분리 권장

@router.get("/{projectId}/ai-draft", response_model=AiDraftResponse, summary="AI 기획서 초안 생성")
async def get_ai_draft(
    projectId: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project = db.query(Project).filter(Project.project_id == projectId).first()
    if not project:
        raise HTTPException(status_code=404, detail="존재하지 않는 프로젝트입니다.")

    try:
        async with httpx.AsyncClient(timeout=280.0) as client:
            res = await client.post(
                f"{AI_SERVER_BASE_URL}/api/task-draft",
                json={
                    "title": project.name,
                    "overview": project.overview or project.business_content or "",
                    "lead_department_code": project.department_code,
                },
            )
        res.raise_for_status()
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="AI 서버 연결에 실패했습니다.")

    data = res.json()
    report_content = build_report_content_html(data["draft"])

    return AiDraftResponse(
        overview=project.overview or "",
        reportContent=report_content,
    )
```

체크할 점:

- **타임아웃 (중요, 실제로 500 재현됨)**: `ieum_ai`가 2026-07-22에 내부 Ollama 호출 타임아웃을 120초 → **240초**로 올렸다(`app/classifier/ollama_client.py`, 커밋 `2805d6a`). 기존 120초로는 실측 생성시간(137~139초)을 못 버텨서 `httpx.ReadTimeout` → 처리되지 않은 예외 → `ieum_ai`가 **500 Internal Server Error**를 그대로 반환하는 게 실제로 재현됐었다 (curl로 `/api/task-draft` 직접 호출해도 동일하게 발생 — 백엔드/네트워크 문제 아니었음). 최신 `ieum_ai` 코드를 pull 받았는지 먼저 확인할 것. 그리고 백엔드가 `ieum_ai`를 호출하는 타임아웃은 `ieum_ai` 내부 240초보다 반드시 더 길게(위 예시처럼 280초 이상) 잡을 것 — 안 그러면 `ieum_ai`가 아직 처리 중인데 백엔드가 먼저 포기해서 이번엔 502로 보인다.
- **`lead_department_code`**: `project.department_code`가 `01`~`08`이 아니면(`09`=관리자 포함) `ieum_ai`가 `400`을 반환한다. `None`이면 `ieum_ai`가 `422`를 반환한다(둘 다 확인됨, 500 아님). 아래 가드로 먼저 걸러줄 것:

```python
if not project.department_code or project.department_code == "09":
    raise HTTPException(status_code=422, detail="AI 초안은 관리자 부서가 아닌 프로젝트에서만 지원됩니다.")
```

  "관리자(09) 부서 프로젝트도 AI 초안을 지원할지"는 코드 버그가 아니라 별도 정책 결정이 필요한 사안 — 지원하려면 `ieum_ai`에 관리자용 도메인/시드 데이터를 새로 만드는 작업이 추가로 필요하다.
- **`guardrail_triggered` / `needs_review`**: 지금 제안 코드는 이 두 플래그를 버리고 있다. 프론트에 "AI가 참고 사업을 못 찾았습니다" 안내나 "재검토 필요" 배지를 보여줄 계획이면 `AiDraftResponse`에 필드를 추가해서 같이 내려줘야 한다 (지금은 범위 밖으로 뒀다 — 필요하면 알려달라).
- **에러 응답**: `ieum_ai` 자체가 다운돼있으면 `httpx.HTTPError`를 잡아 `502`로 변환하도록 위 예시에 넣어뒀다. 원래 프론트에서 봤던 502(Vite 프록시발)와는 다른, "AI 서버가 응답 안 함"을 명확히 구분하는 502다.

## 테스트 방법

1. Ollama(`llama3.1:8b`)와 `ieum_ai` 서버(`8100`)가 떠 있는지 확인: `curl http://localhost:8100/docs`
2. `ieum_backend`(`8000`) 기동
3. `curl http://localhost:8000/projects/{실제 projectId}/ai-draft -H "Authorization: ..."` 로 직접 호출해보고 `reportContent`에 `<h2>`/`<h3>`/`<p>` 태그가 섞인 HTML이 오는지 확인
4. 프론트에서 "AI 답변 초안 생성" 버튼으로 실제 Tiptap 에디터에 반영되는지 확인 (2분 이상 걸릴 수 있음, 로딩 UI 확인)
