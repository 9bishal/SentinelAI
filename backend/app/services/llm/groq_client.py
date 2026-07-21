"""
LLM Gateway — the only place in the codebase that talks to Groq directly.

Provides:
  - model tiering (fast/cheap vs strong model, picked by ModelRoutingCache)
  - retry with backoff (SDK's built-in max_retries + our own timeout wrapper)
  - streaming and non-streaming generation
  - token + cost estimation (Groq pricing is per-model, kept in PRICING below)
  - prompt-cache and semantic-cache lookups happen ABOVE this layer (in the
    chat orchestrator), this class only ever calls the real model.
"""
import time
from dataclasses import dataclass
from typing import AsyncIterator, Optional

from groq import AsyncGroq

from app.core.config import get_settings

settings = get_settings()

# USD per 1M tokens (input, output) — update as Groq pricing changes.
PRICING = {
    "llama-3.1-8b-instant": (0.05, 0.08),
    "llama-3.3-70b-versatile": (0.59, 0.79),
}


@dataclass
class GenerationResult:
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_seconds: float
    estimated_cost_usd: float


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    in_price, out_price = PRICING.get(model, (0.0, 0.0))
    return (input_tokens / 1_000_000) * in_price + (output_tokens / 1_000_000) * out_price


class GroqGateway:
    def __init__(self):
        self._client = AsyncGroq(
            api_key=settings.groq_api_key,
            timeout=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
        )

    async def generate(
        self,
        messages: list[dict],
        model: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ) -> GenerationResult:
        model = model or settings.groq_model_fast
        start = time.perf_counter()
        response = await self._client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        latency = time.perf_counter() - start
        usage = response.usage
        return GenerationResult(
            text=response.choices[0].message.content or "",
            model=model,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            latency_seconds=latency,
            estimated_cost_usd=estimate_cost(
                model, usage.prompt_tokens if usage else 0, usage.completion_tokens if usage else 0
            ),
        )

    async def generate_with_fallback(
        self,
        messages: list[dict],
        primary_model: Optional[str] = None,
        fallback_model: Optional[str] = None,
        **kwargs,
    ) -> GenerationResult:
        """Try the primary (usually cheaper/faster) model; on any failure —
        timeout, rate limit, 5xx — fall back to the stronger model once
        before giving up. Keeps the platform answering during partial Groq
        degradation instead of surfacing a raw error to the user."""
        primary_model = primary_model or settings.groq_model_fast
        fallback_model = fallback_model or settings.groq_model_strong
        try:
            return await self.generate(messages, model=primary_model, **kwargs)
        except Exception:
            return await self.generate(messages, model=fallback_model, **kwargs)

    async def stream(
        self,
        messages: list[dict],
        model: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ) -> AsyncIterator[str]:
        model = model or settings.groq_model_fast
        stream = await self._client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta


groq_gateway = GroqGateway()
