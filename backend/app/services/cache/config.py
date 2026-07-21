"""
Central config for every cache type. All TTLs overridable via env vars.
"""
import os
from dataclasses import dataclass
from enum import Enum

# pyrefly: ignore [missing-import]

class CacheType(str, Enum):
    SEMANTIC_RESPONSE = "semantic_response"
    PROMPT = "prompt"
    EMBEDDING = "embedding"
    RETRIEVAL = "retrieval"
    RERANKING = "reranking"
    DOC_FINGERPRINT = "doc_fingerprint"
    OCR = "ocr"
    EVALUATION = "evaluation"
    METADATA = "metadata"
    RESPONSE_REPAIR = "response_repair"
    GUARDRAIL_DECISION = "guardrail_decision"
    MODEL_ROUTING = "model_routing"
    CONFIGURATION = "configuration"


@dataclass(frozen=True)
class CacheSpec:
    key_prefix: str
    ttl_seconds: int
    # if True, invalidated whenever the source document/embedding changes
    doc_scoped: bool = False


def _ttl(name: str, default: int) -> int:
    return int(os.getenv(f"SENTINELAI_TTL_{name.upper()}", default))


CACHE_SPECS: dict[CacheType, CacheSpec] = {
    CacheType.SEMANTIC_RESPONSE: CacheSpec("sem:resp", _ttl("semantic_response", 3600), doc_scoped=True),
    CacheType.PROMPT: CacheSpec("prompt", _ttl("prompt", 1800)),
    CacheType.EMBEDDING: CacheSpec("embed", _ttl("embedding", 86400)),
    CacheType.RETRIEVAL: CacheSpec("retr", _ttl("retrieval", 900), doc_scoped=True),
    CacheType.RERANKING: CacheSpec("rerank", _ttl("reranking", 900), doc_scoped=True),
    CacheType.DOC_FINGERPRINT: CacheSpec("docfp", _ttl("doc_fingerprint", 0)),  # 0 = no expiry, invalidated on reingest
    CacheType.OCR: CacheSpec("ocr", _ttl("ocr", 0)),
    CacheType.EVALUATION: CacheSpec("eval", _ttl("evaluation", 604800)),
    CacheType.METADATA: CacheSpec("meta", _ttl("metadata", 3600), doc_scoped=True),
    CacheType.RESPONSE_REPAIR: CacheSpec("repair", _ttl("response_repair", 1800)),
    CacheType.GUARDRAIL_DECISION: CacheSpec("guard", _ttl("guardrail_decision", 3600)),
    CacheType.MODEL_ROUTING: CacheSpec("route", _ttl("model_routing", 300)),
    CacheType.CONFIGURATION: CacheSpec("config", _ttl("configuration", 60)),
}

REDIS_URL = os.getenv("SENTINELAI_REDIS_URL", "redis://localhost:6379/0")
EMBEDDING_DIM = int(os.getenv("SENTINELAI_EMBEDDING_DIM", 384))
SEMANTIC_SIMILARITY_THRESHOLD = float(os.getenv("SENTINELAI_SEM_SIM_THRESHOLD", 0.92))
SEMANTIC_CANDIDATE_SCAN_LIMIT = int(os.getenv("SENTINELAI_SEM_SCAN_LIMIT", 500))
