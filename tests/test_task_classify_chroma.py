# -*- coding: utf-8 -*-
"""
chroma_client.py의 TASK(부서 내 세부업무) 분류용 함수 동작 확인 스크립트.

사업계획서용 task_chroma_client.py가 이미 "tasks"라는 컬렉션명을 쓰고 있어서
(부서01 기준 ID가 "01_1"~"01_30"까지 존재) 이름이 겹치면 upsert 시 서로 덮어쓰게 된다.
그래서 이 기능은 완전히 별도인 "task_categories" 컬렉션을 사용한다.

실행: python tests/test_task_classify_chroma.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tempfile
import shutil

from app.core.config import settings
settings.chroma_persist_dir = tempfile.mkdtemp(prefix="task_classify_test_")

from app.vectorstore.chroma_client import add_task_category, search_matching_task_category

SAMPLE_TASKS = [
    {"task_id": 1, "name": "도로시설관리과", "department_code": "01",
     "description": "도로 포장 파손, 포트홀(아스팔트 파임), 도로 균열, 배수로 문제, 도로표지판 불량, "
                     "자전거도로 파손 및 정비를 담당."},
    {"task_id": 2, "name": "교통시설관리과", "department_code": "01",
     "description": "신호등 고장·점멸·오작동, CCTV·무인단속카메라 고장, 가로등 고장·소등·조도 문제를 담당."},
    {"task_id": 1, "name": "복지시설관리과", "department_code": "04",
     "description": "복지시설의 노후 설비 점검 및 보수를 담당."},
]

for t in SAMPLE_TASKS:
    add_task_category(t["task_id"], t["name"], t["department_code"], t["description"])
print("샘플 3건 색인 완료\n")

# 검증 1: 부서 필터링 - 01 부서로 검색하면 04 소속(복지시설관리과)은 절대 안 나와야 함
results = search_matching_task_category("신호등이 고장났어요", "01", top_k=5)
assert len(results) > 0, "검색 결과가 0건입니다"
assert all(r["department_code"] == "01" for r in results), f"부서 필터링 실패: {results}"
assert all(r["name"] != "복지시설관리과" for r in results), f"타 부서 데이터가 섞여나옴: {results}"
print("[통과] 부서 필터링 정상 (04 소속 데이터 미노출)")

# 검증 2: 가장 관련있는 task가 top1로 나오는지
top1 = results[0]
assert top1["name"] == "교통시설관리과", f"예상과 다른 task가 top1: {top1}"
print("[통과] '신호등 고장' → 교통시설관리과로 정확히 매칭")

# 검증 3: top_k=1이면 1건만 반환되고, 응답에 task_id/name/department_code/similarity가 있어야 함
results_top1 = search_matching_task_category("아스팔트가 파였어요", "01", top_k=1)
assert len(results_top1) == 1
top = results_top1[0]
assert top["name"] == "도로시설관리과", f"예상과 다른 결과: {results_top1}"
assert set(top.keys()) == {"task_id", "name", "department_code", "similarity"}, f"응답 필드 이상: {top.keys()}"
print("[통과] top_k=1, '아스팔트 파임' → 도로시설관리과로 정확히 매칭, 응답 필드 정상")

print("\n모든 검증 통과")
shutil.rmtree(settings.chroma_persist_dir, ignore_errors=True)
