"""
Context Builder — turns reranked chunks into the numbered context block the
prompt template expects, applying a token budget so we never blow the
context window or pay for redundant tokens. This is the ONLY place that
decides what the LLM actually sees.
"""
from app.core.config import get_settings

settings = get_settings()

# crude token estimate: ~4 chars/token for English text, good enough for budgeting
CHARS_PER_TOKEN = 4


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // CHARS_PER_TOKEN)


class ContextBuilder:
    def build(self, chunks: list[dict], max_context_tokens: int = 3000) -> tuple[str, list[dict]]:
        """Returns (numbered_context_block, chunks_actually_used).
        Chunks are already reranked highest-confidence-first; we greedily
        include chunks until the token budget is spent, so low-confidence
        tail chunks get dropped before they dilute the prompt."""
        lines = []
        used = []
        budget = max_context_tokens

        for i, chunk in enumerate(chunks, start=1):
            text = chunk["text"].strip()
            cost = _estimate_tokens(text)
            if cost > budget:
                continue
            lines.append(f"[{i}] {text}")
            used.append(chunk)
            budget -= cost
            if budget <= 0:
                break

        return "\n\n".join(lines), used


context_builder = ContextBuilder()
