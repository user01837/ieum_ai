"""
Ollama에 등록된 모델(분류기 handover-classifier, 생성용 llama3.1:8b)을 호출하는 모듈.
"""
import httpx

from app.core.config import settings


async def classify_text(text: str) -> str:
    """텍스트를 8개 도메인(교통/주택·건축/환경/복지/안전/경제·산업/문화·체육·관광/행정·일반) 중 하나로 분류."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        res = await client.post(
            f"{settings.ollama_host}/api/generate",
            json={
                "model": settings.classifier_model_name,
                "prompt": f"텍스트: {text}",
                "stream": False,
            },
        )
        res.raise_for_status()
    return res.json()["response"].strip()


async def generate_draft_answer(complaint_text: str, similar_cases: list[dict]) -> str:
    """유사 사례들을 근거로 삼아 답변 초안을 생성."""
    context_block = "\n\n".join(
        f"[유사사례 {i+1}] {c['document']}" for i, c in enumerate(similar_cases)
    )
    prompt = (
        "다음은 새로 접수된 민원과, 참고할 수 있는 과거 유사 사례입니다. "
        "과거 사례의 처리 방식을 참고하여 공문서체로 답변 초안을 작성하세요.\n\n"
        f"[신규 민원]\n{complaint_text}\n\n"
        f"[참고 사례]\n{context_block}\n\n"
        "[답변 초안]"
    )

    async with httpx.AsyncClient(timeout=30.0) as client:
        res = await client.post(
            f"{settings.ollama_host}/api/generate",
            json={
                "model": settings.generation_model_name,
                "prompt": prompt,
                "stream": False,
            },
        )
        res.raise_for_status()
    return res.json()["response"].strip()
