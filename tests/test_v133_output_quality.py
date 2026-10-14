"""Regression tests for v1.3.3 generated-output quality."""

from models.test_case_model import TestCase
from generation_orchestrator import _retain_unique_content


def _case(
    scenario_ref: str,
    *,
    requirement_ref: str = "REQ-001",
    title: str = "Verify invalid credentials are rejected",
    preconditions: list[str] | None = None,
    steps: list[str] | None = None,
    expected_result: str = "The invalid credentials are rejected.",
) -> TestCase:
    return TestCase(
        id=f"TC-20261014-{int(scenario_ref[-1:]):04d}",
        title=title,
        category="negative",
        priority="high",
        preconditions=preconditions or [],
        steps=steps or ["Enter invalid credentials in the Login form."],
        expected_result=expected_result,
        technique="negative",
        requirement_ref=requirement_ref,
        language_target="manual",
        generated_at="2026-10-14T00:00:00+00:00",
        scenario_ref=scenario_ref,
    )


def test_duplicate_operational_content_is_rejected_even_when_titles_differ() -> None:
    existing = _case("REQ-001-S01", title="Reject invalid username")
    duplicate = _case(
        "REQ-001-S02",
        title="Verify invalid credentials cannot be accepted",
    )
    diagnostics: list[str] = []

    retained = _retain_unique_content([duplicate], [existing], diagnostics)

    assert retained == []
    assert diagnostics == [
        "duplicate generated content rejected for REQ-001-S02; "
        "an equivalent requirement-local test case already exists"
    ]


def test_distinct_operational_content_is_retained() -> None:
    existing = _case("REQ-001-S01")
    distinct = _case(
        "REQ-001-S02",
        steps=["Enter an invalid password in the Login form."],
        expected_result="The invalid password is rejected.",
    )

    retained = _retain_unique_content([distinct], [existing], [])

    assert retained == [distinct]


def test_identical_content_for_different_requirements_is_not_coalesced() -> None:
    existing = _case("REQ-001-S01", requirement_ref="REQ-001")
    separate_requirement = _case("REQ-002-S01", requirement_ref="REQ-002")

    retained = _retain_unique_content([separate_requirement], [existing], [])

    assert retained == [separate_requirement]
