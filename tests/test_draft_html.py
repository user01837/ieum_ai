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
