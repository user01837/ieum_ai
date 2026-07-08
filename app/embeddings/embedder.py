"""
민원/사업 텍스트를 벡터로 변환하는 모듈.
jhgan/ko-sbert-nli 모델을 사용 (한국어 RAG에 적합한 것으로 검증됨).
"""
from functools import lru_cache
from sentence_transformers import SentenceTransformer

from app.core.config import settings


@lru_cache(maxsize=1)
def get_embedder() -> SentenceTransformer:
    """
    모델을 최초 1회만 로드하고 이후에는 캐시된 걸 재사용.
    (매 요청마다 모델을 새로 불러오면 느려짐)
    """
    return SentenceTransformer(settings.embedding_model)


def embed_text(text: str) -> list[float]:
    """단일 텍스트 -> 벡터(float 리스트)"""
    model = get_embedder()
    vector = model.encode(text, normalize_embeddings=True)
    return vector.tolist()


def embed_texts(texts: list[str]) -> list[list[float]]:
    """여러 텍스트를 한 번에 벡터화 (배치 처리, 대량 삽입 시 이걸 사용)"""
    model = get_embedder()
    vectors = model.encode(texts, normalize_embeddings=True)
    return vectors.tolist()
