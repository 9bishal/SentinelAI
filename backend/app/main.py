"""
SentinelAI — Enterprise AI Response Governance Platform.
FastAPI application entrypoint. Wires up routers, /metrics for Prometheus,
CORS, and structured logging.
"""
import logging

# pyrefly: ignore [missing-import]
from fastapi import FastAPI

# pyrefly: ignore [missing-import]
from fastapi.middleware.cors import CORSMiddleware

# pyrefly: ignore [missing-import]
from prometheus_client import make_asgi_app

from app.api.v1.cache import router as cache_router
from app.api.v1.chat import router as chat_router
from app.api.v1.documents import router as documents_router
from app.api.v1.health import router as health_router
from app.core.config import get_settings

settings = get_settings()

logging.basicConfig(
    level=logging.INFO if not settings.debug else logging.DEBUG,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

app = FastAPI(
    title=settings.app_name,
    description="Enterprise AI Response Governance Platform — guardrails, retrieval, "
                "evaluation, and observability sitting between users and any LLM.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten for production deployments
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router, prefix="/api/v1/health", tags=["health"])
app.include_router(chat_router, prefix="/api/v1/chat", tags=["chat"])
app.include_router(documents_router, prefix="/api/v1/documents", tags=["documents"])
app.include_router(cache_router, prefix="/api/v1/cache", tags=["cache"])

app.mount("/metrics", make_asgi_app())  # scraped by docker/prometheus.yml


@app.get("/")
async def root():
    return {
        "service": settings.app_name,
        "status": "running",
        "docs": "/docs",
        "metrics": "/metrics",
    }
