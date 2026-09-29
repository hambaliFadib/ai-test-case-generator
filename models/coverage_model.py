"""Immutable models used by Phase 2 coverage and batch planning."""

from dataclasses import dataclass, field

from models.llm_result import LLMResult
from models.test_case_model import TestCase


SCENARIO_CATEGORIES: tuple[str, ...] = (
    "positive",
    "negative",
    "boundary",
    "edge",
    "security",
)
SCENARIO_TECHNIQUES: tuple[str, ...] = (
    "EP",
    "BVA",
    "negative",
    "exploratory",
    "security",
)


@dataclass(frozen=True)
class ScenarioIntent:
    """One deterministic, source-backed scenario expected to become one case."""

    id: str
    requirement_ref: str
    category: str
    technique: str
    intent: str
    priority: str = "medium"


@dataclass(frozen=True)
class RequirementCoveragePlan:
    """The ordered scenarios planned for one requirement."""

    requirement_ref: str
    scenarios: list[ScenarioIntent] = field(default_factory=list)


@dataclass(frozen=True)
class CoveragePlan:
    """The ordered coverage plan for all analyzed requirements."""

    requirements: list[RequirementCoveragePlan] = field(default_factory=list)


@dataclass(frozen=True)
class GenerationBatch:
    """A bounded, ordered group of requirements and scenario intents."""

    id: str
    requirement_ids: list[str] = field(default_factory=list)
    scenarios: list[ScenarioIntent] = field(default_factory=list)


@dataclass(frozen=True)
class CoverageAudit:
    """Deterministic comparison between planned and generated scenario refs."""

    planned_scenario_ids: list[str] = field(default_factory=list)
    generated_scenario_ids: list[str] = field(default_factory=list)
    missing_scenario_ids: list[str] = field(default_factory=list)
    unexpected_scenario_ids: list[str] = field(default_factory=list)
    duplicate_scenario_ids: list[str] = field(default_factory=list)
    coverage_percentage: float = 0.0


@dataclass(frozen=True)
class GenerationResult:
    """Final Phase 3 generation outcome and completeness evidence."""

    status: str
    requirement_count: int
    testable_requirement_count: int
    excluded_requirement_count: int
    scenario_count: int
    generated_count: int
    coverage_percentage: float
    batch_count: int
    backfill_count: int
    missing_scenarios: list[str] = field(default_factory=list)
    test_cases: list[TestCase] = field(default_factory=list)
    unexpected_scenarios: list[str] = field(default_factory=list)
    duplicate_scenarios: list[str] = field(default_factory=list)
    initial_generated_count: int = 0
    initial_missing_scenarios: list[str] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)
    llm_results: list[LLMResult] = field(default_factory=list)
