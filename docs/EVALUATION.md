# Evaluation

`services/evaluation/evaluator.py`. Two tiers, both cached
(`cache_manager.evaluation`, keyed by `question + answer + context_hash`):

## 1. Heuristic scores — free, runs on every request

Computed directly from the output guardrail's own per-sentence groundedness
data, not a separate model call:

- `faithfulness` — the guardrail's `groundedness_avg` (mean cosine
  similarity between each cited sentence and its cited chunk)
- `context_utilization` — the guardrail's `citation_coverage` (fraction of
  sentences that carried a citation at all)
- `context_precision_proxy` — a cheap stand-in for RAGAS's context
  precision, using groundedness as a proxy rather than a second LLM call
- `flagged_sentence_count` — how many sentences the guardrail had to repair

These aren't a replacement for RAGAS's full metric suite — they're a
zero-cost first pass that catches the majority of quality regressions
without a single extra token spent, which matters when you're evaluating
100% of production traffic rather than a sampled subset.

## 2. LLM-as-judge — sampled, costs a real Groq call

`evaluator.llm_as_judge()` sends the question, context, and answer to the
LLM with a grading prompt (`llm/prompt_templates.py::JUDGE_TEMPLATE`) asking
for JSON-formatted scores: `correctness`, `groundedness`, `safety`,
`completeness`, `citation_quality`.

This is **opt-in per request** (`run_llm_judge: true` in the chat request
body) rather than automatic — a real production deployment would sample a
fixed percentage of traffic (1-10%, typically) instead of exposing this as
a raw per-caller toggle. That sampling policy is a natural home for the
`configuration` cache (see CACHING.md) — store the current sample rate
there and read it in the orchestrator rather than hardcoding it.

## Extension point: full RAGAS integration

The project vision calls for RAGAS's full metric suite (Faithfulness,
Answer Relevancy, Context Recall, Context Precision, Context Utilization).
`ragas` is in `requirements.txt` but not yet wired in — it needs a
reference/ground-truth dataset per query to compute Context Recall
specifically (the other metrics can run reference-free). The natural
integration point is a scheduled batch job (not the request hot path) that
pulls recent `ChatHistory` rows from Postgres, runs the full RAGAS suite
against them, and writes results back to the `evaluations` table —
continuous evaluation, not per-request evaluation.
