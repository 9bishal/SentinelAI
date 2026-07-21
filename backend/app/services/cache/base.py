"""
Base class every cache type extends. Handles:
- key construction
- get/set/delete against Redis
- Prometheus metrics
- doc-scoped invalidation bookkeeping (reverse index: doc_id -> set of cache keys)
"""
import hashlib
import json
import time
from typing import Any, Optional
 
# pyrefly: ignore [missing-import]
import redis.asyncio as redis

from .config import CACHE_SPECS, REDIS_URL, CacheType
from .metrics import CACHE_HITS, CACHE_INVALIDATIONS, CACHE_LATENCY, CACHE_MISSES, CACHE_SET_TOTAL

_redis_client: Optional[redis.Redis] = None


def get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(REDIS_URL, decode_responses=True)
    return _redis_client


def make_hash(*parts: Any) -> str:
    raw = "||".join(json.dumps(p, sort_keys=True, default=str) for p in parts)
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


class RedisCacheBase:
    cache_type: CacheType

    def __init__(self, cache_type: CacheType):
        self.cache_type = cache_type
        self.spec = CACHE_SPECS[cache_type]
        self.r = get_redis()

    def _key(self, key: str) -> str:
        return f"{self.spec.key_prefix}:{key}"

    def _doc_index_key(self, doc_id: str) -> str:
        return f"docidx:{doc_id}"

    async def get(self, key: str) -> Optional[dict]:
        start = time.perf_counter()
        raw = await self.r.get(self._key(key))
        CACHE_LATENCY.labels(self.cache_type.value, "get").observe(time.perf_counter() - start)
        if raw is None:
            CACHE_MISSES.labels(self.cache_type.value).inc()
            return None
        CACHE_HITS.labels(self.cache_type.value).inc()
        return json.loads(raw)

    async def set(self, key: str, value: dict, doc_ids: Optional[list[str]] = None, ttl_override: Optional[int] = None) -> None:
        start = time.perf_counter()
        full_key = self._key(key)
        ttl = ttl_override if ttl_override is not None else self.spec.ttl_seconds
        payload = json.dumps(value, default=str)
        if ttl > 0:
            await self.r.set(full_key, payload, ex=ttl)
        else:
            await self.r.set(full_key, payload)  # no expiry, manual invalidation only

        # maintain reverse index for doc-scoped invalidation
        if self.spec.doc_scoped and doc_ids:
            for doc_id in doc_ids:
                await self.r.sadd(self._doc_index_key(doc_id), full_key)

        CACHE_SET_TOTAL.labels(self.cache_type.value).inc()
        CACHE_LATENCY.labels(self.cache_type.value, "set").observe(time.perf_counter() - start)

    async def delete(self, key: str) -> None:
        await self.r.delete(self._key(key))

    async def invalidate_for_document(self, doc_id: str, reason: str = "document_updated") -> int:
        """Delete every cache entry tied to a given document (any doc-scoped cache)."""
        idx_key = self._doc_index_key(doc_id)
        members = await self.r.smembers(idx_key)
        if not members:
            return 0
        await self.r.delete(*members)
        await self.r.delete(idx_key)
        CACHE_INVALIDATIONS.labels(self.cache_type.value, reason).inc(len(members))
        return len(members)

    async def flush_type(self, reason: str = "manual") -> int:
        """Nuke every key belonging to this cache type. Used on policy/config changes."""
        pattern = f"{self.spec.key_prefix}:*"
        keys = [k async for k in self.r.scan_iter(match=pattern, count=500)]
        if keys:
            await self.r.delete(*keys)
        CACHE_INVALIDATIONS.labels(self.cache_type.value, reason).inc(len(keys))
        return len(keys)
