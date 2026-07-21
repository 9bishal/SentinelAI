"""
Evaluation Service — continuous quality scoring for every response.

Two evaluation modes, both cached (services/cache/domain_caches.EvaluationCache
keyed by query+response+context hash, so re-scoring an identical triple is free):

  1. Heuristic RAGAS-style metrics (no extra LLM call — fast, runs on every
     request): faithfulness, context precision/recall proxies computed from
     the guardrail's own groundedness scores.
  2. LLM-as-Judge (Groq call — sampled, not every request, to control cost):
     correctness, groundedness, safety, completeness, citation_quality.
"""
import json

# pyrefly: ignore [missing-import]
from app.services.cache import cache_manager
# pyrefly: ignore [missing-import]
from app.services.guardrails.output_guardrail import GuardrailReport
# pyrefly: ignore [missing-import]
from app.services.llm.groq_client import groq_gateway
# pyrefly: ignore [missing-import]
from app.services.llm.prompt_templates import render_judge_prompt


def _make_context_hash(context_chunks: list[dict]) -> str:
    return str(hash(tuple(c["id"] for c in context_chunks)))


class Evaluator:
    def heuristic_scores(self, report: GuardrailReport, context_chunks: list[dict]) -> dict:
        """Fast, free, runs on every single request."""
        return {
            "faithfulness": report.groundedness_avg,
            "context_utilization": report.citation_coverage,
            "context_precision_proxy": min(1.0, len(context_chunks) and report.groundedness_avg),
            "flagged_sentence_count": len(report.flagged_sentences),
        }

    async def llm_as_judge(self, question: str, context_block: str, answer: str, context_chunks: list[dict]) -> dict:
        """Sampled — call this for a configurable % of traffic, not every
        request, since it costs a real Groq call."""
        context_hash = _make_context_hash(context_chunks)
        cached = await cache_manager.evaluation.get_scores(question, answer, context_hash)
        if cached is not None:
            return cached

        prompt = render_judge_prompt(question, context_block, answer)
        result = await groq_gateway.generate([{"role": "user", "content": prompt}], temperature=0.0)

        try:
            scores = json.loads(result.text)
        except json.JSONDecodeError:
            scores = {"parse_error": True, "raw": result.text}

        await cache_manager.evaluation.set_scores(question, answer, context_hash, scores)
        return scores


evaluator = Evaluator()
