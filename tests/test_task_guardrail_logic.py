# -*- coding: utf-8 -*-
"""
verify_task_draft_claims / apply_task_guardrail 순수 로직 검증.
실행: python tests/test_task_guardrail_logic.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.classifier.draft_guardrail import (
    verify_task_draft_claims, apply_task_guardrail, TASK_FALLBACK_MESSAGE,
)
from app.vectorstore.task_chroma_client import TASK_FIELDS


def make_draft(budget="", schedule="사업 개요") -> dict:
    d = {field: "내용" for field in TASK_FIELDS}
    d["budget"] = budget
    d["schedule"] = schedule
    return d


REFERENCE_TASKS = [
    {**{f: "" for f in TASK_FIELDS}, "budget": "총사업비 3억원 (지방비 전액)", "schedule": "1분기 착공"},
]

# 케이스 1: draft의 금액이 참고사업 원문에 있는 경우 -> verified
draft1 = make_draft(budget="총사업비 3억원 규모로 추진")
result1 = verify_task_draft_claims(draft1, REFERENCE_TASKS)
assert "금액" in result1["verified_claims"], result1
assert result1["has_unverified"] is False, result1
print("[통과] 참고사업에 있는 금액은 verified_claims로 분류")

# 케이스 2: draft의 금액이 참고사업 원문에 없는 경우 -> unverified
draft2 = make_draft(budget="총사업비 99억원 규모로 추진")
result2 = verify_task_draft_claims(draft2, REFERENCE_TASKS)
assert "금액" in result2["unverified_claims"], result2
assert result2["has_unverified"] is True, result2
print("[통과] 참고사업에 없는 금액은 unverified_claims로 분류")

# 케이스 3: apply_task_guardrail - 유사도 낮으면 9개 필드 전체가 fallback으로 교체
low_sim_tasks = [{**REFERENCE_TASKS[0], "similarity": 40.0}]
guarded_low = apply_task_guardrail(draft2, low_sim_tasks, similarity_threshold=65.0)
assert guarded_low["guardrail_triggered"] is True, guarded_low
assert all(v == TASK_FALLBACK_MESSAGE for v in guarded_low["draft"].values()), guarded_low["draft"]
print("[통과] 유사도 미달 시 9개 필드 전체가 fallback 문구로 교체")

# 케이스 4: apply_task_guardrail - 유사도 충분하면 draft 그대로 + 검증 결과 포함
high_sim_tasks = [{**REFERENCE_TASKS[0], "similarity": 80.0}]
guarded_high = apply_task_guardrail(draft1, high_sim_tasks, similarity_threshold=65.0)
assert guarded_high["guardrail_triggered"] is False, guarded_high
assert guarded_high["draft"]["budget"] == draft1["budget"], guarded_high
assert guarded_high["verification"]["has_unverified"] is False, guarded_high
print("[통과] 유사도 충분 시 draft 원본 유지 + 검증 결과 포함")

# 케이스 5: 참고사업이 아예 없으면(빈 리스트) 유사도 0 취급 -> fallback
guarded_empty = apply_task_guardrail(draft1, [], similarity_threshold=65.0)
assert guarded_empty["guardrail_triggered"] is True, guarded_empty
print("[통과] 참고사업 0건이면 fallback 처리")

print("\n모든 검증 통과")
