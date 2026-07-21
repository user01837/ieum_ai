# -*- coding: utf-8 -*-
"""
/api/similar-tasks, /api/task-draft 엔드포인트 동작 확인 스크립트.

사전 조건:
    1) FastAPI 서버 실행 중: uvicorn app.main:app --reload --port 8100
    2) Ollama 실행 중, generation 모델(llama3.1:8b) 로드 가능
    3) data/seed_tasks_ingest.py 실행 완료 (120건 색인 완료 상태 - Task 2)

실행: python tests/test_task_draft_endpoints.py
"""
import requests

BASE_URL = "http://localhost:8100"

TASK_FIELDS = [
    "overview", "background", "goals", "detailed_plan", "schedule",
    "execution_system", "budget", "expected_effect", "post_management",
]

print("=" * 70)
print("[테스트 1] /api/similar-tasks - 03(환경) 부서로 검색")
print("-" * 70)
res = requests.post(f"{BASE_URL}/api/similar-tasks", json={
    "title": "노후 상수도관 정비 사업",
    "overview": "관내 노후 상수도관을 정비하여 누수를 예방하는 사업",
    "lead_department_code": "03",
    "top_k": 3,
}, timeout=30.0)
res.raise_for_status()
results = res.json()["results"]
assert len(results) > 0, "검색 결과가 0건입니다 - seed_tasks_ingest.py 실행 여부를 확인하세요"
assert all(r["lead_department_code"] == "03" for r in results), f"부서 필터링 실패: {results}"
print(f"[통과] {len(results)}건 검색, 모두 lead_department_code=03")

print("\n" + "=" * 70)
print("[테스트 2] /api/task-draft - 정상 케이스(유사사업 있음)")
print("-" * 70)
res = requests.post(f"{BASE_URL}/api/task-draft", json={
    "title": "노후 상수도관 정비 사업 2차",
    "overview": "1차 사업에서 다루지 못한 구간의 노후 상수도관을 정비하는 사업",
    "lead_department_code": "03",
}, timeout=120.0)
res.raise_for_status()
body = res.json()
print("응답 필드:", list(body.keys()))
assert set(TASK_FIELDS).issubset(body["draft"].keys()), f"draft에 9개 필드 누락: {body['draft'].keys()}"
print("[통과] draft에 9개 필드 모두 존재")
print("guardrail_triggered:", body["guardrail_triggered"])
print("needs_review:", body["needs_review"])
print("execution_system(앞부분):", body["draft"]["execution_system"][:100])

print("\n" + "=" * 70)
print("[테스트 3] /api/task-draft - 유사사업 없을 법한 케이스 (fallback 확인)")
print("-" * 70)
res = requests.post(f"{BASE_URL}/api/task-draft", json={
    "title": "화성 이주 정착촌 건설 사업",
    "overview": "화성에 정착촌을 건설하는 사업",
    "lead_department_code": "03",
}, timeout=180.0)
res.raise_for_status()
body = res.json()
assert body["guardrail_triggered"] is True, f"낮은 유사도인데 guardrail이 작동하지 않음: {body}"
assert all(
    v == "참고할 만한 유사 사업이 충분하지 않습니다. 담당자가 직접 작성해주세요."
    for v in body["draft"].values()
), body["draft"]
print("[통과] 낮은 유사도 케이스에서 guardrail_triggered=True, 9개 필드 모두 안내문으로 대체됨")

print("\n" + "=" * 70)
print("[테스트 4] /api/task-draft - 잘못된 lead_department_code (400 에러 확인)")
print("-" * 70)
res = requests.post(f"{BASE_URL}/api/task-draft", json={
    "title": "테스트", "overview": "테스트", "lead_department_code": "99",
}, timeout=10.0)
assert res.status_code == 400, f"잘못된 부서코드인데 400이 아님: {res.status_code}"
print("[통과] 잘못된 lead_department_code=99 요청에 400 반환")

print("\n모든 테스트 통과")
