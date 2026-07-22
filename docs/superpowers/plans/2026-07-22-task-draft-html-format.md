# 사업계획서 AI 초안 HTML 출력 + 배경 필드 세분화 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `generate_task_draft()`가 반환하는 9개 필드를 프론트엔드 SectionEditor/export가 기대하는 h3/p HTML로 바꾸고, `background` 필드를 "추진 배경"/"사업 필요성" 두 소제목으로 세분화한다.

**Architecture:** LLM은 HTML 태그를 직접 쓰지 않고 가벼운 마크다운(`## 제목`, `- 항목`)만 쓰도록 프롬프트를 바꾼다. 신규 순수 함수 `render_field_html()`이 이 마크다운 텍스트를 결정적으로 `<h3>`/`<p>` HTML로 변환하며, `parse_task_draft_response()`와 `apply_task_guardrail()`의 fallback 경로 양쪽에서 호출된다.

**Tech Stack:** Python (표준 라이브러리 `html`만 추가 사용, 신규 의존성 없음). 기존 `ollama_client.py`/`draft_guardrail.py`/`task_chroma_client.py` 구조 유지.

## Global Constraints

- 테스트는 이 저장소의 기존 관례대로 pytest가 아닌 **plain script 스타일**(`assert` + `print("[통과] ...")`, `python tests/xxx.py`로 직접 실행)로 작성한다. 다른 테스트 파일과 다른 프레임워크를 새로 들이지 않는다.
- `TASK_FIELDS`(9개 키 목록, `app/vectorstore/task_chroma_client.py`)는 변경하지 않는다 — 스키마는 그대로 두고 값의 형식만 바꾼다.
- 신규 코드에 주석은 "왜"가 비직관적일 때만 남긴다("무엇"은 코드 자체로 드러나야 함).

---

### Task 1: `render_field_html()` 변환 함수

**Files:**
- Create: `app/classifier/draft_html.py`
- Test: `tests/test_draft_html.py`

**Interfaces:**
- Produces: `render_field_html(text: str) -> str` — Task 2, Task 3에서 그대로 가져다 쓴다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_draft_html.py` 생성:

```python
# -*- coding: utf-8 -*-
"""
render_field_html()는 순수 함수(네트워크 호출 없음)라 바로 assert로 검증 가능.

실행: python tests/test_draft_html.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.classifier.draft_html import render_field_html

# 케이스 1: "## 제목" -> <h3>
assert render_field_html("## 추진 배경") == "<h3>추진 배경</h3>"
print("[통과] ## 제목 -> h3 변환")

# 케이스 2: "- 항목" -> □ 접두 <p>
assert render_field_html("- 현재 업무 현황") == "<p>&nbsp;&nbsp;&nbsp;&nbsp;□ 현재 업무 현황</p>"
print("[통과] - 항목 -> □ 접두 p 변환")

# 케이스 3: "□ 항목" -> 동일하게 □ 접두 <p> (이미 □로 쓴 경우도 지원)
assert render_field_html("□ 발생 문제") == "<p>&nbsp;&nbsp;&nbsp;&nbsp;□ 발생 문제</p>"
print("[통과] □ 항목 -> □ 접두 p 변환")

# 케이스 4: 일반 줄 -> <p>
assert render_field_html("일반 문장입니다.") == "<p>일반 문장입니다.</p>"
print("[통과] 일반 줄 -> p 변환")

# 케이스 5: 빈 줄은 무시(단락 구분용, 별도 태그 생성 안 함)
assert render_field_html("첫줄\n\n둘째줄") == "<p>첫줄</p>\n<p>둘째줄</p>"
print("[통과] 빈 줄은 무시하고 앞뒤 줄만 변환")

# 케이스 6: 제목+목록 혼합 여러 줄을 한 번에 변환
multi = "## 추진 배경\n- 현재 업무 현황\n- 발생 문제"
expected = (
    "<h3>추진 배경</h3>\n"
    "<p>&nbsp;&nbsp;&nbsp;&nbsp;□ 현재 업무 현황</p>\n"
    "<p>&nbsp;&nbsp;&nbsp;&nbsp;□ 발생 문제</p>"
)
assert render_field_html(multi) == expected, render_field_html(multi)
print("[통과] 제목+목록 혼합 여러 줄 변환")

# 케이스 7: HTML 특수문자는 이스케이프해서 태그가 깨지지 않도록 함
assert render_field_html("A<B> & C") == "<p>A&lt;B&gt; &amp; C</p>"
print("[통과] HTML 특수문자 이스케이프")

# 케이스 8: 빈 문자열 입력 -> 빈 문자열 출력 (예외 없이 안전하게 처리)
assert render_field_html("") == ""
print("[통과] 빈 문자열 입력 시 빈 문자열 반환")

print("\n모든 검증 통과")
```

- [ ] **Step 2: 테스트 실행해서 실패 확인**

Run: `python tests/test_draft_html.py`
Expected: `ModuleNotFoundError: No module named 'app.classifier.draft_html'`

- [ ] **Step 3: 최소 구현 작성**

`app/classifier/draft_html.py` 생성:

```python
# -*- coding: utf-8 -*-
"""
LLM이 생성한 마크다운 라이트 텍스트를 프론트엔드 SectionEditor가 기대하는
h3/p 구조 HTML로 변환하는 모듈.

LLM에게 HTML 태그를 직접 쓰게 하지 않는 이유: JSON 문자열 안에 태그가 안 깨진
HTML을 정확히 넣는 것보다, "## 제목"/"- 항목" 같은 마크다운 마커 몇 개만 인식하게
하는 쪽이 로컬 8B 모델에게 훨씬 안정적이다(ollama_client.py의 _stringify_field
참고 - 이 모델은 "문자열만 쓰라"는 지시도 종종 어긴 전례가 있음). 마커를 못
지켜도 일반 문단으로 안전하게 열화될 뿐, HTML 자체가 깨지지는 않는다.
"""
import html


def render_field_html(text: str) -> str:
    """텍스트를 줄 단위로 순회하며 3가지 패턴만 변환한다(YAGNI - 이 프로젝트
    프롬프트가 실제로 쓰는 만큼만 지원):
      "## 제목"            -> <h3>제목</h3>
      "- 항목" / "□ 항목"  -> <p>&nbsp;&nbsp;&nbsp;&nbsp;□ 항목</p>
      그 외 일반 줄         -> <p>줄 내용</p>
    빈 줄은 단락 구분용으로만 쓰이고 출력에는 나타나지 않는다.
    지원하지 않는 마크다운 문법(굵게, 링크 등)은 일반 텍스트로 취급한다.
    """
    lines = []
    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("## "):
            content = html.escape(line[3:].strip())
            lines.append(f"<h3>{content}</h3>")
        elif line.startswith("- ") or line.startswith("□ "):
            content = html.escape(line[2:].strip())
            lines.append(f"<p>&nbsp;&nbsp;&nbsp;&nbsp;□ {content}</p>")
        else:
            lines.append(f"<p>{html.escape(line)}</p>")
    return "\n".join(lines)
```

- [ ] **Step 4: 테스트 실행해서 통과 확인**

Run: `python tests/test_draft_html.py`
Expected: 마지막 줄에 `모든 검증 통과` 출력, 예외 없음

- [ ] **Step 5: 커밋**

```bash
git add app/classifier/draft_html.py tests/test_draft_html.py
git commit -m "feat: 사업계획 초안 필드용 마크다운-라이트 -> HTML 변환기 추가"
```

---

### Task 2: `generate_task_draft`/`parse_task_draft_response`에 HTML 변환 연결

**Files:**
- Modify: `app/classifier/ollama_client.py:1-9` (import 추가), `app/classifier/ollama_client.py:139-149` (`parse_task_draft_response`), `app/classifier/ollama_client.py:165-180` (프롬프트)
- Test: `tests/test_task_draft_parsing.py` (기존 파일 수정)

**Interfaces:**
- Consumes: `render_field_html(text: str) -> str` (Task 1에서 정의)
- Produces: `parse_task_draft_response(raw: str) -> dict` — 반환값의 9개 필드가 이제 HTML 문자열이라는 점이 바뀜(다른 태스크에 새 시그니처 없음, 기존 시그니처 유지)

- [ ] **Step 1: 실패하는 테스트로 갱신**

`tests/test_task_draft_parsing.py` 전체를 아래 내용으로 교체(기존 5개 케이스의 기대값을 HTML로 갱신 + 6번 케이스 신규 추가):

```python
# -*- coding: utf-8 -*-
"""
parse_task_draft_response()는 순수 함수(네트워크 호출 없음)라 바로 assert로 검증 가능.

실행: python tests/test_task_draft_parsing.py
"""
import sys
import os
import json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.classifier.ollama_client import parse_task_draft_response, _stringify_field

VALID_JSON = """{
    "overview": "o", "background": "b", "goals": "g", "detailed_plan": "d",
    "schedule": "s", "execution_system": "e", "budget": "1000만원",
    "expected_effect": "ef", "post_management": "p"
}"""

# 케이스 1: 정상 JSON만 온 경우 - 값이 <p>...</p> HTML로 변환되는지 확인
result = parse_task_draft_response(VALID_JSON)
assert result["budget"] == "<p>1000만원</p>", result
assert set(result.keys()) == {
    "overview", "background", "goals", "detailed_plan", "schedule",
    "execution_system", "budget", "expected_effect", "post_management",
}
print("[통과] 정상 JSON 파싱 + HTML 변환")

# 케이스 2: JSON 앞뒤에 모델이 군더더기 텍스트를 붙인 경우
WRAPPED = f"물론입니다! 요청하신 JSON은 다음과 같습니다:\n{VALID_JSON}\n감사합니다."
result2 = parse_task_draft_response(WRAPPED)
assert result2["overview"] == "<p>o</p>", result2
print("[통과] 앞뒤 군더더기 텍스트가 있어도 JSON 블록만 추출")

# 케이스 3: 필드 누락 시 ValueError
INCOMPLETE = '{"overview": "o", "background": "b"}'
try:
    parse_task_draft_response(INCOMPLETE)
    raise AssertionError("필드 누락인데 ValueError가 발생하지 않음")
except ValueError as e:
    print(f"[통과] 필드 누락 시 ValueError 발생: {e}")

# 케이스 4: JSON 자체가 아예 없을 때 ValueError
try:
    parse_task_draft_response("죄송합니다, 답변을 생성할 수 없습니다.")
    raise AssertionError("JSON 없는데 ValueError가 발생하지 않음")
except ValueError as e:
    print(f"[통과] JSON 블록 없을 때 ValueError 발생: {e}")

# 케이스 5: LLM이 execution_system 등을 문자열 대신 리스트/객체로 반환한 경우
# (실사용 중 08 행정부 케이스에서 실제로 재현된 패턴)
LIST_VALUE_JSON = """{
    "overview": "o", "background": "b", "goals": "g", "detailed_plan": "d",
    "schedule": "s",
    "execution_system": [
        {"department": "행정부(정보화담당관)", "role": "사업 총괄 및 시스템 구축"},
        {"department": "복지부", "role": "대상자 데이터 제공"}
    ],
    "budget": "1000만원", "expected_effect": "ef", "post_management": "p"
}"""
result5 = parse_task_draft_response(LIST_VALUE_JSON)
assert isinstance(result5["execution_system"], str), result5["execution_system"]
assert "{" not in result5["execution_system"], f"파이썬 repr이 그대로 노출됨: {result5['execution_system']}"
assert "행정부(정보화담당관)" in result5["execution_system"]
assert "복지부" in result5["execution_system"]
print("[통과] 필드 값이 리스트/객체여도 파이썬 repr 없이 읽을 수 있는 문자열로 변환:", result5["execution_system"])

# 케이스 6: background 필드에 "## 소제목" + "- 항목" 마크다운이 있으면 h3/p로 세분화되어 변환됨
BACKGROUND_MD = (
    "## 추진 배경\n"
    "- 현재 업무 현황 설명\n"
    "- 발생 문제 설명\n"
    "\n"
    "## 사업 필요성\n"
    "- 행정 효율 개선 설명"
)
SECTIONED_JSON = json.dumps({
    "overview": "o", "background": BACKGROUND_MD, "goals": "g", "detailed_plan": "d",
    "schedule": "s", "execution_system": "e", "budget": "1000만원",
    "expected_effect": "ef", "post_management": "p",
}, ensure_ascii=False)
result6 = parse_task_draft_response(SECTIONED_JSON)
assert result6["background"] == (
    "<h3>추진 배경</h3>\n"
    "<p>&nbsp;&nbsp;&nbsp;&nbsp;□ 현재 업무 현황 설명</p>\n"
    "<p>&nbsp;&nbsp;&nbsp;&nbsp;□ 발생 문제 설명</p>\n"
    "<h3>사업 필요성</h3>\n"
    "<p>&nbsp;&nbsp;&nbsp;&nbsp;□ 행정 효율 개선 설명</p>"
), result6["background"]
print("[통과] background 필드의 ## 소제목이 h3/p로 세분화 변환됨")

# _stringify_field 자체 동작도 직접 확인
assert _stringify_field("plain") == "plain"
assert _stringify_field({"a": 1, "b": 2}) == "a: 1, b: 2"
assert _stringify_field([{"a": 1}, {"a": 2}]) == "a: 1 / a: 2"
print("[통과] _stringify_field 단위 동작 확인")

print("\n모든 검증 통과")
```

- [ ] **Step 2: 테스트 실행해서 실패 확인**

Run: `python tests/test_task_draft_parsing.py`
Expected: `AssertionError` at 케이스 1 (`result["budget"] == "<p>1000만원</p>"` — 아직 `render_field_html`을 호출하지 않으므로 실제 값은 `"1000만원"`)

- [ ] **Step 3: `ollama_client.py`에 변환 연결 + 프롬프트 갱신**

`app/classifier/ollama_client.py:9` 바로 다음 줄에 import 추가:

```python
from app.vectorstore.task_chroma_client import TASK_FIELDS
from app.classifier.draft_html import render_field_html
```

`app/classifier/ollama_client.py:139-149`의 `parse_task_draft_response`를 아래로 교체:

```python
def parse_task_draft_response(raw: str) -> dict:
    """
    LLM 원본 응답 문자열을 9개 필드(TASK_FIELDS) dict로 파싱.
    JSON 파싱 실패, 또는 9개 필드 중 하나라도 없으면 ValueError.
    각 필드 값은 render_field_html()을 거쳐 h3/p 구조의 HTML 문자열로 변환된다.
    """
    json_block = _extract_json_block(raw)
    data = json.loads(json_block)
    missing = [f for f in TASK_FIELDS if f not in data]
    if missing:
        raise ValueError(f"응답에 누락된 필드: {missing}")
    return {
        field: render_field_html(_stringify_field(data[field]))
        for field in TASK_FIELDS
    }
```

`app/classifier/ollama_client.py:165-180`의 `generate_task_draft` 내부 `prompt = (...)` 블록을 아래로 교체:

```python
    prompt = (
        "다음은 새로 작성해야 할 사업의 사업명·개요와, 참고할 수 있는 과거 유사 완료사업입니다. "
        "아래 지침을 반드시 지켜 신규 사업 하나에 대한 사업계획서 초안을 작성하세요.\n"
        "- 반드시 아래 9개 key만 가진 하나의 JSON 객체로만 답하세요. JSON 앞뒤에 다른 설명을 붙이지 마세요.\n"
        "- key: overview, background, goals, detailed_plan, schedule, execution_system, budget, expected_effect, post_management\n"
        "- 각 key의 값은 반드시 하나의 문자열(string)이어야 합니다. 리스트나 중첩 객체로 작성하지 마세요.\n"
        "- 값 안에서 여러 항목을 나열할 때는 '1) 2) 3)' 같은 번호 대신, 줄마다 '- '로 시작해서 한 줄에 "
        "하나씩 쓰세요(JSON 문자열 안이므로 줄바꿈은 \\n으로 표현하세요).\n"
        "- HTML 태그(<, > 같은 것)는 절대 쓰지 마세요. 일반 텍스트와 '- ' 목록만 쓰세요.\n"
        "- background(추진 배경 및 필요성) 항목만 아래 형식처럼 '## 추진 배경'과 '## 사업 필요성' 두 "
        "소제목으로 나눠서, 각 소제목 아래에 '- '로 시작하는 항목을 2~3개씩 쓰세요. 예시:\n"
        "  ## 추진 배경\\n- (현재 업무에서 발견된 구체적 문제)\\n- (그로 인한 불편이나 민원)\\n\\n"
        "  ## 사업 필요성\\n- (이 사업으로 얻는 행정적 효과)\\n- (이 사업으로 얻는 시민 편익)\n"
        "- 참고사업의 추진체계(execution_system)와 사후관리(post_management)에 나온 부서 간 협업 방식과 "
        "시행착오를 적극 활용해서 구체적으로 작성하세요.\n"
        "- 참고사업에 없는 예산 금액이나 기간을 지어내지 마세요.\n"
        "- 참고사업 중 관련된 내용이 부족하면, 구체적인 수치를 확정하지 말고 일반적인 절차 위주로 작성하세요.\n\n"
        f"[신규 사업명]\n{title}\n\n"
        f"[신규 사업 개요]\n{overview}\n\n"
        f"[참고 사업]\n{context_block}\n\n"
        "[JSON 출력]"
    )
```

- [ ] **Step 4: 테스트 실행해서 통과 확인**

Run: `python tests/test_task_draft_parsing.py`
Expected: 마지막 줄에 `모든 검증 통과` 출력, 예외 없음

- [ ] **Step 5: 커밋**

```bash
git add app/classifier/ollama_client.py tests/test_task_draft_parsing.py
git commit -m "feat: 사업계획 초안 9개 필드를 HTML로 변환, background는 소제목 2개로 세분화"
```

---

### Task 3: 가드레일 fallback 메시지도 HTML로 감싸기

**Files:**
- Modify: `app/classifier/draft_guardrail.py:1-14` (import 추가), `app/classifier/draft_guardrail.py:183-210` (`apply_task_guardrail`)
- Test: `tests/test_task_guardrail_logic.py` (기존 파일 수정)

**Interfaces:**
- Consumes: `render_field_html(text: str) -> str` (Task 1에서 정의)
- Produces: `apply_task_guardrail(...) -> dict` — 유사도 미달 시 반환하는 9개 필드 값이 `<p>...</p>`로 감싸진 HTML이라는 점이 바뀜(시그니처 자체는 그대로)

- [ ] **Step 1: 실패하는 테스트로 갱신**

`tests/test_task_guardrail_logic.py`에서 케이스 3(41~46번째 줄)을 아래로 교체:

```python
# 케이스 3: apply_task_guardrail - 유사도 낮으면 9개 필드 전체가 fallback으로 교체(<p> HTML로 감싸짐)
low_sim_tasks = [{**REFERENCE_TASKS[0], "similarity": 40.0}]
guarded_low = apply_task_guardrail(draft2, low_sim_tasks, similarity_threshold=65.0)
assert guarded_low["guardrail_triggered"] is True, guarded_low
expected_fallback_html = f"<p>{TASK_FALLBACK_MESSAGE}</p>"
assert all(v == expected_fallback_html for v in guarded_low["draft"].values()), guarded_low["draft"]
print("[통과] 유사도 미달 시 9개 필드 전체가 fallback 문구(HTML)로 교체")
```

(파일의 다른 부분은 그대로 둔다.)

- [ ] **Step 2: 테스트 실행해서 실패 확인**

Run: `python tests/test_task_guardrail_logic.py`
Expected: `AssertionError` at 케이스 3 (현재 `guarded_low["draft"]`의 값은 `<p>` 없이 `TASK_FALLBACK_MESSAGE` 그대로)

- [ ] **Step 3: `draft_guardrail.py`에 변환 연결**

`app/classifier/draft_guardrail.py:14` 바로 다음 줄에 import 추가:

```python
from app.vectorstore.task_chroma_client import TASK_FIELDS
from app.classifier.draft_html import render_field_html
```

`app/classifier/draft_guardrail.py:197-203`(`apply_task_guardrail`의 유사도 미달 분기)를 아래로 교체:

```python
    if top1_similarity < similarity_threshold:
        fallback_html = render_field_html(TASK_FALLBACK_MESSAGE)
        fallback_fields = {field: fallback_html for field in TASK_FIELDS}
        return {
            "draft": fallback_fields,
            "guardrail_triggered": True,
            "verification": None,
        }
```

- [ ] **Step 4: 테스트 실행해서 통과 확인**

Run: `python tests/test_task_guardrail_logic.py`
Expected: 마지막 줄에 `모든 검증 통과` 출력, 예외 없음

- [ ] **Step 5: 관련 테스트 전체 재실행(회귀 확인)**

Run:
```bash
python tests/test_draft_html.py
python tests/test_task_draft_parsing.py
python tests/test_task_guardrail_logic.py
```
Expected: 3개 파일 모두 마지막 줄에 `모든 검증 통과`

- [ ] **Step 6: 커밋**

```bash
git add app/classifier/draft_guardrail.py tests/test_task_guardrail_logic.py
git commit -m "fix: 사업계획 초안 가드레일 fallback 문구를 <p> HTML로 감싸 내보내기 시 사라지지 않게 함"
```

---

### Task 4: 실제 모델 응답으로 background 소제목 분리 수동 확인

이 태스크는 자동화된 assert가 아니라, 로컬 8B 모델이 프롬프트 지시(`## 추진 배경` / `## 사업 필요성` 두 소제목)를 실제로 따르는지 눈으로 확인하는 단계다. 스펙의 "위험 요소" 항목(모델이 마커 지시를 안 따를 수 있음)을 검증한다.

**Files:**
- 없음(코드 변경 없음, 실행 확인만)

- [ ] **Step 1: Ollama 서버가 떠 있는지 확인**

Run: `curl http://localhost:11434/api/tags` (또는 `settings.ollama_host` 설정값)
Expected: 200 응답, `models` 목록에 `settings.generation_model_name` 모델 포함

- [ ] **Step 2: `generate_task_draft` 실측 호출**

Run (프로젝트 루트에서):
```bash
python -c "
import asyncio
from app.classifier.ollama_client import generate_task_draft

async def main():
    draft = await generate_task_draft(
        title='관내 버스승강장 저상화 사업',
        overview='노후 버스승강장을 저상화하여 교통약자 접근성을 개선',
        similar_tasks=[],
    )
    print(draft['background'])

asyncio.run(main())
"
```
Expected: 출력에 `<h3>추진 배경</h3>`와 `<h3>사업 필요성</h3>` 두 태그가 모두 포함됨

- [ ] **Step 3: 결과 기록**

- 두 소제목이 모두 나왔다면: 통과, 다음 태스크 없음.
- 하나라도 빠졌다면(모델이 지시를 어긴 경우): 코드를 고치지 말고, `docs/superpowers/specs/2026-07-22-task-draft-html-format-design.md`의 "위험 요소" 절에 실제로 재현된 사례로 업데이트하고, 프롬프트의 예시 문구를 더 구체화하는 후속 작업으로 넘긴다(이번 계획 범위 밖 — 설계 문서 자체가 "재현되면 프롬프트를 강화하는 방식으로 후속 대응"이라고 명시했음).

---

## Self-Review 결과

- **스펙 커버리지:** "LLM은 HTML 태그를 직접 쓰지 않는다"(Task 1), "background만 세분화"(Task 2 프롬프트), "가드레일 fallback도 변환기 통과"(Task 3), "위험 요소 수동 확인"(Task 4) 모두 태스크로 매핑됨. `verify_task_draft_claims`/시드데이터/벡터스토어는 스펙에서도 "변경 없음"이라 태스크를 만들지 않음.
- **플레이스홀더 스캔:** 없음 — 모든 스텝에 실행 가능한 코드/명령이 포함됨.
- **타입/시그니처 일관성:** `render_field_html(text: str) -> str`이 Task 1에서 정의된 그대로 Task 2, Task 3에서 동일하게 사용됨.
