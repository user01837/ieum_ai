# 사업 추진계획서 AI 초안작성 기능 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 신임 담당자가 사업명+개요만 입력하면, 같은 주관부서의 과거 완료 사업을 검색해 사업계획서 9개 섹션(overview/background/goals/detailed_plan/schedule/execution_system/budget/expected_effect/post_management) 초안을 생성해주는 3개 API(`/api/similar-tasks`, `/api/task-draft`, `/api/index-task`)를 추가한다.

**Architecture:** 기존 민원 초안작성(`/api/draft`) 구조(ChromaDB 벡터검색 → 리랭커 재정렬 → LLM 생성 → 2단계 가드레일)를 그대로 따르되, 완전히 별도 컬렉션(`tasks`)과 별도 모듈로 분리해 기존 민원 기능에 대한 회귀 위험을 없앤다.

**Tech Stack:** FastAPI, ChromaDB(PersistentClient), sentence-transformers(`jhgan/ko-sbert-nli` 임베딩 + `BAAI/bge-reranker-v2-m3` 리랭커, 기존 모듈 재사용), Ollama(`llama3.1:8b`)

## Global Constraints

- `lead_department_code`는 반드시 `01`~`08` 중 하나 (아니면 400 에러). 매핑: 01 교통, 02 주택·건축, 03 환경, 04 복지, 05 안전, 06 경제·산업, 07 문화·체육·관광, 08 행정·일반.
- 검색은 `lead_department_code`가 같고 `status_code == "완료"`인 사업만 대상으로 한다.
- 유사도 임계값(`similarity_threshold`)은 65.0 (민원 기능과 동일 값).
- `/api/task-draft`는 항상 `top_k=3`으로 검색한다.
- 벡터화 텍스트는 색인 시·검색 시 모두 `title + "\n" + overview` 로 통일한다 (9개 필드 전체를 벡터화하지 않음).
- 가드레일 사실검증 대상은 `금액`, `기간_일수` 패턴만 사용한다 (민원용의 법조문·퍼센트 패턴은 사용하지 않음).
- 유사도 미달 시 9개 필드 전체를 동일한 문구로 교체한다: `"참고할 만한 유사 사업이 충분하지 않습니다. 담당자가 직접 작성해주세요."`
- ChromaDB 컬렉션명은 `tasks` (기존 `complaints` 컬렉션과 완전히 분리, `app/vectorstore/chroma_client.py`는 수정하지 않음).
- 기존 파일(`chroma_client.py`, `ollama_client.py`의 기존 함수, `draft_guardrail.py`의 기존 함수, `routes.py`의 기존 엔드포인트)의 동작은 변경하지 않는다.

---

## Task 1: `task_chroma_client.py` — 사업 저장/검색 모듈

**Files:**
- Create: `app/vectorstore/task_chroma_client.py`
- Test: `tests/test_task_chroma_client.py`

**Interfaces:**
- Consumes: `app.core.config.settings.chroma_persist_dir`, `app.embeddings.embedder.embed_text/embed_texts`, `app.embeddings.reranker.rerank` (모두 기존 모듈, 변경 없이 그대로 사용)
- Produces:
  - `TASK_FIELDS: list[str]` — 9개 콘텐츠 필드명 리스트 (Task 3, 4에서 import해서 재사용)
  - `add_task(item: dict) -> None`
  - `add_tasks_batch(items: list[dict]) -> None`
  - `search_similar_tasks(title: str, overview: str, lead_department_code: str, top_k: int = 3, rerank_candidates: int = 20, exclude_ids: list[int] | None = None, min_similarity: float | None = None) -> list[dict]` — 반환 dict는 `task_id, year, title, lead_department_code, collab_department_codes(list[str]), domain_code, status_code` + 9개 `TASK_FIELDS` + `similarity(float)`, `rerank_score(float)` 키를 가짐

- [ ] **Step 1: `app/vectorstore/task_chroma_client.py` 작성**

```python
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
```

- [ ] **Step 2: 테스트 스크립트 `tests/test_task_chroma_client.py` 작성**

```python
# -*- coding: utf-8 -*-
"""
task_chroma_client.py 동작 확인 스크립트 (실제 임베딩/리랭커 모델 사용, 목 없음 -
이 프로젝트의 다른 tests/*.py 와 같은 방식: 실행해서 assert 통과 여부를 확인).

실행 위치: ieum_ai 폴더 루트에서
    python tests/test_task_chroma_client.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.vectorstore.task_chroma_client import add_tasks_batch, search_similar_tasks

SAMPLE_TASKS = [
    {
        "task_id": 1, "year": 2024, "title": "노후 상수도관 정비 사업",
        "lead_department_code": "03", "collab_department_codes": ["01", "02"],
        "domain_code": "환경", "overview": "노후 상수도관을 정비하는 사업",
        "background": "b", "goals": "g", "detailed_plan": "d", "schedule": "s",
        "execution_system": "e", "budget": "1000만원", "expected_effect": "ef",
        "post_management": "p", "status_code": "완료",
    },
    {
        "task_id": 2, "year": 2024, "title": "스마트 신호체계 구축사업",
        "lead_department_code": "01", "collab_department_codes": ["05", "08"],
        "domain_code": "교통", "overview": "스마트 신호체계를 구축하는 사업",
        "background": "b", "goals": "g", "detailed_plan": "d", "schedule": "s",
        "execution_system": "e", "budget": "2000만원", "expected_effect": "ef",
        "post_management": "p", "status_code": "완료",
    },
    {
        "task_id": 3, "year": 2025, "title": "미세먼지 저감사업",
        "lead_department_code": "03", "collab_department_codes": ["01"],
        "domain_code": "환경", "overview": "도로 청소차를 확충하는 사업",
        "background": "b", "goals": "g", "detailed_plan": "d", "schedule": "s",
        "execution_system": "e", "budget": "3000만원", "expected_effect": "ef",
        "post_management": "p", "status_code": "진행중",
    },
]

print("샘플 3건 색인 중...")
add_tasks_batch(SAMPLE_TASKS)
print("색인 완료\n")

# 검증 1: 03(환경) 부서로 검색하면 03 소속 사업만 나와야 함
results = search_similar_tasks(
    title="노후 상수도관 정비 사업",
    overview="노후 상수도관을 정비하는 사업",
    lead_department_code="03",
    top_k=5,
)
assert len(results) > 0, "검색 결과가 0건입니다"
assert all(r["lead_department_code"] == "03" for r in results), f"부서 필터링 실패: {results}"
print(f"[통과] 03 부서 검색 결과 {len(results)}건 모두 lead_department_code=03")

# 검증 2: status_code="완료"만 나와야 함 (task_id=3은 진행중이라 제외되어야 함)
returned_ids = {r["task_id"] for r in results}
assert 3 not in returned_ids, f"진행중 사업(task_id=3)이 검색 결과에 포함됨: {results}"
print("[통과] 진행중 사업(task_id=3)은 검색 결과에서 제외됨")

# 검증 3: 01(교통) 부서로 검색하면 task_id=2만 나오고, collab_department_codes가 리스트로 복원돼야 함
results_01 = search_similar_tasks(
    title="스마트 신호체계 구축사업",
    overview="스마트 신호체계를 구축하는 사업",
    lead_department_code="01",
    top_k=5,
)
assert len(results_01) == 1 and results_01[0]["task_id"] == 2, f"01 부서 검색 결과 이상: {results_01}"
assert results_01[0]["collab_department_codes"] == ["05", "08"], f"collab_department_codes 복원 실패: {results_01[0]}"
print("[통과] 01 부서 검색 결과 1건, collab_department_codes 정상 복원")

print("\n모든 검증 통과")
```

- [ ] **Step 3: 실행해서 확인**

Run: `python tests/test_task_chroma_client.py`
Expected: 마지막 줄에 `모든 검증 통과` 출력 (모델 최초 다운로드 시간 제외하면 수 초 내 완료)

- [ ] **Step 4: Commit**

```bash
git add app/vectorstore/task_chroma_client.py tests/test_task_chroma_client.py
git commit -m "feat: 사업계획서용 ChromaDB 검색 모듈(task_chroma_client) 추가"
```

---

## Task 2: `data/seed_tasks_ingest.py` — 120건 색인 스크립트

**Files:**
- Create: `data/seed_tasks_ingest.py`

**Interfaces:**
- Consumes: `app.vectorstore.task_chroma_client.add_tasks_batch` (Task 1), `data.seed_tasks.TASKS` (기존 파일, 120건)
- Produces: `tasks` 컬렉션에 120건이 색인된 상태 (Task 5의 라이브 테스트가 이 상태를 전제로 함)

- [ ] **Step 1: `data/seed_tasks_ingest.py` 작성**

```python
"""
data/seed_tasks.py에 있는 합성 사업 120건을 ChromaDB(tasks 컬렉션)에 일괄 색인하는 스크립트.
실행 방법 (ieum_ai 폴더 루트에서, conda activate ieum_ai 상태로):
    python data/seed_tasks_ingest.py
이미 같은 (lead_department_code, task_id) 조합이 있으면 덮어씁니다(upsert).
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.vectorstore.task_chroma_client import add_tasks_batch
from data.seed_tasks import TASKS


def main():
    print(f"총 {len(TASKS)}건 색인을 시작합니다...")
    add_tasks_batch(TASKS)

    from collections import Counter
    counts = Counter(t["lead_department_code"] for t in TASKS)
    print("\n주관부서별 색인 건수:")
    for dept, cnt in sorted(counts.items()):
        print(f"  {dept}: {cnt}건")
    print(f"\n완료! 총 {len(TASKS)}건이 ChromaDB(tasks 컬렉션)에 색인되었습니다.")
    print("확인하려면 서버 실행 후 /api/similar-tasks 로 검색해보세요.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 실행**

Run: `python data/seed_tasks_ingest.py`
Expected: `주관부서별 색인 건수` 아래 8개 부서(01~08) 각각 `15건`으로 출력, 마지막 줄 `완료! 총 120건이...`

- [ ] **Step 3: 색인 결과 검증**

Run:
```bash
python -c "
from app.vectorstore.task_chroma_client import search_similar_tasks
EXPECTED_TITLE = '교통약자 이동편의 개선사업 (버스승강장 저상화)'
r = search_similar_tasks(
    title=EXPECTED_TITLE,
    overview='관내 버스승강장 저상화 사업',
    lead_department_code='01',
    top_k=1,
)
assert r and r[0]['title'] == EXPECTED_TITLE, r
print('OK top1 title =', r[0]['title'], 'similarity =', r[0]['similarity'])
"
```
Expected: `OK top1 title = 교통약자 이동편의 개선사업 (버스승강장 저상화) similarity = <65 이상의 값>`

- [ ] **Step 4: Commit**

```bash
git add data/seed_tasks_ingest.py
git commit -m "feat: 사업계획서 시드 120건 ChromaDB 색인 스크립트 추가"
```

---

## Task 3: `generate_task_draft()` — LLM 초안 생성

**Files:**
- Modify: `app/classifier/ollama_client.py`
- Test: `tests/test_task_draft_parsing.py`

**Interfaces:**
- Consumes: `app.vectorstore.task_chroma_client.TASK_FIELDS` (Task 1), `app.core.config.settings` (기존)
- Produces:
  - `parse_task_draft_response(raw: str) -> dict` — 순수 함수, 네트워크 호출 없음. 실패 시 `ValueError`
  - `async def generate_task_draft(title: str, overview: str, similar_tasks: list[dict]) -> dict` — 반환값은 `TASK_FIELDS`의 9개 키를 가진 dict. 파싱 실패 시 1회 재시도 후에도 실패하면 `ValueError` 그대로 전파 (Task 5의 라우터가 잡아서 500으로 변환)

- [ ] **Step 1: `app/classifier/ollama_client.py` 맨 위 import에 추가**

```python
import json
import re

from app.vectorstore.task_chroma_client import TASK_FIELDS
```

(기존 `import httpx`, `from app.core.config import settings` 아래에 이어서 추가)

- [ ] **Step 2: 파일 맨 끝에 파싱 함수 추가 (네트워크 호출 없는 순수 함수)**

```python
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
```

- [ ] **Step 3: `tests/test_task_draft_parsing.py` 작성 (네트워크 없이 즉시 실행 가능)**

```python
# -*- coding: utf-8 -*-
"""
parse_task_draft_response()는 순수 함수(네트워크 호출 없음)라 바로 assert로 검증 가능.

실행: python tests/test_task_draft_parsing.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.classifier.ollama_client import parse_task_draft_response

VALID_JSON = """{
    "overview": "o", "background": "b", "goals": "g", "detailed_plan": "d",
    "schedule": "s", "execution_system": "e", "budget": "1000만원",
    "expected_effect": "ef", "post_management": "p"
}"""

# 케이스 1: 정상 JSON만 온 경우
result = parse_task_draft_response(VALID_JSON)
assert result["budget"] == "1000만원", result
assert set(result.keys()) == {
    "overview", "background", "goals", "detailed_plan", "schedule",
    "execution_system", "budget", "expected_effect", "post_management",
}
print("[통과] 정상 JSON 파싱")

# 케이스 2: JSON 앞뒤에 모델이 군더더기 텍스트를 붙인 경우
WRAPPED = f"물론입니다! 요청하신 JSON은 다음과 같습니다:\n{VALID_JSON}\n감사합니다."
result2 = parse_task_draft_response(WRAPPED)
assert result2["overview"] == "o", result2
print("[통과] 앞뒤 군더더기 텍스트가 있어도 JSON 블록만 추출")

# 케이스 3: 필드 누락 시 ValueError
INCOMPLETE = '{"overview": "o", "background": "b"}'
try:
    parse_task_draft_response(INCOMPLETE)
    raise AssertionError("필드 누락인데 ValueError가 발생하지 않음")
except ValueError as e:
    print(f"[통과] 필드 누락 시 ValueError 발생: {e}")

# 케이스 4: JSON 자체가 아예 없을 때 ValueError
try:
    parse_task_draft_response("죄송합니다, 답변을 생성할 수 없습니다.")
    raise AssertionError("JSON 없는데 ValueError가 발생하지 않음")
except ValueError as e:
    print(f"[통과] JSON 블록 없을 때 ValueError 발생: {e}")

print("\n모든 검증 통과")
```

- [ ] **Step 4: 실행해서 확인**

Run: `python tests/test_task_draft_parsing.py`
Expected: `모든 검증 통과`

- [ ] **Step 5: 파일 끝에 `generate_task_draft()` 추가 (LLM 호출부, 실제 호출은 Task 5에서 서버 켜고 확인)**

```python
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
```

- [ ] **Step 6: Commit**

```bash
git add app/classifier/ollama_client.py tests/test_task_draft_parsing.py
git commit -m "feat: 사업계획서 초안 생성(generate_task_draft) 및 JSON 파싱 로직 추가"
```

---

## Task 4: `draft_guardrail.py` — 사업계획 초안용 가드레일

**Files:**
- Modify: `app/classifier/draft_guardrail.py`
- Test: `tests/test_task_guardrail_logic.py`

**Interfaces:**
- Consumes: `app.vectorstore.task_chroma_client.TASK_FIELDS` (Task 1), 기존 파일의 `PATTERNS`, `_normalize` (그대로 재사용)
- Produces:
  - `TASK_FALLBACK_MESSAGE: str`
  - `extract_task_claims(text: str) -> dict[str, list[str]]`
  - `verify_task_draft_claims(draft_fields: dict, referenced_tasks: list[dict]) -> dict` — `{"unverified_claims": {...}, "verified_claims": {...}, "has_unverified": bool}`
  - `apply_task_guardrail(draft_fields: dict, referenced_tasks: list[dict], similarity_threshold: float = 65.0) -> dict` — `{"draft": dict, "guardrail_triggered": bool, "verification": dict | None}` (Task 5의 라우터가 그대로 사용)

- [ ] **Step 1: `app/classifier/draft_guardrail.py` 맨 위 import에 추가**

```python
from app.vectorstore.task_chroma_client import TASK_FIELDS
```

(기존 `import re` 아래에 이어서 추가)

- [ ] **Step 2: 파일 끝(기존 `if __name__ == "__main__":` 블록 앞)에 추가**

```python
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
        fallback_fields = {field: TASK_FALLBACK_MESSAGE for field in TASK_FIELDS}
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
```

- [ ] **Step 3: `tests/test_task_guardrail_logic.py` 작성 (네트워크 없이 즉시 실행 가능)**

```python
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
```

- [ ] **Step 4: 실행해서 확인**

Run: `python tests/test_task_guardrail_logic.py`
Expected: `모든 검증 통과`

- [ ] **Step 5: Commit**

```bash
git add app/classifier/draft_guardrail.py tests/test_task_guardrail_logic.py
git commit -m "feat: 사업계획서 초안용 가드레일(verify_task_draft_claims, apply_task_guardrail) 추가"
```

---

## Task 5: `routes.py` — 엔드포인트 3개 추가 + 종단 테스트

**Files:**
- Modify: `app/api/routes.py`
- Test: `tests/test_task_draft_endpoints.py`

**Interfaces:**
- Consumes: `search_similar_tasks`, `add_task` (Task 1), `generate_task_draft` (Task 3), `apply_task_guardrail` (Task 4)
- Produces: `POST /api/similar-tasks`, `POST /api/task-draft`, `POST /api/index-task` (외부 계약, 이후 프론트/백엔드 연동에서 사용)

- [ ] **Step 1: `app/api/routes.py` 상단 import 수정**

`from fastapi import APIRouter` 를 아래로 교체:

```python
from fastapi import APIRouter, HTTPException
```

기존 import 블록 마지막(`from app.vectorstore.chroma_client import search_similar_complaints, add_complaint` 다음 줄)에 추가:

```python
from app.classifier.ollama_client import generate_task_draft
from app.classifier.draft_guardrail import apply_task_guardrail
from app.vectorstore.task_chroma_client import search_similar_tasks, add_task
```

- [ ] **Step 2: `router = APIRouter(...)` 아래, 기존 request 모델들 사이에 추가**

```python
VALID_LEAD_DEPARTMENT_CODES = {"01", "02", "03", "04", "05", "06", "07", "08"}


def _validate_lead_department_code(code: str) -> None:
    if code not in VALID_LEAD_DEPARTMENT_CODES:
        raise HTTPException(status_code=400, detail=f"invalid lead_department_code: {code}")


class SimilarTasksRequest(BaseModel):
    title: str
    overview: str
    lead_department_code: str
    top_k: int = 3


class TaskDraftRequest(BaseModel):
    title: str
    overview: str
    lead_department_code: str


class IndexTaskRequest(BaseModel):
    task_id: int
    year: int
    title: str
    lead_department_code: str
    collab_department_codes: list[str]
    domain_code: str
    overview: str
    background: str
    goals: str
    detailed_plan: str
    schedule: str
    execution_system: str
    budget: str
    expected_effect: str
    post_management: str
    status_code: str
```

- [ ] **Step 3: 파일 끝(마지막 `index_complaint` 엔드포인트 뒤)에 엔드포인트 3개 추가**

```python
@router.post("/similar-tasks")
async def similar_tasks(req: SimilarTasksRequest):
    """
    주관부서(lead_department_code) 범위 + 완료된 사업만 대상으로 유사 사업 검색.
    """
    _validate_lead_department_code(req.lead_department_code)
    hits = search_similar_tasks(
        title=req.title,
        overview=req.overview,
        lead_department_code=req.lead_department_code,
        top_k=req.top_k,
    )
    return {"results": hits}


@router.post("/task-draft")
async def task_draft(req: TaskDraftRequest):
    """
    유사 완료사업을 근거로 사업계획서 9개 섹션 초안 생성.

    가드레일 2단계 적용 (apply_task_guardrail 참고):
    1) 유사도 가드레일: top1 유사도가 65% 미만이면 9개 필드 전체를 안내 문구로 교체
    2) 사실 검증 가드레일: budget/schedule에 등장하는 금액·기간이 참고사업 원문에
       없으면 needs_review=True로 표시
    """
    _validate_lead_department_code(req.lead_department_code)
    similar = search_similar_tasks(
        title=req.title,
        overview=req.overview,
        lead_department_code=req.lead_department_code,
        top_k=3,
    )

    try:
        draft_fields = await generate_task_draft(req.title, req.overview, similar)
    except ValueError:
        raise HTTPException(status_code=500, detail="초안 생성에 실패했습니다. 다시 시도해주세요.")

    guarded = apply_task_guardrail(draft_fields, similar, similarity_threshold=65.0)

    return {
        "draft": guarded["draft"],
        "referenced_tasks": similar,
        "guardrail_triggered": guarded["guardrail_triggered"],
        "needs_review": (
            guarded["verification"]["has_unverified"]
            if guarded["verification"] else False
        ),
        "unverified_claims": (
            guarded["verification"]["unverified_claims"]
            if guarded["verification"] else {}
        ),
    }


@router.post("/index-task")
async def index_task(req: IndexTaskRequest):
    """
    완료된 사업 1건을 ChromaDB(tasks 컬렉션)에 색인(등록).
    백엔드에서 사업이 '완료' 처리될 때 이 엔드포인트를 호출하는 걸 전제로 함
    (기존 /api/index-complaint와 동일한 계약).
    """
    _validate_lead_department_code(req.lead_department_code)
    add_task(req.model_dump())
    return {"status": "indexed", "task_id": req.task_id, "lead_department_code": req.lead_department_code}
```

- [ ] **Step 4: `tests/test_task_draft_endpoints.py` 작성**

```python
# -*- coding: utf-8 -*-
"""
/api/similar-tasks, /api/task-draft 엔드포인트 동작 확인 스크립트.

사전 조건:
    1) FastAPI 서버 실행 중: uvicorn app.main:app --reload --port 8100
    2) Ollama 실행 중, generation 모델(llama3.1:8b) 로드 가능
    3) data/seed_tasks_ingest.py 실행 완료 (120건 색인 완료 상태 - Task 2)

실행: python tests/test_task_draft_endpoints.py
"""
import requests

BASE_URL = "http://localhost:8100"

TASK_FIELDS = [
    "overview", "background", "goals", "detailed_plan", "schedule",
    "execution_system", "budget", "expected_effect", "post_management",
]

print("=" * 70)
print("[테스트 1] /api/similar-tasks - 03(환경) 부서로 검색")
print("-" * 70)
res = requests.post(f"{BASE_URL}/api/similar-tasks", json={
    "title": "노후 상수도관 정비 사업",
    "overview": "관내 노후 상수도관을 정비하여 누수를 예방하는 사업",
    "lead_department_code": "03",
    "top_k": 3,
}, timeout=30.0)
res.raise_for_status()
results = res.json()["results"]
assert len(results) > 0, "검색 결과가 0건입니다 - seed_tasks_ingest.py 실행 여부를 확인하세요"
assert all(r["lead_department_code"] == "03" for r in results), f"부서 필터링 실패: {results}"
print(f"[통과] {len(results)}건 검색, 모두 lead_department_code=03")

print("\n" + "=" * 70)
print("[테스트 2] /api/task-draft - 정상 케이스(유사사업 있음)")
print("-" * 70)
res = requests.post(f"{BASE_URL}/api/task-draft", json={
    "title": "노후 상수도관 정비 사업 2차",
    "overview": "1차 사업에서 다루지 못한 구간의 노후 상수도관을 정비하는 사업",
    "lead_department_code": "03",
}, timeout=120.0)
res.raise_for_status()
body = res.json()
print("응답 필드:", list(body.keys()))
assert set(TASK_FIELDS).issubset(body["draft"].keys()), f"draft에 9개 필드 누락: {body['draft'].keys()}"
print("[통과] draft에 9개 필드 모두 존재")
print("guardrail_triggered:", body["guardrail_triggered"])
print("needs_review:", body["needs_review"])
print("execution_system(앞부분):", body["draft"]["execution_system"][:100])

print("\n" + "=" * 70)
print("[테스트 3] /api/task-draft - 유사사업 없을 법한 케이스 (fallback 확인)")
print("-" * 70)
res = requests.post(f"{BASE_URL}/api/task-draft", json={
    "title": "화성 이주 정착촌 건설 사업",
    "overview": "화성에 정착촌을 건설하는 사업",
    "lead_department_code": "03",
}, timeout=120.0)
res.raise_for_status()
body = res.json()
assert body["guardrail_triggered"] is True, f"낮은 유사도인데 guardrail이 작동하지 않음: {body}"
assert all(
    v == "참고할 만한 유사 사업이 충분하지 않습니다. 담당자가 직접 작성해주세요."
    for v in body["draft"].values()
), body["draft"]
print("[통과] 낮은 유사도 케이스에서 guardrail_triggered=True, 9개 필드 모두 안내문으로 대체됨")

print("\n" + "=" * 70)
print("[테스트 4] /api/task-draft - 잘못된 lead_department_code (400 에러 확인)")
print("-" * 70)
res = requests.post(f"{BASE_URL}/api/task-draft", json={
    "title": "테스트", "overview": "테스트", "lead_department_code": "99",
}, timeout=10.0)
assert res.status_code == 400, f"잘못된 부서코드인데 400이 아님: {res.status_code}"
print("[통과] 잘못된 lead_department_code=99 요청에 400 반환")

print("\n모든 테스트 통과")
```

- [ ] **Step 5: 서버 실행 후 테스트 실행**

Run (터미널 1): `uvicorn app.main:app --reload --port 8100`
Run (터미널 2): `python tests/test_task_draft_endpoints.py`
Expected: `모든 테스트 통과` (테스트 2, 3은 LLM 호출 포함이라 수십 초 소요될 수 있음)

- [ ] **Step 6: 8개 부서 각각 1건씩 수동 확인 (스펙의 테스트 계획 항목)**

Run:
```bash
python -c "
import requests
samples = [
    ('01', '버스승강장 저상화 확대사업', '기존 저상화 사업의 후속으로 나머지 구간을 개선'),
    ('02', '노후 공동주택 리모델링 2차', '1차 대상에서 제외된 단지의 리모델링 지원'),
    ('03', '노후 하수관로 정비 2차', '1차 사업 이후 남은 구간 하수관로 정비'),
    ('04', '노인맞춤돌봄서비스 확대 2차', '기존 대상자 외 추가 발굴 및 서비스 확대'),
    ('05', '재난안전통신망 확대사업', '기존 통신망 사업의 커버리지 확대'),
    ('06', '전통시장 시설현대화 2차', '1차 사업에서 다루지 못한 시장 추가 지원'),
    ('07', '공공체육시설 확충 2차', '기존 체육시설 확충사업의 후속 사업'),
    ('08', '스마트 민원행정 고도화', '기존 통합 민원시스템의 기능 고도화'),
]
for dept, title, overview in samples:
    res = requests.post('http://localhost:8100/api/task-draft', json={
        'title': title, 'overview': overview, 'lead_department_code': dept,
    }, timeout=120.0)
    res.raise_for_status()
    body = res.json()
    refs = [r['lead_department_code'] for r in body['referenced_tasks']]
    print(f'[{dept}] guardrail_triggered={body[\"guardrail_triggered\"]} 참고사업 부서={refs}')
"
```
Expected: 8줄 모두 출력되고, 각 줄의 `참고사업 부서` 리스트가 전부 해당 `dept` 코드와 같은 값만 포함(다른 부서 코드가 섞이면 실패)

- [ ] **Step 7: Commit**

```bash
git add app/api/routes.py tests/test_task_draft_endpoints.py
git commit -m "feat: 사업계획서 초안작성 API(/api/similar-tasks, /api/task-draft, /api/index-task) 추가"
```

---

## Self-Review 결과

- **스펙 커버리지**: 아키텍처(Task 1,5) / 검색 필터(Task 1) / LLM 프롬프트·JSON 파싱(Task 3) / 가드레일(Task 4) / 엔드포인트 3개(Task 5) / 색인 스크립트(Task 2) / 부서코드 검증(Task 5) / 에러처리(Task 3,5) / 테스트계획(각 Task의 Step)까지 스펙의 모든 섹션이 태스크로 매핑됨.
- **플레이스홀더 스캔**: TBD/TODO/"적절히 처리" 같은 표현 없음, 모든 스텝에 완전한 코드 포함.
- **타입/시그니처 일관성**: `TASK_FIELDS`(Task 1 정의) → Task 3, 4에서 동일하게 import해서 사용. `search_similar_tasks(title, overview, lead_department_code, ...)` 시그니처가 Task 1 정의와 Task 5 호출부에서 동일. `apply_task_guardrail`의 반환 키(`draft`, `guardrail_triggered`, `verification`)가 Task 4 정의와 Task 5 사용부에서 동일.
