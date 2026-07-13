# -*- coding: utf-8 -*-
"""
법률챗봇 검색 + 답변 생성 (답변 출력 속도 최우선 설계).

기존 generate_draft_answer()(민원 답변 초안, num_predict=300, top_k=3)와 비교해서
아래 3가지를 줄여 응답 속도를 끌어올림:
    1) top_k: 3 → 2   (검색 결과가 적을수록 프롬프트가 짧아져 생성이 빨라짐)
    2) num_predict: 300 → 150  (답변 길이 자체를 짧게 제한 - 법률챗봇은 대화형이라
       한 번에 긴 공문서체 답변보다 간결한 응답이 자연스러움)
    3) 프롬프트 지시문 자체도 대폭 축소 (draft 프롬프트처럼 8줄짜리 세부 지침을
       주지 않고 핵심 지침 2줄만 사용 - 프롬프트가 길수록 첫 토큰까지 걸리는
       시간(prefill)도 늘어나므로 이것도 속도에 영향을 줌)

사용 위치: app/api/routes.py에 /api/legal-chat 엔드포인트로 연결
"""
import httpx
import chromadb

from app.core.config import settings
from app.embeddings.embedder import embed_text

LEGAL_COLLECTION_NAME = "legal_documents"

_legal_client = None
_legal_collection = None


def get_legal_collection():
    global _legal_client, _legal_collection
    if _legal_collection is None:
        _legal_client = chromadb.PersistentClient(path=settings.chroma_persist_dir)
        _legal_collection = _legal_client.get_or_create_collection(
            name=LEGAL_COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
    return _legal_collection


def search_legal_articles(query_text: str, top_k: int = 2) -> list[dict]:
    """질문과 유사한 법령 조문 검색 (top_k=2로 최소화 - 속도 우선)."""
    collection = get_legal_collection()
    vector = embed_text(query_text)

    result = collection.query(query_embeddings=[vector], n_results=top_k)

    hits = []
    ids = result.get("ids", [[]])[0]
    documents = result.get("documents", [[]])[0]
    metadatas = result.get("metadatas", [[]])[0]
    distances = result.get("distances", [[]])[0]

    for i in range(len(ids)):
        similarity_pct = round((1 - distances[i]) * 100, 1)
        hits.append({
            "law_title": metadatas[i].get("law_title"),
            "article_no": metadatas[i].get("article_no"),
            "article_title": metadatas[i].get("article_title"),
            "document": documents[i],
            "similarity": similarity_pct,
        })
    return hits


async def generate_legal_answer(question: str, articles: list[dict]) -> str:
    """
    검색된 조문을 근거로 짧고 빠르게 답변 생성.
    프롬프트를 최소화하고 num_predict를 낮춰 응답 속도를 우선함.
    """
    context_block = "\n".join(
        f"[{a['law_title']} 제{a['article_no']}조({a['article_title']})] {a['document']}"
        for a in articles
    )
    prompt = (
        "다음 법령 조문만 근거로 질문에 간결히 답하세요. 조문에 없는 내용은 지어내지 마세요.\n\n"
        f"[조문]\n{context_block}\n\n"
        f"[질문]\n{question}\n\n"
        "[답변]"
    )

    async with httpx.AsyncClient(timeout=60.0) as client:
        res = await client.post(
            f"{settings.ollama_host}/api/generate",
            json={
                "model": settings.generation_model_name,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.1,
                    "num_predict": 150,  # draft(300)보다 절반으로 줄여서 속도 우선
                },
            },
        )
        res.raise_for_status()
    return res.json()["response"].strip()