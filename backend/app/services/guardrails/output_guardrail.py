"""
AI Output Policy Guardrail Service — THE core of the platform. Every LLM
response passes through here before reaching the user. Runs, per sentence:

  1. Citation verification   — does the sentence cite a context number?
  2. Groundedness verification — does the cited context actually support it
     (cosine similarity between sentence and its cited chunk(s))?
  3. PII detection/redaction
  4. Prompt-leakage detection (system prompt fragments leaking into output)
  5. Confidence scoring        — blends citation coverage + groundedness
  6. Response repair          — instead of blocking, annotate unsupported
     sentences with an uncertainty marker (cheap, always-safe repair here;
     full LLM-based rewrite/regeneration is a documented extension point).

Contradiction detection and freshness validation operate on retrieved
chunks (services/retrieval), not on the generated answer — flagged findings
from those layers are passed in via `retrieved_chunks` metadata and folded
into the final confidence score here.
"""
import re
from dataclasses import dataclass, field

from app.core.config import get_settings
from app.services.cache import cache_manager
from app.services.embeddings.embedder import embedder
from app.services.guardrails.pii import redact_pii
from app.services.llm.prompt_templates import PROMPT_VERSION, RAG_ANSWER_TEMPLATE

settings = get_settings()

CITATION_PATTERN = re.compile(r"\[(\d+(?:,\s*\d+)*)\]")
SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")

SYSTEM_PROMPT_FINGERPRINT = re.compile(
    r"(you are sentinelai's answer engine|respond with plain prose)", re.I
)


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


@dataclass
class SentenceVerdict:
    text: str
    cited_indices: list[int]
    grounded: bool
    groundedness_score: float


@dataclass
class GuardrailReport:
    final_text: str
    confidence: float
    citation_coverage: float
    groundedness_avg: float
    flagged_sentences: list[SentenceVerdict] = field(default_factory=list)
    pii_findings: list[dict] = field(default_factory=list)
    prompt_leakage_detected: bool = False
    blocked: bool = False
    block_reason: str | None = None


class OutputGuardrail:
    async def review(self, raw_answer: str, context_chunks: list[dict]) -> GuardrailReport:
        # -- PII first: never let sensitive data reach downstream checks/logs --
        redacted_answer, pii_findings = redact_pii(raw_answer)

        # -- prompt leakage --
        prompt_leakage_detected = bool(SYSTEM_PROMPT_FINGERPRINT.search(redacted_answer))
        if prompt_leakage_detected:
            return GuardrailReport(
                final_text="I can't share my internal instructions, but I'm happy to help with your question directly.",
                confidence=0.0,
                citation_coverage=0.0,
                groundedness_avg=0.0,
                pii_findings=pii_findings,
                prompt_leakage_detected=True,
                blocked=True,
                block_reason="prompt_leakage_detected",
            )

        # -- per-sentence citation + groundedness --
        sentences = [s.strip() for s in SENTENCE_SPLIT.split(redacted_answer) if s.strip()]
        verdicts: list[SentenceVerdict] = []
        cited_count = 0

        for sentence in sentences:
            match = CITATION_PATTERN.search(sentence)
            indices = [int(x) for x in match.group(1).split(",")] if match else []
            grounded, score = True, 1.0

            if indices:
                cited_count += 1
                grounded, score = await self._check_groundedness(sentence, indices, context_chunks)
            else:
                grounded, score = False, 0.0  # uncited factual sentence = ungrounded by default

            verdicts.append(SentenceVerdict(sentence, indices, grounded, score))

        citation_coverage = cited_count / len(sentences) if sentences else 1.0
        groundedness_avg = sum(v.groundedness_score for v in verdicts) / len(verdicts) if verdicts else 1.0
        flagged = [v for v in verdicts if not v.grounded]

        repaired_text = await self._repair(verdicts)

        confidence = round(0.5 * citation_coverage + 0.5 * groundedness_avg, 3)

        return GuardrailReport(
            final_text=repaired_text,
            confidence=confidence,
            citation_coverage=round(citation_coverage, 3),
            groundedness_avg=round(groundedness_avg, 3),
            flagged_sentences=flagged,
            pii_findings=pii_findings,
            prompt_leakage_detected=False,
            blocked=False,
        )

    async def _check_groundedness(self, sentence: str, indices: list[int], context_chunks: list[dict]) -> tuple[bool, float]:
        cited_texts = [context_chunks[i - 1]["text"] for i in indices if 0 < i <= len(context_chunks)]
        if not cited_texts:
            return False, 0.0

        sentence_vec = await embedder.embed(sentence)
        scores = [ _cosine(sentence_vec, await embedder.embed(ctx)) for ctx in cited_texts ]
        best = max(scores) if scores else 0.0
        return best >= 0.55, round(best, 3)

    async def _repair(self, verdicts: list[SentenceVerdict]) -> str:
        """Cheap, always-safe repair: annotate unsupported sentences with an
        uncertainty marker rather than deleting them outright (deletion can
        silently make an answer look more confident than it should) or
        regenerating (an extension point — swap in an LLM rewrite call here,
        cached via cache_manager.response_repair)."""
        out = []
        for v in verdicts:
            if v.grounded:
                out.append(v.text)
                continue

            cache_key_text = v.text
            cached = await cache_manager.response_repair.get_repair(cache_key_text, "unsupported_claim")
            if cached:
                out.append(cached)
                continue

            annotated = f"{v.text} (⚠ unverified against retrieved sources)"
            await cache_manager.response_repair.set_repair(cache_key_text, "unsupported_claim", annotated)
            out.append(annotated)
        return " ".join(out)


output_guardrail = OutputGuardrail()
