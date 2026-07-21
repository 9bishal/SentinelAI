"""
Hybrid Retrieval Engine — combines BM25 (lexical) + dense vector search,
fuses scores with Reciprocal Rank Fusion (RRF), then hands the fused
candidate list to the reranker. Also handles:
  - duplicate chunk removal (by chunk id / near-identical text hash)
  - document version prioritization (prefers highest doc_version on conflict)
  - retrieval-cache check/store (see services/cache/domain_caches.RetrievalCache)
"""
from app.core.config import get_settings
from app.services.cache import cache_manager
from app.services.embeddings.embedder import embedder

from .bm25 import bm25_retriever
from .chroma_store import chroma_store
from .reranker import reranker

settings = get_settings()

RRF_K = 60  # standard RRF smoothing constant


def _reciprocal_rank_fusion(dense_ranked: list[dict], bm25_ranked: list[dict]) -> list[dict]:
    scores: dict[str, float] = {}
    chunks_by_id: dict[str, dict] = {}

    for rank, chunk in enumerate(dense_ranked):
        scores[chunk["id"]] = scores.get(chunk["id"], 0) + 1 / (RRF_K + rank + 1)
        chunks_by_id[chunk["id"]] = chunk

    for rank, chunk in enumerate(bm25_ranked):
        scores[chunk["id"]] = scores.get(chunk["id"], 0) + 1 / (RRF_K + rank + 1)
        chunks_by_id.setdefault(chunk["id"], chunk)

    fused = sorted(chunks_by_id.values(), key=lambda c: scores[c["id"]], reverse=True)
    for chunk in fused:
        chunk["fusion_score"] = scores[chunk["id"]]
    return fused


def _dedupe_and_prioritize_versions(chunks: list[dict]) -> list[dict]:
    """Drop duplicate chunks and, when the same logical chunk exists across
    multiple document versions, keep only the highest doc_version."""
    best_by_content_key: dict[str, dict] = {}
    for chunk in chunks:
        meta = chunk.get("metadata", {}) or {}
        content_key = meta.get("content_hash") or chunk["id"]
        existing = best_by_content_key.get(content_key)
        if existing is None or meta.get("doc_version", 0) > (existing.get("metadata", {}) or {}).get("doc_version", 0):
            best_by_content_key[content_key] = chunk
    return list(best_by_content_key.values())


class HybridRetriever:
    async def retrieve(self, query: str, top_k: int | None = None, where: dict | None = None) -> list[dict]:
        top_k = top_k or settings.retrieval_top_k

        cached = await cache_manager.retrieval.get_results(query, where or {})
        if cached is not None:
            return cached

        query_embedding = await embedder.embed(query)
        dense_results = chroma_store.dense_search(query_embedding, top_k=top_k, where=where)
        bm25_results = bm25_retriever.search(query, top_k=top_k, where=where)

        fused = _reciprocal_rank_fusion(dense_results, bm25_results)
        deduped = _dedupe_and_prioritize_versions(fused)

        reranked = await reranker.rerank(query, deduped[: top_k * 2])  # widen pre-rerank pool

        doc_ids = list({c.get("metadata", {}).get("doc_id") for c in reranked if c.get("metadata", {}).get("doc_id")})
        await cache_manager.retrieval.set_results(query, where or {}, reranked, doc_ids=doc_ids)
        return reranked


hybrid_retriever = HybridRetriever()
