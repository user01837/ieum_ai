# 공공이음 AI 서버 API 명세

공무원 인사이동 시 업무 인수인계를 돕는 AI 서비스의 백엔드 연동 문서. 모든 엔드포인트는 `POST`이며, prefix `/api`가 붙습니다.

- **Base URL**: `http://<host>:8100`
- **인증**: 없음 (내부망 전용)
- **임베딩**: `jhgan/ko-sbert-nli`
- **리랭커**: `BAAI/bge-reranker-v2-m3`
- **생성모델**: `llama3.1:8b`

## 목차

- [최근 변경사항](#최근-변경사항)
- [부서 코드](#부서-코드)
- 민원 초안: [`/similar-cases`](#post-apisimilar-cases) · [`/draft`](#post-apidraft) · [`/index-complaint`](#post-apiindex-complaint)
- 법률 QA: [`/legal-chat`](#post-apilegal-chat)
- 사업계획서 초안: [`/similar-tasks`](#post-apisimilar-tasks) · [`/task-draft`](#post-apitask-draft) · [`/index-task`](#post-apiindex-task)
- TASK 분류(신규): [`/classify-task`](#post-apiclassify-task) · [`/index-task-category`](#post-apiindex-task-category)

---

## 최근 변경사항

지난 스펙 이후 반영된 변경점 — 백엔드 연동 시 아래 항목 확인 필요.

- **포트**: 기본 포트가 `8100`으로 재정상화됨 (임시로 8200을 썼던 기간 있었음, 지금은 8100이 정식)
- **부서 코드**: `department_code` / `lead_department_code`는 전부 `"01"~"08"` 숫자 코드 문자열 사용 (DB DEPARTMENT 테이블과 동일)
- **유사도 기본값**: `/api/similar-cases`의 `min_similarity` 기본값이 `65.0`으로 적용됨
- **Fallback 문구**: 민원 초안(`/api/draft`) fallback 안내문구가 격식체 장문에서 짧은 안내문("AI 초안을 생성하지 못했습니다…")으로 변경됨 — 사업계획서 쪽과 톤 통일
- **신규 엔드포인트**: `/api/classify-task`, `/api/index-task-category` 추가 (부서 내 세부업무 자동 분류)
- **`/api/task-draft` 응답 형식**: `draft`의 9개 필드 값이 평문에서 `<h3>`/`<p>` HTML로 변경됨. `background` 필드는 `<h3>추진 배경</h3>` / `<h3>사업 필요성</h3>` 두 소제목으로 분리되어 옴. 백엔드 연동 상세는 [`백엔드_연동_가이드_AI초안.md`](./백엔드_연동_가이드_AI초안.md) 참고

---

## 부서 코드

| 코드 | 부서명 | 코드 | 부서명 |
|---|---|---|---|
| `01` | 교통 | `05` | 안전 |
| `02` | 주택·건축 | `06` | 경제·산업 |
| `03` | 환경 | `07` | 문화·체육·관광 |
| `04` | 복지 | `08` | 행정·일반 |

---

## 민원 초안

### `POST /api/similar-cases`
유사 민원 검색 (LLM 미사용). 부서 범위 내에서 벡터 검색 + 리랭커로 유사 민원을 검색만 함. "유사사례 추가 검색" 버튼용으로 `exclude_ids`/`min_similarity` 지원.

**Request Body**

| 필드 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `query_text` | string | — | 검색할 민원 텍스트 |
| `department_code` | string | — | 부서 코드 (01~08) |
| `top_k` | int | 2 | 반환 건수 |
| `exclude_ids` | int[] | [] | 이미 보여준 complaint_id 제외 |
| `min_similarity` | float | 65.0 | 이 값 미만 결과 제외 |

```json
// Request
{
  "query_text": "도로에 포트홀이 있어요",
  "department_code": "01",
  "top_k": 2
}
```

```json
// Response 200
{
  "results": [{
    "complaint_id": 20,
    "title": "불법 주정차 단속 요청",
    "content": "...",
    "answer": "",
    "department_code": "01",
    "domain_code": "기타",
    "status_code": "완료",
    "similarity": 76.4,
    "rerank_score": 0.9963
  }]
}
```

> 결과가 빈 배열이면 "더 이상 유사 사례 없음" — 추가검색 버튼 비활성화 처리 권장.

### `POST /api/draft`
민원 답변 초안 생성 (LLM). 내부적으로 similar-cases와 동일한 검색(top_k=3)을 먼저 하고, 그 결과를 근거로 Llama3.1이 답변 초안을 생성.

**Request Body**

| 필드 | 타입 | 설명 |
|---|---|---|
| `complaint_text` | string | 민원 원문 |
| `department_code` | string | 부서 코드 (01~08) |

```json
// Request
{ "complaint_text": "가로등이 꺼져있어요", "department_code": "01" }
```

```json
// Response 200
{
  "draft": "...",
  "referenced_cases": [ "..." ],
  "guardrail_triggered": false,
  "needs_review": false,
  "unverified_claims": {}
}
```

> **응답 지연**: LLM 생성 구간이라 30초~2분 소요. 타임아웃 120초 이상, 로딩 UI 필수.
>
> **guardrail_triggered=true**면 `draft`가 안내문구로 대체됨 (위 변경사항 참고). **needs_review=true**는 draft는 그대로 두고 "재확인 필요" 배지만 붙이는 용도.

### `POST /api/index-complaint`
완료 민원 색인. 민원이 "완료" 처리될 때 백엔드가 호출 — 검색 대상 코퍼스에 추가.

**Request Body**

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `complaint_id` | int | ✓ | 민원 ID |
| `title` | string | ✓ | 제목 |
| `content` | string | ✓ | 본문 |
| `department_code` | string | ✓ | 부서 코드 |
| `domain_code` | string | | 통계용 (검색 필터엔 미사용) |
| `status_code` | string | | — |

```json
// Response 200
{ "status": "indexed", "complaint_id": 401 }
```

---

## 법률 QA

### `POST /api/legal-chat`
법령 조문 기반 질의응답. 6개 법령 607개 조문 코퍼스에서 검색. 부서 구분 없이 전 직원 접근 가능 (우측하단 챗봇 아이콘 전용).

**Request Body**

| 필드 | 타입 | 설명 |
|---|---|---|
| `question` | string | 질문 (department_code 불필요) |

```json
// Response 200
{ "answer": "...", "referenced_articles": [ "..." ] }
```

---

## 사업계획서 초안

### `POST /api/similar-tasks`
유사 완료사업 검색 (LLM 미사용). 주관부서(lead_department_code) 범위 + 완료(status_code="완료") 사업만 대상. "이런 사업 참고하세요" 미리보기용.

**Request Body**

| 필드 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `title` | string | — | 신규 사업명 |
| `overview` | string | — | 신규 사업 개요 |
| `lead_department_code` | string | — | 주관부서 코드 |
| `top_k` | int | 3 | 반환 건수 |

```json
// Response 200
{ "results": [{
    "task_id": 1, "year": 2024, "title": "노후 하수관로 정비사업",
    "lead_department_code": "03", "collab_department_codes": ["01","02"],
    "domain_code": "환경", "status_code": "완료",
    "overview": "...", "background": "...", "goals": "...",
    "detailed_plan": "...", "schedule": "...", "execution_system": "...",
    "budget": "...", "expected_effect": "...", "post_management": "...",
    "similarity": 85.6, "rerank_score": 0.9496
}] }
```

### `POST /api/task-draft`
사업계획서 초안 생성 (LLM, 핵심 기능). 유사 완료사업 검색 → LLM이 9개 섹션 초안 생성 → 2단계 가드레일 적용.

**Request Body**

| 필드 | 타입 | 설명 |
|---|---|---|
| `title` | string | 사업명 |
| `overview` | string | 사업 개요 |
| `lead_department_code` | string | 주관부서 코드 |

**Response — draft 9개 필드**: `overview · background · goals · detailed_plan · schedule · execution_system · budget · expected_effect · post_management`

> **값 형식이 HTML임** (2026-07-22부터): 각 필드는 `<h3>`/`<p>` 태그를 포함한 HTML 문자열. `background`만 `<h3>추진 배경</h3>` / `<h3>사업 필요성</h3>` 두 소제목으로 분리되어 옴. 프론트가 이 값을 그대로 Tiptap에 주입/렌더링하는 걸 전제로 함.

```json
// Response 200
{
  "draft": {
    "overview": "<p>노후 버스승강장을 저상화하여 교통약자 접근성을 개선하는 사업입니다.</p>",
    "background": "<h3>추진 배경</h3>\n<p>&nbsp;&nbsp;&nbsp;&nbsp;□ 노후 버스승강장이 많아 교통약자 이용이 어려움</p>\n<h3>사업 필요성</h3>\n<p>&nbsp;&nbsp;&nbsp;&nbsp;□ 저상버스 승강장 설치로 이동 편의 향상</p>",
    "...": "<p>...</p>"
  },
  "referenced_tasks": [ "..." ],
  "guardrail_triggered": false,
  "needs_review": true,
  "unverified_claims": { "금액": ["3천만원"] }
}
```

> **응답 지연**: 실측 최대 2분 17초 (HTML 마크다운 지시문이 추가되며 프롬프트가 길어져 기존 103초보다 늘어남). 타임아웃 180초 이상 권장.
>
> **lead_department_code**가 01~08이 아니면 `400` 에러.
>
> **guardrail_triggered=true**면 9개 필드 전부 "참고할 만한 유사 사업이 충분하지 않습니다. 담당자가 직접 작성해주세요."로 대체됨 (top1 유사도 65% 미만일 때, `<p>` HTML로 감싸져서 옴).

### `POST /api/index-task`
완료 사업 색인. 사업이 "완료" 처리될 때 백엔드가 호출. (기존 index-complaint와 동일 계약)

**Request Body**

| 필드 | 타입 | 설명 |
|---|---|---|
| `task_id`, `year` | int | 사업 ID · 완료연도 |
| `title`, `overview` | string | 사업명 · 개요 |
| `lead_department_code` | string | 주관부서 |
| `collab_department_codes` | string[] | 협력부서 목록 |
| `domain_code`, `status_code` | string | 도메인 · 상태 ("완료") |
| `background`, `goals`, `detailed_plan`, `schedule`, `execution_system`, `budget`, `expected_effect`, `post_management` | string | 나머지 9섹션 필드 |

```json
// Response 200
{ "status": "indexed", "task_id": 1, "lead_department_code": "03" }
```

---

## TASK 분류 (신규)

### `POST /api/classify-task`
부서 내 세부업무 자동 분류. 민원 텍스트 + department_code를 받아, 그 부서 안의 가장 유사한 세부업무(Task)를 찾아 반환. 담당자 배정(TASK_ASSIGNEE)은 하지 않음 — 여기까지가 AI 서버 역할.

**Request Body**

| 필드 | 타입 | 설명 |
|---|---|---|
| `complaint_text` | string | 민원 텍스트 |
| `department_code` | string | 부서 코드 (현재 01 교통만 데이터 존재) |

```json
// Request
{ "complaint_text": "신호등이 고장났어요", "department_code": "01" }
```

```json
// Response 200
{ "task_id": 2, "task_name": "교통시설관리과", "similarity": 74.6 }
```

> **task_id는 실제 DB TASK.task_id와 다를 수 있는 AI 서버 내부 임시 ID**입니다. `/api/index-task-category`로 색인된 항목만 실제 DB ID와 일치가 보장됩니다 — 아래 참고.
>
> 매칭 결과 없으면 `{"task_id": null, "task_name": null, "similarity": 0.0}` 반환. 유사도 임계값(fallback)은 아직 미적용 — 결과 있으면 무조건 top1 반환.

### `POST /api/index-task-category`
세부업무(TASK) 색인. **부서관리자가 실제 DB TASK 테이블에 업무를 새로 생성하는 시점(진짜 task_id 발급 시점)**에 반드시 호출 — 그래야 `/api/classify-task`가 반환하는 번호가 처음부터 진짜 DB PK와 일치함.

**Request Body**

| 필드 | 타입 | 설명 |
|---|---|---|
| `task_id` | int | **실제 DB TASK.task_id (AUTO_INCREMENT 값 그대로)** |
| `name` | string | 업무과명 |
| `department_code` | string | 소속 부서 코드 |
| `description` | string | 업무 설명 (검색 정확도에 직결 — 구어체 예시 문구 포함 권장) |

```json
// Response 200
{ "status": "indexed", "task_id": 100, "department_code": "01" }
```

> **department_code**가 01~08이 아니면 `400` 에러. Delete API는 없음 — 잘못 색인했으면 같은 task_id로 다시 호출(upsert)해 덮어써야 함.

---

공공이음(이음표) AI 서버 · 이 문서는 실제 코드/테스트 검증 기준으로 작성됨 · 백엔드 연동 시 이 문서 기준으로 계약 확인 요망
