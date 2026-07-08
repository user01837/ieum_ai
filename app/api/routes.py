from fastapi import APIRouter
from pydantic import BaseModel

from app.classifier.ollama_client import classify_text, generate_draft_answer
from app.vectorstore.chroma_client import search_similar_complaints, add_complaint

router = APIRouter(prefix="/api", tags=["ai"])


class ClassifyRequest(BaseModel):
    text: str


class ClassifyResponse(BaseModel):
    domain_code: str


class SimilarCasesRequest(BaseModel):
    query_text: str
    department_code: str
    domain_code: str | None = None
    top_k: int = 3


class DraftRequest(BaseModel):
    complaint_text: str
    department_code: str
    domain_code: str | None = None


class IndexComplaintRequest(BaseModel):
    complaint_id: int
    title: str
    content: str
    department_code: str
    domain_code: str | None = None
    status_code: str | None = None


@router.post("/classify", response_model=ClassifyResponse)
async def classify(req: ClassifyRequest):
    """민원/사업 텍스트를 8개 도메인 중 하나로 분류 (Qwen2.5-3B QLoRA 분류기)."""
    domain_code = await classify_text(req.text)
    return ClassifyResponse(domain_code=domain_code)


@router.post("/similar-cases")
async def similar_cases(req: SimilarCasesRequest):
    """부서 범위 내에서 유사 민원 검색 (ChromaDB 벡터 검색)."""
    hits = search_similar_complaints(
        query_text=req.query_text,
        department_code=req.department_code,
        domain_code=req.domain_code,
        top_k=req.top_k,
    )
    return {"results": hits}


@router.post("/draft")
async def draft_answer(req: DraftRequest):
    """유사사례를 근거로 답변 초안 생성 (Llama3.1)."""
    similar = search_similar_complaints(
        query_text=req.complaint_text,
        department_code=req.department_code,
        domain_code=req.domain_code,
        top_k=3,
    )
    draft = await generate_draft_answer(req.complaint_text, similar)
    return {"draft": draft, "referenced_cases": similar}


@router.post("/index-complaint")
async def index_complaint(req: IndexComplaintRequest):
    """
    완료된 민원 1건을 ChromaDB에 색인(등록).
    FastAPI backend에서 민원이 '완료' 처리될 때 이 엔드포인트를 호출하는 걸 전제로 함.
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
