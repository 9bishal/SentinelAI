"""
Embedding cache — avoids re-computing embeddings for text seen before.
Keyed by hash(text + model_name). Long TTL since embeddings for the same
text+model never change (only invalidated on model migration).
"""
from typing import Optional

from .base import RedisCacheBase, make_hash
from .config import CacheType


class EmbeddingCache(RedisCacheBase):
    def __init__(self):
        super().__init__(CacheType.EMBEDDING)

    def key_for(self, text: str, model_name: str) -> str:
        return make_hash(text, model_name)

    async def get_embedding(self, text: str, model_name: str) -> Optional[list[float]]:
        cached = await self.get(self.key_for(text, model_name))
        return cached["vector"] if cached else None

    async def set_embedding(self, text: str, model_name: str, vector: list[float]) -> None:
        await self.set(self.key_for(text, model_name), {"vector": vector, "model": model_name})

    async def invalidate_model(self, model_name: str) -> int:
        """Call this when migrating to a new embedding model — old vectors are stale."""
        # embeddings aren't doc-scoped, so we scan+filter by model tag stored in value
        pattern = f"{self.spec.key_prefix}:*"
        deleted = 0
        async for k in self.r.scan_iter(match=pattern, count=500):
            raw = await self.r.get(k)
            if raw and f'"model": "{model_name}"' in raw:
                await self.r.delete(k)
                deleted += 1
        return deleted
