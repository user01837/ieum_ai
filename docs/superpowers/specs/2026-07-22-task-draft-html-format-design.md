# 사업계획서 AI 초안 HTML 출력 + 배경 필드 세분화 설계

- 작성일: 2026-07-22
- 관련 기존 기능: 사업 추진계획서 AI 초안작성 (`docs/superpowers/specs/2026-07-21-task-draft-design.md`)
- 관련 파일: `app/classifier/ollama_client.py`, `app/classifier/draft_guardrail.py`, `app/vectorstore/task_chroma_client.py`

## 배경 및 목적

프론트엔드(`ieum_frontend`)의 기획서 편집기(SectionEditor, Tiptap)와 백엔드(`ieum_backend`)의
내보내기(export) 기능은 각 섹션 내용이 `h2`/`h3`/`p` 태그를 포함한 HTML이라고 가정하고 동작한다
(내보내기 시 `BeautifulSoup`로 `h3`/`p`만 훑어서 텍스트를 뽑아냄). 반면 `ieum_ai`의
`generate_task_draft()`가 지금 생성하는 9개 필드는 순수 텍스트 한 덩어리라 이 가정과 맞지 않는다.

또한 담당자가 "Ⅱ. 추진 배경 및 필요성"을 검토할 때 "추진 배경"과 "사업 필요성"이 섞인 문단
하나보다, 두 소제목으로 나뉜 형태가 더 읽기 쉽다는 요구가 있었다.

> 참고: `SectionEditor.jsx`/`export_project`(9섹션 컬럼, `sec_overview` 등)는 조사 결과
> `ieum_frontend`/`ieum_backend`의 현재 어떤 브랜치에도 존재하지 않으며, `ieum_ai`와 아직
> 연결되어 있지 않다. 이번 설계는 **`ieum_ai`가 내려주는 9개 필드의 형식**만 다루고,
> 프론트/백엔드 연동은 범위 밖으로 둔다 (아래 "범위 밖" 참고).

## 핵심 결정

1. **LLM은 HTML 태그를 직접 쓰지 않는다.** 대신 가벼운 마크다운 표기(`## 소제목`, `- 항목`)만
   쓰게 하고, Python 코드가 이를 결정적으로 HTML로 변환한다.
   이유: `_stringify_field`의 기존 주석에 남아있듯, 이 프로젝트에서 쓰는 로컬 8B 모델은
   "문자열만 쓰라"는 지시도 종종 어긴 전례(리스트/객체로 응답)가 있다. 여기에 "태그가 안 깨진
   HTML을 JSON 문자열 안에 정확히 넣어라"까지 요구하면 실패 지점이 하나 더 늘어난다.
   마크다운 마커 인식 실패는 "그냥 일반 문단으로 렌더링"으로 안전하게 열화되지만, HTML 태그
   깨짐은 미리보기 자체가 깨질 수 있다.
2. **`background` 필드만 `## 추진 배경` / `## 사업 필요성` 두 소제목으로 세분화한다.**
   `TASK_FIELDS`(9개 키) 스키마는 그대로 유지 — `background`는 여전히 문자열 값 1개이고,
   내용 안에 마크다운 소제목 마커가 2개 들어가는 것뿐이다. 벡터스토어 메타데이터, 시드 데이터
   (`data/seed_tasks.py`), 나머지 8개 필드 구조는 변경하지 않는다.

## 변환 규칙 (신규: `app/classifier/draft_html.py`)

```python
def render_field_html(text: str) -> str:
    """LLM이 생성한 마크다운 라이트 텍스트를 h3/p 구조 HTML로 변환.
    지원하는 문법은 3가지뿐(YAGNI) - 이 프로젝트 프롬프트가 실제로 쓰는 만큼만:
      "## 제목"      -> <h3>제목</h3>
      "- 항목" / "□ 항목" -> <p>&nbsp;&nbsp;&nbsp;&nbsp;□ 항목</p>
      그 외 일반 줄   -> <p>줄 내용</p>
    빈 줄은 무시(단락 구분용)."""
```

- 줄 단위(`text.split("\n")`)로 순회하며 위 3가지 패턴만 매칭. 그 외 마크다운 문법(굵게, 링크,
  중첩 리스트 등)은 지원하지 않고 일반 텍스트로 취급 — 처리 실패가 아니라 "그냥 평문으로 보임"
  정도로만 열화된다.
- HTML 이스케이프: 각 줄 내용은 `html.escape()`를 거쳐 `<p>`/`<h3>` 사이에 넣는다
  (LLM 출력에 우연히 `<`, `>`, `&`가 섞여도 태그가 깨지지 않도록).

## 프롬프트 변경 (`generate_task_draft`)

기존 프롬프트 지침에 아래 항목을 추가/대체한다:

- (유지) "9개 key만 가진 JSON 객체로만 답하라", "각 key 값은 문자열 하나".
- (신규) "각 필드 값 안에서 여러 항목을 나열할 때는 `1) 2) 3)` 대신 줄마다 `- `로 시작해서
  한 줄에 하나씩 쓰세요."
- (신규, `background` 필드 전용) 아래 형식을 그대로 예시로 프롬프트에 포함:
  ```
  ## 추진 배경
  - (현재 업무 현황)
  - (발생 문제)
  - (개선 필요성)

  ## 사업 필요성
  - (행정 효율 개선)
  - (업무 처리시간 단축)
  - (서비스 품질 향상)
  ```
  괄호 안은 실제 예시 문장으로 채워 few-shot처럼 보여준다(플레이스홀더 문구 그대로 출력하는
  것을 방지하기 위해 실제 사업 사례 기반 문장을 예시로 사용).
- HTML 태그(`<`, `>`)를 직접 쓰지 말라고 명시 — 마크다운 마커만 쓰게 유도.

## 파싱 파이프라인 변경 (`parse_task_draft_response`)

```
raw (LLM 응답)
  -> _extract_json_block()         (기존, 변경 없음)
  -> json.loads()                  (기존, 변경 없음)
  -> _stringify_field(value)       (기존, 변경 없음 - 리스트/객체 방어)
  -> render_field_html(text)       (신규 - 9개 필드 전부에 적용)
```

`render_field_html`은 순수 함수(입력 텍스트 → 출력 HTML)라 어떤 필드든 동일하게 적용 가능.
필드별로 분기하지 않는다 — `background`가 다른 필드와 다르게 보이는 건 프롬프트가 그 필드에서만
`##` 마커를 쓰도록 유도했기 때문이지, 파싱 코드가 필드를 구분해서가 아니다.

## 가드레일 변경 (`draft_guardrail.py`)

`TASK_FALLBACK_MESSAGE`는 지금 `<p>` 태그 없는 순수 문자열이다. `export_project`의
`html_to_text`가 `h3`/`p` 태그만 훑기 때문에, 이대로 두면 가드레일 발동 시(유사 사업 부족)
안내문이 미리보기/내보내기에서 통째로 사라진다.

`apply_task_guardrail`에서 fallback으로 9개 필드를 채울 때 `TASK_FALLBACK_MESSAGE`를
그대로 넣지 않고 `render_field_html(TASK_FALLBACK_MESSAGE)`를 거쳐서 `<p>...</p>`로 감싼 뒤
채운다.

## 영향받는 파일

| 파일 | 변경 내용 |
|---|---|
| `app/classifier/draft_html.py` | 신규. `render_field_html()` |
| `app/classifier/ollama_client.py` | 프롬프트 문구 변경, `parse_task_draft_response`에 `render_field_html` 호출 추가 |
| `app/classifier/draft_guardrail.py` | fallback 필드 채울 때 `render_field_html` 적용 |
| `tests/test_task_draft_parsing.py` | HTML 변환 케이스 추가 (`##`/`-` 마커 → h3/p 변환 확인) |
| `tests/test_task_guardrail_logic.py` | fallback 결과가 `<p>` 태그로 감싸져 있는지 확인 |

`app/vectorstore/task_chroma_client.py`(시드 데이터/벡터화 대상)와
`app/classifier/draft_guardrail.py`의 `verify_task_draft_claims`(금액/기간 정규식 검증)는
변경 없음 — 정규식은 마크다운 마커가 섞여도 숫자 패턴 매칭에 영향받지 않는다.

## 에러 처리

- `render_field_html`은 입력이 어떤 텍스트든(마커가 하나도 없어도, 형식이 어긋나도) 예외를
  던지지 않고 항상 유효한 HTML 문자열을 반환한다 — 인식 못 한 줄은 그냥 `<p>` 문단으로 처리.
- 기존 JSON 파싱 실패/필드 누락 시 재시도·500 에러 흐름은 변경 없음.

## 테스트 계획

- `render_field_html` 단위 테스트: `## 제목`, `- 항목`, 일반 줄, 빈 줄, HTML 특수문자
  이스케이프 각각 확인
- `parse_task_draft_response`: 9개 필드 모두 결과값이 `<`로 시작하는 HTML인지(순수 텍스트가
  그대로 남아있지 않은지) 확인
- `apply_task_guardrail`: fallback 발동 시 9개 필드 값이 `<p>...</p>` 형태인지 확인
- 실제 Ollama 모델 호출로 `background` 필드가 실제로 `<h3>추진 배경</h3>` /
  `<h3>사업 필요성</h3>` 두 소제목을 포함하는지 수동 확인 (모델이 지시를 안 따를 가능성이
  있으므로 자동 테스트로 강제하지 않고 육안 확인 + 프롬프트 튜닝으로 보완)

## 위험 요소 / 열린 질문

- 마크다운 마커 추가로 프롬프트 출력 토큰이 늘어나 기존 `num_predict: 800`으로는 9개 필드
  전체를 다 못 채우고 잘릴 가능성이 있다. 구현 단계에서 실제 응답 길이를 보고 필요 시
  `num_predict`를 올린다(설계 시점에 미리 확정하지 않음 - 과도한 선제 최적화 방지).
- 모델이 `background` 필드에서 `##` 마커를 지시대로 안 쓸 수 있다. 이 경우
  `render_field_html`이 마커 없는 일반 텍스트로 안전하게 처리하므로 기능이 깨지지는 않지만,
  "두 소제목으로 분리해서 보인다"는 요구사항은 충족되지 않는다. 재현되면 프롬프트에 예시를
  더 강화하는 방식으로 후속 대응.

## 범위 밖(이번 설계에 포함하지 않음)

- `ieum_backend`의 `Project` 모델에 9개 섹션 컬럼 추가, `ieum_frontend`의
  `SectionEditor` 컴포넌트 구현 — 두 저장소 모두 현재 이 구조가 없고, 이번 설계는 `ieum_ai`가
  내려주는 응답 형식만 다룬다.
- `background` 외 나머지 8개 필드를 프론트 템플릿의 세부 하위 항목(가/나, 산출근거 등)까지
  전부 재현하도록 강제하는 것 — `- ` 목록으로 항목이 분리되는 정도까지만 다루고, 프론트
  템플릿의 모든 플레이스홀더 구조를 1:1로 맞추지는 않는다.
