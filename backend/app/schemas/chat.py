from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    session_id: str = Field(default="default")
    question: str
    filters: dict | None = None
    run_llm_judge: bool = False  # sampled evaluation is opt-in per-request; wire a % sampler for prod


class CitationInfo(BaseModel):
    index: int
    chunk_id: str
    doc_id: str | None = None
    rerank_score: float | None = None


class ChatResponse(BaseModel):
    answer: str
    confidence: float
    citation_coverage: float
    groundedness_avg: float
    citations: list[CitationInfo]
    cache_hit: bool
    model_used: str
    latency_ms: int
    estimated_cost_usd: float
    guardrail_flags: list[str] = []
    evaluation: dict | None = None
