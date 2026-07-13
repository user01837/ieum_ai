# -*- coding: utf-8 -*-
"""
RAGAS에서 context_precision=0.0으로 나온 5개 케이스를 직접 호출해서
실제로 /api/draft가 어떤 유사사례(referenced_cases)를 검색해오는지 확인하는 디버그 스크립트.
채점(OpenAI) 없이 순수하게 검색 결과만 눈으로 확인하는 용도.

실행 위치: ieum_ai/tests 폴더 (ragas_goldset_40.json이 같은 폴더에 있어야 함)
"""
import json
import requests

BASE_URL = "http://localhost:8100"

DOMAIN_TO_DEPT_CODE = {
    "교통": "TRAF",
    "주택·건축": "URBAN",
    "환경": "ENV",
    "복지": "WELF",
    "안전": "SAFETY",
    "경제·산업": "ECON",
    "문화·체육·관광": "CULT",
    "행정·일반": "GEN",
}

# CSV 기준 no=20,23,27,32,39 (0-indexed로는 19,22,26,31,38)
TARGET_NOS = [20, 23, 27, 32, 39]

with open("ragas_goldset_40.json", encoding="utf-8") as f:
    goldset = json.load(f)

targets = [item for item in goldset if item["no"] in TARGET_NOS]

for item in targets:
    no = item["no"]
    domain = item["domain"]
    question = item["question"]
    dept_code = DOMAIN_TO_DEPT_CODE.get(domain)

    print("=" * 70)
    print(f"[{no}] 도메인: {domain} | department_code: {dept_code}")
    print(f"질문: {question}")
    print(f"골드셋 기대 context: {item['context']}")
    print("-" * 70)

    try:
        res = requests.post(
            f"{BASE_URL}/api/draft",
            json={
                "complaint_text": question,
                "department_code": dept_code,
                "domain_code": domain,
            },
            timeout=120.0,
        )
        res.raise_for_status()
        body = res.json()
        referenced = body.get("referenced_cases", [])
        draft = body.get("draft", "")

        print(f"실제 검색된 유사사례 개수: {len(referenced)}")
        for i, case in enumerate(referenced):
            print(f"  사례 {i+1}: {case}")
        if not referenced:
            print("  ⚠ 검색 결과가 비어있음 (referenced_cases = [])")
        print(f"\n생성된 draft (앞부분 200자):\n{draft[:200]}")
    except Exception as e:
        print(f"[에러] {e}")
    print()
