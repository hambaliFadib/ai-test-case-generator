"""Defensive parsing and contract validation of LLM JSON responses."""

from datetime import datetime, timezone
import json
import re
from typing import Any

from models.coverage_model import ScenarioIntent
from models.test_case_model import TestCase


class ParseError(ValueError):
    """Raised when an LLM response is not valid JSON."""


class ValidationError(ValueError):
    """Raised when a response item violates the test-case contract."""

    def __init__(self, reason: str, item_index: int | None = None) -> None:
        """Create an error with an optional zero-based response item index."""

        self.item_index = item_index
        prefix = f"Item {item_index}: " if item_index is not None else "Response: "
        super().__init__(prefix + reason)


def parse_response(raw_response: str) -> list[TestCase]:
    """Parse, validate, and materialize every test case in an LLM response."""

    if not isinstance(raw_response, str) or not raw_response.strip():
        raise ParseError(f"Could not parse empty LLM response. Raw response: {raw_response!r}")
    cleaned = _strip_markdown_fence(raw_response)
    try:
        decoded: Any = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ParseError(f"Could not parse LLM JSON response: {exc}. Raw response: {raw_response!r}") from exc
    if not isinstance(decoded, list):
        raise ValidationError("expected a JSON array of test case objects")

    cases: list[TestCase] = []
    required_fields = set(TestCase.required_fields())
    date_prefix = datetime.now(timezone.utc).strftime("%Y%m%d")
    for index, item in enumerate(decoded):
        original_fields = set(item.keys()) if isinstance(item, dict) else None
        if isinstance(item, dict):
            item = dict(item)
            item["id"] = f"TC-{date_prefix}-{index + 1:04d}"
            item["generated_at"] = datetime.now(timezone.utc).isoformat()
        _validate_item(item, index, required_fields, original_fields)
        cases.append(TestCase(**{field: item[field] for field in TestCase.required_fields()}))
    return cases


def parse_batch_response(
    raw_response: str,
    expected_scenarios: list[ScenarioIntent],
) -> list[TestCase]:
    """Strictly parse one Phase 3 batch without requiring full batch coverage."""

    if not isinstance(raw_response, str) or not raw_response.strip():
        raise ParseError(f"Could not parse empty batch response. Raw response: {raw_response!r}")
    expected_by_id = {scenario.id: scenario for scenario in expected_scenarios}
    if len(expected_by_id) != len(expected_scenarios):
        raise ValidationError("expected scenarios contain duplicate scenario_ref values")

    cleaned = _strip_markdown_fence(raw_response)
    try:
        decoded: Any = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ParseError(f"Could not parse batch JSON response: {exc}") from exc
    if not isinstance(decoded, list):
        raise ValidationError("expected a JSON array of batch test case objects")

    cases: list[TestCase] = []
    seen_scenarios: set[str] = set()
    required_fields = set(TestCase.phase3_required_fields())
    for index, item in enumerate(decoded):
        original_fields = set(item.keys()) if isinstance(item, dict) else None
        _validate_item(item, index, required_fields, original_fields)
        scenario_ref = item["scenario_ref"]
        requirement_ref = item["requirement_ref"]
        if not isinstance(scenario_ref, str) or not scenario_ref.strip():
            raise ValidationError("scenario_ref must be a non-empty string", index)
        expected = expected_by_id.get(scenario_ref)
        if expected is None:
            raise ValidationError(f"unknown or unplanned scenario_ref '{scenario_ref}'", index)
        if requirement_ref != expected.requirement_ref:
            raise ValidationError(
                f"scenario_ref '{scenario_ref}' belongs to requirement '{expected.requirement_ref}', not '{requirement_ref}'",
                index,
            )
        if scenario_ref in seen_scenarios:
            raise ValidationError(f"duplicate scenario_ref '{scenario_ref}'", index)
        if requirement_ref == "REQ-UNTRACED":
            raise ValidationError("REQ-UNTRACED is invalid for Phase 3 batch generation", index)
        seen_scenarios.add(scenario_ref)

        materialized = dict(item)
        materialized["id"] = f"TC-00000000-{index + 1:04d}"
        cases.append(
            TestCase(
                **{
                    field: materialized[field]
                    for field in TestCase.phase3_required_fields()
                }
            )
        )
    return cases


def _strip_markdown_fence(raw_response: str) -> str:
    """Remove one accidental Markdown JSON fence while preserving JSON content."""

    cleaned = raw_response.strip()
    match = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", cleaned, flags=re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else cleaned


def _validate_item(
    item: Any,
    index: int,
    required_fields: set[str],
    original_fields: set[str] | None = None,
) -> None:
    """Validate one decoded response item and report its exact index and defect."""

    if not isinstance(item, dict):
        raise ValidationError("expected an object", index)
    fields_to_check = original_fields if original_fields is not None else set(item.keys())
    missing = required_fields.difference(fields_to_check)
    if missing:
        missing_names = ", ".join(sorted(missing))
        raise ValidationError(f"missing required field(s): {missing_names}", index)
    if item["category"] not in TestCase.CATEGORIES:
        allowed = ", ".join(TestCase.CATEGORIES)
        raise ValidationError(f"category must be one of: {allowed}", index)
    if item["priority"] not in TestCase.PRIORITIES:
        raise ValidationError("priority is invalid", index)
    if item["technique"] not in TestCase.TECHNIQUES:
        raise ValidationError("technique is invalid", index)
    if item["language_target"] not in TestCase.LANGUAGES:
        raise ValidationError("language_target is invalid", index)
    if not isinstance(item["preconditions"], list) or not all(isinstance(value, str) for value in item["preconditions"]):
        raise ValidationError("preconditions must be a list of strings", index)
    if not isinstance(item["steps"], list) or not item["steps"] or not all(isinstance(value, str) and value.strip() for value in item["steps"]):
        raise ValidationError("steps must be a non-empty list of non-empty strings", index)
    if not isinstance(item["expected_result"], str) or not item["expected_result"].strip():
        raise ValidationError("expected_result must be a non-empty string", index)
    for field in ("id", "title", "requirement_ref", "generated_at"):
        if not isinstance(item[field], str) or not item[field].strip():
            raise ValidationError(f"{field} must be a non-empty string", index)
