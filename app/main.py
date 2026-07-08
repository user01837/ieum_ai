from fastapi import FastAPI

from app.api.routes import router

app = FastAPI(title="공공이음 AI 서버", description="RAG + 분류기 + 답변생성")

app.include_router(router)


@app.get("/")
async def health_check():
    return {"status": "ok", "service": "ieum_ai"}
