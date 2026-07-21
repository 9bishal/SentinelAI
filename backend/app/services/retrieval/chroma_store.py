"""
Thin wrapper around a ChromaDB collection. We embed ourselves (via
services/embeddings/embedder.py, all-MiniLM-L6-v2) rather than letting
Chroma manage embeddings, so the exact same vectors back retrieval AND the
semantic cache/embedding cache — one embedding space for the whole platform.

Metadata filtering, parent-child retrieval, and document version priority
are implemented via Chroma's `where` filter + a `parent_chunk_id` /
`doc_version` field stored on every chunk at ingestion time.
"""
from functools import lru_cache
from typing import Optional

import chromadb

from app.core.config import get_settings

settings = get_settings()


@lru_cache
def get_client() -> chromadb.ClientAPI:
    return chromadb.HttpClient(host=settings.chroma_host, port=settings.chroma_port)


@lru_cache
def get_collection():
    return get_client().get_or_create_collection(
        name=settings.chroma_collection,
        metadata={"hnsw:space": "cosine"},
    )


class ChromaStore:
    """Lazily connects on first use — importing this module (e.g. transitively,
    via main.py's router imports) must not require Chroma to already be up."""

    @property
    def collection(self):
        return get_collection()

    def upsert_chunks(
        self,
        ids: list[str],
        embeddings: list[list[float]],
        documents: list[str],
        metadatas: list[dict],
    ) -> None:
        self.collection.upsert(ids=ids, embeddings=embeddings, documents=documents, metadatas=metadatas)

    def dense_search(
        self,
        query_embedding: list[float],
        top_k: int,
        where: Optional[dict] = None,
    ) -> list[dict]:
        result = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            where=where,
        )
        chunks = []
        for i in range(len(result["ids"][0])):
            chunks.append({
                "id": result["ids"][0][i],
                "text": result["documents"][0][i],
                "metadata": result["metadatas"][0][i],
                "dense_distance": result["distances"][0][i],
            })
        return chunks

    def delete_by_document(self, doc_id: str) -> None:
        """Called on re-ingestion/deletion — keeps Chroma in sync with the
        doc-scoped cache invalidation in cache_manager.on_document_updated."""
        self.collection.delete(where={"doc_id": doc_id})

    def all_documents_for_bm25(self, where: Optional[dict] = None) -> list[dict]:
        """Pulls the full text corpus (or a filtered subset) for BM25 scoring.
        For very large corpora, replace with a persisted BM25 index rebuilt
        incrementally by the ingestion worker instead of pulling every call."""
        result = self.collection.get(where=where, include=["documents", "metadatas"])
        return [
            {"id": result["ids"][i], "text": result["documents"][i], "metadata": result["metadatas"][i]}
            for i in range(len(result["ids"]))
        ]


chroma_store = ChromaStore()
