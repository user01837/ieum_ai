# 민원 접수 공개 폼(citizen apply page) 설계

- 작성일: 2026-07-28
- 관련 저장소: `ieum_frontend`(신규 공개 페이지), `ieum_backend`(`due_date` 자동 설정 추가)
- 관련 기존 기능: [외부 민원 접수 API 설계](./2026-07-22-external-petition-intake-design.md) — 그 문서에서 만든 `POST /petitions/external`을 그대로 재사용한다.

## 배경 및 목적

`POST /petitions/external`은 지금까지 Swagger로만 테스트됐다. 이번 작업은 시민이 로그인 없이 직접 민원을 접수할 수 있는 프론트엔드 공개 페이지를 만드는 것이다 — 새 백엔드 엔드포인트는 만들지 않고, 기존 API를 프론트에서 그대로 호출한다.

## 인증 방식에 대한 결정 (중요)

`POST /petitions/external`은 `X-API-Key` 헤더로 인증한다 — 원래는 "우리가 신뢰하는 외부 시스템(국민신문고 등)"을 인증하기 위한 키다. 공개 웹페이지에서 이 API를 직접 호출하면 키가 브라우저 JS 번들에 그대로 포함되어 누구나 개발자도구로 추출할 수 있다는 문제가 있음을 사용자에게 명시적으로 안내했다.

**대안(별도의 인증 없는 공개 엔드포인트 신설)을 제안했으나, 사용자가 "어차피 프로젝트용 개발이라 괜찮다"며 기존 API를 키와 함께 그대로 프론트에서 호출하는 방식을 선택했다.** 이 설계는 그 결정을 따른다 — 프로덕션 수준의 보안이 필요해지면 위 대안(로직을 공유 함수로 분리해 인증 없는 엔드포인트 신설)으로 전환할 것을 권장하는 내용을 문서에 남긴다.

## 아키텍처

```
[시민 브라우저 - /apply 페이지]
        │
        │ POST /petitions/external (X-API-Key 헤더 포함)
        ▼
[ieum_backend: create_external_petition] (기존 로직 그대로, due_date 계산만 추가)
    - 부서 자동분류(ieum_ai /api/classify-department)
    - 업무 자동분류(ieum_ai /api/classify-task)
    - 담당자 자동배정(미완료건 최소 보유자)
    - Petition 생성 (received_at=now, due_date=now+14일 ← 신규)
        │
        ▼
[응답: petitionId, departmentCode] → 프론트가 완료 화면에 표시
```

`/apply`는 `ieum_frontend`의 라우터에서 `MainLayout`/로그인 보호 트리 밖의 최상위 라우트로 추가한다 (`/login`과 동일한 위치 레벨).

## 컴포넌트

### 1. `ieum_backend` — `create_external_petition`에 `due_date` 추가

`app/api/routers/petition.py`의 `Petition(...)` 생성 부분에 한 줄 추가:

```python
petition = Petition(
    title=req.title,
    content=req.content,
    department_code=department_code,
    task_id=task_id,
    assignee_user_id=assignee_user_id,
    status_code="01",
    received_at=datetime.now(),
    due_date=datetime.now() + timedelta(days=14),  # 신규
)
```

`timedelta`가 이미 import돼 있는지 확인, 없으면 `from datetime import datetime, timedelta`로 보강.

### 2. `ieum_frontend` — 신규 페이지 `src/pages/Apply/Apply.jsx` (+ `Apply.module.css`)

`Login.jsx`/`Login.module.css`와 동일한 톤(네이비 그라디언트 배경, 흰색 카드, `--navy`/`--ink`/`--ink-soft`/`--line-strong` 등 기존 CSS 변수 재사용)으로 작성한다.

**입력 화면 (기본 상태)**
- 로고 + "민원 접수" 타이틀
- 제목(input, 필수), 내용(textarea, 필수) — 빈 값이면 제출 막고 필드 아래 인라인 에러 표시
- "접수하기" 버튼 — 제출 중 비활성화 + 로딩 표시
- 실패 시 카드 안에 에러 메시지 표시, 재시도 가능하도록 버튼 다시 활성화

**완료 화면 (같은 페이지 내 상태 전환, 라우트 이동 없음)**
- "민원이 정상적으로 접수되었습니다" 안내
- 접수번호(`petitionId`)
- 배정 부서명 — 응답엔 `departmentCode`만 오므로, 기존 `getDepartments()`(`src/api/dept.js`, `Login.jsx`에서 이미 인증 없이 쓰고 있음)로 목록을 불러와 이름으로 변환해 표시
- 처리예정일 — 프론트에서 제출 시점 기준 `오늘 + 14일`을 계산해 표시(백엔드 계산과 동일한 규칙)
- "새 민원 접수하기" 버튼 → 입력 화면 상태로 초기화

### 3. `ieum_frontend` — API 호출 함수 (`src/api/petition.js`에 추가)

기존 `api`(axios, `src/api/axios.js`) 인스턴스는 요청 인터셉터에서 로그인 토큰을 자동으로 붙인다 — 시민은 토큰이 없는 상태이므로 이 인스턴스를 그대로 쓰지 않고, `X-API-Key` 헤더만 실어서 별도로 호출한다.

```javascript
export const submitExternalPetition = async ({ title, content }) => {
  const response = await api.post(
    "/petitions/external",
    { title, content },
    { headers: { "X-API-Key": import.meta.env.VITE_EXTERNAL_PETITION_API_KEY } }
  );
  return response.data; // { petitionId, departmentCode }
};
```

기존 `api`(axios) 인스턴스의 baseURL만 그대로 쓰고, 이 요청에만 `X-API-Key` 헤더를 추가로 얹는다. Authorization 헤더는 토큰이 없으면 인터셉터가 아예 안 붙이므로 문제 없다.

### 4. `ieum_frontend` — 라우팅 (`src/routes/Router.jsx`)

최상위 라우트에 추가 (로그인 불필요):

```javascript
{
  path: "/apply",
  element: <Apply />,
},
```

### 5. `ieum_frontend` — 환경변수

`.env`에 `VITE_EXTERNAL_PETITION_API_KEY=<실제 키 값>` 추가, `.env.sample`에는 플레이스홀더로 추가(`VITE_EXTERNAL_PETITION_API_KEY=your-api-key-here`).

## 에러 처리

| 상황 | 처리 |
|---|---|
| 제목/내용 미입력 | 서버 호출 전 프론트에서 막고 인라인 에러 표시 |
| 네트워크 오류/서버 다운 | "일시적인 오류로 접수에 실패했습니다. 잠시 후 다시 시도해주세요" + 재시도 가능(버튼 재활성화) |
| 백엔드 5xx 응답 | 위와 동일 처리 |
| 401(API 키 불일치) | 이론상 발생 안 함(우리 프론트가 올바른 키를 보냄) — 발생하면 위와 동일한 일반 에러 메시지로 처리(사용자에게 키 문제라는 세부사항 노출 안 함) |

## 테스트

이 프로젝트는 프론트/백엔드 모두 자동화 테스트가 없는 기존 관례를 따른다.

- 백엔드: `due_date` 로직을 스크립트로 직접 호출 후, DB에서 생성된 Petition의 `due_date`가 `received_at + 14일`인지 확인
- 프론트: 개발 서버(`npm run dev`)로 `/apply` 접속 → 제목/내용 입력 후 제출 → 완료 화면에 접수번호·부서명·처리예정일 정상 표시 확인 → 실제 DB에 반영됐는지 확인

## 범위 밖

- 별도의 인증 없는 공개 엔드포인트 신설 — 이번엔 기존 API를 키와 함께 그대로 쓰기로 결정. 프로덕션급 보안이 필요해지면 로직을 공유 함수로 분리해 재검토 권장
- 이름·연락처 등 추가 입력 필드 — 제목/내용만 받기로 확정
- 첨부파일 업로드 — 요청 없었음, 범위 밖
- 접수 후 시민이 자기 민원 처리 현황을 조회하는 기능 — 요청 없었음, 범위 밖
