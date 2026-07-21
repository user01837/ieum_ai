# -*- coding: utf-8 -*-
"""
parse_task_draft_response()는 순수 함수(네트워크 호출 없음)라 바로 assert로 검증 가능.

실행: python tests/test_task_draft_parsing.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.classifier.ollama_client import parse_task_draft_response, _stringify_field

VALID_JSON = """{
    "overview": "o", "background": "b", "goals": "g", "detailed_plan": "d",
    "schedule": "s", "execution_system": "e", "budget": "1000만원",
    "expected_effect": "ef", "post_management": "p"
}"""

# 케이스 1: 정상 JSON만 온 경우
result = parse_task_draft_response(VALID_JSON)
assert result["budget"] == "1000만원", result
assert set(result.keys()) == {
    "overview", "background", "goals", "detailed_plan", "schedule",
    "execution_system", "budget", "expected_effect", "post_management",
}
print("[통과] 정상 JSON 파싱")

# 케이스 2: JSON 앞뒤에 모델이 군더더기 텍스트를 붙인 경우
WRAPPED = f"물론입니다! 요청하신 JSON은 다음과 같습니다:\n{VALID_JSON}\n감사합니다."
result2 = parse_task_draft_response(WRAPPED)
assert result2["overview"] == "o", result2
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

# _stringify_field 자체 동작도 직접 확인
assert _stringify_field("plain") == "plain"
assert _stringify_field({"a": 1, "b": 2}) == "a: 1, b: 2"
assert _stringify_field([{"a": 1}, {"a": 2}]) == "a: 1 / a: 2"
print("[통과] _stringify_field 단위 동작 확인")

print("\n모든 검증 통과")
