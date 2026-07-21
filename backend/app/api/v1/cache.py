"""
Admin-facing router. Mount at /api/v1/cache in your main FastAPI app:

    from app.api.cache_router import router as cache_router
    app.include_router(cache_router, prefix="/api/v1/cache", tags=["cache"])
"""
# pyrefly: ignore [missing-import]
from fastapi import APIRouter
# pyrefly: ignore [missing-import]
from pydantic import BaseModel

from app.services.cache import cache_manager

router = APIRouter()


class DocumentInvalidateRequest(BaseModel):
    doc_id: str


class EmbeddingInvalidateRequest(BaseModel):
    model_name: str


class PolicyInvalidateRequest(BaseModel):
    scope: str = "all"


@router.get("/stats")
async def get_cache_stats():
    return await cache_manager.stats()


@router.post("/invalidate/document")
async def invalidate_document(body: DocumentInvalidateRequest):
    return await cache_manager.on_document_updated(body.doc_id)


@router.post("/invalidate/embeddings")
async def invalidate_embeddings(body: EmbeddingInvalidateRequest):
    return await cache_manager.on_embeddings_regenerated(body.model_name)


@router.post("/invalidate/policy")
async def invalidate_policy(body: PolicyInvalidateRequest):
    return await cache_manager.on_policy_changed(body.scope)
