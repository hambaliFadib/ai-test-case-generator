"""Provider-neutral result metadata returned by Phase 3 adapters."""

from dataclasses import dataclass


@dataclass(frozen=True)
class LLMResult:
    """Text plus provider metadata, when the provider exposes it."""

    text: str
    model: str
    finish_reason: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
