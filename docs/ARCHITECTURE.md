# Architecture

## Module map

```
backend/app/
├── main.py                    # FastAPI entrypoint, router wiring, /metrics mount
├── core/
│   └── config.py               # Settings — the only place env vars are read (except cache/)
├── api/v1/
│   ├── chat.py                  # POST /api/v1/chat/query
│   ├── documents.py             # POST /api/v1/documents/ingest (enqueues Celery task)
│   ├── cache.py                 # GET /stats, POST /invalidate/* — admin cache control
│   └── health.py                 # liveness/readiness
├── services/
│   ├── orchestrator.py          # ChatOrchestrator — wires every layer together, in order
│   ├── cache/                   # 13-layer caching system — see CACHING.md
│   ├── embeddings/
│   │   └── embedder.py           # all-MiniLM-L6-v2, cache-aware, singleton-loaded
│   ├── retrieval/
│   │   ├── chroma_store.py        # ChromaDB wrapper (dense search + metadata filter)
│   │   ├── bm25.py                 # lexical scoring over the same corpus
│   │   ├── hybrid_retriever.py     # RRF fusion, dedupe, version priority, orchestration
│   │   └── reranker.py             # cross-encoder rerank, cached
│   ├── context/
│   │   └── context_builder.py     # token-budgeted, numbered context block
│   ├── llm/
│   │   ├── groq_client.py          # LLM Gateway: retry, fallback, streaming, cost tracking
│   │   └── prompt_templates.py     # versioned prompt templates
│   ├── guardrails/
│   │   ├── input_guardrail.py      # injection / jailbreak / leakage detection
│   │   ├── output_guardrail.py     # THE core service — see GUARDRAILS.md
│   │   └── pii.py                    # regex-based PII detect + redact
│   ├── evaluation/
│   │   └── evaluator.py            # heuristic RAGAS-style + sampled LLM-as-judge
│   └── ingestion/
│       ├── chunking.py              # semantic (sentence-window) chunking
│       └── pipeline.py               # fingerprint → chunk → embed → store → invalidate
├── workers/
│   ├── celery_app.py               # RabbitMQ broker, Redis result backend
│   └── tasks.py                     # ingest_document_task, batch_ingest_task
├── models/
│   ├── db.py                        # async SQLAlchemy engine/session
│   └── tables.py                    # Document, Chunk, ChatHistory, Evaluation, GuardrailLog, ModelUsage
├── schemas/                          # Pydantic request/response models
└── analytics/
    └── langfuse_client.py           # tracing — no-op if keys unset
```

## Request lifecycle

A single `POST /api/v1/chat/query` call walks through, in order:

1. **Input guardrail** (`guardrails/input_guardrail.py`) — regex/keyword
   detection of injection, jailbreak, and leakage attempts. Cached by
   `(text, prompt_version)` so repeated adversarial probes cost nothing on
   the second attempt.
2. **Semantic response cache** (`cache/semantic_cache.py`, RedisVL) — if a
   semantically similar question was answered before, return it immediately.
   Still counted and traced, just skips retrieval + generation.
3. **Hybrid retrieval** (`retrieval/hybrid_retriever.py`) — BM25 + dense
   search fused with Reciprocal Rank Fusion, deduplicated, version-prioritized,
   then reranked with a cross-encoder. Every stage (retrieval, reranking)
   is independently cached.
4. **Context builder** — greedily packs the highest-ranked chunks into a
   numbered context block under a token budget.
5. **LLM Gateway** (`llm/groq_client.py`) — calls Groq with a fast model
   first, falls back to a stronger model on failure. Prompt-level caching
   sits directly above this call.
6. **Output guardrail** (`guardrails/output_guardrail.py`) — THE core
   service. Per-sentence citation + groundedness checks, PII redaction,
   prompt-leakage detection, confidence scoring, and repair (annotation)
   of unsupported claims instead of blocking outright.
7. **Evaluation** — heuristic scores computed for free from the guardrail's
   own groundedness data; LLM-as-judge scoring is sampled (opt-in per
   request via `run_llm_judge`) since it costs a real model call.
8. **Cache write + trace** — the governed answer is stored in the semantic
   cache for future similar questions, and the whole turn is traced to
   Langfuse (model, latency, cost, cache hit, confidence, guardrail actions).

## Design principles this repo tries to hold to

- **Every stage is independently cacheable and independently observable.**
  No single "do everything" cache, no single "safety score" — see CACHING.md
  and GUARDRAILS.md for why that granularity matters operationally.
- **Repair over reject.** The output guardrail's default posture is to
  annotate uncertainty, not delete or refuse — see GUARDRAILS.md.
- **One embedding space for the whole platform.** Documents, queries, and
  the semantic cache all embed with the same model (`all-MiniLM-L6-v2`), so
  cache hit rate isn't silently hurt by embedding-space mismatch.
- **Extension points are documented, not faked.** OCR, query rewriting, and
  full RAGAS integration are real stubs with a clear "wire this in here"
  comment rather than placeholder code that looks complete but isn't.
