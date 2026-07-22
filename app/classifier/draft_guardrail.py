# -*- coding: utf-8 -*-
"""
답변(draft) 텍스트에 등장하는 '구체적 사실'(법조문 번호, 금액, 기간 등)이
참고사례(referenced_cases) 원문에 실제로 존재하는지 검증하는 후처리 모듈.

목적: 가드레일(유사도 임계값)만으로는 못 막는 문제 보완.
     "참고사례는 관련 있게 잘 찾아왔는데, 모델이 그 안에 없는 숫자/법조문을 지어내는" 케이스 탐지.

사용 위치: app/classifier/ollama_client.py의 generate_draft_answer() 호출 직후,
          /api/draft 응답을 만들기 전에 verify_draft_claims()를 거치도록 연결.
"""
import re

from app.vectorstore.task_chroma_client import TASK_FIELDS
from app.classifier.draft_html import render_field_html


# ── 1. 답변 텍스트에서 '검증이 필요한 구체적 사실'을 추출하는 패턴들 ──────────

_LAW_ARTICLE_PATTERN = re.compile(r"[가-힣]+(?:\s[가-힣]+){0,5}\s*제\s*\d+\s*조(?:의\s*\d+)?(?:\s*제\s*\d+\s*항)?")

PATTERNS = {
    "금액": re.compile(r"\d[\d,]*\s*(?:원|천원|만원|천만원|억원)"),
    "기간_일수": re.compile(r"\d+\s*(?:영업일|일|주|개월|년)(?:\s*이내|\s*이상|\s*미만|\s*이하)?"),
    "퍼센트": re.compile(r"\d+(?:\.\d+)?\s*(?:%|퍼센트|프로)"),
}


def _extract_law_claims(text: str) -> list[str]:
    """법 이름(여러 단어 가능, '법' 또는 '법률'로 끝남) + 제N조 패턴을 추출."""
    results = []
    for m in _LAW_ARTICLE_PATTERN.finditer(text):
        full = m.group(0)
        name_part = re.split(r"제\s*\d+\s*조", full)[0].strip()
        if name_part.endswith("법") or name_part.endswith("법률"):
            results.append(full)
    return results


def _normalize(s: str) -> str:
    """공백 차이로 인한 오탐 방지용 정규화."""
    return re.sub(r"\s+", "", s)


def extract_claims(text: str) -> dict[str, list[str]]:
    """답변 텍스트에서 카테고리별 구체적 사실 조각을 추출."""
    claims = {}

    law_claims = _extract_law_claims(text)
    if law_claims:
        claims["법조문"] = list(set(law_claims))

    for category, pattern in PATTERNS.items():
        matches = pattern.findall(text)
        if matches:
            claims[category] = list(set(matches))
    return claims


def verify_draft_claims(draft_text: str, referenced_cases: list[dict]) -> dict:
    """
    draft_text에서 추출한 구체적 사실이 referenced_cases의 원문(document)에
    실제로 존재하는지 대조 (공백 차이는 무시하고 비교).

    Returns:
        {
            "unverified_claims": {"법조문": ["건축법 제73조"], ...},  # 참고사례에 없는 것들
            "verified_claims": {"금액": ["10만원"], ...},              # 참고사례에 있어서 확인된 것들
            "has_unverified": bool,  # 하나라도 검증 안 된 게 있으면 True
        }
    """
    reference_text = " ".join(
        f"{case.get('title', '')} {case.get('content', '')} {case.get('answer', '')}"
        for case in referenced_cases
    )
    reference_norm = _normalize(reference_text)

    claims = extract_claims(draft_text)
    unverified = {}
    verified = {}

    for category, items in claims.items():
        unverified_items = [item for item in items if _normalize(item) not in reference_norm]
        verified_items = [item for item in items if _normalize(item) in reference_norm]
        if unverified_items:
            unverified[category] = unverified_items
        if verified_items:
            verified[category] = verified_items

    return {
        "unverified_claims": unverified,
        "verified_claims": verified,
        "has_unverified": bool(unverified),
    }


def apply_guardrail(
    draft_text: str,
    referenced_cases: list[dict],
    similarity_threshold: float = 65.0,
    fallback_message: str = (
        "유사 사례가 충분히 확인되지 않아 AI 초안을 생성하지 못했습니다. "
        "담당자가 현장 확인 후 직접 답변을 작성해 주세요."
    ),
) -> dict:
    """
    두 단계 가드레일을 순서대로 적용:
    1) 유사도 가드레일: top1 유사도가 threshold 미만이면 draft 자체를 fallback으로 교체
    2) 사실 검증 가드레일: 유사도는 통과했지만 검증 안 된 구체적 사실이 있으면 경고 플래그만 추가
       (draft는 그대로 두되, has_unverified=True로 표시해 화면에 "⚠검토 필요" 배지 등을 붙일 수 있게 함)

    Returns:
        {
            "draft": str,               # 최종 draft (fallback으로 교체됐을 수도 있음)
            "guardrail_triggered": bool, # 유사도 가드레일 작동 여부
            "verification": dict,        # verify_draft_claims() 결과 (fallback 처리 시엔 스킵)
        }
    """
    top1_similarity = referenced_cases[0]["similarity"] if referenced_cases else 0.0

    if top1_similarity < similarity_threshold:
        return {
            "draft": fallback_message,
            "guardrail_triggered": True,
            "verification": None,
        }

    verification = verify_draft_claims(draft_text, referenced_cases)
    return {
        "draft": draft_text,
        "guardrail_triggered": False,
        "verification": verification,
    }


# ── 사업계획서 초안용 가드레일 (민원용과 별도 함수 - 검증 대상이 다름) ──────────

TASK_FALLBACK_MESSAGE = "참고할 만한 유사 사업이 충분하지 않습니다. 담당자가 직접 작성해주세요."


def extract_task_claims(text: str) -> dict[str, list[str]]:
    """사업계획 초안에서 검증이 필요한 구체적 사실(금액, 기간)만 추출.
    민원용 extract_claims()와 달리 법조문·퍼센트는 검사하지 않음
    (내부 참고용 초안이라 법적 근거 검증까지는 불필요하다고 판단)."""
    claims = {}
    for category in ("금액", "기간_일수"):
        matches = PATTERNS[category].findall(text)
        if matches:
            claims[category] = list(set(matches))
    return claims


def verify_task_draft_claims(draft_fields: dict, referenced_tasks: list[dict]) -> dict:
    """
    draft_fields의 budget, schedule 텍스트에서 추출한 금액/기간이 referenced_tasks의
    9개 필드(TASK_FIELDS) 원문에 실제로 존재하는지 대조.
    """
    reference_text = " ".join(
        " ".join(str(task.get(field, "")) for field in TASK_FIELDS)
        for task in referenced_tasks
    )
    reference_norm = _normalize(reference_text)

    target_text = f"{draft_fields.get('budget', '')} {draft_fields.get('schedule', '')}"
    claims = extract_task_claims(target_text)

    unverified = {}
    verified = {}
    for category, items in claims.items():
        unverified_items = [item for item in items if _normalize(item) not in reference_norm]
        verified_items = [item for item in items if _normalize(item) in reference_norm]
        if unverified_items:
            unverified[category] = unverified_items
        if verified_items:
            verified[category] = verified_items

    return {
        "unverified_claims": unverified,
        "verified_claims": verified,
        "has_unverified": bool(unverified),
    }


def apply_task_guardrail(
    draft_fields: dict,
    referenced_tasks: list[dict],
    similarity_threshold: float = 65.0,
) -> dict:
    """
    두 단계 가드레일 (apply_guardrail()과 동일한 흐름, 대상만 9개 필드로 확장):
    1) 유사도 가드레일: top1 유사도가 threshold 미만이면 9개 필드 전체를
       TASK_FALLBACK_MESSAGE로 교체
    2) 사실 검증 가드레일: 유사도는 통과했지만 budget/schedule에 검증 안 된 금액/기간이
       있으면 has_unverified=True로 표시 (draft_fields는 그대로 두고 플래그만 추가)
    """
    top1_similarity = referenced_tasks[0]["similarity"] if referenced_tasks else 0.0

    if top1_similarity < similarity_threshold:
        fallback_html = render_field_html(TASK_FALLBACK_MESSAGE)
        fallback_fields = {field: fallback_html for field in TASK_FIELDS}
        return {
            "draft": fallback_fields,
            "guardrail_triggered": True,
            "verification": None,
        }

    verification = verify_task_draft_claims(draft_fields, referenced_tasks)
    return {
        "draft": draft_fields,
        "guardrail_triggered": False,
        "verification": verification,
    }


if __name__ == "__main__":
    # 간단한 동작 확인용 예시
    sample_draft = (
        "민원 처리에 관한 법률 제9조에 따라 대지는 도로에 2미터 이상 접하여야 하며, "
        "처리기간은 10영업일이고 수수료는 3천원이며 감면율은 30퍼센트입니다."
    )
    sample_cases = [
        {"document": "민원 처리에 관한 법률 제9조에 따라 처리기간은 연장될 수 있다..."},
    ]
    result = verify_draft_claims(sample_draft, sample_cases)
    print("검증 안 된 것:", result["unverified_claims"])
    print("검증 된 것:", result["verified_claims"])

