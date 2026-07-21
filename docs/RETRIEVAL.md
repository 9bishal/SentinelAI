# Retrieval

`services/retrieval/hybrid_retriever.py` is the entrypoint; everything else
in this directory supports it.

## Pipeline

```
query
  │
  ├──► dense search (ChromaDB, cosine, all-MiniLM-L6-v2 embeddings)
  │
  ├──► BM25 lexical search (rank_bm25, rebuilt per query from the corpus)
  │
  ▼
Reciprocal Rank Fusion (RRF, k=60)
  │
  ▼
Deduplication + document-version prioritization
  │
  ▼
Cross-encoder reranking (ms-marco-MiniLM-L-6-v2, top candidates only)
  │
  ▼
top-N chunks → Context Builder
```

## Why hybrid, not just dense

Dense retrieval is great at semantic similarity ("what's a good tent for
cold weather" ↔ "recommended shelter for sub-zero camping") and bad at exact
matches (a product SKU, an error code, a proper noun it's never seen).
BM25 is the reverse. Fusing both with RRF gets the benefit of each without
needing to tune a single blended score by hand — RRF only cares about each
method's *rank order*, not its raw score scale, which is what makes it work
well combining two very differently-scaled signals (cosine distance vs.
BM25 score).

## Deduplication + version prioritization

Real document sets have near-duplicate chunks (boilerplate, repeated
headers) and multiple versions of the same document. `hybrid_retriever.py`
groups candidates by a `content_hash` stored in chunk metadata at ingestion
time, and keeps only the highest `doc_version` per group — so a stale
policy doc doesn't out-rank its own replacement just because it happened to
score slightly higher on this particular query.

## Reranking

The RRF-fused, deduplicated list is still just rank order from two cheap
methods. A cross-encoder scores `(query, chunk)` pairs jointly (rather than
comparing independently-computed embeddings), which is meaningfully more
accurate — and meaningfully more expensive, which is why it only runs on
the fused shortlist (`top_k * 2` candidates), not the full corpus, and why
its scores are cached per `(query, chunk_id_set)`.

## Caching

Retrieval results and reranking scores are both cached independently (see
CACHING.md) and both invalidate automatically on `on_document_updated`, so
stale results from a since-edited document never linger past a re-ingest.

## Extension points

- **Query Intelligence Layer** (query rewriting, multi-query expansion,
  conversation-aware rewriting) is referenced in the project vision but not
  yet implemented as its own module — the natural place to add it is
  immediately before `hybrid_retriever.retrieve()` is called in
  `services/orchestrator.py`, rewriting `question` before it's used as both
  the cache key and the retrieval query.
- **Metadata filtering** is already wired end-to-end (the `where` parameter
  flows from the API request through retrieval, BM25, and Chroma), but no
  router currently exposes ACL-style filters to callers — that's the
  natural hook point for RBAC.
