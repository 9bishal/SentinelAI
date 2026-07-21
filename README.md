# SentinelAI — AI Response Governance Platform

**The LLM is not the product. The governance layer is the product.**

SentinelAI is an open-source middleware platform that sits between users and
any LLM, treating the model as one component inside a larger governed
system. Every request and every generated response passes through
retrieval, guardrail, evaluation, caching, and observability layers before
it reaches a user — the same shape of system internal AI platform teams at
larger orgs build to run LLMs safely at scale.

This repo is a from-scratch, runnable reference implementation, built to be
read, forked, and learned from — not a wrapper around a single API call.

## Why this exists

Most public RAG projects stop at "retrieve chunks, stuff them in a prompt,
call the model." That's maybe 20% of what it takes to run an LLM feature in
an enterprise setting. The other 80% is:

- Is this response actually grounded in retrieved evidence, or did the model
  make something up?
- Did the response leak PII, secrets, or the system prompt?
- Does every claim have a citation, and does the citation actually support it?
- How confident should we be in this answer, and can we quantify that?
- What did this cost, how long did it take, and would a cache have avoided it?

SentinelAI implements all of the above as explicit, inspectable layers —
not a single opaque "safety" call.

## Architecture at a glance

```
User Request
    │
    ▼
API Gateway (FastAPI)
    │
    ▼
Input Guardrail ──── blocks prompt injection / jailbreaks / leakage attempts
    │
    ▼
Semantic Response Cache (RedisVL) ──── hit? return immediately, still governed
    │ miss
    ▼
Query Intelligence ──── rewriting / expansion (extension point, see docs)
    │
    ▼
Hybrid Retrieval Engine ──── BM25 + dense (ChromaDB) → RRF fusion → dedupe →
    │                        cross-encoder rerank (each stage independently cached)
    ▼
Context Builder ──── token-budgeted, numbered context block
    │
    ▼
LLM Gateway (Groq) ──── model tiering, retry, fallback, streaming, cost tracking
    │
    ▼
Output Policy Guardrail ──── groundedness · citations · PII · prompt-leakage ·
    │                         confidence scoring · response repair (not just block)
    ▼
Evaluation Service ──── heuristic RAGAS-style metrics + sampled LLM-as-judge
    │
    ▼
Governed Response ──── returned to user, traced to Langfuse, scored in Prometheus
```

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full breakdown of
every layer, and the other docs below for deep dives.

## Documentation

| Doc | Covers |
|---|---|
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | Full system design, module map, data flow |
| [CACHING.md](docs/CACHING.md) | 13-layer caching system (RedisVL / Redis LangCache) |
| [GUARDRAILS.md](docs/GUARDRAILS.md) | Input + output guardrails, groundedness, PII, repair |
| [RETRIEVAL.md](docs/RETRIEVAL.md) | Hybrid BM25+dense retrieval, RRF fusion, reranking |
| [EVALUATION.md](docs/EVALUATION.md) | Heuristic scoring + LLM-as-judge |
| [INGESTION.md](docs/INGESTION.md) | Async document pipeline (Celery + RabbitMQ) |
| [GETTING_STARTED.md](docs/GETTING_STARTED.md) | Local setup, env vars, first request |

## Stack

FastAPI · Groq (Llama 3.1/3.3) · ChromaDB · Redis Stack / RedisVL / Redis
LangCache · PostgreSQL · RabbitMQ + Celery · sentence-transformers
(`all-MiniLM-L6-v2`) · Prometheus + Grafana · Langfuse · Docker Compose

## Quick start

```bash
git clone https://github.com/9bishal/sentinelai.git
cd sentinelai
cp .env.example .env   # fill in SENTINELAI_GROQ_API_KEY at minimum
docker compose up -d
curl http://localhost:8000/api/v1/health/live
```

Full walkthrough (uploading a document, asking a governed question, reading
the guardrail flags on the response) is in
[GETTING_STARTED.md](docs/GETTING_STARTED.md).

## Project status

This is an actively developed portfolio/reference project — architecture
and core layers are implemented and wired end-to-end; some extension points
(OCR backend, query rewriting, full RAGAS integration, RBAC) are
deliberately left as documented stubs rather than padded out with fake
complexity. See each doc's "extension points" section.

Issues and PRs welcome — see [CONTRIBUTING](#contributing) below.

## Contributing

Good first issues:
- Wire a real query-rewriting step into `services/retrieval/` (currently an
  extension point — see RETRIEVAL.md)
- Add a filterable `doc_id` field to the semantic cache's RedisVL index so
  `on_document_updated` can precisely invalidate instead of full-clearing
  (see CACHING.md's "tradeoff" callout)
- Plug in an OCR backend for scanned PDFs (`services/ingestion/pipeline.py`)
- Full RAGAS integration in `services/evaluation/evaluator.py`

## License

MIT — see [LICENSE](LICENSE).
