"""Small provider-independent helpers for Phase 3 generation."""

from models.llm_result import LLMResult


_TRUNCATION_REASONS = {
    "length",
    "max_tokens",
    "max_output_tokens",
}


def is_truncated(result: LLMResult) -> bool:
    """Return whether a provider explicitly stopped for an output-length limit."""

    if not isinstance(result, LLMResult) or not result.finish_reason:
        return False
    normalized = result.finish_reason.strip().lower().replace("-", "_").replace(" ", "_")
    return normalized in _TRUNCATION_REASONS
