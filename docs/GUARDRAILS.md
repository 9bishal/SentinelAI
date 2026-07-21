# Guardrails

Two guardrail stages, both in `services/guardrails/`. Every decision they
make is cached (`cache_manager.guardrail_decision`) and keyed by rule/prompt
version, so a policy change automatically invalidates stale verdicts
platform-wide (see `cache_manager.on_policy_changed()` in CACHING.md).

## Input guardrail (`input_guardrail.py`)

Runs before anything else touches the request. Regex/keyword-based —
deliberately not an LLM call — for three reasons: it needs to be fast (it's
on every request's hot path), explainable (a regex match is auditable; an
LLM's "this looks like an injection" verdict is not, without its own
evaluation layer), and adversarially robust to at least the same degree as
the rest of the pipeline (an LLM-based guardrail can itself be
prompt-injected).

Detects: prompt injection ("ignore previous instructions"), jailbreak
framing ("you are now in DAN/developer mode"), and prompt-leakage attempts
("what is your system prompt").

**Extension point:** for stronger coverage, add an LLM-based secondary
check behind the regex layer — call it only when the regex layer is
inconclusive, not on every request, to keep latency and cost down.

## Output guardrail (`output_guardrail.py`) — the core of the platform

Every generated response passes through `OutputGuardrail.review()` before
it reaches a user. It runs, per sentence:

1. **PII detection + redaction** (`pii.py`) — regex-based, runs first, so
   no sensitive data leaks into any downstream check, log, or trace.
2. **Prompt-leakage detection** — checks the raw answer for fragments of
   the system/prompt template itself; if found, the entire response is
   replaced with a safe refusal rather than repaired (this is the one case
   where the guardrail blocks outright instead of annotating).
3. **Citation verification** — does each sentence carry a `[n]` citation?
4. **Groundedness verification** — for cited sentences, does the cited
   chunk actually support the claim? Measured as cosine similarity between
   the sentence's embedding and its cited chunk's embedding (same
   `all-MiniLM-L6-v2` model used everywhere else), thresholded at 0.55.
5. **Confidence scoring** — `0.5 × citation_coverage + 0.5 × groundedness_avg`,
   a simple, auditable blend rather than an opaque single number.
6. **Response repair** — instead of deleting or blocking unsupported
   sentences, they're annotated: `"... (⚠ unverified against retrieved
   sources)"`. Repairs are cached (`cache_manager.response_repair`) since
   the same unsupported claim often recurs across sessions.

### Why repair, not reject

A governance layer that blocks every uncertain response teaches users to
route around it. The project's stated goal — maximize usefulness while
minimizing enterprise risk — means the default posture should be "tell the
user what's uncertain," not "refuse to answer." Full block is reserved for
the one case (prompt leakage) where the content itself is the problem, not
just its confidence level.

### Extension point: LLM-based repair

The current repair step is a cheap, always-safe annotation. A stronger
(and more expensive) repair would call the LLM again with only the
unsupported sentence + fresh context, asking it to either produce a
grounded rewrite or drop the claim. Wire that into
`OutputGuardrail._repair()` — the `response_repair` cache is already keyed
in a way that supports either strategy without a schema change.

## What's intentionally not implemented as a separate "hallucination
detector"

Hallucination detection here is *not* a separate model call — it falls out
of the same per-sentence groundedness check used for citations. A dedicated
hallucination classifier is a reasonable addition (and a good place to
plug in a NLI-based entailment model), but the platform treats "ungrounded"
and "hallucinated" as the same underlying signal rather than paying for two
separate checks that would usually agree.
