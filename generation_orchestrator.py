"""Phase 3 generation orchestration with strict completeness enforcement."""

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
import hashlib
import re
import unicodedata
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
from llm_adapter import LLMError, create_adapter
from models.coverage_model import BatchDiagnostic, CoveragePlan, EvidenceAtom, GenerationResult, ScenarioIntent, ScenarioRejection
from models.input_model import ParsedInput
from models.llm_result import LLMResult
from models.requirement_model import Requirement
from models.test_case_model import TestCase
from prompt_builder import build_batch_prompt
from profiles import DEFAULT_PROFILE, resolve_profile
from requirement_analyzer import analyze_requirements
from response_parser import ParseError, ValidationError, parse_batch_response_result
from validator import (
    TestCaseValidationError,
    validate_batch_traceability,
    validate_traceability,
    validate_test_cases,
)


def _normalize_case_content(value: str) -> str:
    """Normalize text for conservative duplicate-output detection."""
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"[\W_]+", " ", normalized, flags=re.UNICODE).strip()


def _case_content_fingerprint(test_case: TestCase) -> tuple:
    """Identify duplicate operational content within one requirement.

    Titles and trace IDs are excluded so cosmetic title rewrites or different
    planned scenario refs do not disguise cases with identical execution content.
    """
    return (
        test_case.requirement_ref.strip().casefold(),
        tuple(_normalize_case_content(value) for value in test_case.preconditions),
        tuple(_normalize_case_content(value) for value in test_case.steps),
        _normalize_case_content(test_case.expected_result),
    )


def _retain_unique_content(
    candidates: list[TestCase],
    existing: list[TestCase],
    diagnostics: list[str],
) -> list[TestCase]:
    """Reject duplicate execution content so its planned scenario can be backfilled."""
    seen = {
        _case_content_fingerprint(case)
        for case in existing
        if case.scenario_ref.strip()
    }
    retained: list[TestCase] = []
    for case in candidates:
        if not case.scenario_ref.strip():
            retained.append(case)
            continue
        fingerprint = _case_content_fingerprint(case)
        if fingerprint in seen:
            diagnostics.append(
                f"duplicate generated content rejected for {case.scenario_ref}; "
                "an equivalent requirement-local test case already exists"
            )
            continue
        seen.add(fingerprint)
        retained.append(case)
    return retained


def generate_test_suite(
    parsed_input: ParsedInput,
    settings: Settings | None,
    language_target: str = "manual",
    output_language: str = "en",
    profile: str = DEFAULT_PROFILE,
    adapter: Any | None = None,
) -> GenerationResult:
    """Generate, audit, backfill, and finalize one complete scenario suite."""

    diagnostics: list[str] = []
    llm_results: list[LLMResult] = []
    batch_diagnostics: list[BatchDiagnostic] = []
    call_index = 0
    try:
        resolved_profile = resolve_profile(profile)
    except Exception as exc:
        return _failed_result([], 0, 0, 0, 0, 0, [f"profile resolution failed: {exc}"])
    try:
        requirements = analyze_requirements(parsed_input)
    except Exception as exc:
        return _failed_result([], 0, 0, 0, 0, 0, [f"requirement analysis failed: {exc}"])

    testable_count = sum(requirement.status == "TESTABLE" for requirement in requirements)
    excluded_count = sum(requirement.status == "EXCLUDED" for requirement in requirements)
    try:
        plan = plan_coverage(requirements, profile=resolved_profile)
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
    initial_wave_provider_unavailable = True
    for batch in batches:
        call_index += 1
        before = audit_coverage(plan, merged_cases)
        outcome = _generate_batch(
            adapter,
            [requirement_by_id[requirement_id] for requirement_id in batch.requirement_ids],
            batch.scenarios,
            language_target,
            output_language,
            diagnostics,
            llm_results,
            evidence_atoms=plan.evidence_atoms,
            existing_cases=merged_cases,
            call_index=call_index,
            phase="initial",
            round_number=None,
            batch_id=batch.id,
            coverage_before=before,
        )
        merged_cases.extend(outcome.test_cases)
        after = audit_coverage(plan, merged_cases)
        if outcome.diagnostic is not None:
            batch_diagnostics.append(replace(
                outcome.diagnostic,
                coverage_after_count=len(after.generated_scenario_ids),
                missing_after=list(after.missing_scenario_ids),
            ))
        if not outcome.provider_unavailable:
            initial_wave_provider_unavailable = False

    initial_audit = audit_coverage(plan, merged_cases)
    initial_generated_count = len(merged_cases)
    initial_missing = list(initial_audit.missing_scenario_ids)
    backfill_count = 0
    current_audit = initial_audit
    attempted_backfill_prompts: dict[str, int] = {}

    planned_by_id = {
        scenario.id: scenario
        for requirement_plan in plan.requirements
        for scenario in requirement_plan.scenarios
    }
    # Persistent provider unavailability cannot be recovered by retrying
    # the same batches in this run; skip backfill entirely and keep the
    # planned references visible as missing.
    if initial_wave_provider_unavailable and batches:
        diagnostics.append(
            "backfill skipped: every initial batch failed with provider "
            "unavailability"
        )
    else:
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
            round_provider_unavailable = True
            round_skipped_no_progress = False
            for backfill_batch in backfill_batches:
                target_scenarios = backfill_batch.scenarios
                target_requirements = [
                    requirement_by_id[requirement_id]
                    for requirement_id in backfill_batch.requirement_ids
                ]
                before = audit_coverage(plan, merged_cases)
                prompt = build_batch_prompt(
                    target_requirements,
                    target_scenarios,
                    language_target=language_target,
                    output_language=output_language,
                    evidence_atoms=plan.evidence_atoms,
                )
                prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
                previous_coverage = attempted_backfill_prompts.get(prompt_hash)
                if previous_coverage is not None and len(before.generated_scenario_ids) <= previous_coverage:
                    round_skipped_no_progress = True
                    diagnostics.append(
                        f"backfill skipped: repeated prompt without coverage progress "
                        f"(round {attempt + 1}, {backfill_batch.id})"
                    )
                    batch_diagnostics.append(BatchDiagnostic(
                        call_index=call_index + 1,
                        phase="backfill",
                        round_number=attempt + 1,
                        batch_id=backfill_batch.id,
                        target_scenario_ids=[scenario.id for scenario in target_scenarios],
                        rejected_scenarios=[
                            ScenarioRejection(scenario.id, "backfill_gate", "repeated_prompt_no_progress")
                            for scenario in target_scenarios
                        ],
                        outcome="skipped_no_progress",
                        prompt_sha256=prompt_hash,
                        error_code="repeated_prompt_no_progress",
                        coverage_before_count=len(before.generated_scenario_ids),
                        coverage_after_count=len(before.generated_scenario_ids),
                        missing_before=list(before.missing_scenario_ids),
                        missing_after=list(before.missing_scenario_ids),
                    ))
                    continue
                attempted_backfill_prompts[prompt_hash] = len(before.generated_scenario_ids)
                diagnostics.append(
                    f"backfill round {attempt + 1} {backfill_batch.id} targeting "
                    + ", ".join(scenario.id for scenario in target_scenarios)
                )
                backfill_count += 1
                call_index += 1
                outcome = _generate_batch(
                    adapter,
                    target_requirements,
                    target_scenarios,
                    language_target,
                    output_language,
                    diagnostics,
                    llm_results,
                    evidence_atoms=plan.evidence_atoms,
                    existing_cases=merged_cases,
                    call_index=call_index,
                    phase="backfill",
                    round_number=attempt + 1,
                    batch_id=backfill_batch.id,
                    coverage_before=before,
                )
                merged_cases.extend(outcome.test_cases)
                if not outcome.provider_unavailable:
                    round_provider_unavailable = False
                current_audit = audit_coverage(plan, merged_cases)
                if outcome.diagnostic is not None:
                    batch_diagnostics.append(replace(
                        outcome.diagnostic,
                        coverage_after_count=len(current_audit.generated_scenario_ids),
                        missing_after=list(current_audit.missing_scenario_ids),
                    ))
                if not current_audit.missing_scenario_ids:
                    break
            if not current_audit.missing_scenario_ids:
                break
            if round_provider_unavailable and backfill_batches:
                if round_skipped_no_progress:
                    diagnostics.append(
                        f"backfill stopped after round {attempt + 1}: repeated prompt "
                        "produced no new coverage"
                    )
                    break
                diagnostics.append(
                    f"backfill stopped after round {attempt + 1}: every batch "
                    "failed with provider unavailability"
                )
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
        batch_diagnostics=batch_diagnostics,
        unresolved_baseline=(
            [] if status == "failed" else list(plan.unresolved_baseline)
        ),
    )


@dataclass(frozen=True)
class BatchOutcome:
    """Result of one batch attempt, including provider-failure classification."""

    test_cases: list[TestCase] = field(default_factory=list)
    provider_unavailable: bool = False
    provider_error: bool = False
    diagnostic: BatchDiagnostic | None = None


def _generate_batch(
    adapter: Any,
    requirements: list[Requirement],
    scenarios: list[ScenarioIntent],
    language_target: str,
    output_language: str,
    diagnostics: list[str],
    llm_results: list[LLMResult],
    evidence_atoms: list[EvidenceAtom] | None = None,
    existing_cases: list[TestCase] | None = None,
    *,
    call_index: int = 1,
    phase: str = "initial",
    round_number: int | None = None,
    batch_id: str = "BATCH-UNKNOWN",
    coverage_before: Any | None = None,
) -> BatchOutcome:
    """Generate one batch and return privacy-safe, scenario-level provenance."""

    target_ids = [scenario.id for scenario in scenarios]
    prompt_hash: str | None = None
    result: LLMResult | None = None
    rejected: list[ScenarioRejection] = []
    duplicate_ids: list[str] = []
    accepted_ids: list[str] = []
    provider_status: int | None = None
    provider_unavailable = False
    error_code: str | None = None
    error_type: str | None = None
    outcome_name = "unknown"

    def diagnostic() -> BatchDiagnostic:
        return BatchDiagnostic(
            call_index=call_index,
            phase=phase,
            round_number=round_number,
            batch_id=batch_id,
            target_scenario_ids=target_ids,
            accepted_scenario_ids=accepted_ids,
            rejected_scenarios=rejected,
            outcome=outcome_name,
            prompt_sha256=prompt_hash,
            finish_reason=result.finish_reason if result else None,
            input_tokens=result.input_tokens if result else None,
            output_tokens=result.output_tokens if result else None,
            provider_status_code=provider_status,
            provider_unavailable=provider_unavailable,
            error_code=error_code,
            error_type=error_type,
            coverage_before_count=len(coverage_before.generated_scenario_ids) if coverage_before else len(existing_cases or []),
            missing_before=list(coverage_before.missing_scenario_ids) if coverage_before else target_ids,
        )

    try:
        prompt = build_batch_prompt(
            requirements,
            scenarios,
            language_target=language_target,
            output_language=output_language,
            evidence_atoms=evidence_atoms,
        )
        prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        raw_result = (
            adapter.generate_result(prompt)
            if callable(getattr(adapter, "generate_result", None))
            else adapter.generate(prompt)
        )
        result = _coerce_result(raw_result)
        llm_results.append(result)
        if is_truncated(result):
            outcome_name = "rejected_truncated"
            error_code = "provider_output_truncated"
            error_type = "truncation"
            rejected = [ScenarioRejection(item, "provider", error_code) for item in target_ids]
            diagnostics.append("batch generation failed: provider result was truncated")
            return BatchOutcome(diagnostic=diagnostic())
        try:
            parsed = parse_batch_response_result(
                result.text,
                scenarios,
                language_target=language_target,
                evidence_atoms=evidence_atoms,
            )
        except ParseError as exc:
            outcome_name = "rejected_parse"
            error_code = "invalid_json"
            error_type = type(exc).__name__
            rejected = [ScenarioRejection(item, "parse", error_code) for item in target_ids]
            diagnostics.append(f"batch generation failed: {type(exc).__name__}")
            return BatchOutcome(diagnostic=diagnostic())
        except ValidationError as exc:
            outcome_name = "rejected_traceability"
            error_code = "batch_traceability_invalid"
            error_type = type(exc).__name__
            rejected = [ScenarioRejection(item, "traceability", error_code) for item in target_ids]
            diagnostics.append(f"batch generation failed: {type(exc).__name__}")
            return BatchOutcome(diagnostic=diagnostic())

        for scenario_id in parsed.invalid_scenario_ids:
            rejected.append(ScenarioRejection(scenario_id, "content_validation", "semantic_or_contract_rejection"))
        diagnostics.extend(f"batch item rejected: {error}" for error in parsed.item_errors)
        validate_batch_traceability(parsed.test_cases, scenarios)
        unique_cases = _retain_unique_content(
            parsed.test_cases,
            existing_cases or [],
            diagnostics,
        )
        retained_ids = {case.scenario_ref for case in unique_cases}
        parsed_ids = {case.scenario_ref for case in parsed.test_cases}
        for scenario_id in sorted(parsed_ids - retained_ids):
            duplicate_ids.append(scenario_id)
            rejected.append(ScenarioRejection(scenario_id, "deduplication", "duplicate_operational_content"))
        accepted_ids = [case.scenario_ref for case in unique_cases]
        returned_ids = parsed_ids | set(parsed.invalid_scenario_ids)
        for scenario_id in target_ids:
            if scenario_id not in returned_ids:
                rejected.append(ScenarioRejection(scenario_id, "provider_response", "scenario_omitted"))
        outcome_name = "accepted" if not rejected else ("partial_accepted" if accepted_ids else "rejected_content")
        return BatchOutcome(test_cases=unique_cases, diagnostic=diagnostic())
    except LLMError as exc:
        provider_status = exc.status_code
        provider_unavailable = bool(exc.provider_unavailable)
        outcome_name = "provider_unavailable" if provider_unavailable else "provider_error"
        error_code = "provider_http_error" if provider_status is not None else "provider_transport_error"
        error_type = type(exc).__name__
        rejected = [ScenarioRejection(item, "provider", error_code) for item in target_ids]
        diagnostics.append("batch generation failed: provider unavailable" if provider_unavailable else f"batch generation failed: {type(exc).__name__}")
        return BatchOutcome(
            provider_unavailable=provider_unavailable,
            provider_error=True,
            diagnostic=diagnostic(),
        )
    except Exception as exc:
        outcome_name = "rejected_batch"
        error_code = "batch_processing_error"
        error_type = type(exc).__name__
        rejected = [ScenarioRejection(item, "batch", error_code) for item in target_ids]
        diagnostics.append(f"batch generation failed: {type(exc).__name__}")
        return BatchOutcome(diagnostic=diagnostic())


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
