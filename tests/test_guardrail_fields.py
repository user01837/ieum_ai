# -*- coding: utf-8 -*-
"""
가드레일 적용 확인용 간단 테스트.
/api/draft 응답 전체(JSON)를 그대로 찍어서 guardrail_triggered, needs_review,
unverified_claims 필드가 잘 나오는지 눈으로 확인하는 스크립트.

실행 위치: 어디서든 상관없음 (FastAPI 서버 8100 켜져 있으면 됨)
"""
import json
import requests

BASE_URL = "http://localhost:8100"

# 일부러 다른 성격의 질문 2개를 테스트 (하나는 유사도 높을 만한 것, 하나는 낮을 만한 것)
test_cases = [
    {
        "complaint_text": "소상공인 대출 지원을 문의하는 민원엔 어떻게 답변하나요?",
        "department_code": "ECON",
        "domain_code": "경제·산업",
    },
    {
        "complaint_text": "우주선 발사장 인근 소음 민원엔 어떻게 답변하나요?",  # 코퍼스에 없을 법한, 일부러 만든 케이스
        "department_code": "ECON",
        "domain_code": "경제·산업",
    },
]

for i, case in enumerate(test_cases, 1):
    print("=" * 70)
    print(f"[테스트 {i}] {case['complaint_text']}")
    print("-" * 70)

    res = requests.post(f"{BASE_URL}/api/draft", json=case, timeout=120.0)
    res.raise_for_status()
    body = res.json()

    # 전체 응답 구조 확인 (필드가 다 있는지)
    print("응답에 포함된 필드:", list(body.keys()))
    print()
    print("guardrail_triggered:", body.get("guardrail_triggered"))
    print("needs_review:", body.get("needs_review"))
    print("unverified_claims:", body.get("unverified_claims"))
    print()
    print("draft (앞부분 150자):", body.get("draft", "")[:150])
    print()
