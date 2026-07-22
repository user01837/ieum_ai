# -*- coding: utf-8 -*-
"""
/api/classify-department 엔드포인트 동작 확인 스크립트.

사전 조건:
    1) FastAPI 서버 실행 중: uvicorn app.main:app --reload --port 8100
    2) Ollama 실행 중, 분류 모델(handover-classifier) 로드 가능

실행: python tests/test_classify_department_endpoint.py
"""
import requests

BASE_URL = "http://localhost:8100"

print("=" * 70)
print("[테스트 1] 교통 관련 민원 -> 01")
print("-" * 70)
res = requests.post(f"{BASE_URL}/api/classify-department", json={
    "title": "버스정류장 앞 불법주차 신고",
    "content": "버스정류장 앞에 차량이 계속 불법주차를 해서 승하차가 어렵습니다.",
}, timeout=30.0)
res.raise_for_status()
body = res.json()
print("응답:", body)
assert "department_code" in body, f"department_code 필드 누락: {body}"
assert body["department_code"] in {"01", "02", "03", "04", "05", "06", "07", "08"}, body
print("[통과] department_code가 01~08 중 하나로 반환됨:", body["department_code"])

print("\n모든 테스트 통과")
