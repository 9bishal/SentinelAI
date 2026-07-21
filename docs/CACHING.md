# SentinelAI — Multi-Layer Caching Architecture

> Part of **SentinelAI – AI Response Governance Platform**.
> This doc covers the caching layer only. See `/docs` for the other layers
> (guardrails, retrieval, evaluation, observability).

## Why 13 caches instead of one?

A single "response cache" only helps when a user asks the *exact* same
question twice. In a real RAG + governance pipeline, expensive work happens
at every stage — embedding, retrieval, reranking, evaluation, guardrail
checks — and each stage has its own reuse pattern and its own invalidation
trigger. Caching all of it as one blob means one config change (e.g. a
guardrail rule update) forces you to blow away retrieval results that were
still perfectly valid.

So each stage gets its own cache, its own TTL, its own invalidation reason,
and its own Prometheus hit/miss counters — while sharing one Redis instance
and one base implementation.

## The 13 caches

| Cache | Purpose | Default TTL | Invalidated by |
|---|---|---|---|
| Semantic Response | Reuse an answer for a *semantically similar* prior query | 1h | doc update, embeddings regenerated |
| Prompt | Cache fully-rendered prompt templates | 30m | manual |
| Embedding | Avoid re-embedding identical text | 24h | embedding model migration |
| Retrieval | Raw hybrid search results per query+filters | 15m | doc update |
| Reranking | Cross-encoder scores per query+chunk-set | 15m | doc update |
| Document Fingerprint | Content hash to skip re-ingesting identical uploads | none (manual) | re-ingestion |
| OCR | OCR output per page-image hash | none (manual) | manual |
| Evaluation | RAGAS / LLM-judge scores per (query, response, context) | 7d | manual |
| Metadata | Doc/chunk metadata (author, version, ACL) | 1h | doc update |
| Response Repair | Cached repair of a known unsupported claim | 30m | manual |
| Guardrail Decision | Injection/PII/policy verdict per (text, rule version) | 1h | policy change |
| Model Routing | Which model tier handles a query class | 5m | manual |
| Configuration | Policy/config reads to avoid hammering Postgres | 60s | policy change |

All TTLs are env-overridable: `SENTINELAI_TTL_<CACHE_NAME>`.

## Design

```
services/cache/
├── config.py          # CacheType enum + CacheSpec (prefix, TTL, doc_scoped)
├── metrics.py          # Prometheus Counters/Histograms shared by every cache
├── base.py             # RedisCacheBase: get/set/delete + doc-scoped invalidation
├── embedding_cache.py   # text+model -> vector
├── semantic_cache.py    # cosine-similarity lookup over cached query embeddings
├── domain_caches.py      # the remaining 10 thin key-builder caches
└── manager.py           # CacheManager — single import point + invalidation events
```

Every cache extends `RedisCacheBase`, which gives it for free:

- namespaced keys (`{prefix}:{hash}`)
- Prometheus hit/miss/set/invalidation counters, labeled by cache type
- optional **doc-scoped reverse index**: when a cache entry is written with
  `doc_ids=[...]`, those IDs are added to a `docidx:{doc_id}` set. Calling
  `invalidate_for_document(doc_id)` deletes every cache entry across every
  cache type that was derived from that document — in one call, without a
  full `SCAN`.

## Semantic cache: built on RedisVL (and optionally Redis LangCache)

The semantic response cache is implemented with **RedisVL**, not hand-rolled
cosine scanning. Two backends, chosen via `SENTINELAI_LANGCACHE_MODE`:

- **`local` (default)** — `redisvl.extensions.cache.llm.SemanticCache` against
  your own self-hosted **Redis Stack** instance (the `redis` service in
  `docker-compose.yml` runs `redis/redis-stack-server`, not plain Redis —
  RediSearch's HNSW vector index is what makes similarity lookup fast at
  scale). No external account needed.
- **`managed`** — `redisvl.extensions.cache.llm.LangCacheSemanticCache`,
  Redis's hosted **LangCache** service. Requires a LangCache account
  (`cache_id` + `api_key`, set in `.env`). Same interface, zero Redis ops.

Both are wrapped by `SemanticResponseCache` (`semantic_cache.py`) so the rest
of the platform only ever calls `lookup()` / `store()` — swapping backends
is a one-line env var change, not a code change.

Embeddings for the local backend come from **`all-MiniLM-L6-v2`** via
`HFTextVectorizer` — the same model used for document/query embeddings
everywhere else in the platform (`services/embeddings/embedder.py`), so the
semantic cache and the retriever share one embedding space.

One tradeoff worth stating explicitly: RedisVL's semantic cache index isn't
declared with `doc_id` as a filterable field by default, so precise
per-document invalidation (like the reverse-index trick the other 12 caches
use, see below) isn't wired up for it — `on_document_updated` currently does
a full `clear()` on this cache specifically. That's a deliberate, documented
simplification; the fix is a five-line change (declare `doc_ids` as a
filterable tag field, then delete-by-filter instead of clear-all) and is a
good first PR for anyone picking up this repo.

## Automatic invalidation — the three triggers

The platform defines exactly three events that can make a cache entry wrong:

1. **A document changes** (re-upload, new version, deletion)
   → `cache_manager.on_document_updated(doc_id)`
   → sweeps semantic response, retrieval, reranking, and metadata caches
   for that document.

2. **Embeddings are regenerated** (model migration, re-embedding job)
   → `cache_manager.on_embeddings_regenerated(model_name)`
   → drops stale embedding-cache entries for the old model, and flushes
   retrieval/reranking/semantic caches wholesale (their results were built
   on now-invalid vectors).

3. **Policy changes** (guardrail rule update, company policy edit)
   → `cache_manager.on_policy_changed(scope)`
   → flushes guardrail-decision and configuration caches.

Wire these three calls into the ingestion pipeline, the embedding worker,
and the policy admin API respectively — nothing else needs to know caching
exists.

## Observability

Every cache operation emits:

- `sentinelai_cache_hits_total{cache_type}`
- `sentinelai_cache_misses_total{cache_type}`
- `sentinelai_cache_sets_total{cache_type}`
- `sentinelai_cache_invalidations_total{cache_type, reason}`
- `sentinelai_cache_operation_seconds{cache_type, operation}` (histogram)

`/metrics` is mounted via `prometheus_client.make_asgi_app()`. Point
Prometheus at it (see `docker/prometheus.yml`) and build a Grafana panel per
cache type: hit ratio = `hits / (hits + misses)`.

## Admin API

```
GET  /api/v1/cache/stats
POST /api/v1/cache/invalidate/document     { "doc_id": "..." }
POST /api/v1/cache/invalidate/embeddings   { "model_name": "..." }
POST /api/v1/cache/invalidate/policy       { "scope": "..." }
```

## Local setup

```bash
docker compose up -d redis   # runs redis/redis-stack-server (needed for vector search)
pip install redis redisvl prometheus-client sentence-transformers
```

```python
from app.services.cache import cache_manager

cached = await cache_manager.retrieval.get_results(query, filters)
if cached is None:
    results = run_hybrid_retrieval(query, filters)
    await cache_manager.retrieval.set_results(query, filters, results, doc_ids=[...])
```
