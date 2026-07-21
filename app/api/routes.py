from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.classifier.ollama_client import generate_draft_answer
from app.classifier.draft_guardrail import apply_guardrail
from app.classifier.legal_chat import search_legal_articles, generate_legal_answer
from app.vectorstore.chroma_client import search_similar_complaints, add_complaint, search_matching_task_category
from app.classifier.ollama_client import generate_task_draft
from app.classifier.draft_guardrail import apply_task_guardrail
from app.vectorstore.task_chroma_client import search_similar_tasks, add_task

router = APIRouter(prefix="/api", tags=["ai"])


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


class SimilarCasesRequest(BaseModel):
    query_text: str
    department_code: str
    top_k: int = 2
    exclude_ids: list[int] = []
    min_similarity: float = 65.0


class DraftRequest(BaseModel):
    complaint_text: str
    department_code: str


class IndexComplaintRequest(BaseModel):
    complaint_id: int
    title: str
    content: str
    department_code: str
    domain_code: str | None = None
    status_code: str | None = None


class LegalChatRequest(BaseModel):
    question: str


class ClassifyTaskRequest(BaseModel):
    complaint_text: str
    department_code: str


@router.post("/similar-cases")
async def similar_cases(req: SimilarCasesRequest):
    """
    부서 범위 내에서 유사 민원 검색 (ChromaDB 벡터 검색 + 리랭커).

    최초 호출: exclude_ids/min_similarity 없이 호출 -> 유사도 상위 top_k(기본 2)건 반환
    "유사사례 추가 검색" 버튼 클릭 시: exclude_ids에 이미 보여준 complaint_id 목록,
      min_similarity=65.0 전달 -> 중복 제외 + 65% 이상인 것만 반환.
      결과가 빈 배열이면 더 이상 없다는 뜻 -> 프론트에서 안내 문구 표시 + 버튼 비활성화 처리.
    """
    hits = search_similar_complaints(
        query_text=req.query_text,
        department_code=req.department_code,
        top_k=req.top_k,
        exclude_ids=req.exclude_ids,
        min_similarity=req.min_similarity,
    )
    return {"results": hits}


@router.post("/draft")
async def draft_answer(req: DraftRequest):
    """
    유사사례를 근거로 답변 초안 생성 (Llama3.1).

    가드레일 2단계 적용:
    1) 유사도 가드레일: top1 유사도가 65% 미만이면 draft를 안전한 안내 문구로 자동 교체
       (guardrail_triggered=True로 표시)
    2) 사실 검증 가드레일: 유사도는 통과했지만 draft 안의 법조문/금액/기간 등 구체적 사실이
       참고사례 원문에 없으면 needs_review=True로 표시 (draft 자체는 그대로 반환, 프론트에서
       "⚠ AI 생성 정보 재확인 필요" 배지 등으로 안내하는 용도)
    """
    similar = search_similar_complaints(
        query_text=req.complaint_text,
        department_code=req.department_code,
        top_k=3,
    )
    draft = await generate_draft_answer(req.complaint_text, similar)

    guarded = apply_guardrail(draft, similar, similarity_threshold=65.0)

    return {
        "draft": guarded["draft"],
        "referenced_cases": similar,
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


@router.post("/legal-chat")
async def legal_chat(req: LegalChatRequest):
    """
    법률챗봇 - 질문과 관련된 법령 조문을 검색해 근거로 답변 생성.
    우측하단 챗봇 아이콘 전용 엔드포인트 (부서/프로젝트 무관, 전 직원 접근).

    /api/draft와 달리 department_code를 받지 않음 - 법률 정보는
    부서 구분 없이 전체 법령 코퍼스(legal_documents 컬렉션)에서 검색하기 때문.
    답변 속도를 위해 top_k=2, num_predict=150으로 제한 (legal_chat.py 참고).
    """
    articles = search_legal_articles(req.question, top_k=2)
    answer = await generate_legal_answer(req.question, articles)

    return {
        "answer": answer,
        "referenced_articles": articles,
    }


@router.post("/index-complaint")
async def index_complaint(req: IndexComplaintRequest):
    """
    완료된 민원 1건을 ChromaDB에 색인(등록).
    FastAPI backend에서 민원이 '완료' 처리될 때 이 엔드포인트를 호출하는 걸 전제로 함.
    domain_code는 여기서만 유지 - 색인 시 메타데이터(통계/분석용)로 저장, 검색 필터링에는 미사용.
    """
    add_complaint(
        complaint_id=req.complaint_id,
        title=req.title,
        content=req.content,
        department_code=req.department_code,
        domain_code=req.domain_code,
        status_code=req.status_code,
    )
    return {"status": "indexed", "complaint_id": req.complaint_id}


@router.post("/classify-task")
async def classify_task(req: ClassifyTaskRequest):
    """민원 텍스트를 부서 내 세부 업무과(TASK)로 분류.
    담당자 배정은 여기서 하지 않음 - task_id만 반환, 백엔드가 TASK_ASSIGNEE 조회해서 배정 처리.
    여기서 반환하는 task_id는 AI 서버 내부 벡터 매칭용 임시 ID이며, 실제 DB TASK.task_id와의
    매핑 방식은 백엔드와 별도 협의 필요 (data/seed_task_categories.py 주석 참고)."""
    matches = search_matching_task_category(req.complaint_text, req.department_code, top_k=1)
    if not matches:
        return {"task_id": None, "task_name": None, "similarity": 0.0}
    top = matches[0]
    return {"task_id": top["task_id"], "task_name": top["name"], "similarity": top["similarity"]}


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
