# -*- coding: utf-8 -*-
"""
task_chroma_client.py 동작 확인 스크립트 (실제 임베딩/리랭커 모델 사용, 목 없음 -
이 프로젝트의 다른 tests/*.py 와 같은 방식: 실행해서 assert 통과 여부를 확인).

실행 위치: ieum_ai 폴더 루트에서
    python tests/test_task_chroma_client.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.vectorstore.task_chroma_client import add_tasks_batch, search_similar_tasks

SAMPLE_TASKS = [
    {
        "task_id": 1, "year": 2024, "title": "노후 상수도관 정비 사업",
        "lead_department_code": "03", "collab_department_codes": ["01", "02"],
        "domain_code": "환경", "overview": "노후 상수도관을 정비하는 사업",
        "background": "b", "goals": "g", "detailed_plan": "d", "schedule": "s",
        "execution_system": "e", "budget": "1000만원", "expected_effect": "ef",
        "post_management": "p", "status_code": "완료",
    },
    {
        "task_id": 2, "year": 2024, "title": "스마트 신호체계 구축사업",
        "lead_department_code": "01", "collab_department_codes": ["05", "08"],
        "domain_code": "교통", "overview": "스마트 신호체계를 구축하는 사업",
        "background": "b", "goals": "g", "detailed_plan": "d", "schedule": "s",
        "execution_system": "e", "budget": "2000만원", "expected_effect": "ef",
        "post_management": "p", "status_code": "완료",
    },
    {
        "task_id": 3, "year": 2025, "title": "미세먼지 저감사업",
        "lead_department_code": "03", "collab_department_codes": ["01"],
        "domain_code": "환경", "overview": "도로 청소차를 확충하는 사업",
        "background": "b", "goals": "g", "detailed_plan": "d", "schedule": "s",
        "execution_system": "e", "budget": "3000만원", "expected_effect": "ef",
        "post_management": "p", "status_code": "진행중",
    },
]

print("샘플 3건 색인 중...")
add_tasks_batch(SAMPLE_TASKS)
print("색인 완료\n")

# 검증 1: 03(환경) 부서로 검색하면 03 소속 사업만 나와야 함
results = search_similar_tasks(
    title="노후 상수도관 정비 사업",
    overview="노후 상수도관을 정비하는 사업",
    lead_department_code="03",
    top_k=5,
)
assert len(results) > 0, "검색 결과가 0건입니다"
assert all(r["lead_department_code"] == "03" for r in results), f"부서 필터링 실패: {results}"
print(f"[통과] 03 부서 검색 결과 {len(results)}건 모두 lead_department_code=03")

# 검증 2: status_code="완료"만 나와야 함 (task_id=3은 진행중이라 제외되어야 함)
returned_ids = {r["task_id"] for r in results}
assert 3 not in returned_ids, f"진행중 사업(task_id=3)이 검색 결과에 포함됨: {results}"
print("[통과] 진행중 사업(task_id=3)은 검색 결과에서 제외됨")

# 검증 3: 01(교통) 부서로 검색하면 task_id=2만 나오고, collab_department_codes가 리스트로 복원돼야 함
results_01 = search_similar_tasks(
    title="스마트 신호체계 구축사업",
    overview="스마트 신호체계를 구축하는 사업",
    lead_department_code="01",
    top_k=5,
)
assert len(results_01) == 1 and results_01[0]["task_id"] == 2, f"01 부서 검색 결과 이상: {results_01}"
assert results_01[0]["collab_department_codes"] == ["05", "08"], f"collab_department_codes 복원 실패: {results_01[0]}"
print("[통과] 01 부서 검색 결과 1건, collab_department_codes 정상 복원")

print("\n모든 검증 통과")
