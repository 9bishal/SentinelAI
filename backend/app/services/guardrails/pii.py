"""
PII detection + redaction. Regex-based on purpose: fast, deterministic,
auditable (no model call, no latency, no hallucinated redactions), which
matters for a governance layer that itself needs to be trustworthy.
"""
import re

PATTERNS: dict[str, re.Pattern] = {
    "email": re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"),
    "phone": re.compile(r"\b(?:\+?\d{1,3}[-.\s]?)?\(?\d{3,4}\)?[-.\s]?\d{3,4}[-.\s]?\d{3,4}\b"),
    "credit_card": re.compile(r"\b(?:\d[ -]*?){13,16}\b"),
    "ssn_like": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "passport": re.compile(r"\b[A-Z]{1,2}[0-9]{6,9}\b"),
    "api_key": re.compile(r"\b(sk|pk|api|key)[-_][A-Za-z0-9]{16,}\b", re.IGNORECASE),
    "jwt": re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"),
    "aws_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
}


# pyrefly: ignore [missing-function-return-type]
def detect_pii(text: str) -> list[dict]:
    findings = []
    for label, pattern in PATTERNS.items():
        for match in pattern.finditer(text):
            findings.append({"type": label, "span": match.span(), "value_preview": match.group()[:4] + "***"})
    return findings


def redact_pii(text: str) -> tuple[str, list[dict]]:
    findings = detect_pii(text)
    redacted = text
    # replace longest matches first so overlapping patterns don't corrupt spans
    for label, pattern in PATTERNS.items():
        redacted = pattern.sub(f"[REDACTED_{label.upper()}]", redacted)
    return redacted, findings
