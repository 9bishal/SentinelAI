"""
Document Ingestion Pipeline — the synchronous logic that Celery tasks
(workers/tasks.py) call per document. Kept separate from the Celery task
definitions so it's directly unit-testable without a broker running.

Pipeline: fingerprint check -> chunk -> embed (batched) -> upsert to Chroma
        -> cache invalidation (cache_manager.on_document_updated)

OCR is intentionally NOT implemented inline here — it's a documented
extension point (see docs/INGESTION.md): plug in `pytesseract` or a hosted
OCR API in `extract_text_with_ocr()` and call it before chunking when the
uploaded file is a scanned PDF (no extractable text layer).
"""
import hashlib

# pyrefly: ignore [missing-import]
from app.services.cache import cache_manager
# pyrefly: ignore [missing-import]
from app.services.embeddings.embedder import embedder
# pyrefly: ignore [missing-import]
from app.services.retrieval.chroma_store import chroma_store

# pyrefly: ignore [missing-import]
from .chunking import semantic_chunk


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def extract_text_with_ocr(file_path: str) -> str:
    """Extension point. Wire in pytesseract / a hosted OCR API here for
    scanned PDFs with no text layer. Raising NotImplementedError keeps this
    honest rather than silently returning an empty string."""
    raise NotImplementedError("OCR backend not wired in yet — see docs/INGESTION.md")


class IngestionPipeline:
    async def ingest_document(self, doc_id: str, doc_version: int, raw_text: str, source_metadata: dict) -> dict:
        content_hash = _content_hash(raw_text)

        if await cache_manager.doc_fingerprint.is_duplicate(doc_id, content_hash):
            return {"doc_id": doc_id, "status": "skipped_duplicate", "chunks_ingested": 0}

        chunks = semantic_chunk(raw_text)
        embeddings = await embedder.embed_batch(chunks)

        ids = [f"{doc_id}:v{doc_version}:{i}" for i in range(len(chunks))]
        metadatas = [
            {
                "doc_id": doc_id,
                "doc_version": doc_version,
                "chunk_index": i,
                "content_hash": _content_hash(chunk),
                **source_metadata,
            }
            for i, chunk in enumerate(chunks)
        ]

        # remove any previous version's chunks for this doc_id before writing new ones
        chroma_store.delete_by_document(doc_id)
        chroma_store.upsert_chunks(ids=ids, embeddings=embeddings, documents=chunks, metadatas=metadatas)

        await cache_manager.doc_fingerprint.set_fingerprint(doc_id, content_hash)
        await cache_manager.metadata.set_metadata(doc_id, {**source_metadata, "doc_version": doc_version}, )
        invalidation_result = await cache_manager.on_document_updated(doc_id)

        return {
            "doc_id": doc_id,
            "status": "ingested",
            "chunks_ingested": len(chunks),
            "cache_invalidated": invalidation_result,
        }


ingestion_pipeline = IngestionPipeline()
