"""
Semantic Response Cache — backed by RedisVL, not hand-rolled cosine scanning.

Two backends, selected via SENTINELAI_LANGCACHE_MODE env var:

  "local" (default) -> redisvl.extensions.cache.llm.SemanticCache against your
      own self-hosted Redis Stack instance (docker-compose ships this, no
      external account needed). Vector index = RediSearch HNSW, so this
      scales far past the earlier scan-based prototype.

  "managed" -> redisvl.extensions.cache.llm.LangCacheSemanticCache, Redis's
      hosted LangCache service. Requires a LangCache account: cache_id +
      api_key (see .env.example). Use this if you don't want to operate
      Redis yourself.

Both expose the same three methods the rest of the platform calls:
    await semantic_cache.lookup(query_text)
    await semantic_cache.store(query_text, response, doc_ids=None)
    await semantic_cache.flush_type(reason)

Embeddings (local mode only) come from all-MiniLM-L6-v2 via HFTextVectorizer
— the same model used for document embeddings (services/embeddings/embedder.py),
so cache hit-rate isn't hurt by using two different embedding spaces.
"""
import os
import time
from typing import Optional

from redisvl.extensions.cache.llm import LangCacheSemanticCache, SemanticCache
from redisvl.utils.vectorize import HFTextVectorizer

from .config import CACHE_SPECS, REDIS_URL, SEMANTIC_SIMILARITY_THRESHOLD, CacheType
from .metrics import CACHE_HITS, CACHE_LATENCY, CACHE_MISSES, CACHE_SET_TOTAL

EMBEDDING_MODEL_NAME = os.getenv("SENTINELAI_EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
LANGCACHE_MODE = os.getenv("SENTINELAI_LANGCACHE_MODE", "local")  # "local" | "managed"


def _build_backend():
    ttl = CACHE_SPECS[CacheType.SEMANTIC_RESPONSE].ttl_seconds or None
    # redisvl's distance_threshold is a *distance* (0 = identical), while
    # SENTINELAI_SEM_SIM_THRESHOLD is expressed as a *similarity* (1 = identical).
    distance_threshold = round(1 - SEMANTIC_SIMILARITY_THRESHOLD, 4)

    if LANGCACHE_MODE == "managed":
        return LangCacheSemanticCache(
            name="sentinelai_semantic_cache",
            server_url=os.environ["SENTINELAI_LANGCACHE_URL"],
            cache_id=os.environ["SENTINELAI_LANGCACHE_CACHE_ID"],
            api_key=os.environ["SENTINELAI_LANGCACHE_API_KEY"],
            ttl=ttl,
        )

    vectorizer = HFTextVectorizer(model=EMBEDDING_MODEL_NAME)
    return SemanticCache(
        name="sentinelai_semantic_cache",
        redis_url=REDIS_URL,
        vectorizer=vectorizer,
        distance_threshold=distance_threshold,
        ttl=ttl,
    )


class SemanticResponseCache:
    """Thin async wrapper that adds SentinelAI's metrics + a uniform interface
    on top of RedisVL's SemanticCache / LangCacheSemanticCache."""

    def __init__(self):
        self.cache_type = CacheType.SEMANTIC_RESPONSE
        self._backend = _build_backend()

    async def lookup(self, query_text: str) -> Optional[dict]:
        start = time.perf_counter()
        hits = await self._backend.acheck(prompt=query_text)
        CACHE_LATENCY.labels(self.cache_type.value, "get").observe(time.perf_counter() - start)

        if not hits:
            CACHE_MISSES.labels(self.cache_type.value).inc()
            return None

        CACHE_HITS.labels(self.cache_type.value).inc()
        top = hits[0]
        return {
            "response": top.get("response"),
            "similarity": 1 - float(top.get("vector_distance", 0.0)),
            "metadata": top.get("metadata"),
        }

    async def store(self, query_text: str, response: str, doc_ids: Optional[list[str]] = None) -> None:
        start = time.perf_counter()
        await self._backend.astore(
            prompt=query_text,
            response=response,
            metadata={"doc_ids": doc_ids or []},
        )
        CACHE_SET_TOTAL.labels(self.cache_type.value).inc()
        CACHE_LATENCY.labels(self.cache_type.value, "set").observe(time.perf_counter() - start)

    async def invalidate_for_document(self, doc_id: str, reason: str = "document_updated") -> int:
        """RedisVL's semantic cache index isn't keyed by doc_id the way our
        other caches are (see base.py's docidx reverse index). A precise
        per-document delete would require declaring doc_id as a filterable
        field up front and querying+deleting matches; the pragmatic default
        here is a full clear, since semantic-cache entries are cheap to
        regenerate and this only fires on document updates, not every request."""
        await self._backend.aclear()
        return -1  # -1 = "full flush", not a precise count

    async def flush_type(self, reason: str = "manual") -> int:
        await self._backend.aclear()
        return -1
