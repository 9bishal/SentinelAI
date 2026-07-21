"""
Langfuse integration — traces prompts, responses, retrieved chunks, latency,
token usage, cache hits, evaluation scores, guardrail actions, model
selected, and cost for every request. Wrapped in a thin client so the rest
of the app never imports langfuse directly (keeps it swappable/optional —
if LANGFUSE keys aren't set, this becomes a no-op).
"""
# pyrefly: ignore [missing-import]
from functools import lru_cache

from app.core.config import get_settings

settings = get_settings()


@lru_cache
def _client():
    if not (settings.langfuse_public_key and settings.langfuse_secret_key):
        return None
    # pyrefly: ignore [missing-import]
    from langfuse import Langfuse

    return Langfuse(
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key,
        host=settings.langfuse_host,
    )


class ObservabilityClient:
    def trace_chat_turn(self, *, session_id: str, question: str, answer: str, retrieved_chunks: list[dict],
                         model: str, latency_ms: int, cost_usd: float, cache_hit: bool,
                         confidence: float, guardrail_actions: list[str]) -> None:
        client = _client()
        if client is None:
            return  # Langfuse not configured — silently skip, don't break the request path

        trace = client.trace(
            name="chat_turn",
            session_id=session_id,
            input={"question": question},
            output={"answer": answer},
            metadata={
                "model": model,
                "latency_ms": latency_ms,
                "cost_usd": cost_usd,
                "cache_hit": cache_hit,
                "confidence": confidence,
                "guardrail_actions": guardrail_actions,
                "retrieved_chunk_ids": [c.get("id") for c in retrieved_chunks],
            },
        )
        trace.update(tags=["sentinelai"])


observability = ObservabilityClient()
