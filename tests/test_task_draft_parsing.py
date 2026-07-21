# -*- coding: utf-8 -*-
"""
parse_task_draft_response()는 순수 함수(네트워크 호출 없음)라 바로 assert로 검증 가능.

실행: python tests/test_task_draft_parsing.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.classifier.ollama_client import parse_task_draft_response

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

print("\n모든 검증 통과")
