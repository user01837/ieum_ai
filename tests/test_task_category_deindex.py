# -*- coding: utf-8 -*-
"""
/api/task-category 삭제 엔드포인트 동작 확인 스크립트.

사전 조건:
    1) FastAPI 서버 실행 중: uvicorn app.main:app --reload --port 8100

실행: python tests/test_task_category_deindex.py
"""
import requests

BASE_URL = "http://localhost:8100"
TEST_TASK_ID = 88888
TEST_DEPARTMENT = "01"

print("=" * 70)
print("[준비] 테스트용 업무 색인")
print("-" * 70)
res = requests.post(f"{BASE_URL}/api/index-task-category", json={
    "task_id": TEST_TASK_ID,
    "name": "삭제테스트용업무",
    "department_code": TEST_DEPARTMENT,
    "description": "삭제테스트용업무",
}, timeout=30.0)
res.raise_for_status()
print("색인 완료:", res.json())

print("\n" + "=" * 70)
print("[테스트 1] classify-task로 방금 색인한 업무가 검색되는지 확인")
print("-" * 70)
res = requests.post(f"{BASE_URL}/api/classify-task", json={
    "complaint_text": "삭제테스트용업무 관련 민원입니다",
    "department_code": TEST_DEPARTMENT,
}, timeout=30.0)
res.raise_for_status()
body = res.json()
print("classify-task 응답:", body)
assert body["task_id"] == TEST_TASK_ID, f"방금 색인한 업무가 top1으로 안 나옴: {body}"
print("[통과] 색인 직후 classify-task에서 검색됨")

print("\n" + "=" * 70)
print("[테스트 2] 삭제 엔드포인트 호출")
print("-" * 70)
res = requests.delete(f"{BASE_URL}/api/task-category/{TEST_DEPARTMENT}/{TEST_TASK_ID}", timeout=10.0)
res.raise_for_status()
body = res.json()
print("삭제 응답:", body)
assert body == {"status": "deleted", "task_id": TEST_TASK_ID, "department_code": TEST_DEPARTMENT}, body
print("[통과] 삭제 엔드포인트가 200과 함께 예상된 응답 반환")

print("\n" + "=" * 70)
print("[테스트 3] 삭제 후 classify-task에서 더 이상 top1으로 안 나오는지 확인")
print("-" * 70)
res = requests.post(f"{BASE_URL}/api/classify-task", json={
    "complaint_text": "삭제테스트용업무 관련 민원입니다",
    "department_code": TEST_DEPARTMENT,
}, timeout=30.0)
res.raise_for_status()
body = res.json()
print("classify-task 응답:", body)
assert body["task_id"] != TEST_TASK_ID, f"삭제했는데 여전히 top1으로 나옴: {body}"
print("[통과] 삭제 후에는 더 이상 검색되지 않음")

print("\n" + "=" * 70)
print("[테스트 4] 존재하지 않는 id를 다시 삭제해도 에러 안 나는지 확인(멱등)")
print("-" * 70)
res = requests.delete(f"{BASE_URL}/api/task-category/{TEST_DEPARTMENT}/{TEST_TASK_ID}", timeout=10.0)
res.raise_for_status()
print("[통과] 이미 삭제된 id를 다시 삭제해도 200 반환:", res.json())

print("\n모든 테스트 통과")
