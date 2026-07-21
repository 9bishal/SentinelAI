"""
Chat Orchestrator — wires every layer together in the order the platform
vision requires. This is the "middleware that sits between users and any
LLM" described in the project brief; everything else is a service this
file calls in sequence.

    input guardrail
        -> semantic cache lookup (skip straight to guardrail+return on hit)
        -> hybrid retrieval (BM25 + dense + rerank, all individually cached)
        -> context builder (token-budgeted)
        -> prompt cache lookup / LLM Gateway (Groq, with fallback)
        -> output guardrail (groundedness, citations, PII, repair)
        -> evaluation (heuristic always, LLM-as-judge if sampled)
        -> semantic cache store
        -> observability trace
"""
import time

# pyrefly: ignore [missing-import]
from app.services.cache import cache_manager

# pyrefly: ignore [missing-import]
from app.services.context.context_builder import context_builder

# pyrefly: ignore [missing-import]
from app.services.evaluation.evaluator import evaluator

# pyrefly: ignore [missing-import]
from app.services.guardrails.input_guardrail import input_guardrail
from app.services.guardrails.output_guardrail import output_guardrail
from app.services.llm.groq_client import groq_gateway
from app.services.llm.prompt_templates import render_rag_answer_prompt
from app.services.retrieval.hybrid_retriever import hybrid_retriever
from app.analytics.langfuse_client import observability


class GovernedChatResponse:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class ChatOrchestrator:
    async def handle(self, session_id: str, question: str, filters: dict | None = None,
                      run_llm_judge: bool = False) -> GovernedChatResponse:
        start = time.perf_counter()
        guardrail_actions: list[str] = []

        # 1. Input guardrail
        input_result = await input_guardrail.check(question)
        if not input_result.allowed:
            guardrail_actions.append(f"input_blocked:{input_result.reason}")
            return GovernedChatResponse(
                answer="I can't help with that request.",
                confidence=0.0, citation_coverage=0.0, groundedness_avg=0.0,
                citations=[], cache_hit=False, model_used="none",
                latency_ms=int((time.perf_counter() - start) * 1000),
                estimated_cost_usd=0.0, guardrail_flags=guardrail_actions, evaluation=None,
            )

        # 2. Semantic response cache — skip retrieval+generation entirely on a hit
        cached = await cache_manager.semantic_response.lookup(question)
        if cached is not None:
            guardrail_actions.append("semantic_cache_hit")
            latency_ms = int((time.perf_counter() - start) * 1000)
            observability.trace_chat_turn(
                session_id=session_id, question=question, answer=cached["response"],
                retrieved_chunks=[], model="cache", latency_ms=latency_ms, cost_usd=0.0,
                cache_hit=True, confidence=cached.get("similarity", 1.0), guardrail_actions=guardrail_actions,
            )
            return GovernedChatResponse(
                answer=cached["response"], confidence=round(cached.get("similarity", 1.0), 3),
                citation_coverage=1.0, groundedness_avg=1.0, citations=[],
                cache_hit=True, model_used="cache", latency_ms=latency_ms,
                estimated_cost_usd=0.0, guardrail_flags=guardrail_actions, evaluation=None,
            )

        # 3. Hybrid retrieval (BM25 + dense + rerank; each stage independently cached)
        retrieved_chunks = await hybrid_retriever.retrieve(question, where=filters)

        # 4. Context builder — token-budgeted, numbered context block
        context_block, used_chunks = context_builder.build(retrieved_chunks)

        # 5. Prompt cache + LLM Gateway
        rendered_prompt = render_rag_answer_prompt(question, context_block)
        cached_prompt_response = await cache_manager.prompt.get_rendered("rag_answer", {"prompt": rendered_prompt})

        if cached_prompt_response is not None:
            raw_answer, model_used, cost_usd = cached_prompt_response, "cache", 0.0
            guardrail_actions.append("prompt_cache_hit")
        else:
            generation = await groq_gateway.generate_with_fallback([{"role": "user", "content": rendered_prompt}])
            raw_answer, model_used, cost_usd = generation.text, generation.model, generation.estimated_cost_usd
            await cache_manager.prompt.set_rendered("rag_answer", {"prompt": rendered_prompt}, raw_answer)

        # 6. Output guardrail — groundedness, citations, PII, repair
        report = await output_guardrail.review(raw_answer, used_chunks)
        if report.blocked:
            guardrail_actions.append(f"output_blocked:{report.block_reason}")
        if report.pii_findings:
            guardrail_actions.append(f"pii_redacted:{len(report.pii_findings)}")
        if report.flagged_sentences:
            guardrail_actions.append(f"unsupported_claims_repaired:{len(report.flagged_sentences)}")

        # 7. Evaluation — heuristic always, LLM-as-judge if sampled
        evaluation = evaluator.heuristic_scores(report, used_chunks)
        if run_llm_judge and not report.blocked:
            evaluation["llm_judge"] = await evaluator.llm_as_judge(question, context_block, report.final_text, used_chunks)

        # 8. Store in semantic cache for future semantically-similar queries
        if not report.blocked:
            doc_ids = list({c.get("metadata", {}).get("doc_id") for c in used_chunks if c.get("metadata", {}).get("doc_id")})
            await cache_manager.semantic_response.store(question, report.final_text, doc_ids=doc_ids)

        latency_ms = int((time.perf_counter() - start) * 1000)
        citations = [
            {"index": i, "chunk_id": c["id"], "doc_id": c.get("metadata", {}).get("doc_id"), "rerank_score": c.get("rerank_score")}
            for i, c in enumerate(used_chunks, start=1)
        ]

        observability.trace_chat_turn(
            session_id=session_id, question=question, answer=report.final_text,
            retrieved_chunks=used_chunks, model=model_used, latency_ms=latency_ms,
            cost_usd=cost_usd, cache_hit=False, confidence=report.confidence,
            guardrail_actions=guardrail_actions,
        )

        return GovernedChatResponse(
            answer=report.final_text, confidence=report.confidence,
            citation_coverage=report.citation_coverage, groundedness_avg=report.groundedness_avg,
            citations=citations, cache_hit=False, model_used=model_used,
            latency_ms=latency_ms, estimated_cost_usd=cost_usd,
            guardrail_flags=guardrail_actions, evaluation=evaluation,
        )


chat_orchestrator = ChatOrchestrator()
