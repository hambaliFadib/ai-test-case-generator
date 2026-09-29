"""Models and enum contracts for generated test cases."""

from dataclasses import dataclass, field
from typing import ClassVar


@dataclass(frozen=True)
class TestCase:
    """A single structured test case generated from a requirement."""

    id: str
    title: str
    category: str
    priority: str
    preconditions: list[str] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)
    expected_result: str = ""
    technique: str = ""
    requirement_ref: str = "REQ-UNTRACED"
    language_target: str = "manual"
    generated_at: str = ""
    scenario_ref: str = ""

    CATEGORIES: ClassVar[tuple[str, ...]] = (
        "positive",
        "negative",
        "boundary",
        "edge",
        "security",
    )
    PRIORITIES: ClassVar[tuple[str, ...]] = ("high", "medium", "low")
    TECHNIQUES: ClassVar[tuple[str, ...]] = (
        "EP",
        "BVA",
        "negative",
        "exploratory",
        "security",
    )
    LANGUAGES: ClassVar[tuple[str, ...]] = (
        "python",
        "javascript",
        "typescript",
        "java",
        "manual",
    )

    @classmethod
    def required_fields(cls) -> tuple[str, ...]:
        """Return the exact fields required in every generated test case."""

        return (
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

    @classmethod
    def phase3_required_fields(cls) -> tuple[str, ...]:
        """Return the strict batch-generation contract fields."""

        return (*cls.required_fields(), "scenario_ref")
