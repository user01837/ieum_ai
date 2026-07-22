# 외부 민원 접수 API 설계

- 작성일: 2026-07-22
- 관련 저장소: `ieum_ai`(부서 분류 엔드포인트), `ieum_backend`(접수 엔드포인트)
- 관련 기존 코드: `ieum_backend/app/api/routers/petition.py`, `ieum_ai/app/classifier/ollama_client.py`의 `classify_text`

## 배경 및 목적

지금 `ieum_backend`의 `petition.py`에는 민원 조회/답변/첨부파일 API는 있지만, **새 민원을 접수(생성)하는 API가 없다.** 국민신문고·정부24 같은 외부 민원 채널을 통해 접수된 민원이 우리 플랫폼(`ieum_backend`)에 자동으로 들어오는 흐름을 만드는 것이 목적. 프로젝트가 개발 단계이므로 실제 외부 시스템 연동은 하지 않고, "이런 외부 시스템이 이 API를 호출한다"는 전제로 접수 API 자체만 구현한다.

부서 자동 분류에는 `ieum_ai`에 이미 구현되어 있었다가 2026-07-15(`8f76643`)에 API 표면에서 제거된 `classify_text`(8도메인 분류기, Qwen2.5-3B QLoRA)를 재사용한다 — 함수 자체는 지금도 코드에 남아있고 아무도 호출하지 않는 상태였다.

## 아키텍처

```
[가상 외부 시스템: 국민신문고/정부24]
        │
        │ POST /petitions/external   (X-API-Key 헤더)
        │ { "title": "...", "content": "..." }
        ▼
[ieum_backend: petition.py 신규 엔드포인트]
        │
        │ POST /api/classify-department  { "title": "...", "content": "..." }
        ▼
[ieum_ai: routes.py 신규 엔드포인트] → classify_text() 재사용
        │
        │ { "department_code": "01" }  (실패 시 ieum_backend가 "08"로 폴백)
        ▼
[ieum_backend: PETITION 테이블에 INSERT]
  title, content, department_code, status_code="01"(대기중),
  received_at=now(), task_id=NULL, assignee_user_id=NULL
        ▼
[기존 민원 목록/상세 화면에 그대로 노출 — 담당자가 나중에 배정/답변]
```

## 컴포넌트

### 1. `ieum_ai` — `POST /api/classify-department` (신규)

- **Request**: `{"title": str, "content": str}`
- **Response**: `{"department_code": str}` (`"01"`~`"08"`)
- **구현**:
  - `text = f"{title}\n{content}"`
  - `domain_name = await classify_text(text)` (기존 함수 그대로 재사용, 내부의 `_rule_based_override` 오분류 보정도 자동 적용됨)
  - `DOMAIN_CATEGORIES = ["교통", "주택·건축", "환경", "복지", "안전", "경제·산업", "문화·체육·관광", "행정·일반"]`의 인덱스가 부서 코드 `01`~`08` 순서와 정확히 같다는 점을 이용해 `department_code = f"{DOMAIN_CATEGORIES.index(domain_name) + 1:02d}"`로 매핑.
- 파일: `app/api/routes.py`에 엔드포인트 추가. 매핑 로직은 순수 함수로 분리해서 단위 테스트 가능하게 한다 (예: `app/classifier/ollama_client.py`에 `domain_name_to_department_code(name: str) -> str` 추가).

### 2. `ieum_backend` — `POST /petitions/external` (신규)

- **인증**: 요청 헤더 `X-API-Key`를 신규 설정값 `settings.EXTERNAL_PETITION_API_KEY`(환경변수, `.env.local`)와 비교. 불일치/누락 시 `401`.
- **Request**: `{"title": str, "content": str}` (Petition 모델의 필수 필드와 동일 — 그 외 필드는 전부 nullable이라 안 받아도 됨)
- **처리 순서**:
  1. `httpx.AsyncClient(timeout=15.0)`로 `{settings.AI_SERVER}/api/classify-department` 호출 (기존 `_call_ai_to_index_petition`과 같은 `settings.AI_SERVER` 설정 재사용)
  2. 성공하면 응답의 `department_code` 사용. 실패(연결 오류/타임아웃/4xx/5xx 무엇이든)하면 `"08"`(행정·일반)로 폴백 — **민원 접수 자체는 절대 막지 않는다.**
  3. `Petition(title=req.title, content=req.content, department_code=department_code, status_code="01", received_at=datetime.now())` 생성 후 `db.add` + `db.commit`
- **Response**: `{"petitionId": int, "departmentCode": str}`
- 파일: `app/api/routers/petition.py`에 엔드포인트 추가 (기존 라우터 재사용, 새 라우터 파일 만들지 않음 — 이미 Petition 관련 로직이 다 여기 모여있음).

## 에러 처리

| 상황 | 응답 |
|---|---|
| `X-API-Key` 없음/불일치 | `401` |
| `title`/`content` 비어있음 | `422` (Pydantic 자동 검증) |
| `ieum_ai` `/api/classify-department` 실패 | 부서 `"08"`로 폴백, 민원은 정상 접수됨 (`200`) |
| DB 오류 | 기존 다른 엔드포인트와 동일하게 처리(별도 특수 처리 없음) |

## 테스트

- **`ieum_ai`**: `domain_name_to_department_code()` 매핑 함수를 이 저장소의 기존 관례(plain script, `assert` + `print`, `python tests/test_xxx.py`로 실행)대로 단위 테스트. 8개 도메인명 전부가 올바른 코드로 매핑되는지, 알 수 없는 이름이 들어왔을 때의 동작까지 확인.
- **`ieum_backend`**: 이 저장소에는 테스트 파일이 하나도 없다(확인 완료) — 기존 관례를 따라 새 테스트 프레임워크를 도입하지 않고, curl로 직접 호출해 수동 검증한다 (API 키 정상/누락, 정상 접수 후 기존 민원 목록 조회 API에서 보이는지까지 확인).

## 범위 밖 (이번 설계에 포함하지 않음)

- `task_id` 자동 배정(부서 내 세부업무 자동 분류, `/api/classify-task`와의 연동) — 필요하면 별도 설계
- 실제 외부 시스템(국민신문고 등) 연동 — 이번엔 접수 API 자체만 구현, 호출자는 curl/Postman으로 대체
- 민원인 이름/연락처 등 제출자 정보 — `Petition` 모델에 해당 컬럼이 없어 이번 범위에서 다루지 않음
