from fastapi import APIRouter

from app.schemas.chat import ChatRequest, ChatResponse, CitationInfo
from app.services.orchestrator import chat_orchestrator

router = APIRouter()


@router.post("/query", response_model=ChatResponse)
async def query(body: ChatRequest) -> ChatResponse:
    result = await chat_orchestrator.handle(
        session_id=body.session_id,
        question=body.question,
        filters=body.filters,
        run_llm_judge=body.run_llm_judge,
    )
    return ChatResponse(
        answer=result.answer,
        confidence=result.confidence,
        citation_coverage=result.citation_coverage,
        groundedness_avg=result.groundedness_avg,
        citations=[CitationInfo(**c) for c in result.citations],
        cache_hit=result.cache_hit,
        model_used=result.model_used,
        latency_ms=result.latency_ms,
        estimated_cost_usd=result.estimated_cost_usd,
        guardrail_flags=result.guardrail_flags,
        evaluation=result.evaluation,
    )
