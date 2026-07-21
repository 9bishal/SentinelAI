"""
Central settings object. Everything configurable lives here, loaded from env
vars / .env. Cache module (services/cache) reads its own env vars directly
so it stays self-contained and portable into other projects.
"""
from functools import lru_cache

# pyrefly: ignore [missing-import]
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="../.env", env_prefix="SENTINELAI_", extra="ignore")

    # -- Core --
    app_name: str = "SentinelAI"
    environment: str = "development"
    debug: bool = True

    # -- Postgres --
    database_url: str = "postgresql+asyncpg://sentinelai:sentinelai@localhost:5432/sentinelai"

    # -- Redis / Cache --
    redis_url: str = "redis://localhost:6379/0"

    # -- ChromaDB --
    chroma_host: str = "localhost"
    chroma_port: int = 8001
    chroma_collection: str = "sentinelai_documents"

    # -- RabbitMQ / Celery --
    rabbitmq_url: str = "amqp://guest:guest@localhost:5672//"
    celery_result_backend: str = "redis://localhost:6379/1"

    # -- Embeddings --
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_dim: int = 384

    # -- Groq / LLM --
    groq_api_key: str = ""
    groq_model_fast: str = "llama-3.1-8b-instant"
    groq_model_strong: str = "llama-3.3-70b-versatile"
    llm_timeout_seconds: int = 30
    llm_max_retries: int = 3

    # -- Retrieval --
    retrieval_top_k: int = 20
    rerank_top_k: int = 5
    cross_encoder_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    # -- Guardrails --
    hallucination_flag_threshold: float = 0.5  # fraction of unsupported sentences that trips a flag
    min_citation_coverage: float = 0.6

    # -- Observability --
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"


@lru_cache
def get_settings() -> Settings:
    return Settings()
