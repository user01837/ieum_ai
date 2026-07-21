# -*- coding: utf-8 -*-
"""
/api/classify-task 엔드포인트 동작 확인 스크립트.

사전 조건:
    1) FastAPI 서버 실행 중: uvicorn app.main:app --port 8200
    2) data/seed_task_categories_ingest.py 실행 완료 (교통부 6개 Task 색인 완료)

8개 케이스 중 최소 6개 이상 정확히 매칭되면 성공.

실행: python tests/test_classify_task_endpoint.py
"""
import requests

BASE_URL = "http://localhost:8200"

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
