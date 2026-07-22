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
