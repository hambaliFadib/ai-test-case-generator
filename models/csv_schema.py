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
