"""Deterministic bounded batch planning for Phase 2."""

from __future__ import annotations

from models.coverage_model import CoveragePlan, GenerationBatch, ScenarioIntent
from models.requirement_model import Requirement
from prompt_builder import build_batch_prompt


MAX_REQUIREMENTS_PER_BATCH = 6
MAX_SCENARIOS_PER_BATCH = 20
MAX_PROMPT_CHARS = 30_000


def plan_batches(
    requirements: list[Requirement],
    coverage_plan: CoveragePlan,
) -> list[GenerationBatch]:
    """Group planned scenarios into stable batches within all hard limits."""

    requirements_by_id = {requirement.id: requirement for requirement in requirements}
    if len(requirements_by_id) != len(requirements):
        raise ValueError("Requirements must have unique IDs before batch planning.")

    plan_by_id: dict[str, list[ScenarioIntent]] = {}
    all_scenario_ids: set[str] = set()
    for requirement_plan in coverage_plan.requirements:
        if requirement_plan.requirement_ref not in requirements_by_id:
            raise ValueError(
                f"Coverage plan references unknown requirement '{requirement_plan.requirement_ref}'."
            )
        if requirement_plan.requirement_ref in plan_by_id:
            raise ValueError(
                f"Coverage plan contains duplicate requirement '{requirement_plan.requirement_ref}'."
            )
        plan_by_id[requirement_plan.requirement_ref] = list(requirement_plan.scenarios)

    for requirement_ref, scenarios in plan_by_id.items():
        for scenario in scenarios:
            if scenario.requirement_ref != requirement_ref:
                raise ValueError(
                    f"Scenario '{scenario.id}' does not reference its planned requirement."
                )
            if scenario.id in all_scenario_ids:
                raise ValueError(f"Coverage plan contains duplicate scenario '{scenario.id}'.")
            all_scenario_ids.add(scenario.id)

    batches: list[GenerationBatch] = []
    current_requirement_ids: list[str] = []
    current_scenarios: list[ScenarioIntent] = []

    def flush() -> None:
        nonlocal current_requirement_ids, current_scenarios
        if current_scenarios:
            batches.append(
                GenerationBatch(
                    id=f"BATCH-{len(batches) + 1:03d}",
                    requirement_ids=list(current_requirement_ids),
                    scenarios=list(current_scenarios),
                )
            )
        current_requirement_ids = []
        current_scenarios = []

    for requirement in requirements:
        scenarios = plan_by_id.get(requirement.id, [])
        if not scenarios:
            continue
        _validate_scenario_ids(scenarios)

        if _fits(
            current_requirement_ids + [requirement.id],
            current_scenarios + scenarios,
            requirements_by_id,
        ):
            current_requirement_ids.append(requirement.id)
            current_scenarios.extend(scenarios)
            continue

        flush()
        if len(scenarios) <= MAX_SCENARIOS_PER_BATCH and _fits(
            [requirement.id], scenarios, requirements_by_id
        ):
            current_requirement_ids = [requirement.id]
            current_scenarios = list(scenarios)
            continue

        start = 0
        while start < len(scenarios):
            end = start
            while end < len(scenarios) and end - start < MAX_SCENARIOS_PER_BATCH:
                candidate = scenarios[start : end + 1]
                if not _fits([requirement.id], candidate, requirements_by_id):
                    break
                end += 1
            if end == start:
                raise ValueError(
                    f"Requirement '{requirement.id}' cannot fit within the prompt character limit."
                )
            chunk = scenarios[start:end]
            batches.append(
                GenerationBatch(
                    id=f"BATCH-{len(batches) + 1:03d}",
                    requirement_ids=[requirement.id],
                    scenarios=list(chunk),
                )
            )
            start = end

    flush()
    return batches


def _validate_scenario_ids(scenarios: list[ScenarioIntent]) -> None:
    ids = [scenario.id for scenario in scenarios]
    if len(ids) != len(set(ids)):
        raise ValueError("Scenario IDs must be unique within a requirement plan.")


def _fits(
    requirement_ids: list[str],
    scenarios: list[ScenarioIntent],
    requirements_by_id: dict[str, Requirement],
) -> bool:
    if len(set(requirement_ids)) > MAX_REQUIREMENTS_PER_BATCH:
        return False
    if len(scenarios) > MAX_SCENARIOS_PER_BATCH:
        return False
    selected = [requirements_by_id[requirement_id] for requirement_id in requirement_ids]
    return len(build_batch_prompt(selected, scenarios)) <= MAX_PROMPT_CHARS
