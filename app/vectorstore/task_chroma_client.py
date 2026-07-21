# -*- coding: utf-8 -*-
"""
ChromaDB 연결 + 유사 사업 검색 모듈 (사업 추진계획서용).

app/vectorstore/chroma_client.py(민원용)와 같은 패턴이지만 완전히 별도 컬렉션을 쓴다.
- 컬렉션: tasks
- 벡터화 대상: title + overview (9개 필드 중 검색 질의로 쓰는 부분만. 나머지 7개 필드는
  결과 표시용 메타데이터로만 저장하고 벡터화하지 않음 - 색인/검색 시 기준을 통일해야
  임베딩 유사도가 의미 있게 비교되기 때문)
- 필터: lead_department_code + status_code="완료" (진행중/보류 사업은 사후관리 노하우가
  아직 없거나 불확정이라 검색 대상에서 제외)

검색 과정은 chroma_client.py와 동일:
    1) 임베딩 유사도로 넉넉히(rerank_candidates개) 후보를 뽑고
    2) 리랭커(cross-encoder)로 질문-문서 쌍을 직접 비교해 재정렬
    3) 재정렬된 순서에서 상위 top_k개만 반환

주의: 이 모듈은 저장된 벡터를 검색만 담당한다.
120건 시드 데이터를 여기 넣는 배치 스크립트는 data/seed_tasks_ingest.py 참고.
"""
import chromadb

from app.core.config import settings
from app.embeddings.embedder import embed_text, embed_texts
from app.embeddings.reranker import rerank

_client = None
_collection = None

COLLECTION_NAME = "tasks"

# 사업계획서 9개 콘텐츠 필드 (task_id/year/title/lead_department_code/
# collab_department_codes/domain_code/status_code는 메타데이터로 별도 취급)
TASK_FIELDS = [
    "overview", "background", "goals", "detailed_plan", "schedule",
    "execution_system", "budget", "expected_effect", "post_management",
]


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


def _make_id(item: dict) -> str:
    """task_id는 부서별로 1~15가 반복되므로(예: 01번 부서의 1번, 03번 부서의 1번이 둘 다
    존재), 컬렉션 전체에서 고유해야 하는 ChromaDB id는 lead_department_code를 붙여 조합."""
    return f"{item['lead_department_code']}_{item['task_id']}"


def _build_metadata(item: dict) -> dict:
    """collab_department_codes는 리스트라 ChromaDB 메타데이터(스칼라 값만 허용)에
    그대로 못 넣으므로 쉼표로 join해서 저장하고, 조회 시 다시 split해서 되돌린다."""
    metadata = {
        "task_id": item["task_id"],
        "year": item["year"],
        "title": item["title"],
        "lead_department_code": item["lead_department_code"],
        "collab_department_codes": ",".join(item["collab_department_codes"]),
        "domain_code": item["domain_code"],
        "status_code": item["status_code"],
    }
    for field in TASK_FIELDS:
        metadata[field] = item[field]
    return metadata


def _metadata_to_result(metadata: dict) -> dict:
    result = {
        "task_id": metadata.get("task_id"),
        "year": metadata.get("year"),
        "title": metadata.get("title", ""),
        "lead_department_code": metadata.get("lead_department_code"),
        "collab_department_codes": (
            metadata.get("collab_department_codes", "").split(",")
            if metadata.get("collab_department_codes") else []
        ),
        "domain_code": metadata.get("domain_code"),
        "status_code": metadata.get("status_code"),
    }
    for field in TASK_FIELDS:
        result[field] = metadata.get(field, "")
    return result


def add_task(item: dict) -> None:
    """사업 1건을 벡터화해서 ChromaDB에 저장(이미 있으면 덮어씀).
    item은 data/seed_tasks.py의 TASKS 원소와 동일한 키 구조를 가져야 함."""
    text = f"{item['title']}\n{item['overview']}"
    vector = embed_text(text)
    collection = get_collection()
    collection.upsert(
        ids=[_make_id(item)],
        embeddings=[vector],
        documents=[text],
        metadatas=[_build_metadata(item)],
    )


def add_tasks_batch(items: list[dict]) -> None:
    """여러 건을 한 번에 저장(초기 데이터 적재용)."""
    texts = [f"{it['title']}\n{it['overview']}" for it in items]
    vectors = embed_texts(texts)
    collection = get_collection()
    collection.upsert(
        ids=[_make_id(it) for it in items],
        embeddings=vectors,
        documents=texts,
        metadatas=[_build_metadata(it) for it in items],
    )


def search_similar_tasks(
    title: str,
    overview: str,
    lead_department_code: str,
    top_k: int = 3,
    rerank_candidates: int = 20,
    exclude_ids: list[int] | None = None,
    min_similarity: float | None = None,
) -> list[dict]:
    """
    사업명+개요와 유사한 과거 완료 사업을, 같은 주관부서 범위 내에서 검색.

    - lead_department_code가 같은 사업만 검색 (협력부서로만 참여한 사업은 제외)
    - status_code="완료"인 사업만 검색

    1) 임베딩 유사도로 rerank_candidates개 후보 확보
    2) exclude_ids / min_similarity로 후보 필터링
    3) 리랭커로 재정렬
    4) 상위 top_k개 반환
    """
    collection = get_collection()
    query_text = f"{title}\n{overview}"
    vector = embed_text(query_text)

    where = {
        "$and": [
            {"lead_department_code": lead_department_code},
            {"status_code": "완료"},
        ]
    }

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
        task_id = metadatas[i].get("task_id")
        if task_id in exclude_set:
            continue
        similarity_pct = round((1 - distances[i]) * 100, 1)
        if min_similarity is not None and similarity_pct < min_similarity:
            continue
        entry = _metadata_to_result(metadatas[i])
        entry["similarity"] = similarity_pct
        entry["_search_text"] = documents[i]
        candidates.append(entry)

    if not candidates:
        return []

    rerank_scores = rerank(query_text, [c["_search_text"] for c in candidates])
    for c, score in zip(candidates, rerank_scores):
        c["rerank_score"] = round(score, 4)
        del c["_search_text"]

    candidates.sort(key=lambda c: c["rerank_score"], reverse=True)

    return candidates[:top_k]
