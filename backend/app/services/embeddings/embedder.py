"""
Single embedding model used across the entire platform:
sentence-transformers/all-MiniLM-L6-v2 (384-dim, fast, good enough for
retrieval-quality dense vectors without needing a GPU).

Using ONE model everywhere (documents, queries, and the semantic cache's
HFTextVectorizer) matters: if the cache embedded queries with a different
model than the retriever embeds documents with, similarity scores would be
meaningless across the two spaces.

Model loading is a singleton — sentence-transformers loads ~90MB of weights,
you do not want to do that per-request.
"""
from functools import lru_cache
from typing import Optional

from sentence_transformers import SentenceTransformer

from app.core.config import get_settings
from app.services.cache import cache_manager

MODEL_NAME = get_settings().embedding_model.removeprefix("sentence-transformers/")


@lru_cache
def _model() -> SentenceTransformer:
    return SentenceTransformer(MODEL_NAME)


class Embedder:
    """Cache-aware embedding service. Always check the embedding cache before
    running the model — repeated chunks/queries across documents are common
    (headers, boilerplate, FAQ-style repeated questions)."""

    def __init__(self, model_name: Optional[str] = None):
        self.model_name = model_name or MODEL_NAME

    async def embed(self, text: str) -> list[float]:
        cached = await cache_manager.embedding.get_embedding(text, self.model_name)
        if cached is not None:
            return cached
        vector = _model().encode(text, normalize_embeddings=True).tolist()
        await cache_manager.embedding.set_embedding(text, self.model_name, vector)
        return vector

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Batches through the model for anything not already cached — used
        by the ingestion pipeline over hundreds of chunks at once."""
        results: list[Optional[list[float]]] = [None] * len(texts)
        to_compute_idx: list[int] = []
        to_compute_text: list[str] = []

        for i, text in enumerate(texts):
            cached = await cache_manager.embedding.get_embedding(text, self.model_name)
            if cached is not None:
                results[i] = cached
            else:
                to_compute_idx.append(i)
                to_compute_text.append(text)

        if to_compute_text:
            vectors = _model().encode(to_compute_text, normalize_embeddings=True, batch_size=32).tolist()
            for idx, text, vector in zip(to_compute_idx, to_compute_text, vectors):
                results[idx] = vector
                await cache_manager.embedding.set_embedding(text, self.model_name, vector)

        return results  # type: ignore[return-value]


embedder = Embedder()
