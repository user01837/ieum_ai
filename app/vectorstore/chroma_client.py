"""
ChromaDB 연결 + 저장/검색 모듈.

컬렉션 하나(complaints)에 민원 텍스트를 저장하고,
department_code(부서) 메타데이터로 필터링한 뒤 벡터 유사도로 검색한다.

주의: 이 모듈은 "저장된 벡터를 검색"만 담당한다.
실제 민원 데이터를 여기 넣는 배치 스크립트는 scripts/ingest_complaints.py 참고 (별도 작성 필요).
"""
import chromadb

from app.core.config import settings
from app.embeddings.embedder import embed_text, embed_texts

_client = None
_collection = None

COLLECTION_NAME = "complaints"


def get_client() -> chromadb.ClientAPI:
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(path=settings.chroma_persist_dir)
    return _client


def get_collection():
    global _collection
    if _collection is None:
        client = get_client()
        _collection = client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
    return _collection


def add_complaint(
    complaint_id: int,
    title: str,
    content: str,
    department_code: str,
    domain_code: str | None = None,
    status_code: str | None = None,
) -> None:
    """민원 1건을 벡터화해서 ChromaDB에 저장(이미 있으면 덮어씀)."""
    text = f"{title}\n{content}"
    vector = embed_text(text)
    collection = get_collection()
    collection.upsert(
        ids=[str(complaint_id)],
        embeddings=[vector],
        documents=[text],
        metadatas=[{
            "complaint_id": complaint_id,
            "department_code": department_code,
            "domain_code": domain_code or "",
            "status_code": status_code or "",
        }],
    )


def add_complaints_batch(items: list[dict]) -> None:
    """
    여러 건을 한 번에 저장 (초기 데이터 이관용).
    items 각 원소: {"complaint_id", "title", "content", "department_code", "domain_code", "status_code"}
    """
    texts = [f"{it['title']}\n{it['content']}" for it in items]
    vectors = embed_texts(texts)
    collection = get_collection()
    collection.upsert(
        ids=[str(it["complaint_id"]) for it in items],
        embeddings=vectors,
        documents=texts,
        metadatas=[{
            "complaint_id": it["complaint_id"],
            "department_code": it["department_code"],
            "domain_code": it.get("domain_code") or "",
            "status_code": it.get("status_code") or "",
        } for it in items],
    )


def search_similar_complaints(
    query_text: str,
    department_code: str,
    domain_code: str | None = None,
    top_k: int = 3,
) -> list[dict]:
    """
    질문/민원 텍스트와 유사한 과거 민원을 부서 범위 내에서 검색.
    domain_code를 주면 도메인까지 같이 필터링(분류기가 붙인 라벨 활용).
    """
    collection = get_collection()
    vector = embed_text(query_text)

    where = {"department_code": department_code}
    if domain_code:
        where = {"$and": [{"department_code": department_code}, {"domain_code": domain_code}]}

    result = collection.query(
        query_embeddings=[vector],
        n_results=top_k,
        where=where,
    )

    hits = []
    ids = result.get("ids", [[]])[0]
    documents = result.get("documents", [[]])[0]
    metadatas = result.get("metadatas", [[]])[0]
    distances = result.get("distances", [[]])[0]

    for i in range(len(ids)):
        # cosine distance -> 유사도(%)로 변환 (거리가 작을수록 유사)
        similarity_pct = round((1 - distances[i]) * 100, 1)
        hits.append({
            "complaint_id": metadatas[i].get("complaint_id"),
            "document": documents[i],
            "department_code": metadatas[i].get("department_code"),
            "domain_code": metadatas[i].get("domain_code"),
            "status_code": metadatas[i].get("status_code"),
            "similarity": similarity_pct,
        })
    return hits
