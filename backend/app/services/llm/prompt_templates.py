"""
Versioned prompt templates. Bumping PROMPT_VERSION invalidates the guardrail
decision cache (decisions are keyed by rule/prompt version) and the prompt
cache automatically, since both are keyed off this string.
"""
PROMPT_VERSION = "v1.2"

RAG_ANSWER_TEMPLATE = """You are SentinelAI's answer engine. Answer ONLY using \
the numbered context below. Every factual sentence in your answer must be \
traceable to at least one context number. If the context does not contain \
the answer, say so explicitly instead of guessing.

Context:
{context_block}

Question: {question}

Respond with plain prose. After each sentence that makes a factual claim, \
cite the supporting context number(s) in brackets, e.g. [1] or [1,3].
"""

JUDGE_TEMPLATE = """You are grading an AI-generated answer for an enterprise \
governance platform. Score each dimension from 0.0 to 1.0.

Question: {question}
Context provided to the model: {context_block}
Answer to grade: {answer}

Return ONLY a JSON object with these keys:
correctness, groundedness, safety, completeness, citation_quality
"""


def render_rag_answer_prompt(question: str, context_block: str) -> str:
    return RAG_ANSWER_TEMPLATE.format(question=question, context_block=context_block)


def render_judge_prompt(question: str, context_block: str, answer: str) -> str:
    return JUDGE_TEMPLATE.format(question=question, context_block=context_block, answer=answer)
