"""Models representing resolved input documents."""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ParsedInput:
    """Normalized input content produced by an input parser."""

    source_type: str
    source_name: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)
