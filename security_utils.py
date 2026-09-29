"""Safe redaction helpers for user-visible provider diagnostics."""

import os
import re


_BEARER_TOKEN = re.compile(r"(?i)(\bbearer\s+)[^\s,;]+")
_NAMED_SECRET = re.compile(
    r"(?i)\b(api[_-]?key|authorization|token|password|secret)\b\s*[:=]\s*[^\s,;]+"
)
_COMMON_API_KEY = re.compile(r"\b(?:sk|key)-[A-Za-z0-9_-]{8,}\b")


def redact_sensitive_detail(detail: str) -> str:
    """Remove configured secrets and common credential-shaped values."""

    redacted = detail
    for variable in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        secret = os.environ.get(variable)
        if secret:
            redacted = redacted.replace(secret, "[REDACTED]")
    redacted = _BEARER_TOKEN.sub(r"\1[REDACTED]", redacted)
    redacted = _NAMED_SECRET.sub(lambda match: f"{match.group(1)}=[REDACTED]", redacted)
    return _COMMON_API_KEY.sub("[REDACTED]", redacted)
