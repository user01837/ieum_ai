# /apply 페이지 국민신문고 스타일 재구성 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 기존 `/apply` 페이지(민원 접수 공개 폼)의 UI를 로그인 카드 스타일에서 국민신문고 실제 접수 페이지에 가까운 관공서 문서 스타일(흰 배경, 무채색, 안내문구, 글자수 카운터)로 교체한다.

**Architecture:** `ieum_frontend`의 `src/pages/Apply/Apply.jsx`와 `Apply.module.css`만 수정한다. API 호출(`submitExternalPetition`), 검증 로직, 라우팅은 전혀 건드리지 않는다 — 순수 UI/마크업 교체.

**Tech Stack:** React + Vite + CSS Modules (기존과 동일).

## Global Constraints

- 필드는 제목·내용 두 개만 유지 — 첨부파일 UI 추가 금지(범위 밖).
- 로고·브랜딩 헤더("공무원 업무지원 플랫폼" 등) 제거, 페이지가 바로 안내문구·폼으로 시작.
- 안내 문구(상단 6줄, 유의사항 4줄)는 설계 문서에 명시된 텍스트를 정확히 그대로 사용한다(로그인 유지시간 문구는 제외).
- 강조 색상은 무채색(회색/검정) 계열 — 기존 `var(--navy)` 파란 계열 대신 사용.
- API 호출·검증·라우팅 로직은 변경하지 않는다.
- 이 프로젝트는 자동화 테스트가 없는 관례 — `npm run dev`로 브라우저 수동 확인.

참고 문서: `docs/superpowers/specs/2026-07-28-petition-apply-govstyle-redesign-design.md`

---

### Task 1: `/apply` 페이지를 국민신문고 스타일로 재구성

**Files:**
- Modify: `ieum_frontend/src/pages/Apply/Apply.jsx` (전체 교체)
- Modify: `ieum_frontend/src/pages/Apply/Apply.module.css` (전체 교체)

**Interfaces:**
- Consumes: `submitExternalPetition`을 감싼 `useSubmitExternalPetitionMutation` (기존, 변경 없음), `getDepartments()` (기존, 변경 없음)
- Produces: 없음 (이 페이지를 소비하는 다른 컴포넌트 없음 — 라우트 엔드포인트)

- [ ] **Step 1: Apply.jsx를 아래 코드로 전체 교체**

`ieum_frontend/src/pages/Apply/Apply.jsx`의 전체 내용을 다음으로 바꾼다:

```jsx
import { useState } from "react";
import styles from "./Apply.module.css";
import { useQuery } from "@tanstack/react-query";
import { getDepartments } from "../../api/dept";
import { useSubmitExternalPetitionMutation } from "../../hooks/mutations/usePetitionMutations";

const TITLE_MAX_LENGTH = 200;
const CONTENT_MAX_LENGTH = 40000;

const INTRO_NOTICES = [
  "제목과 내용은 접수 후 수정, 삭제가 불가능하므로 다시 확인하시고 신청해 주시기 바랍니다.",
  "규제 관련 민원의 경우 규제신문고로 이관될 수 있습니다.",
  "신고성 민원의 경우 청렴포털시스템으로 이관될 수 있습니다.",
  "허위신고 등은 명예훼손, 무고죄 등으로 처벌될 수 있습니다.",
  "민원 내용에 따라 여러 부처에서 처리될 수 있으니, 민감한 내용이 포함되어 있을 경우 기관별로 해당내용을 제출해주시기 바랍니다.",
  "공무원에 대한 폭언, 욕설 등은 관련 법령(형법, 경범죄처벌법)에 따라 법적조치를 받을 수 있습니다.",
];

const CAUTION_NOTICES = [
  "민원신청을 유도한 후 금융 정보(계좌, 카드, 비밀번호 등)를 요구하는 전화사기(보이스피싱)에 주의하시기 바랍니다.",
  "고소장 등 법정서식이 필요한 신청은 해당 기관에 사전 문의하시기 바랍니다.",
  "현금영수증 미발급·발급거부, 신용카드 결제거부, 탈세제보신고는 국세청 홈(손)택스로 접속> 상담/제보(클릭)를 이용하여주시기 바랍니다.",
  "민원 내용을 자세히 작성해주시면 원활한 민원 처리에 도움이 됩니다.",
];

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
        dueDate: data.dueDate,
      });
    },
    onError: (error) => {
      console.error('민원 접수 실패:', error);
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
        {result ? (
          <div className={styles.panel}>
            <div className={styles.panelTitle}>민원이 정상적으로 접수되었습니다</div>
            <div className={styles.panelSub}>아래 내용을 확인해 주세요.</div>

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

            <div className={styles.buttonRow}>
              <button type="button" className={styles.submitButton} onClick={handleReset}>
                새 민원 접수하기
              </button>
            </div>
          </div>
        ) : (
          <form className={styles.panel} onSubmit={handleSubmit}>
            <ul className={styles.introNotices}>
              {INTRO_NOTICES.map((text) => (
                <li key={text}>{text}</li>
              ))}
            </ul>

            <div className={styles.sectionHeader}>
              <span className={styles.sectionTitle}>민원내용</span>
              <span className={styles.requiredHint}>* 표는 필수 입력사항입니다.</span>
            </div>

            <ul className={styles.cautionNotices}>
              {CAUTION_NOTICES.map((text) => (
                <li key={text}>※ {text}</li>
              ))}
            </ul>

            <div className={styles.field}>
              <div className={styles.fieldLabelRow}>
                <label htmlFor="apply-title">민원 제목</label>
                <span className={styles.requiredBadge}>필수입력</span>
              </div>
              <input
                id="apply-title"
                className={styles.textInput}
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                maxLength={TITLE_MAX_LENGTH}
                placeholder="민원 제목을 입력하세요"
              />
              <div className={styles.charCount}>({title.length}/{TITLE_MAX_LENGTH})</div>
              {titleError && (
                <div className={styles.fieldError}>* 제목을 입력해 주세요.</div>
              )}
            </div>

            <div className={styles.field}>
              <div className={styles.fieldLabelRow}>
                <label htmlFor="apply-content">민원 내용</label>
                <span className={styles.requiredBadge}>필수입력</span>
              </div>
              <textarea
                id="apply-content"
                className={styles.textArea}
                value={content}
                onChange={(e) => setContent(e.target.value)}
                maxLength={CONTENT_MAX_LENGTH}
                placeholder="민원 내용을 입력하세요"
                rows={10}
              />
              <div className={styles.charCount}>({content.length}/{CONTENT_MAX_LENGTH})</div>
              {contentError && (
                <div className={styles.fieldError}>* 내용을 입력해 주세요.</div>
              )}
            </div>

            {submitError && (
              <div className={styles.fieldError}>{submitError}</div>
            )}

            <div className={styles.buttonRow}>
              <button type="submit" className={styles.submitButton} disabled={isPending}>
                {isPending ? "접수 중..." : "접수하기"}
              </button>
            </div>
          </form>
        )}

        <div className={styles.footNote}>
          문의사항은 관할 부서로 연락해 주세요.
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Apply.module.css를 아래 코드로 전체 교체**

`ieum_frontend/src/pages/Apply/Apply.module.css`의 전체 내용을 다음으로 바꾼다:

```css
.applyPage {
  margin: 0;
  font-family: 'Noto Sans KR', sans-serif;
  background: #fff;
  min-height: 100vh;
  display: flex;
  justify-content: center;
  padding: 40px 16px;
  color: var(--ink);
}

.wrap {
  width: 720px;
  max-width: 100%;
}

.panel {
  background: #fff;
  border: 1px solid var(--line-strong);
  border-radius: 4px;
  padding: 32px;
}

.panelTitle {
  font-weight: 700;
  font-size: 18px;
  margin-bottom: 6px;
}

.panelSub {
  font-size: 13px;
  color: var(--ink-soft);
  margin-bottom: 20px;
}

.introNotices {
  list-style: none;
  padding: 0;
  margin: 0 0 24px;
  font-size: 12.5px;
  color: var(--ink-soft);
  line-height: 1.8;
}

.sectionHeader {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  border-bottom: 2px solid var(--ink);
  padding-bottom: 10px;
  margin-bottom: 14px;
}

.sectionTitle {
  font-size: 16px;
  font-weight: 700;
}

.requiredHint {
  font-size: 12px;
  color: var(--ink-tertiary);
}

.cautionNotices {
  list-style: none;
  padding: 12px 14px;
  margin: 0 0 24px;
  background: var(--bg);
  border: 1px solid var(--line-strong);
  border-radius: 4px;
  font-size: 12px;
  color: var(--ink-soft);
  line-height: 1.9;
}

.field {
  margin-bottom: 24px;
}

.fieldLabelRow {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.fieldLabelRow label {
  font-size: 14px;
  font-weight: 700;
}

.requiredBadge {
  font-size: 11px;
  color: #c0392b;
  border: 1px solid #c0392b;
  border-radius: 3px;
  padding: 1px 6px;
}

.textInput {
  width: 100%;
  padding: 10px 12px;
  border: 1px solid var(--line-strong);
  border-radius: 4px;
  font-family: inherit;
  box-sizing: border-box;
}

.textArea {
  width: 100%;
  padding: 10px 12px;
  border: 1px solid var(--line-strong);
  border-radius: 4px;
  font-family: inherit;
  resize: vertical;
  box-sizing: border-box;
}

.charCount {
  text-align: right;
  font-size: 11.5px;
  color: var(--ink-tertiary);
  margin-top: 4px;
}

.fieldError {
  font-size: 11px;
  color: red;
  margin-top: 6px;
}

.buttonRow {
  text-align: center;
  margin-top: 28px;
}

.submitButton {
  background: #333;
  color: #fff;
  padding: 12px 40px;
  border-radius: 4px;
  border: none;
  font-weight: 700;
  cursor: pointer;
}

.submitButton:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.resultRow {
  display: flex;
  justify-content: space-between;
  padding: 12px 0;
  border-bottom: 1px solid var(--line-strong);
}

.resultRow:last-of-type {
  border-bottom: none;
}

.resultLabel {
  font-size: 13px;
  color: var(--ink-soft);
}

.resultValue {
  font-size: 13px;
  font-weight: 700;
}

.footNote {
  text-align: center;
  font-size: 12px;
  color: var(--ink-tertiary);
  margin-top: 16px;
}
```

- [ ] **Step 3: 개발 서버로 직접 확인**

`ieum_frontend` 디렉터리에서:

```bash
npm run dev
```

브라우저로 `/apply` 접속해서 확인:
1. 로고·브랜딩 없이 안내문구부터 바로 시작하는지
2. 상단 6줄 안내 문구, "민원내용" 섹션 헤더, `※` 유의사항 4줄이 정확한 텍스트로 표시되는지
3. 제목/내용 필드에 `필수입력` 배지가 붙어있고, 입력할 때마다 글자수 카운터(`(n/200)`, `(n/40000)`)가 실시간으로 갱신되는지
4. 200자/40000자를 넘겨 입력이 안 되는지(브라우저가 `maxLength`로 막아주는지)
5. 아무것도 입력 안 하고 "접수하기" 클릭 시 기존과 동일하게 인라인 에러가 뜨는지
6. 정상 제출 시 완료 화면(접수번호/배정 부서/처리예정일)이 같은 무채색 톤으로 표시되는지
7. "새 민원 접수하기" 클릭 시 입력 화면으로 정상 복귀하는지
8. 전체적으로 네이비 그라디언트나 카드 그림자 없이, 흰 배경 + 회색 테두리 박스 느낌인지 육안 확인

- [ ] **Step 4: 커밋**

```bash
git add src/pages/Apply/Apply.jsx src/pages/Apply/Apply.module.css
git commit -m "feat: /apply 페이지를 국민신문고 스타일(흰 배경, 안내문구, 글자수 카운터)로 재구성"
```

---

## 범위 밖 (설계 문서와 동일)

- 첨부파일 업로드
- 백엔드/API 변경
- "기존 민원 첨부", "상세내용 펼치기" 등 국민신문고의 다른 부가 기능
