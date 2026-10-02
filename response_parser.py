"""Defensive parsing and contract validation of LLM JSON responses."""

from datetime import datetime, timezone
from dataclasses import dataclass
import json
import re
from typing import Any

from models.coverage_model import EvidenceAtom, ScenarioIntent
from models.test_case_model import TestCase
from semantic_quality import ScenarioAuthority, build_authorities, validate_content


class ParseError(ValueError):
    """Raised when an LLM response is not valid JSON."""


class ValidationError(ValueError):
    """Raised when a response item violates the test-case contract."""

    def __init__(self, reason: str, item_index: int | None = None) -> None:
        """Create an error with an optional zero-based response item index."""

        self.item_index = item_index
        prefix = f"Item {item_index}: " if item_index is not None else "Response: "
        super().__init__(prefix + reason)


LLM_BATCH_CONTENT_FIELDS: tuple[str, ...] = (
    "scenario_ref",
    "title",
    "preconditions",
    "steps",
    "expected_result",
)


@dataclass(frozen=True)
class BatchParseResult:
    """Parsed valid batch items plus item-local content diagnostics."""

    test_cases: list[TestCase]
    item_errors: list[str]
    invalid_scenario_ids: list[str]


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
    language_target: str = "manual",
) -> list[TestCase]:
    """Parse one batch while preserving the legacy list return type."""

    return parse_batch_response_result(
        raw_response,
        expected_scenarios,
        language_target=language_target,
    ).test_cases


def parse_batch_response_result(
    raw_response: str,
    expected_scenarios: list[ScenarioIntent],
    language_target: str = "manual",
    evidence_atoms: list[EvidenceAtom] | None = None,
) -> BatchParseResult:
    """Parse minimal provider content with strict batch traceability.

    ``evidence_atoms`` feeds the deterministic semantic-quality gate so every
    item is validated against its scenario's authorized evidence scope. The
    same gate applies to normal generation, backfill, and salvage because they
    all parse through this function.
    """

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

    # Traceability is batch-fatal. Validate every join key before salvaging
    # item-local natural-language defects so no valid sibling is merged from a
    # response that crosses batch boundaries or duplicates a scenario.
    seen_scenarios: set[str] = set()
    normalized_items: list[tuple[int, dict[str, Any], ScenarioIntent]] = []
    for index, item in enumerate(decoded):
        if not isinstance(item, dict):
            raise ValidationError("expected an object", index)
        if "scenario_ref" not in item:
            raise ValidationError("missing required field(s): scenario_ref", index)
        scenario_ref = item["scenario_ref"]
        if not isinstance(scenario_ref, str) or not scenario_ref.strip():
            raise ValidationError("scenario_ref must be a non-empty string", index)
        expected = expected_by_id.get(scenario_ref)
        if expected is None:
            raise ValidationError(f"unknown or unplanned scenario_ref '{scenario_ref}'", index)
        if scenario_ref in seen_scenarios:
            raise ValidationError(f"duplicate scenario_ref '{scenario_ref}'", index)
        seen_scenarios.add(scenario_ref)
        normalized_items.append((index, item, expected))

    cases: list[TestCase] = []
    item_errors: list[str] = []
    invalid_scenario_ids: list[str] = []
    generated_at = datetime.now(timezone.utc).isoformat()
    authorities = build_authorities(expected_scenarios, evidence_atoms)
    for index, item, expected in normalized_items:
        error = _validate_batch_content(
            item, index, expected, authorities.get(expected.id)
        )
        if error is not None:
            item_errors.append(f"{expected.id}: {error}")
            invalid_scenario_ids.append(expected.id)
            continue
        cases.append(
            TestCase(
                id=f"TC-00000000-{index + 1:04d}",
                title=item["title"],
                category=expected.category,
                priority=expected.priority,
                preconditions=item["preconditions"],
                steps=item["steps"],
                expected_result=item["expected_result"],
                technique=expected.technique,
                requirement_ref=expected.requirement_ref,
                language_target=language_target,
                generated_at=generated_at,
                scenario_ref=expected.id,
            )
        )
    return BatchParseResult(cases, item_errors, invalid_scenario_ids)


def _validate_batch_content(
    item: dict[str, Any],
    index: int,
    expected: ScenarioIntent,
    authority: ScenarioAuthority | None = None,
) -> str | None:
    """Return an item-local content error without weakening traceability."""

    missing = [field for field in LLM_BATCH_CONTENT_FIELDS if field not in item]
    if missing:
        return f"item {index}: missing required field(s): {', '.join(missing)}"
    if not isinstance(item["title"], str) or not item["title"].strip():
        return f"item {index}: title must be a non-empty string"
    if not isinstance(item["preconditions"], list) or not all(
        isinstance(value, str) for value in item["preconditions"]
    ):
        return f"item {index}: preconditions must be a list of strings"
    if not isinstance(item["steps"], list) or not item["steps"] or not all(
        isinstance(value, str) and value.strip() for value in item["steps"]
    ):
        return f"item {index}: steps must be a non-empty list of non-empty strings"
    if not isinstance(item["expected_result"], str) or not item["expected_result"].strip():
        return f"item {index}: expected_result must be a non-empty string"
    boundary_error = _validate_provider_boundary(item, index, expected)
    if boundary_error is not None:
        return boundary_error
    if authority is None:
        return None
    quality_error = validate_content(
        title=item["title"],
        preconditions=item["preconditions"],
        steps=item["steps"],
        expected_result=item["expected_result"],
        authority=authority,
    )
    if quality_error is not None:
        return f"item {index}: semantic quality: {quality_error}"
    return None


_PROVIDER_CLAIM_FAMILIES: tuple[tuple[str, re.Pattern[str], re.Pattern[str]], ...] = (
    (
        "dialog behavior",
        re.compile(r"\b(?:dialog|modal|popup|confirmation window)\b", re.IGNORECASE),
        re.compile(r"\b(?:dialog|modal|popup|confirmation window)\b", re.IGNORECASE),
    ),
    (
        "navigation outcome",
        re.compile(
            r"\b(?:navigat\w*|redirect\w*|go(?:es|ing)?\s+back|return\w*\s+to|"
            r"leav\w*\s+(?:the\s+)?(?:page|screen|form|view|list|detail|user)|"
            r"remain\w*\s+on|stay\w*\s+on)\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(?:navigat\w*|redirect\w*|go(?:es|ing)?\s+back|return\w*\s+to|"
            r"leav\w*|remain\w*\s+on|stay\w*\s+on|keep\w*)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "state-change",
        re.compile(
            r"\b(?:clear\w*|discard\w*|reset\w*|revert\w*|delete\w*|remove\w*|"
            r"blank\w*|empt\w*|unchanged|(?:no|without)\s+(?:any\s+)?"
            r"(?:change\w*|data|value\w*|field\w*))\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(?:clear\w*|discard\w*|reset\w*|revert\w*|delete\w*|remove\w*|"
            r"blank\w*|empt\w*|unchanged|(?:no|without)\s+(?:any\s+)?"
            r"(?:change\w*|data|value\w*|field\w*))\b",
            re.IGNORECASE,
        ),
    ),
    (
        "persistence",
        re.compile(
            r"\b(?:save\w*|persist\w*|store\w*|database|backend)\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(?:save\w*|persist\w*|store\w*|database|backend)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "submission outcome",
        re.compile(r"\bsubmit\w*\b", re.IGNORECASE),
        re.compile(
            r"\b(?:submit\w*|prevent\w*|reject\w*|mandatory|empt\w*|invalid\w*)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "external side effect",
        re.compile(
            r"\b(?:toast|notification|email|audit log|api request|backend request|"
            r"status\s+(?:change\w*|update\w*)|record\s+update\w*)\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(?:toast|notification|email|audit log|api request|backend request|"
            r"status\s+(?:change\w*|update\w*)|record\s+update\w*)\b",
            re.IGNORECASE,
        ),
    ),
)
_SAMPLE_VALUE_PATTERN = re.compile(r"\bsample value\s+['\"]([^'\"]+)['\"]", re.IGNORECASE)
_GENERATION_CONSTRAINT_PATTERN = re.compile(
    r"\b(?:non[- ]exhaustive|not exhaustive|not the only|only possible|only failure|only value)\b",
    re.IGNORECASE,
)
_PREVENTED_PERSISTENCE_PATTERN = re.compile(
    r"(?:\b(?:cannot|can't|not allowed to|not|never|prevent\w*|block\w*|"
    r"disable\w*|reject\w*|fail\w*)\b.{0,80}\b(?:save\w*|persist\w*|"
    r"store\w*|database|backend)\b|\b(?:save\w*|persist\w*|store\w*|"
    r"database|backend)\b.{0,80}\b(?:cannot|can't|not allowed|not|never|"
    r"prevent\w*|block\w*|disable\w*|reject\w*|fail\w*)\b)",
    re.IGNORECASE | re.DOTALL,
)


def _validate_provider_boundary(
    item: dict[str, Any],
    index: int,
    expected: ScenarioIntent,
) -> str | None:
    """Keep provider-authored content inside the supplied scenario intent."""

    operational_text = " ".join([*item["steps"], item["expected_result"]])
    for family, generated_pattern, intent_pattern in _PROVIDER_CLAIM_FAMILIES:
        if generated_pattern.search(operational_text) and not intent_pattern.search(expected.intent):
            if (
                family == "persistence"
                and re.search(r"\b(?:prevent\w*|reject\w*|empt\w*|mandatory|invalid\w*)\b", expected.intent, re.IGNORECASE)
                and _PREVENTED_PERSISTENCE_PATTERN.search(operational_text)
            ):
                continue
            return (
                f"item {index}: unsupported {family} claim in steps/expected_result; "
                "the scenario intent does not state that outcome"
            )

    if _GENERATION_CONSTRAINT_PATTERN.search(operational_text):
        return (
            f"item {index}: generation-constraint wording must not become an observable "
            "steps/expected_result assertion"
        )

    sample_match = _SAMPLE_VALUE_PATTERN.search(expected.intent)
    if sample_match and sample_match.group(1).casefold() not in item["expected_result"].casefold():
        return (
            f"item {index}: expected_result must retain the supplied sample literal "
            f"'{sample_match.group(1)}'"
        )
    return None


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
