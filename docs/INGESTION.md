# Document Ingestion

## Pipeline

```
POST /api/v1/documents/ingest
        │
        ▼
Celery task enqueued (RabbitMQ) ── returns task_id immediately, doesn't block
        │
        ▼ (worker container picks up the job)
Content fingerprint check ── skip entirely if identical content already ingested
        │
        ▼
Semantic chunking (sentence-window, ~300 tokens, 2-sentence overlap)
        │
        ▼
Batch embedding (all-MiniLM-L6-v2, cache-aware — see embedder.py)
        │
        ▼
Upsert to ChromaDB (old version's chunks deleted first)
        │
        ▼
Cache invalidation (cache_manager.on_document_updated)
```

## Why Celery + RabbitMQ instead of processing inline

Uploading up to 100 PDFs simultaneously needs to not block the API, needs
retry-on-failure without losing progress, and needs to scale horizontally
(add more worker replicas, not more API server threads) — a job queue is
the right tool, not a background `asyncio.create_task`.

`workers/tasks.py::batch_ingest_task` fans a batch upload out into one
Celery task per document, so a bulk upload of 100 files is 100 independent,
individually-retryable jobs distributed across however many `worker`
containers are running (`docker-compose.yml` runs 2 replicas by default;
scale with `docker compose up -d --scale worker=8`).

Retry policy lives on the task itself (`IngestionTask` in `tasks.py`):
exponential backoff, up to 3 retries, jittered to avoid thundering-herd
retries against Chroma/Postgres.

## Semantic chunking, not fixed-length slicing

`services/ingestion/chunking.py` splits on paragraph and sentence
boundaries first, then groups sentences into ~300-token chunks with a
2-sentence overlap — this keeps related sentences together far better than
slicing every N characters, which routinely cuts a sentence (or a citation
context) in half.

## Fingerprinting — skip duplicate work

`DocumentFingerprintCache` (see CACHING.md) stores a content hash per
`doc_id`. Re-uploading an identical file is a no-op (`status:
skipped_duplicate`) rather than re-running the full chunk → embed → store
pipeline — this matters a lot in practice, since "did I already upload
this?" is one of the most common real-world ingestion questions.

## Extension point: OCR

`services/ingestion/pipeline.py::extract_text_with_ocr()` is a deliberate
stub that raises `NotImplementedError`. Scanned PDFs with no extractable
text layer need this wired in before `semantic_chunk()` runs — plug in
`pytesseract`, a hosted OCR API, or a vision-LLM-based extraction call, and
cache the per-page output in `OCRCache` (already implemented — see
CACHING.md) since OCR is the single slowest step in the pipeline and PDF
pages are rarely re-processed once OCR'd.
