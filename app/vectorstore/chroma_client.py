"""
ChromaDB 연결 + 유사 사례 검색 모듈.

컬렉션 하나(complaints)에 민원 텍스트를 저장하고
department_code(부서) 메타데이터로 필터링한 후 벡터 유사도로 검색한다.

검색 과정:
    1) 임베딩 유사도로 넉넉히(rerank_candidates개) 후보를 뽑고
    2) 리랭커(cross-encoder)로 질문-문서 쌍을 직접 비교해 재정렬
    3) 재정렬된 순서에서 상위 top_k개만 반환
    (가드레일 판단에 쓰이는 similarity 값은 리랭커 점수가 아니라
     기존 임베딩 유사도를 그대로 유지 - 65% 임계값 로직과의 일관성 유지 목적)

주의: 이 모듈은 저장된 벡터를 검색만 담당한다.
실제 민원 데이터를 여기 넣는 배치 스크립트는 data/seed_ingest.py 참고.
"""
import chromadb

from app.core.config import settings
from app.embeddings.embedder import embed_text, embed_texts
from app.embeddings.reranker import rerank

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
    answer: str | None = None,
) -> None:
    """민원 1건을 벡터화해서 ChromaDB에 저장(이미 있으면 덮어씀).
    검색용 벡터는 title+content 기준으로 계산하되,
    title/content/answer는 각각 메타데이터로 따로 저장해 응답 시 분리 반환 가능하게 함."""
    text = f"{title}\n{content}"
    vector = embed_text(text)
    collection = get_collection()
    collection.upsert(
        ids=[str(complaint_id)],
        embeddings=[vector],
        documents=[text],
        metadatas=[{
            "complaint_id": complaint_id,
            "title": title,
            "content": content,
            "answer": answer or "",
            "department_code": department_code,
            "domain_code": domain_code or "",
            "status_code": status_code or "",
        }],
    )


def add_complaints_batch(items: list[dict]) -> None:
    """
    여러 건을 한 번에 저장(초기 데이터 적재용).
    items 각 원소: {"complaint_id", "title", "content", "department_code", "domain_code", "status_code", "answer"}
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
            "title": it["title"],
            "content": it["content"],
            "answer": it.get("answer") or "",
            "department_code": it["department_code"],
            "domain_code": it.get("domain_code") or "",
            "status_code": it.get("status_code") or "",
        } for it in items],
    )


def search_similar_complaints(
    query_text: str,
    department_code: str,
    top_k: int = 3,
    rerank_candidates: int = 20,
    exclude_ids: list[int] | None = None,
    min_similarity: float | None = None,
) -> list[dict]:
    """
    질문/민원 텍스트와 유사한 과거 민원을 부서 범위 내에서 검색.
    (domain_code는 department_code와 1:1 매핑이라 필터링에서 제거함 - 2026-07-14)

    exclude_ids: 이미 보여준 민원 ID 목록 - "유사사례 추가 검색" 시 중복 제외용
    min_similarity: 지정 시 이 값 미만인 결과는 제외 - "추가 검색"에서 65 이상만 보여줄 때 사용

    1) 임베딩 유사도로 rerank_candidates개 후보 확보
    2) exclude_ids / min_similarity로 후보 필터링
    3) 리랭커로 재정렬
    4) 상위 top_k개 반환 (title/content/answer 분리 필드로 응답 - 2026-07-14)
    """
    collection = get_collection()
    vector = embed_text(query_text)

    where = {"department_code": department_code}

    result = collection.query(
        query_embeddings=[vector],
        n_results=rerank_candidates,
        where=where,
    )

    ids = result.get("ids", [[]])[0]
    documents = result.get("documents", [[]])[0]
    metadatas = result.get("metadatas", [[]])[0]
    distances = result.get("distances", [[]])[0]

    exclude_set = set(exclude_ids) if exclude_ids else set()

    candidates = []
    for i in range(len(ids)):
        complaint_id = metadatas[i].get("complaint_id")
        if complaint_id in exclude_set:
            continue
        similarity_pct = round((1 - distances[i]) * 100, 1)
        if min_similarity is not None and similarity_pct < min_similarity:
            continue
        candidates.append({
            "complaint_id": complaint_id,
            "title": metadatas[i].get("title", ""),
            "content": metadatas[i].get("content", ""),
            "answer": metadatas[i].get("answer", ""),
            "department_code": metadatas[i].get("department_code"),
            "domain_code": metadatas[i].get("domain_code"),
            "status_code": metadatas[i].get("status_code"),
            "similarity": similarity_pct,
            "_search_text": documents[i],
        })

    if not candidates:
        return []

    rerank_scores = rerank(query_text, [c["_search_text"] for c in candidates])
    for c, score in zip(candidates, rerank_scores):
        c["rerank_score"] = round(score, 4)
        del c["_search_text"]

    candidates.sort(key=lambda c: c["rerank_score"], reverse=True)

    return candidates[:top_k]
