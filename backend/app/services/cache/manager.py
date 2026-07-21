"""
CacheManager — single object the rest of the app imports. Wires up all 13
cache types and exposes the three invalidation events the platform needs:

  on_document_updated(doc_id)      -> called by ingestion pipeline
  on_embeddings_regenerated(model) -> called after embedding model migration
  on_policy_changed(scope)         -> called by admin/policy API

Wire these calls into ingestion/, workers/, and the policy admin router.
"""
from .config import CacheType
from .domain_caches import (
    ConfigurationCache,
    DocumentFingerprintCache,
    EvaluationCache,
    GuardrailDecisionCache,
    MetadataCache,
    ModelRoutingCache,
    OCRCache,
    PromptCache,
    RerankingCache,
    ResponseRepairCache,
    RetrievalCache,
)
from .embedding_cache import EmbeddingCache
from .semantic_cache import SemanticResponseCache


class CacheManager:
    def __init__(self):
        self.semantic_response = SemanticResponseCache()
        self.prompt = PromptCache()
        self.embedding = EmbeddingCache()
        self.retrieval = RetrievalCache()
        self.reranking = RerankingCache()
        self.doc_fingerprint = DocumentFingerprintCache()
        self.ocr = OCRCache()
        self.evaluation = EvaluationCache()
        self.metadata = MetadataCache()
        self.response_repair = ResponseRepairCache()
        self.guardrail_decision = GuardrailDecisionCache()
        self.model_routing = ModelRoutingCache()
        self.configuration = ConfigurationCache()

        # doc-scoped caches that need to be swept when a document changes
        self._doc_scoped = [
            self.semantic_response,
            self.retrieval,
            self.reranking,
            self.metadata,
        ]

    async def on_document_updated(self, doc_id: str) -> dict[str, int]:
        """Call this after re-ingestion/re-chunking/version bump of a document.
        Sweeps every cache entry derived from that document."""
        results = {}
        for cache in self._doc_scoped:
            results[cache.cache_type.value] = await cache.invalidate_for_document(doc_id, reason="document_updated")
        return results

    async def on_embeddings_regenerated(self, model_name: str) -> dict[str, int]:
        """Call this after an embedding model migration. Embedding cache
        entries for the old model are stale; retrieval/rerank/semantic
        results built on old vectors are also stale."""
        results = {"embedding": await self.embedding.invalidate_model(model_name)}
        for cache in (self.retrieval, self.reranking, self.semantic_response):
            results[cache.cache_type.value] = await cache.flush_type(reason="embeddings_regenerated")
        return results

    async def on_policy_changed(self, scope: str = "all") -> dict[str, int]:
        """Call this from the policy/admin API whenever guardrail rules or
        company policy config change. Stale guardrail verdicts and config
        reads must not linger."""
        results = {}
        for cache in (self.guardrail_decision, self.configuration):
            results[cache.cache_type.value] = await cache.flush_type(reason=f"policy_changed:{scope}")
        return results

    async def stats(self) -> dict:
        """Cheap snapshot for a /cache/stats admin endpoint. Real dashboards
        should read Prometheus (sentinelai_cache_hits_total etc.) instead."""
        r = self.configuration.r  # any RedisCacheBase instance shares the same client
        info = await r.info("memory")
        return {
            "used_memory_human": info.get("used_memory_human"),
            "cache_types": [c.value for c in CacheType],
        }


cache_manager = CacheManager()
