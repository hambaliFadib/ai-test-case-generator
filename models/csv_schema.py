"""CSV export column contract."""

from typing import Final


CSV_COLUMNS: Final[tuple[str, ...]] = (
    "id",
    "title",
    "category",
    "priority",
    "preconditions",
    "steps",
    "expected_result",
    "technique",
    "requirement_ref",
    "language_target",
    "generated_at",
)

# Production v1.3 export keeps the legacy columns and adds the scenario-level
# traceability needed by the completeness engine.
TRACEABLE_CSV_COLUMNS: Final[tuple[str, ...]] = (
    "id",
    "title",
    "category",
    "priority",
    "preconditions",
    "steps",
    "expected_result",
    "technique",
    "requirement_ref",
    "scenario_ref",
    "language_target",
    "generated_at",
)
