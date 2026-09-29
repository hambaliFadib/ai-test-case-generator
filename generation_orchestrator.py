"""Phase 3 generation orchestration with strict completeness enforcement."""

from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

from backfill_generator import (
    MAX_BACKFILL_ATTEMPTS,
    plan_backfill_batches,
)
from batch_planner import plan_batches
from config import Settings
from coverage_auditor import audit_coverage
from coverage_planner import plan_coverage
from generation_utils import is_truncated
from llm_adapter import create_adapter
from models.coverage_model import CoveragePlan, GenerationResult, ScenarioIntent
from models.input_model import ParsedInput
from models.llm_result import LLMResult
from models.requirement_model import Requirement
from models.test_case_model import TestCase
from prompt_builder import build_batch_prompt
from requirement_analyzer import analyze_requirements
from response_parser import parse_batch_response
from validator import (
    TestCaseValidationError,
    validate_batch_traceability,
    validate_traceability,
    validate_test_cases,
)


def generate_test_suite(
    parsed_input: ParsedInput,
    settings: Settings | None,
    language_target: str = "manual",
    output_language: str = "en",
    profile: str = "balanced",
    adapter: Any | None = None,
) -> GenerationResult:
    """Generate, audit, backfill, and finalize one complete scenario suite."""

    diagnostics: list[str] = []
    llm_results: list[LLMResult] = []
    try:
        requirements = analyze_requirements(parsed_input)
    except Exception as exc:
        return _failed_result([], 0, 0, 0, 0, 0, [f"requirement analysis failed: {exc}"])

    testable_count = sum(requirement.status == "TESTABLE" for requirement in requirements)
    excluded_count = sum(requirement.status == "EXCLUDED" for requirement in requirements)
    try:
        plan = plan_coverage(requirements, profile=profile)
        scenario_count = _scenario_count(plan)
        if scenario_count == 0:
            return _failed_result(
                requirements,
                testable_count,
                excluded_count,
                0,
                0,
                0,
                ["coverage plan contains zero scenarios"],
            )
        batches = plan_batches(requirements, plan)
    except Exception as exc:
        return _failed_result(
            requirements,
            testable_count,
            excluded_count,
            0,
            0,
            0,
            [f"coverage or batch planning failed: {exc}"],
        )

    if adapter is None:
        try:
            adapter = create_adapter(settings)  # type: ignore[arg-type]
        except Exception as exc:
            return _failed_result(
                requirements,
                testable_count,
                excluded_count,
                scenario_count,
                len(batches),
                0,
                [f"adapter setup failed: {exc}"],
            )

    requirement_by_id = {requirement.id: requirement for requirement in requirements}
    merged_cases: list[TestCase] = []
    for batch in batches:
        batch_cases = _generate_batch(
            adapter,
            [requirement_by_id[requirement_id] for requirement_id in batch.requirement_ids],
            batch.scenarios,
            language_target,
            output_language,
            diagnostics,
            llm_results,
        )
        merged_cases.extend(batch_cases)

    initial_audit = audit_coverage(plan, merged_cases)
    initial_generated_count = len(merged_cases)
    initial_missing = list(initial_audit.missing_scenario_ids)
    backfill_count = 0
    current_audit = initial_audit

    planned_by_id = {
        scenario.id: scenario
        for requirement_plan in plan.requirements
        for scenario in requirement_plan.scenarios
    }
    for attempt in range(MAX_BACKFILL_ATTEMPTS):
        if not current_audit.missing_scenario_ids:
            break
        missing_scenarios = [
            planned_by_id[scenario_id]
            for scenario_id in current_audit.missing_scenario_ids
        ]
        backfill_batches = plan_backfill_batches(
            requirements,
            missing_scenarios,
        )
        for backfill_batch in backfill_batches:
            target_scenarios = backfill_batch.scenarios
            target_requirements = [
                requirement_by_id[requirement_id]
                for requirement_id in backfill_batch.requirement_ids
            ]
            diagnostics.append(
                f"backfill round {attempt + 1} {backfill_batch.id} targeting "
                + ", ".join(scenario.id for scenario in target_scenarios)
            )
            backfill_count += 1
            merged_cases.extend(
                _generate_batch(
                    adapter,
                    target_requirements,
                    target_scenarios,
                    language_target,
                    output_language,
                    diagnostics,
                    llm_results,
                )
            )
            current_audit = audit_coverage(plan, merged_cases)
            if not current_audit.missing_scenario_ids:
                break
        if not current_audit.missing_scenario_ids:
            break

    final_audit = audit_coverage(plan, merged_cases)
    ordered_cases = _order_cases(merged_cases, final_audit.planned_scenario_ids)
    final_cases = _assign_final_ids(ordered_cases)

    status = _status_for(final_audit, final_cases)
    if status == "complete":
        known_requirements = set(requirement_by_id)
        scenario_requirements = {
            scenario.id: scenario.requirement_ref
            for scenario in planned_by_id.values()
        }
        try:
            validate_traceability(
                final_cases,
                known_requirements,
                set(planned_by_id),
                scenario_requirements,
            )
            validate_test_cases(final_cases)
        except TestCaseValidationError as exc:
            diagnostics.append(f"final validation failed: {exc}")
            status = "partial" if final_cases else "failed"

    return GenerationResult(
        status=status,
        requirement_count=len(requirements),
        testable_requirement_count=testable_count,
        excluded_requirement_count=excluded_count,
        scenario_count=scenario_count,
        generated_count=len(final_cases),
        coverage_percentage=final_audit.coverage_percentage,
        batch_count=len(batches),
        backfill_count=backfill_count,
        missing_scenarios=list(final_audit.missing_scenario_ids),
        test_cases=final_cases,
        unexpected_scenarios=list(final_audit.unexpected_scenario_ids),
        duplicate_scenarios=list(final_audit.duplicate_scenario_ids),
        initial_generated_count=initial_generated_count,
        initial_missing_scenarios=initial_missing,
        diagnostics=diagnostics,
        llm_results=llm_results,
    )


def _generate_batch(
    adapter: Any,
    requirements: list[Requirement],
    scenarios: list[ScenarioIntent],
    language_target: str,
    output_language: str,
    diagnostics: list[str],
    llm_results: list[LLMResult],
) -> list[TestCase]:
    """Generate one strict batch; failures return no cases and remain auditable."""

    try:
        prompt = build_batch_prompt(
            requirements,
            scenarios,
            language_target=language_target,
            output_language=output_language,
        )
        raw_result = (
            adapter.generate_result(prompt)
            if callable(getattr(adapter, "generate_result", None))
            else adapter.generate(prompt)
        )
        result = _coerce_result(raw_result)
        llm_results.append(result)
        if is_truncated(result):
            raise ValueError(
                f"provider result was truncated (finish_reason={result.finish_reason})"
            )
        cases = parse_batch_response(result.text, scenarios)
        validate_batch_traceability(cases, scenarios)
        return cases
    except Exception as exc:
        diagnostics.append(f"batch generation failed: {exc}")
        return []


def _coerce_result(value: Any) -> LLMResult:
    if isinstance(value, LLMResult):
        return value
    if isinstance(value, str):
        return LLMResult(text=value, model="")
    raise TypeError("adapter must return LLMResult or text")


def _requirements_for_scenarios(
    scenarios: list[ScenarioIntent],
    requirement_by_id: dict[str, Requirement],
) -> list[Requirement]:
    requirement_ids: list[str] = []
    for scenario in scenarios:
        if scenario.requirement_ref not in requirement_ids:
            requirement_ids.append(scenario.requirement_ref)
    return [requirement_by_id[requirement_id] for requirement_id in requirement_ids]


def _scenario_count(plan: CoveragePlan) -> int:
    return sum(len(requirement_plan.scenarios) for requirement_plan in plan.requirements)


def _order_cases(test_cases: list[TestCase], planned_ids: list[str]) -> list[TestCase]:
    grouped: dict[str, list[TestCase]] = {}
    for test_case in test_cases:
        grouped.setdefault(test_case.scenario_ref, []).append(test_case)
    ordered: list[TestCase] = []
    for scenario_id in planned_ids:
        ordered.extend(grouped.pop(scenario_id, []))
    for scenario_id in sorted(grouped):
        ordered.extend(grouped[scenario_id])
    return ordered


def _assign_final_ids(test_cases: list[TestCase]) -> list[TestCase]:
    date_prefix = datetime.now(timezone.utc).strftime("%Y%m%d")
    generated_at = datetime.now(timezone.utc).isoformat()
    return [
        replace(
            test_case,
            id=f"TC-{date_prefix}-{index:04d}",
            generated_at=generated_at,
        )
        for index, test_case in enumerate(test_cases, start=1)
    ]


def _status_for(audit: Any, test_cases: list[TestCase]) -> str:
    if not test_cases:
        return "failed"
    if (
        audit.planned_scenario_ids
        and not audit.missing_scenario_ids
        and not audit.unexpected_scenario_ids
        and not audit.duplicate_scenario_ids
        and audit.coverage_percentage == 100.0
        and len(test_cases) == len(audit.planned_scenario_ids)
    ):
        return "complete"
    return "partial"


def _failed_result(
    requirements: list[Requirement],
    testable_count: int,
    excluded_count: int,
    scenario_count: int,
    batch_count: int,
    backfill_count: int,
    diagnostics: list[str],
) -> GenerationResult:
    return GenerationResult(
        status="failed",
        requirement_count=len(requirements),
        testable_requirement_count=testable_count,
        excluded_requirement_count=excluded_count,
        scenario_count=scenario_count,
        generated_count=0,
        coverage_percentage=0.0,
        batch_count=batch_count,
        backfill_count=backfill_count,
        diagnostics=diagnostics,
    )
