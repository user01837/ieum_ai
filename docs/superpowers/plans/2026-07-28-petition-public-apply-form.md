# 민원 접수 공개 폼(/apply) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 시민이 로그인 없이 제목/내용만 입력해 민원을 접수할 수 있는 공개 페이지(`/apply`)를 `ieum_frontend`에 신설하고, 접수된 민원의 처리예정일이 접수일+14일로 자동 설정되게 한다.

**Architecture:** 프론트엔드 `/apply` 페이지가 기존 `ieum_backend`의 `POST /petitions/external`(API 키 인증)을 `X-API-Key` 헤더와 함께 직접 호출한다. 새 백엔드 엔드포인트는 만들지 않는다. `ieum_backend`의 `create_external_petition`에는 `due_date` 자동 계산 로직 한 줄만 추가한다.

**Tech Stack:** React + Vite + React Query(`@tanstack/react-query`) + CSS Modules (프론트), FastAPI + SQLAlchemy (백엔드, 기존 그대로).

## Global Constraints

- API 키는 프론트 `.env`의 `VITE_EXTERNAL_PETITION_API_KEY`로 관리한다. 이 키는 브라우저 번들에 노출되는 것을 인지하고 감수한 결정이다(설계 문서 참고) — 별도 인증 없는 엔드포인트를 새로 만들지 않는다.
- 폼 필드는 제목(title)·내용(content) 두 개만 받는다. 이름/연락처/첨부파일은 범위 밖.
- 새 페이지는 로그인 보호(`protectedLoader`) 밖의 최상위 라우트여야 한다.
- 시각적으로 기존 `Login.jsx`/`Login.module.css`와 동일한 톤(네이비 그라디언트 배경 + 흰색 카드, `--navy`/`--ink`/`--ink-soft`/`--line-strong` CSS 변수)을 따른다.
- 이 프로젝트는 프론트/백엔드 모두 자동화 테스트가 없는 기존 관례를 따른다 — 새로 테스트 프레임워크를 도입하지 않고, 스크립트/브라우저로 수동 검증한다.

참고 문서: `docs/superpowers/specs/2026-07-28-petition-public-apply-form-design.md`

---

### Task 1: 백엔드 — 접수 시 처리예정일(due_date) 자동 설정

**Files:**
- Modify: `ieum_backend/app/api/routers/petition.py` (5번째 줄의 import, 208~216번째 줄 `Petition(...)` 생성부)

**Interfaces:**
- Consumes: 없음 (기존 `create_external_petition` 함수 내부 로직만 수정)
- Produces: `POST /petitions/external`로 생성된 모든 `Petition` 행의 `due_date` 컬럼이 `received_at + 14일`로 채워짐. 이후 프론트(Task 2)는 이 값을 API 응답으로 다시 받아오지 않고 자체적으로 `오늘+14일`을 계산해 표시하므로, 이 Task와 Task 2는 서로 독립적으로 완료 가능함.

- [ ] **Step 1: import 문에 timedelta 추가**

`ieum_backend/app/api/routers/petition.py` 5번째 줄:

```python
from datetime import datetime
```

를 다음으로 변경:

```python
from datetime import datetime, timedelta
```

- [ ] **Step 2: Petition 생성 시 due_date 계산 추가**

같은 파일의 `create_external_petition` 함수 안, 아래 블록(현재 208~216번째 줄 부근)을 찾는다:

```python
    petition = Petition(
        title=req.title,
        content=req.content,
        department_code=department_code,
        task_id=task_id,
        assignee_user_id=assignee_user_id,
        status_code="01",
        received_at=datetime.now(),
    )
```

아래처럼 `due_date` 한 줄을 추가한다:

```python
    petition = Petition(
        title=req.title,
        content=req.content,
        department_code=department_code,
        task_id=task_id,
        assignee_user_id=assignee_user_id,
        status_code="01",
        received_at=datetime.now(),
        due_date=datetime.now() + timedelta(days=14),
    )
```

- [ ] **Step 3: 백엔드 서버 기동 확인**

`ieum_backend` 디렉터리에서(가상환경 활성화 상태로):

```bash
python -m uvicorn app.main:app --reload
```

콘솔에 에러 없이 `Application startup complete.`가 뜨는지 확인한다. (이미 `--reload`로 떠있는 서버가 있다면 파일 저장 시 자동 반영되므로 이 단계는 생략 가능.)

- [ ] **Step 4: 실제 호출로 검증**

`.env.local`의 `EXTERNAL_PETITION_API_KEY` 값을 확인한 뒤(값은 파일에서 직접 확인, 커밋 금지), 아래처럼 실제 엔드포인트를 호출한다 (PowerShell 예시, `<API_KEY>`는 실제 값으로 치환):

```powershell
$body = '{"title":"due_date 테스트용 민원","content":"테스트 내용입니다."}'
$r = Invoke-RestMethod -Uri "http://localhost:8000/petitions/external" -Method POST -Body $body -ContentType "application/json" -Headers @{ "X-API-Key" = "<API_KEY>" }
$r
```

응답으로 `petitionId`, `departmentCode`가 나오는 것을 확인한다.

- [ ] **Step 5: DB에서 due_date 값 확인**

`ieum_backend` 디렉터리에서:

```bash
python -c "
from app.db.session import SessionLocal
from app.models.petition import Petition
db = SessionLocal()
p = db.query(Petition).order_by(Petition.petition_id.desc()).first()
print('petition_id:', p.petition_id)
print('received_at:', p.received_at)
print('due_date:', p.due_date)
print('diff_days:', (p.due_date - p.received_at).days)
db.close()
"
```

`diff_days`가 `14`로 출력되는지 확인한다. (Step 4에서 만든 테스트용 민원이므로 확인 후 지워도 되고, 데모 데이터로 남겨둬도 무방함 — 별도 정리 불필요.)

- [ ] **Step 6: 커밋**

```bash
git add app/api/routers/petition.py
git commit -m "feat: 외부 민원 접수 시 처리예정일(due_date)을 접수일+14일로 자동 설정"
```

---

### Task 2: 프론트엔드 — 민원 접수 공개 페이지 `/apply`

**Files:**
- Modify: `ieum_frontend/src/api/petition.js` (API 호출 함수 추가)
- Modify: `ieum_frontend/src/hooks/mutations/usePetitionMutations.js` (mutation 훅 추가)
- Create: `ieum_frontend/src/pages/Apply/Apply.jsx`
- Create: `ieum_frontend/src/pages/Apply/Apply.module.css`
- Modify: `ieum_frontend/src/routes/Router.jsx` (라우트 등록)
- Modify: `ieum_frontend/.env` (API 키 추가)
- Modify: `ieum_frontend/.env.sample` (플레이스홀더 추가)

**Interfaces:**
- Consumes: `getDepartments()` (`src/api/dept.js`, 기존 함수, `[{code, name}, ...]` 반환) — 응답의 `departmentCode`를 부서명으로 변환하는 데 사용.
- Produces: `submitExternalPetition({title, content})` — `POST /petitions/external`을 `X-API-Key` 헤더와 함께 호출, `{petitionId, departmentCode}` 반환. `useSubmitExternalPetitionMutation(options)` — 이 함수를 감싼 React Query mutation 훅, `options`(onSuccess/onError 등)를 그대로 전달받음.

- [ ] **Step 1: API 호출 함수 추가**

`ieum_frontend/src/api/petition.js` 파일 맨 끝에 아래 함수를 추가한다:

```javascript
/**
 * 시민이 로그인 없이 민원을 접수하는 공개 API (외부 민원 접수 API를 그대로 재사용)
 * @param {object} payload - { title, content }
 */
export const submitExternalPetition = async ({ title, content }) => {
  const response = await api.post(
    '/petitions/external',
    { title, content },
    { headers: { 'X-API-Key': import.meta.env.VITE_EXTERNAL_PETITION_API_KEY } }
  );
  return response.data;
};
```

- [ ] **Step 2: mutation 훅 추가**

`ieum_frontend/src/hooks/mutations/usePetitionMutations.js` 파일 맨 위 import 줄:

```javascript
import { answerPetition, tempSavePetition, deleteAttachment, findSimilarPetitions, createDraftAnswer } from '../../api/petition';
```

를 다음으로 변경(`submitExternalPetition` 추가):

```javascript
import { answerPetition, tempSavePetition, deleteAttachment, findSimilarPetitions, createDraftAnswer, submitExternalPetition } from '../../api/petition';
```

파일 맨 끝에 아래 훅을 추가한다:

```javascript
/**
 * 민원 접수 공개 폼(/apply)에서 쓰는 Mutation
 * @param {object} options - react-query useMutation options
 */
export const useSubmitExternalPetitionMutation = (options) => {
  return useMutation({
    mutationFn: submitExternalPetition,
    ...options,
  });
};
```

- [ ] **Step 3: 환경변수 추가**

`ieum_frontend/.env`에서(기존 `VITE_API_BASE_URL=http://localhost:8000` 다음 줄에) 아래 줄을 추가한다. 값은 `ieum_backend/.env.local`의 `EXTERNAL_PETITION_API_KEY`와 동일한 실제 키 값으로 채운다(파일에서 직접 확인 후 입력, 커밋 시 이 파일은 git-ignore 대상인지 먼저 확인):

```
VITE_EXTERNAL_PETITION_API_KEY=<실제 키 값>
```

`ieum_frontend/.env.sample`에는 플레이스홀더로 추가한다:

```
VITE_EXTERNAL_PETITION_API_KEY=your-api-key-here
```

- [ ] **Step 4: Apply 페이지 컴포넌트 작성**

`ieum_frontend/src/pages/Apply/Apply.jsx` 파일을 새로 만든다:

```jsx
import { useState } from "react";
import styles from "./Apply.module.css";
import logo from "../../assets/logo.png";
import { useQuery } from "@tanstack/react-query";
import { getDepartments } from "../../api/dept";
import { useSubmitExternalPetitionMutation } from "../../hooks/mutations/usePetitionMutations";

function addDays(date, days) {
  const result = new Date(date);
  result.setDate(result.getDate() + days);
  return result;
}

function formatDate(date) {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

export default function Apply() {
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [titleError, setTitleError] = useState(false);
  const [contentError, setContentError] = useState(false);
  const [submitError, setSubmitError] = useState("");
  const [result, setResult] = useState(null);

  const { data: deptList } = useQuery({
    queryKey: ["departments"],
    queryFn: getDepartments,
    staleTime: Infinity,
  });

  const { mutate: submitMutate, isPending } = useSubmitExternalPetitionMutation({
    onSuccess: (data) => {
      setResult({
        petitionId: data.petitionId,
        departmentCode: data.departmentCode,
        dueDate: formatDate(addDays(new Date(), 14)),
      });
    },
    onError: () => {
      setSubmitError("일시적인 오류로 접수에 실패했습니다. 잠시 후 다시 시도해주세요.");
    },
  });

  const handleSubmit = (e) => {
    e.preventDefault();
    setTitleError(false);
    setContentError(false);
    setSubmitError("");

    let hasError = false;
    if (!title.trim()) {
      setTitleError(true);
      hasError = true;
    }
    if (!content.trim()) {
      setContentError(true);
      hasError = true;
    }
    if (hasError) return;

    submitMutate({ title, content });
  };

  const handleReset = () => {
    setTitle("");
    setContent("");
    setResult(null);
    setSubmitError("");
  };

  const departmentName =
    result && deptList?.find((d) => d.code === result.departmentCode)?.name;

  return (
    <div className={styles.applyPage}>
      <div className={styles.wrap}>
        <div className={styles.brandrow}>
          <div><img className={styles["img-box"]} src={logo} alt="loader image" /></div>
          <div>
            <div className="brand-title">공무원 업무지원 플랫폼</div>
            <div className="brand-sub">전국 지방자치단체 통합 업무관리 시스템</div>
          </div>
        </div>

        {result ? (
          <div className={styles.card}>
            <div className={styles["card-title"]}>민원이 정상적으로 접수되었습니다</div>
            <div className={styles["card-sub"]}>아래 내용을 확인해 주세요.</div>

            <div className={styles.resultRow}>
              <span className={styles.resultLabel}>접수번호</span>
              <span className={styles.resultValue}>{result.petitionId}</span>
            </div>
            <div className={styles.resultRow}>
              <span className={styles.resultLabel}>배정 부서</span>
              <span className={styles.resultValue}>{departmentName || result.departmentCode}</span>
            </div>
            <div className={styles.resultRow}>
              <span className={styles.resultLabel}>처리예정일</span>
              <span className={styles.resultValue}>{result.dueDate}</span>
            </div>

            <div className={styles.buttonContainer}>
              <button type="button" className={styles["btn-primary"]} onClick={handleReset}>
                새 민원 접수하기
              </button>
            </div>
          </div>
        ) : (
          <form className={styles.card} onSubmit={handleSubmit}>
            <div className={styles["card-title"]}>민원 접수</div>
            <div className={styles["card-sub"]}>제목과 내용을 입력해 주세요.</div>

            <div className={styles.field}>
              <label>제목</label>
              <div className={styles.inputwrap}>
                <input
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  placeholder="민원 제목을 입력하세요"
                />
              </div>
              {titleError && (
                <div className={`${styles["field-error"]} show`}>* 제목을 입력해 주세요.</div>
              )}
            </div>

            <div className={styles.field}>
              <label>내용</label>
              <div className={styles.inputwrap}>
                <textarea
                  className={styles.textarea}
                  value={content}
                  onChange={(e) => setContent(e.target.value)}
                  placeholder="민원 내용을 입력하세요"
                  rows={6}
                />
              </div>
              {contentError && (
                <div className={`${styles["field-error"]} show`}>* 내용을 입력해 주세요.</div>
              )}
            </div>

            {submitError && (
              <div className={`${styles["field-error"]} show`}>{submitError}</div>
            )}

            <div className={styles.buttonContainer}>
              <button type="submit" className={styles["btn-primary"]} disabled={isPending}>
                {isPending ? "접수 중..." : <>접수하기 <span>→</span></>}
              </button>
            </div>
          </form>
        )}

        <div className={styles.footlink}>
          문의사항은 <b>관할 부서</b>로 연락해 주세요.
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 5: 스타일시트 작성**

`ieum_frontend/src/pages/Apply/Apply.module.css` 파일을 새로 만든다:

```css
.applyPage {
  margin:0;
  font-family:'Noto Sans KR', sans-serif;
  background: linear-gradient(to top, var(--navy), white);
  min-height:100vh;
  display:flex;
  justify-content:center;
  align-items:center;
  color:var(--ink);
}

.wrap{width:420px;max-width:92vw;}

.brandrow{
  text-align:center;
  color:#fff;
  margin-bottom:20px;
}

.img-box {
  width: 120px;
  height: 120px;
}

.card{
  background:#fff;
  border-radius:16px;
  padding:30px;
  box-shadow:0 20px 50px rgba(0,0,0,.25);
}

.card-title{font-weight:700;margin-bottom:5px;}
.card-sub{font-size:12px;color:var(--ink-soft);margin-bottom:20px;}

.field{margin-bottom:16px;}
label{font-size:12px;font-weight:700;color:var(--ink-soft);display:block;margin-bottom:6px;}

.inputwrap{
  position:relative;
}
.inputwrap input{
  width:100%;
  padding:12px;
  border:1px solid var(--line-strong);
  border-radius:8px;
}

.textarea{
  width:100%;
  padding:12px;
  border:1px solid var(--line-strong);
  border-radius:8px;
  font-family:inherit;
  resize:vertical;
}

.btn-primary{
  background:var(--navy);
  color:#fff;
  text-align:center;
  padding:12px;
  border-radius:8px;
  cursor:pointer;
  width: 100%;
  border: none;
  font-weight:700;
  margin-top: 20px;
}
.btn-primary:disabled{
  opacity:0.6;
  cursor:not-allowed;
}

.buttonContainer {
  text-align: center;
}

.field-error{
  font-size:11px;
  color:red;
  margin-top:6px;
  margin-left: 5px;
}

.resultRow{
  display:flex;
  justify-content:space-between;
  padding:12px 0;
  border-bottom:1px solid var(--line-strong);
}
.resultRow:last-of-type{
  border-bottom:none;
}
.resultLabel{
  font-size:13px;
  color:var(--ink-soft);
}
.resultValue{
  font-size:13px;
  font-weight:700;
}

.footlink{
  color: #fff;
  text-decoration: none;
  text-align: center;
  margin-top: 16px;
}
```

- [ ] **Step 6: 라우트 등록**

`ieum_frontend/src/routes/Router.jsx`의 import 블록(8~21번째 줄 부근)에 추가:

```javascript
import Apply from "../pages/Apply/Apply";
```

`const router = createBrowserRouter([` 안, `/login` 라우트 바로 다음(로그인 보호 트리 `element: (<AuthLoader>...)` 블록 **앞**)에 추가:

```javascript
  {
    path: "/apply",
    element: <Apply />,
  },
```

즉 최종 구조는 다음과 같아야 한다 (앞뒤 기존 라우트는 그대로 둠):

```javascript
const router = createBrowserRouter([
  {
    path: "/",
    element: <Login />,
  },
  {
    path: "/login",
    element: <Login />,
  },
  {
    path: "/apply",
    element: <Apply />,
  },
  {
    element: (
      <AuthLoader><MainLayout /></AuthLoader>
    ),
    loader: protectedLoader,
    ...
```

- [ ] **Step 7: 개발 서버로 직접 확인**

`ieum_frontend` 디렉터리에서:

```bash
npm run dev
```

브라우저로 `http://localhost:5173/apply` 접속:
1. 아무것도 입력하지 않고 "접수하기" 클릭 → 제목/내용 아래에 인라인 에러 메시지가 뜨는지 확인
2. 제목("테스트 민원"), 내용("테스트 내용입니다") 입력 후 "접수하기" 클릭 → 버튼이 "접수 중..."으로 바뀌었다가, 완료 화면(접수번호/배정 부서/처리예정일)으로 전환되는지 확인
3. 처리예정일이 오늘 날짜+14일인지 확인
4. "새 민원 접수하기" 클릭 → 입력 화면으로 돌아가는지 확인

- [ ] **Step 8: DB 반영 확인**

`ieum_backend` 디렉터리에서 Task 1의 Step 5와 동일한 스크립트를 다시 실행해, 방금 Step 7에서 만든 "테스트 민원"이 실제로 DB에 저장되고 `due_date`가 채워져 있는지 확인한다.

- [ ] **Step 9: 커밋**

```bash
git add src/api/petition.js src/hooks/mutations/usePetitionMutations.js src/pages/Apply/Apply.jsx src/pages/Apply/Apply.module.css src/routes/Router.jsx .env.sample
git commit -m "feat: 로그인 없이 접수 가능한 민원 접수 공개 페이지(/apply) 추가"
```

(`.env`는 git-ignore 대상이면 커밋 대상에서 자동 제외됨 — 커밋 전 `git status`로 `.env`가 스테이징되지 않았는지 반드시 확인.)

---

## 범위 밖 (설계 문서와 동일)

- 별도의 인증 없는 공개 엔드포인트 신설
- 이름·연락처 등 추가 입력 필드, 첨부파일 업로드
- 시민이 자기 민원 처리 현황을 조회하는 기능
