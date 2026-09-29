"""Models representing normalized, traceable requirements."""

from dataclasses import dataclass, field


REQUIREMENT_STATUSES: tuple[str, ...] = (
    "TESTABLE",
    "INFORMATIONAL",
    "EXCLUDED",
    "UNRESOLVED",
)


@dataclass(frozen=True)
class Requirement:
    """A normalized, traceable requirement extracted from source content."""

    # Keep legacy fields in their original positional order.
    id: str
    statement: str
    acceptance_criteria: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    source_section: str = ""
    has_numeric_or_date_field: bool = False

    # v1.3 structured-requirement metadata.
    title: str = ""
    details: list[str] = field(default_factory=list)
    status: str = "TESTABLE"
    tags: list[str] = field(default_factory=list)
    numeric_limits: list[str] = field(default_factory=list)
