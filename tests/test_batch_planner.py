from batch_planner import (
    MAX_PROMPT_CHARS,
    MAX_REQUIREMENTS_PER_BATCH,
    MAX_SCENARIOS_PER_BATCH,
    plan_batches,
)
from coverage_planner import plan_coverage
from models.coverage_model import (
    CoveragePlan,
    RequirementCoveragePlan,
    ScenarioIntent,
)
from models.requirement_model import Requirement
from prompt_builder import build_batch_prompt


def requirement(requirement_id: str, statement: str = "The page displays a value.") -> Requirement:
    return Requirement(id=requirement_id, statement=statement, title=requirement_id)


def custom_scenarios(requirement_id: str, count: int) -> list[ScenarioIntent]:
    return [
        ScenarioIntent(
            id=f"{requirement_id}-S{index:02d}",
            requirement_ref=requirement_id,
            category="positive",
            technique="EP",
            intent=f"Verify source-backed scenario {index}.",
        )
        for index in range(1, count + 1)
    ]


def test_requirement_limit_is_never_exceeded() -> None:
    requirements = [requirement(f"REQ-{index:03d}") for index in range(1, 8)]
    batches = plan_batches(requirements, plan_coverage(requirements))

    assert len(batches) == 2
    assert all(len(batch.requirement_ids) <= MAX_REQUIREMENTS_PER_BATCH for batch in batches)


def test_scenario_limit_is_never_exceeded_and_oversized_requirement_is_split() -> None:
    requirement_item = requirement("REQ-001")
    scenarios = custom_scenarios("REQ-001", 25)
    plan = CoveragePlan([RequirementCoveragePlan("REQ-001", scenarios)])

    batches = plan_batches([requirement_item], plan)

    assert [len(batch.scenarios) for batch in batches] == [20, 5]
    assert all(len(batch.scenarios) <= MAX_SCENARIOS_PER_BATCH for batch in batches)
    assert [scenario.id for batch in batches for scenario in batch.scenarios] == [
        scenario.id for scenario in scenarios
    ]


def test_prompt_character_limit_causes_deterministic_split() -> None:
    requirements = [
        requirement("REQ-001", "A " + ("large requirement " * 1000)),
        requirement("REQ-002", "B " + ("large requirement " * 1000)),
    ]
    plan = plan_coverage(requirements)

    batches = plan_batches(requirements, plan)

    assert len(batches) == 2
    for batch in batches:
        selected = [item for item in requirements if item.id in batch.requirement_ids]
        assert len(build_batch_prompt(selected, batch.scenarios)) <= MAX_PROMPT_CHARS


def test_scenarios_stay_together_when_the_requirement_fits() -> None:
    requirements = [requirement("REQ-001"), requirement("REQ-002")]
    plan = CoveragePlan(
        [
            RequirementCoveragePlan("REQ-001", custom_scenarios("REQ-001", 2)),
            RequirementCoveragePlan("REQ-002", custom_scenarios("REQ-002", 2)),
        ]
    )

    batches = plan_batches(requirements, plan)

    assert len(batches) == 1
    assert batches[0].requirement_ids == ["REQ-001", "REQ-002"]


def test_batch_order_and_ids_are_deterministic() -> None:
    requirements = [requirement(f"REQ-{index:03d}") for index in range(1, 9)]
    plan = plan_coverage(requirements)

    first = plan_batches(requirements, plan)
    second = plan_batches(requirements, plan)

    assert first == second
    assert [batch.id for batch in first] == ["BATCH-001", "BATCH-002"]


def test_unknown_requirement_reference_fails() -> None:
    plan = CoveragePlan(
        [RequirementCoveragePlan("UNKNOWN", custom_scenarios("UNKNOWN", 1))]
    )

    try:
        plan_batches([requirement("REQ-001")], plan)
    except ValueError as exc:
        assert "unknown requirement" in str(exc)
    else:
        raise AssertionError("Unknown requirement reference did not fail")
