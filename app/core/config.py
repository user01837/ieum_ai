from pydantic_settings import BaseSettings
from pathlib import Path

# 이 파일(config.py) 기준으로 프로젝트 루트를 계산 (app/core/config.py → 두 단계 위 = ieum_ai/)
BASE_DIR = Path(__file__).resolve().parent.parent.parent

class Settings(BaseSettings):
    chroma_persist_dir: str = str(BASE_DIR / "chroma_data")
    embedding_model: str = "jhgan/ko-sbert-nli"
    ollama_host: str = "http://localhost:11434"
    classifier_model_name: str = "handover-classifier"
    generation_model_name: str = "llama3.1:8b"
    ai_server_port: int = 8100
    class Config:
        env_file = ".env"

settings = Settings()