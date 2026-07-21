"""
Ollama에 등록된 모델(분류기 handover-classifier, 생성용 llama3.1:8b)을 호출하는 모듈.
"""
import httpx
import json
import re

from app.core.config import settings
from app.vectorstore.task_chroma_client import TASK_FIELDS


DOMAIN_CATEGORIES = ["교통", "주택·건축", "환경", "복지", "안전", "경제·산업", "문화·체육·관광", "행정·일반"]

# 파인튜닝 학습 데이터의 instruction과 완전히 동일한 문구.
# (한 글자라도 다르면 모델이 학습 때 본 패턴과 어긋나므로 임의로 수정 금지)
CLASSIFY_INSTRUCTION = (
    "다음 공무원 업무 텍스트를 아래 8개 카테고리 중 하나로만 분류하세요. "
    "카테고리: 교통, 주택·건축, 환경, 복지, 안전, 경제·산업, 문화·체육·관광, 행정·일반 "
    "카테고리 이름만 답하세요."
)

# 모델이 특정 단어에서 반복적으로 오분류하는 것을 확인한 경우, 원본 입력 텍스트 기준으로
# 규칙 기반 보정을 우선 적용한다. (재파인튜닝 전까지의 임시 보정 - 학습 데이터 보강 시 제거 검토)
CATEGORY_OVERRIDE_KEYWORDS = {
    "교통": ["주정차", "주차구역", "불법주차", "불법 주차", "우선주차구역", "거주자우선주차"],
}


def _rule_based_override(original_text: str) -> str | None:
    """원본 입력에 알려진 오분류 유발 단어가 있으면 해당 카테고리로 강제 지정."""
    for category, keywords in CATEGORY_OVERRIDE_KEYWORDS.items():
        if any(kw in original_text for kw in keywords):
            return category
    return None


def _extract_category(raw_response: str) -> str:
    """
    모델이 뒤에 다른 텍스트를 이어 붙이거나 설명을 더 생성해도,
    8개 정식 카테고리 중 실제로 등장한 것만 안전하게 추출한다.
    매칭되는 카테고리가 없으면 '행정·일반'으로 안전하게 폴백한다.
    """
    for category in DOMAIN_CATEGORIES:
        if category in raw_response:
            return category
    return "행정·일반"


async def classify_text(text: str) -> str:
    """텍스트를 8개 도메인 중 하나로 분류."""
    prompt = f"{CLASSIFY_INSTRUCTION}\n\n텍스트: {text}"

    async with httpx.AsyncClient(timeout=10.0) as client:
        res = await client.post(
            f"{settings.ollama_host}/api/generate",
            json={
                "model": settings.classifier_model_name,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "num_predict": 10,  # "안전", "주택·건축" 같은 짧은 카테고리명만 나오면 됨
                    "temperature": 0.1,
                },
            },
        )
        res.raise_for_status()
    raw = res.json()["response"].strip()

    # 1) 알려진 오분류 단어가 원본 텍스트에 있으면 규칙 기반으로 강제 보정
    override = _rule_based_override(text)
    if override:
        return override

    # 2) 없으면 모델 응답에서 파싱
    return _extract_category(raw)


async def generate_draft_answer(complaint_text: str, similar_cases: list[dict]) -> str:
    """유사 사례들을 근거로 삼아 답변 초안을 생성."""
    context_block = "\n\n".join(
        f"[유사사례 {i+1}] {c['title']}\n{c['content']}" for i, c in enumerate(similar_cases)
    )
    prompt = (
    "다음은 새로 접수된 민원과, 참고할 수 있는 과거 유사 사례입니다. "
    "아래 지침을 반드시 지켜 신규 민원 하나에 대한 답변 초안을 작성하세요.\n"
    "- 참고 사례를 하나씩 나열하거나 요약하지 말고, 신규 민원에 대한 하나의 통일된 답변만 작성하세요.\n"
    "- 참고 사례에 등장하는 구체적인 조치 방식(예: 어떤 조치를 했는지, 어떤 기준으로 판단했는지)이 "
    "이번 신규 민원과 관련 있다면 적극적으로 활용하여 최대한 구체적으로 답변하세요.\n"
    "- 참고 사례에 없는 사실(부서명, 조치 결과, 수치 등)을 지어내지 마세요.\n"
    "- 참고 사례 중 이번 민원과 실질적으로 관련된 내용이 전혀 없다면, 구체적인 결론을 확정하지 말고 "
    "현장 확인 후 절차를 진행하겠다는 취지로만 답하세요. 같은 문장을 반복하지 마세요.\n"
    "- 마크다운 서식(굵게, 제목, 번호 목록 등)을 쓰지 말고, 자연스러운 문단으로만 작성하세요.\n"
    "- '안녕하십니까. 귀하께서 제기하신 민원에 대해 답변드립니다.'로 시작하고, "
    "'~하였습니다', '~조치하겠습니다'처럼 확정적인 어조로 작성하세요.\n\n"
    f"[신규 민원]\n{complaint_text}\n\n"
    f"[참고 사례]\n{context_block}\n\n"
    "[답변 초안]"
)

    async with httpx.AsyncClient(timeout=120.0) as client:
        res = await client.post(
            f"{settings.ollama_host}/api/generate",
            json={
                "model": settings.generation_model_name,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.2,
                    "num_predict": 300,
                },
            },
        )
        res.raise_for_status()
    return res.json()["response"].strip()


def _extract_json_block(raw: str) -> str:
    """모델 응답에 JSON 앞뒤로 다른 텍스트가 붙어 나올 수 있어 {...} 블록만 추출."""
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        raise ValueError("응답에서 JSON 블록을 찾을 수 없음")
    return match.group(0)


def parse_task_draft_response(raw: str) -> dict:
    """
    LLM 원본 응답 문자열을 9개 필드(TASK_FIELDS) dict로 파싱.
    JSON 파싱 실패, 또는 9개 필드 중 하나라도 없으면 ValueError.
    """
    json_block = _extract_json_block(raw)
    data = json.loads(json_block)
    missing = [f for f in TASK_FIELDS if f not in data]
    if missing:
        raise ValueError(f"응답에 누락된 필드: {missing}")
    return {field: str(data[field]) for field in TASK_FIELDS}


async def generate_task_draft(title: str, overview: str, similar_tasks: list[dict]) -> dict:
    """유사 완료사업들을 근거로 사업계획서 9개 섹션 초안을 생성.
    similar_tasks가 빈 리스트여도 호출은 되며(빈 컨텍스트로 생성), 이후 라우터에서
    apply_task_guardrail이 유사도 0으로 처리해 결과를 안내문으로 대체한다."""
    context_block = "\n\n".join(
        f"[참고사업 {i+1}] {t['title']}\n"
        f"- 개요: {t['overview']}\n"
        f"- 추진체계: {t['execution_system']}\n"
        f"- 사후관리: {t['post_management']}\n"
        f"- 예산: {t['budget']}\n"
        f"- 일정: {t['schedule']}"
        for i, t in enumerate(similar_tasks)
    )
    prompt = (
        "다음은 새로 작성해야 할 사업의 사업명·개요와, 참고할 수 있는 과거 유사 완료사업입니다. "
        "아래 지침을 반드시 지켜 신규 사업 하나에 대한 사업계획서 초안을 작성하세요.\n"
        "- 반드시 아래 9개 key만 가진 하나의 JSON 객체로만 답하세요. JSON 앞뒤에 다른 설명을 붙이지 마세요.\n"
        "- key: overview, background, goals, detailed_plan, schedule, execution_system, budget, expected_effect, post_management\n"
        "- 참고사업의 추진체계(execution_system)와 사후관리(post_management)에 나온 부서 간 협업 방식과 "
        "시행착오를 적극 활용해서 구체적으로 작성하세요.\n"
        "- 참고사업에 없는 예산 금액이나 기간을 지어내지 마세요.\n"
        "- 참고사업 중 관련된 내용이 부족하면, 구체적인 수치를 확정하지 말고 일반적인 절차 위주로 작성하세요.\n\n"
        f"[신규 사업명]\n{title}\n\n"
        f"[신규 사업 개요]\n{overview}\n\n"
        f"[참고 사업]\n{context_block}\n\n"
        "[JSON 출력]"
    )

    async def _call_llm() -> str:
        async with httpx.AsyncClient(timeout=120.0) as client:
            res = await client.post(
                f"{settings.ollama_host}/api/generate",
                json={
                    "model": settings.generation_model_name,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.2, "num_predict": 800},
                },
            )
            res.raise_for_status()
        return res.json()["response"].strip()

    raw = await _call_llm()
    try:
        return parse_task_draft_response(raw)
    except ValueError:
        raw_retry = await _call_llm()
        return parse_task_draft_response(raw_retry)

