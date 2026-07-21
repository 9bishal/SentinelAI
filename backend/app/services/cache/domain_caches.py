"""
Lightweight caches that only need deterministic key -> JSON value semantics.
Each wraps RedisCacheBase with a domain-specific key builder so callers never
construct raw keys by hand.
"""
from typing import Optional

from .base import RedisCacheBase, make_hash
from .config import CacheType


class PromptCache(RedisCacheBase):
    """Caches fully-rendered prompt templates (post variable substitution)."""
    def __init__(self):
        super().__init__(CacheType.PROMPT)

    async def get_rendered(self, template_id: str, variables: dict) -> Optional[str]:
        cached = await self.get(make_hash(template_id, variables))
        return cached["rendered"] if cached else None

    async def set_rendered(self, template_id: str, variables: dict, rendered: str) -> None:
        await self.set(make_hash(template_id, variables), {"rendered": rendered})


class RetrievalCache(RedisCacheBase):
    """Caches raw hybrid-retrieval results (pre-rerank) per query+filters."""
    def __init__(self):
        super().__init__(CacheType.RETRIEVAL)

    async def get_results(self, query: str, filters: dict) -> Optional[list[dict]]:
        cached = await self.get(make_hash(query, filters))
        return cached["chunks"] if cached else None

    async def set_results(self, query: str, filters: dict, chunks: list[dict], doc_ids: list[str]) -> None:
        await self.set(make_hash(query, filters), {"chunks": chunks}, doc_ids=doc_ids)


class RerankingCache(RedisCacheBase):
    """Caches cross-encoder rerank scores for a (query, chunk_set) pair."""
    def __init__(self):
        super().__init__(CacheType.RERANKING)

    async def get_scores(self, query: str, chunk_ids: list[str]) -> Optional[list[float]]:
        cached = await self.get(make_hash(query, sorted(chunk_ids)))
        return cached["scores"] if cached else None

    async def set_scores(self, query: str, chunk_ids: list[str], scores: list[float], doc_ids: list[str]) -> None:
        await self.set(make_hash(query, sorted(chunk_ids)), {"scores": scores}, doc_ids=doc_ids)


class DocumentFingerprintCache(RedisCacheBase):
    """Stores a content hash per document so re-uploads of identical files
    skip the entire ingestion pipeline (OCR, chunk, embed)."""
    def __init__(self):
        super().__init__(CacheType.DOC_FINGERPRINT)

    async def get_fingerprint(self, doc_id: str) -> Optional[str]:
        cached = await self.get(doc_id)
        return cached["fingerprint"] if cached else None

    async def set_fingerprint(self, doc_id: str, content_hash: str) -> None:
        await self.set(doc_id, {"fingerprint": content_hash})

    async def is_duplicate(self, doc_id: str, content_hash: str) -> bool:
        existing = await self.get_fingerprint(doc_id)
        return existing == content_hash


class OCRCache(RedisCacheBase):
    """Caches OCR output per page image hash — OCR is the slowest ingestion step."""
    def __init__(self):
        super().__init__(CacheType.OCR)

    async def get_text(self, page_image_hash: str) -> Optional[str]:
        cached = await self.get(page_image_hash)
        return cached["text"] if cached else None

    async def set_text(self, page_image_hash: str, text: str) -> None:
        await self.set(page_image_hash, {"text": text})


class EvaluationCache(RedisCacheBase):
    """Caches RAGAS / LLM-as-judge scores for a given (query, response, context) triple."""
    def __init__(self):
        super().__init__(CacheType.EVALUATION)

    async def get_scores(self, query: str, response: str, context_hash: str) -> Optional[dict]:
        return await self.get(make_hash(query, response, context_hash))

    async def set_scores(self, query: str, response: str, context_hash: str, scores: dict) -> None:
        await self.set(make_hash(query, response, context_hash), scores)


class MetadataCache(RedisCacheBase):
    """Caches document/chunk metadata lookups (author, version, ACL tags)."""
    def __init__(self):
        super().__init__(CacheType.METADATA)

    async def get_metadata(self, doc_id: str) -> Optional[dict]:
        return await self.get(doc_id)

    async def set_metadata(self, doc_id: str, metadata: dict) -> None:
        await self.set(doc_id, metadata, doc_ids=[doc_id])


class ResponseRepairCache(RedisCacheBase):
    """Caches repaired/regenerated response segments so identical unsupported
    claims aren't re-repaired on every request."""
    def __init__(self):
        super().__init__(CacheType.RESPONSE_REPAIR)

    async def get_repair(self, original_segment: str, violation_type: str) -> Optional[str]:
        cached = await self.get(make_hash(original_segment, violation_type))
        return cached["repaired"] if cached else None

    async def set_repair(self, original_segment: str, violation_type: str, repaired: str) -> None:
        await self.set(make_hash(original_segment, violation_type), {"repaired": repaired})


class GuardrailDecisionCache(RedisCacheBase):
    """Caches input/output guardrail verdicts (injection check, PII scan
    result, policy check) for identical text, keyed by guardrail rule version
    so a rule change auto-invalidates via key namespace, not a scan."""
    def __init__(self):
        super().__init__(CacheType.GUARDRAIL_DECISION)

    async def get_decision(self, text: str, rule_version: str, stage: str) -> Optional[dict]:
        return await self.get(make_hash(text, rule_version, stage))

    async def set_decision(self, text: str, rule_version: str, stage: str, decision: dict) -> None:
        await self.set(make_hash(text, rule_version, stage), decision)


class ModelRoutingCache(RedisCacheBase):
    """Short-TTL cache for model-tier routing decisions (which model handles
    this query class), so routing logic isn't recomputed every request."""
    def __init__(self):
        super().__init__(CacheType.MODEL_ROUTING)

    async def get_route(self, query_class: str) -> Optional[dict]:
        return await self.get(query_class)

    async def set_route(self, query_class: str, route: dict) -> None:
        await self.set(query_class, route)


class ConfigurationCache(RedisCacheBase):
    """Very short TTL cache for policy/config lookups (e.g. company PII
    policy, active model tier config) to avoid hitting Postgres on every
    request while still picking up admin changes within ~60s."""
    def __init__(self):
        super().__init__(CacheType.CONFIGURATION)

    async def get_config(self, config_key: str) -> Optional[dict]:
        return await self.get(config_key)

    async def set_config(self, config_key: str, value: dict) -> None:
        await self.set(config_key, value)
