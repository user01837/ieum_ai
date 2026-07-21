# 사업 추진계획서 AI 초안작성 기능 설계

- 작성일: 2026-07-21
- 관련 기존 기능: 민원 답변 초안작성 (`/api/similar-cases`, `/api/draft` — `app/api/routes.py`)
- 관련 데이터: `data/seed_tasks.py` (8개 부서 x 15건, 총 120건 합성 사업계획서 코퍼스)

## 배경 및 목적

신임 담당자가 새 사업을 맡았을 때, 전임자 또는 다른 담당자가 과거에 비슷한 사업을 어떻게 추진했는지
(특히 부서 간 협업을 어떻게 했는지, 어떤 시행착오가 있었는지)를 참고하여 사업계획서 초안을 빠르게
작성할 수 있도록 돕는다. 민원 답변 초안작성 기능과 큰 구조(검색 → LLM 생성 → 가드레일)는 같지만,
출력물의 형태와 위험 요소가 달라 별도 구현이 필요하다.

## 민원 초안작성과의 핵심 차이

| 항목 | 민원 답변 초안 | 사업계획 초안 |
|---|---|---|
| 출력 형태 | 답변 문단 1개(자연어 텍스트) | 9개 섹션으로 구조화된 문서 |
| 목적 | 시민에게 나가는 확정 답변 | 담당자가 참고 후 직접 수정하는 내부 초안 |
| 검색 필터 | `department_code` (담당부서) | `lead_department_code` (주관부서)만, `status_code="완료"`만 |
| 사실검증 가드레일 대상 | 법조문·금액·기간·퍼센트 | 금액·기간만 (내부 초안이라 법조문 검증 불필요) |

## 아키텍처

```
[신임 담당자] --사업명+개요+lead_department_code--> POST /api/task-draft
                                    │
                                    ├─ search_similar_tasks(title+overview, lead_department_code, status="완료")
                                    │     └─ task_chroma_client.py: 임베딩검색(20개 후보) → 리랭커 → top_k(3)
                                    │
                                    ├─ top1 유사도 < 임계값(65%)?
                                    │     ├─ Yes → fallback 안내문구로 9개 필드 대체, guardrail_triggered=True
                                    │     └─ No  → generate_task_draft() 호출 (LLM, JSON 9필드 생성)
                                    │
                                    └─ verify_task_draft_claims(draft, similar) - 금액/기간 수치만 검증
                                          └─ needs_review 플래그 + unverified_claims 반환
```

### 신규/변경 파일

1. **`app/vectorstore/task_chroma_client.py`** (신규)
   - 컬렉션명 `tasks` (기존 `complaints` 컬렉션과 완전히 분리 — 회귀 위험 차단)
   - `add_task(...)`, `add_tasks_batch(...)`: `data/seed_tasks.py`의 120건 색인용.
     저장 시 벡터화하는 텍스트는 `title + "\n" + overview` 만 사용(9개 필드 전체가 아님) —
     검색 질의도 같은 조합(title+overview)으로 만들어야 임베딩이 같은 기준으로 비교되기 때문.
     `background` 이하 7개 필드와 메타데이터는 벡터화 없이 결과 표시용으로만 함께 저장.
   - `search_similar_tasks(title, overview, lead_department_code, top_k=3, rerank_candidates=20, exclude_ids=None, min_similarity=None)`:
     - 내부에서 `query_text = f"{title}\n{overview}"`로 조합해 임베딩
     - `where = {"$and": [{"lead_department_code": lead_department_code}, {"status_code": "완료"}]}`
     - 나머지 로직(임베딩검색 → 리랭커 재정렬 → top_k)은 기존 `search_similar_complaints`와 동일 패턴

2. **`app/classifier/ollama_client.py`** (함수 추가)
   - `generate_task_draft(title: str, overview: str, similar_tasks: list[dict]) -> dict`
   - 프롬프트에 "아래 9개 key를 가진 JSON으로만 답하라"고 명시하고, 참고 사업의
     `execution_system`/`post_management`를 실제 협업 사례로 적극 활용하도록 지시
   - JSON 파싱 실패 시 1회 재시도, 재시도도 실패하면 예외를 던져 라우터에서
     `500 {"error": "초안 생성에 실패했습니다. 다시 시도해주세요."}` 응답

3. **`app/classifier/draft_guardrail.py`** (함수 추가, 기존 함수는 그대로 둠)
   - `extract_task_claims(text)`: 기존 `PATTERNS`에서 `금액`, `기간_일수`만 사용 (법조문 패턴 제외)
   - `verify_task_draft_claims(draft_fields: dict, referenced_tasks: list[dict]) -> dict`
     - `draft_fields`의 `budget`, `schedule` 텍스트에서 금액/기간을 추출해 참고 사업들의
       9개 필드 원문과 대조
     - 반환 형태는 기존 `verify_draft_claims`와 동일한 구조(`unverified_claims`, `verified_claims`, `has_unverified`)
   - `apply_task_guardrail(draft_fields, referenced_tasks, similarity_threshold=65.0)`:
     - top1 유사도 미만이면 9개 필드 전체를 **동일한 안내 문구**로 교체:
       `"참고할 만한 유사 사업이 충분하지 않습니다. 담당자가 직접 작성해주세요."`
       (필드별로 다른 문구를 만들지 않고 9개 필드 모두 이 한 문장으로 통일 — 민원의 `fallback_message`와 같은 방식)
     - 통과 시 `verify_task_draft_claims` 결과를 얹어서 반환

4. **`app/api/routes.py`** (엔드포인트 3개 추가)

   ```python
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

   - `POST /api/similar-tasks` → `search_similar_tasks` 호출, `{"results": [...]}`
   - `POST /api/task-draft` → 검색 → `generate_task_draft` → `apply_task_guardrail` →
     `{"draft": {...9개 필드...}, "referenced_tasks": [...], "guardrail_triggered": bool, "needs_review": bool, "unverified_claims": {...}}`
   - `POST /api/index-task` → `status_code == "완료"`인 사업 1건을 `add_task`로 색인.
     (백엔드에서 사업이 "완료" 처리될 때 이 엔드포인트를 호출하는 것을 전제로 함 — 기존 `/api/index-complaint`와 동일한 계약)

### `lead_department_code` 유효성 검증

01~08 외의 값이 들어오면 3개 엔드포인트 모두 400 에러 반환 (`{"error": "invalid lead_department_code"}`).

## 에러 처리

- 검색 결과 0건(해당 부서의 완료 사업이 아직 하나도 없음) → `top1 유사도 < 임계값` 분기와 동일하게 처리(빈 리스트 → 유사도 0 취급 → fallback)
- LLM JSON 파싱 실패 → 1회 재시도 → 최종 실패 시 500 에러
- `lead_department_code` 값이 01~08 목록에 없음 → 400 에러

## 테스트 계획

- `search_similar_tasks`: 부서 필터링이 정확한지(예: `03` 조회 시 `05` 소속 사업이 섞여 나오지 않는지), `status_code="완료"` 외 데이터가 제외되는지
- `verify_task_draft_claims`: 금액/기간만 검사하고 법조문 패턴은 무시하는지(민원용 함수와의 혼용 방지)
- `apply_task_guardrail`: 유사도 임계값 미만일 때 9개 필드가 모두 fallback으로 교체되는지
- `data/seed_tasks.py`의 실제 120건 데이터를 색인한 뒤, 8개 부서 각각에 대해 수동으로 1건씩
  `task-draft` 호출 → 같은 부서 사업만 참고되는지, 협업 내용이 초안에 반영되는지 육안 확인

## 범위 밖(이번 설계에 포함하지 않음)

- `collab_department_codes`를 활용한 교차 부서 검색(추후 필요 시 별도 설계)
- 사업 초안을 프론트엔드에서 실제로 저장/수정하는 UI 흐름(백엔드 API 설계까지만 다룸)
