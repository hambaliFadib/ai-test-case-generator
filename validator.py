"""Deterministic validation for generated test cases."""

from datetime import datetime
import re

from models.test_case_model import TestCase


class TestCaseValidationError(ValueError):
    """Raised when one or more generated test cases violate the contract."""


_TEST_CASE_ID = re.compile(r"^TC-\d{8}-\d{4}$")


def validate_test_cases(test_cases: list[TestCase]) -> list[TestCase]:
    """Validate all test cases and return them unchanged when valid."""

    seen_ids: set[str] = set()
    for index, test_case in enumerate(test_cases):
        _validate_one(test_case, index, seen_ids)
    return test_cases


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
