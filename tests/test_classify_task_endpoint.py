# -*- coding: utf-8 -*-
"""
/api/classify-task 엔드포인트 동작 확인 스크립트.

사전 조건:
    1) FastAPI 서버 실행 중: uvicorn app.main:app --port 8200
    2) data/task_category_ingest.py 실행 완료 (교통부 6개 Task 색인 완료)

8개 케이스 중 최소 6개 이상 정확히 매칭되면 성공.

실행: python tests/test_classify_task_endpoint.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests

BASE_URL = "http://localhost:8100"

CASES = [
    ("아스팔트가 파여서 위험합니다", "01", "도로시설관리과"),
    ("신호등이 고장났어요", "01", "교통시설관리과"),
    ("가로등이 꺼져있어요", "01", "교통시설관리과"),
    ("CCTV가 고장난 것 같아요", "01", "교통시설관리과"),
    ("불법주차 좀 단속해주세요", "01", "교통단속과"),
    ("버스 배차간격이 너무 길어요", "01", "대중교통과"),
    ("거주자 우선주차구역 관련 문의", "01", "주차관리과"),
    ("교통유발부담금이 얼마인가요", "01", "교통행정과"),
]

correct = 0
for complaint_text, department_code, expected in CASES:
    res = requests.post(f"{BASE_URL}/api/classify-task", json={
        "complaint_text": complaint_text,
        "department_code": department_code,
    }, timeout=30.0)
    res.raise_for_status()
    body = res.json()
    ok = body["task_name"] == expected
    correct += ok
    mark = "O" if ok else "X"
    print(f"[{mark}] '{complaint_text}' -> 예상: {expected}, 실제: {body['task_name']} (유사도 {body['similarity']})")

print(f"\n{correct}/{len(CASES)} 정확히 매칭됨")
assert correct >= 6, f"6개 미만 매칭 - 목표 미달 ({correct}/{len(CASES)})"
print("[통과] 8개 중 6개 이상 매칭 목표 달성")

print("\n" + "=" * 70)
print("[테스트] /api/index-task-category - 신규 업무과 색인 후 즉시 검색되는지 확인")
print("-" * 70)
TEST_TASK_ID = 9999  # 테스트 전용 고정 ID (재실행 시 upsert로 덮어써서 누적 안 됨)
res = requests.post(f"{BASE_URL}/api/index-task-category", json={
    "task_id": TEST_TASK_ID,
    "name": "테스트업무과",
    "department_code": "01",
    "description": "테스트용 업무과 설명입니다. 예: 테스트 민원이 들어왔어요.",
}, timeout=15.0)
res.raise_for_status()
assert res.json() == {"status": "indexed", "task_id": TEST_TASK_ID, "department_code": "01"}, res.json()
print("[통과] 색인 응답 정상")

res = requests.post(f"{BASE_URL}/api/classify-task", json={
    "complaint_text": "테스트 민원이 들어왔어요", "department_code": "01",
}, timeout=15.0)
body = res.json()
assert body["task_id"] == TEST_TASK_ID and body["task_name"] == "테스트업무과", body
print("[통과] 색인 직후 신규 업무과가 검색됨:", body)

res = requests.post(f"{BASE_URL}/api/index-task-category", json={
    "task_id": 1, "name": "x", "department_code": "99", "description": "y",
}, timeout=10.0)
assert res.status_code == 400, f"잘못된 department_code인데 400이 아님: {res.status_code}"
print("[통과] 잘못된 department_code=99 요청에 400 반환")

from app.vectorstore.chroma_client import get_task_category_collection
get_task_category_collection().delete(ids=["01_9999"])
print("[정리] 테스트용 업무과 삭제 완료")
