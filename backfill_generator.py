"""Deterministic limits for targeted Phase 3 scenario backfill."""

from batch_planner import MAX_PROMPT_CHARS, MAX_REQUIREMENTS_PER_BATCH
from models.coverage_model import GenerationBatch, ScenarioIntent
from models.requirement_model import Requirement
from prompt_builder import build_batch_prompt


MAX_BACKFILL_ATTEMPTS = 2
MAX_BACKFILL_SCENARIOS_PER_BATCH = 8


def chunk_scenarios(
    scenarios: list[ScenarioIntent],
    chunk_size: int = MAX_BACKFILL_SCENARIOS_PER_BATCH,
) -> list[list[ScenarioIntent]]:
    """Split missing scenarios into small, ordered backfill requests."""

    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than zero")
    return [
        scenarios[start : start + chunk_size]
        for start in range(0, len(scenarios), chunk_size)
    ]


def plan_backfill_batches(
    requirements: list[Requirement],
    scenarios: list[ScenarioIntent],
) -> list[GenerationBatch]:
    """Plan small backfill batches within all normal Phase 2 hard limits."""

    requirements_by_id = {requirement.id: requirement for requirement in requirements}
    batches: list[GenerationBatch] = []
    current_scenarios: list[ScenarioIntent] = []
    current_requirement_ids: list[str] = []

    def fits(candidate_scenarios: list[ScenarioIntent], candidate_ids: list[str]) -> bool:
        if len(candidate_scenarios) > MAX_BACKFILL_SCENARIOS_PER_BATCH:
            return False
        if len(candidate_ids) > MAX_REQUIREMENTS_PER_BATCH:
            return False
        selected = [requirements_by_id[requirement_id] for requirement_id in candidate_ids]
        return len(build_batch_prompt(selected, candidate_scenarios, for_sizing=True)) <= MAX_PROMPT_CHARS

    def flush() -> None:
        nonlocal current_scenarios, current_requirement_ids
        if current_scenarios:
            batches.append(
                GenerationBatch(
                    id=f"BACKFILL-BATCH-{len(batches) + 1:03d}",
                    requirement_ids=list(current_requirement_ids),
                    scenarios=list(current_scenarios),
                )
            )
        current_scenarios = []
        current_requirement_ids = []

    for scenario in scenarios:
        if scenario.requirement_ref not in requirements_by_id:
            raise ValueError(
                f"Backfill scenario references unknown requirement '{scenario.requirement_ref}'."
            )
        candidate_ids = list(current_requirement_ids)
        if scenario.requirement_ref not in candidate_ids:
            candidate_ids.append(scenario.requirement_ref)
        candidate_scenarios = [*current_scenarios, scenario]
        if current_scenarios and not fits(candidate_scenarios, candidate_ids):
            flush()
            candidate_ids = [scenario.requirement_ref]
            candidate_scenarios = [scenario]
        if not fits(candidate_scenarios, candidate_ids):
            raise ValueError(
                f"Backfill scenario '{scenario.id}' cannot fit within the prompt limits."
            )
        current_requirement_ids = candidate_ids
        current_scenarios = candidate_scenarios
    flush()
    return batches
