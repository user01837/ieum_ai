"""
검색 결과 재정렬(rerank)용 모듈.
1차 임베딩 검색으로 넉넉히 뽑은 후보를, cross-encoder로 질문-문서 쌍을 직접 비교해
더 정교하게 재정렬하는 데 사용.
BAAI/bge-reranker-v2-m3 사용 (BGE-M3와 같은 팀, 다국어/한국어 지원).
"""
from functools import lru_cache
from sentence_transformers import CrossEncoder

RERANKER_MODEL_NAME = "BAAI/bge-reranker-v2-m3"


@lru_cache(maxsize=1)
def get_reranker() -> CrossEncoder:
    """모델은 최초 1회만 로드하고 이후엔 캐시된 걸 재사용 (매 요청마다 새로 부르면 느려짐)."""
    return CrossEncoder(RERANKER_MODEL_NAME)


def rerank(query: str, documents: list[str]) -> list[float]:
    """query와 documents 각각의 관련도 점수를 계산 (점수가 높을수록 더 관련 있음)."""
    if not documents:
        return []
    model = get_reranker()
    pairs = [(query, doc) for doc in documents]
    scores = model.predict(pairs)
    return [float(s) for s in scores]
