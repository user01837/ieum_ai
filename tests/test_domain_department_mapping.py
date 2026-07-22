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
