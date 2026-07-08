from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    chroma_persist_dir: str = "./chroma_data"
    embedding_model: str = "jhgan/ko-sbert-nli"

    ollama_host: str = "http://localhost:11434"
    classifier_model_name: str = "handover-classifier"
    generation_model_name: str = "llama3.1:8b"

    ai_server_port: int = 8100

    class Config:
        env_file = ".env"


settings = Settings()
