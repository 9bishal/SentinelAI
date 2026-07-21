"""
Cross-Encoder Re-ranking — a CrossEncoder scores (query, chunk) pairs
directly (more accurate than cosine similarity, more expensive), so it only
runs on the fused RRF shortlist, not the full corpus. Results are cached by
(query, chunk_id set) since reranking is the most compute-heavy retrieval step.
"""
from functools import lru_cache

from sentence_transformers import CrossEncoder

from app.core.config import get_settings
from app.services.cache import cache_manager

settings = get_settings()


@lru_cache
def _model() -> CrossEncoder:
    return CrossEncoder(settings.cross_encoder_model)


class Reranker:
    async def rerank(self, query: str, candidates: list[dict]) -> list[dict]:
        if not candidates:
            return []

        chunk_ids = [c["id"] for c in candidates]
        cached_scores = await cache_manager.reranking.get_scores(query, chunk_ids)

        if cached_scores is not None:
            scores = cached_scores
        else:
            pairs = [(query, c["text"]) for c in candidates]
            scores = [float(s) for s in _model().predict(pairs)]
            doc_ids = list({c.get("metadata", {}).get("doc_id") for c in candidates if c.get("metadata", {}).get("doc_id")})
            await cache_manager.reranking.set_scores(query, chunk_ids, scores, doc_ids=doc_ids)

        for chunk, score in zip(candidates, scores):
            chunk["rerank_score"] = score

        ranked = sorted(candidates, key=lambda c: c["rerank_score"], reverse=True)
        return ranked[: settings.rerank_top_k]


reranker = Reranker()
