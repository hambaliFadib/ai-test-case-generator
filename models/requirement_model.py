"""Models representing testable requirements."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Requirement:
    """A normalized, traceable requirement extracted from source content."""

    id: str
    statement: str
    acceptance_criteria: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    source_section: str = ""
    has_numeric_or_date_field: bool = False
