"""Deterministic validation for generated test cases."""

from datetime import datetime
import re

from models.test_case_model import TestCase
from models.coverage_model import ScenarioIntent


class TestCaseValidationError(ValueError):
    """Raised when one or more generated test cases violate the contract."""


_TEST_CASE_ID = re.compile(r"^TC-\d{8}-\d{4}$")


def validate_test_cases(test_cases: list[TestCase]) -> list[TestCase]:
    """Validate all test cases and return them unchanged when valid."""

    seen_ids: set[str] = set()
    for index, test_case in enumerate(test_cases):
        _validate_one(test_case, index, seen_ids)
    return test_cases


def validate_batch_traceability(
    test_cases: list[TestCase],
    expected_scenarios: list[ScenarioIntent],
) -> list[TestCase]:
    """Validate Phase 3 refs for a batch, allowing an intentionally partial response."""

    expected_by_id = {scenario.id: scenario for scenario in expected_scenarios}
    if len(expected_by_id) != len(expected_scenarios):
        raise TestCaseValidationError("Expected scenarios contain duplicate IDs.")
    validate_test_cases(test_cases)
    seen: set[str] = set()
    for index, test_case in enumerate(test_cases):
        _validate_traceability_item(test_case, index, expected_by_id, seen)
    return test_cases


def validate_traceability(
    test_cases: list[TestCase],
    known_requirement_ids: set[str] | list[str],
    planned_scenario_ids: set[str] | list[str],
    scenario_requirements: dict[str, str] | None = None,
) -> list[TestCase]:
    """Validate Phase 3 refs against the complete known requirement/scenario set."""

    known_requirements = set(known_requirement_ids)
    planned_ids = set(planned_scenario_ids)
    validate_test_cases(test_cases)
    seen: set[str] = set()
    for index, test_case in enumerate(test_cases):
        if not isinstance(test_case.scenario_ref, str) or not test_case.scenario_ref.strip() or test_case.scenario_ref == "REQ-UNTRACED":
            raise TestCaseValidationError(
                f"Item {index}: scenario_ref must be non-empty for Phase 3."
            )
        if test_case.requirement_ref == "REQ-UNTRACED" or test_case.requirement_ref not in known_requirements:
            raise TestCaseValidationError(
                f"Item {index}: unknown requirement_ref '{test_case.requirement_ref}'."
            )
        if test_case.scenario_ref not in planned_ids:
            raise TestCaseValidationError(
                f"Item {index}: unknown scenario_ref '{test_case.scenario_ref}'."
            )
        if scenario_requirements is not None:
            expected_requirement = scenario_requirements.get(test_case.scenario_ref)
            if expected_requirement != test_case.requirement_ref:
                raise TestCaseValidationError(
                    f"Item {index}: scenario_ref '{test_case.scenario_ref}' belongs to '{expected_requirement}', not '{test_case.requirement_ref}'."
                )
        if test_case.scenario_ref in seen:
            raise TestCaseValidationError(
                f"Item {index}: duplicate scenario_ref '{test_case.scenario_ref}'."
            )
        seen.add(test_case.scenario_ref)
    return test_cases


def _validate_traceability_item(
    test_case: TestCase,
    index: int,
    expected_by_id: dict[str, ScenarioIntent],
    seen: set[str],
) -> None:
    """Validate one generated case against an expected batch scenario."""

    scenario_ref = test_case.scenario_ref
    if not isinstance(scenario_ref, str) or not scenario_ref.strip() or scenario_ref == "REQ-UNTRACED":
        raise TestCaseValidationError(
            f"Item {index}: scenario_ref must be non-empty for Phase 3."
        )
    expected = expected_by_id.get(scenario_ref)
    if expected is None:
        raise TestCaseValidationError(
            f"Item {index}: unknown or unplanned scenario_ref '{scenario_ref}'."
        )
    if test_case.requirement_ref != expected.requirement_ref:
        raise TestCaseValidationError(
            f"Item {index}: scenario_ref '{scenario_ref}' belongs to '{expected.requirement_ref}', not '{test_case.requirement_ref}'."
        )
    if scenario_ref in seen:
        raise TestCaseValidationError(
            f"Item {index}: duplicate scenario_ref '{scenario_ref}'."
        )
    if test_case.requirement_ref == "REQ-UNTRACED":
        raise TestCaseValidationError(
            f"Item {index}: REQ-UNTRACED is invalid for Phase 3."
        )
    seen.add(scenario_ref)


def _validate_one(test_case: TestCase, index: int, seen_ids: set[str]) -> None:
    """Validate one test case against required fields and enum contracts."""

    if not isinstance(test_case, TestCase):
        raise TestCaseValidationError(f"Item {index}: expected a TestCase instance.")
    for field in TestCase.required_fields():
        if not hasattr(test_case, field):
            raise TestCaseValidationError(f"Item {index}: missing required field '{field}'.")
    if not _TEST_CASE_ID.fullmatch(test_case.id):
        raise TestCaseValidationError(f"Item {index}: invalid test case ID '{test_case.id}'.")
    if test_case.id in seen_ids:
        raise TestCaseValidationError(f"Item {index}: duplicate test case ID '{test_case.id}'.")
    seen_ids.add(test_case.id)
    if not isinstance(test_case.title, str) or not test_case.title.strip():
        raise TestCaseValidationError(f"Item {index}: title must be non-empty.")
    if test_case.category not in TestCase.CATEGORIES:
        raise TestCaseValidationError(f"Item {index}: invalid category '{test_case.category}'.")
    if test_case.priority not in TestCase.PRIORITIES:
        raise TestCaseValidationError(f"Item {index}: invalid priority '{test_case.priority}'.")
    if not isinstance(test_case.preconditions, list) or not all(isinstance(value, str) for value in test_case.preconditions):
        raise TestCaseValidationError(f"Item {index}: preconditions must be a list of strings.")
    if not isinstance(test_case.steps, list) or not test_case.steps or not all(isinstance(value, str) and value.strip() for value in test_case.steps):
        raise TestCaseValidationError(f"Item {index}: steps must be a non-empty list of non-empty strings.")
    if not isinstance(test_case.expected_result, str) or not test_case.expected_result.strip():
        raise TestCaseValidationError(f"Item {index}: expected_result must be non-empty.")
    if test_case.technique not in TestCase.TECHNIQUES:
        raise TestCaseValidationError(f"Item {index}: invalid technique '{test_case.technique}'.")
    if not isinstance(test_case.requirement_ref, str) or not test_case.requirement_ref.strip():
        raise TestCaseValidationError(f"Item {index}: requirement_ref must be non-empty.")
    if test_case.language_target not in TestCase.LANGUAGES:
        raise TestCaseValidationError(f"Item {index}: invalid language_target '{test_case.language_target}'.")
    if not isinstance(test_case.generated_at, str) or not test_case.generated_at.strip():
        raise TestCaseValidationError(f"Item {index}: generated_at must be non-empty.")
    try:
        datetime.fromisoformat(test_case.generated_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise TestCaseValidationError(f"Item {index}: generated_at must be ISO 8601.") from exc
