"""
Input Guardrail Service — the first thing every request passes through.
Heuristic, regex/keyword-based detection (fast, explainable, no extra LLM
call on the hot path) for: prompt injection, jailbreak attempts, prompt
leakage attempts, and unsafe instructions. Decisions are cached (keyed by
text + PROMPT_VERSION as the "rule version") since the same adversarial
strings get retried often.
"""
import re

from app.services.cache import cache_manager
from app.services.llm.prompt_templates import PROMPT_VERSION

INJECTION_PATTERNS = [
    re.compile(r"ignore (all|any|previous|the) (previous |above )?instructions", re.I),
    re.compile(r"disregard (your|the) (system|previous) prompt", re.I),
    re.compile(r"you are now (in )?(dan|developer mode|jailbreak)", re.I),
    re.compile(r"reveal (your|the) (system|hidden) prompt", re.I),
    re.compile(r"print (your|the) (system|initial) (prompt|instructions)", re.I),
    re.compile(r"act as if you have no (restrictions|filters|guardrails)", re.I),
    re.compile(r"pretend (you are|to be) .* with no (rules|restrictions)", re.I),
]

LEAKAGE_PATTERNS = [
    re.compile(r"what (is|are) your (system|developer) (prompt|instructions)", re.I),
    re.compile(r"repeat (the|your) (words|instructions) above", re.I),
]


class InputGuardrailResult:
    def __init__(self, allowed: bool, reason: str | None = None, sanitized_text: str | None = None):
        self.allowed = allowed
        self.reason = reason
        self.sanitized_text = sanitized_text


class InputGuardrail:
    async def check(self, text: str) -> InputGuardrailResult:
        cached = await cache_manager.guardrail_decision.get_decision(text, PROMPT_VERSION, "input")
        if cached is not None:
            return InputGuardrailResult(**cached)

        result = self._evaluate(text)
        await cache_manager.guardrail_decision.set_decision(
            text, PROMPT_VERSION, "input",
            {"allowed": result.allowed, "reason": result.reason, "sanitized_text": result.sanitized_text},
        )
        return result

    def _evaluate(self, text: str) -> InputGuardrailResult:
        for pattern in INJECTION_PATTERNS:
            if pattern.search(text):
                return InputGuardrailResult(allowed=False, reason=f"prompt_injection_detected:{pattern.pattern[:40]}")

        for pattern in LEAKAGE_PATTERNS:
            if pattern.search(text):
                return InputGuardrailResult(allowed=False, reason="prompt_leakage_attempt")

        return InputGuardrailResult(allowed=True, sanitized_text=text.strip())


input_guardrail = InputGuardrail()
