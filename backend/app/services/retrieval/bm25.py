"""
BM25 lexical scoring over the same chunk corpus Chroma holds, for hybrid
retrieval. Built fresh per query from ChromaStore.all_documents_for_bm25 —
fine up to tens of thousands of chunks. Past that, persist and incrementally
update a BM25Okapi index in the ingestion worker instead of rebuilding here.
"""
from rank_bm25 import BM25Okapi

from .chroma_store import chroma_store


def _tokenize(text: str) -> list[str]:
    return text.lower().split()


class BM25Retriever:
    def search(self, query: str, top_k: int, where: dict | None = None) -> list[dict]:
        corpus = chroma_store.all_documents_for_bm25(where=where)
        if not corpus:
            return []
        tokenized_corpus = [_tokenize(doc["text"]) for doc in corpus]
        bm25 = BM25Okapi(tokenized_corpus)
        scores = bm25.get_scores(_tokenize(query))

        ranked = sorted(zip(corpus, scores), key=lambda pair: pair[1], reverse=True)[:top_k]
        return [{**doc, "bm25_score": float(score)} for doc, score in ranked]


bm25_retriever = BM25Retriever()
