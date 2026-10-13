from pathlib import Path

import pytest

from models.input_model import ParsedInput
from requirement_analyzer import (
    RequirementAnalysisError,
    _constraints_for_statement,
    _is_requirement_candidate,
    analyze_requirements,
)


FIXTURES = Path(__file__).parent / "fixtures"


def parsed(text: str, name: str = "inline.md") -> ParsedInput:
    return ParsedInput("markdown", name, text)


def fixture(name: str) -> ParsedInput:
    path = FIXTURES / name
    return ParsedInput("markdown", str(path), path.read_text(encoding="utf-8"))


def test_explicit_ids_are_preserved() -> None:
    requirements = analyze_requirements(fixture("structured_requirements.md"))

    assert [requirement.id for requirement in requirements] == [
        "CALC-CREATE-017",
        "PB-DETAIL-008",
        "RATE-006",
    ]


def test_bullets_do_not_become_independent_requirements() -> None:
    requirements = analyze_requirements(fixture("structured_requirements.md"))

    assert len(requirements) == 3
    assert "success dialog is displayed" in requirements[0].details
    assert "result can be reviewed" in requirements[0].details


def test_title_and_source_section_are_preserved() -> None:
    requirements = analyze_requirements(fixture("structured_requirements.md"))

    assert requirements[0].title == "Success Result"
    assert requirements[0].source_section == "Product > Billing"


def test_expected_block_is_captured() -> None:
    requirements = analyze_requirements(fixture("structured_requirements.md"))

    assert requirements[0].acceptance_criteria == [
        "success dialog is displayed",
        "result can be reviewed",
    ]


def test_numeric_limit_is_captured() -> None:
    requirements = analyze_requirements(fixture("structured_requirements.md"))

    assert requirements[1].numeric_limits == ["Remark has a maximum of 255 characters."]
    assert requirements[1].has_numeric_or_date_field is True


def test_legacy_input_keeps_sequential_req_ids() -> None:
    requirements = analyze_requirements(fixture("legacy_requirements.md"))

    assert [requirement.id for requirement in requirements] == ["REQ-001", "REQ-002"]


def test_duplicate_explicit_ids_fail() -> None:
    text = """\
### MU-001 - First
System displays the first behavior.

### MU-001 - Duplicate
System displays the second behavior.
"""

    with pytest.raises(RequirementAnalysisError, match="Duplicate explicit requirement ID"):
        analyze_requirements(parsed(text, "duplicate.md"))


def test_open_questions_section_classifies_requirement_as_unresolved() -> None:
    text = """\
## Open Questions

### RATE-099 - Retry Rule
The exact retry behavior is unknown.
"""

    requirements = analyze_requirements(parsed(text, "open-questions.md"))

    assert requirements[0].status == "UNRESOLVED"


def test_excluded_section_classifies_requirement_as_excluded() -> None:
    text = """\
## Excluded Business Rules

### RATE-098 - Rating Formula
Do not generate formula-based test cases.
"""

    requirements = analyze_requirements(parsed(text, "excluded.md"))

    assert requirements[0].status == "EXCLUDED"


def test_local_do_not_infer_guardrail_does_not_exclude_testable_requirement() -> None:
    text = """\
## Rating

### RATE-001 - Rating Display
The page displays rating values.
Do not infer the rating formula.
"""

    requirements = analyze_requirements(parsed(text, "guardrail.md"))

    assert requirements[0].status == "TESTABLE"


def test_nested_heading_remains_inside_explicit_requirement_block() -> None:
    requirements = analyze_requirements(fixture("structured_requirements.md"))

    assert requirements[2].source_section == "Product > Notes"
    assert "matching results are displayed" in requirements[2].details
    assert "unrelated results are not displayed" in requirements[2].acceptance_criteria


# ---------------------------------------------------------------------------
# Analyzer provenance regression (Evidence Binding v2 smoke regression)
# ---------------------------------------------------------------------------

_SMOKE_LOGIN_TEXT = """\
User Login

The system provides a login form with:
- Username
- Password

The user submits by clicking "Login".
The system accepts valid username+valid password and allows login.
If username/password combination invalid, displays "Invalid username or password".
Username required.
Password required.
Username accepts alphanumeric.
Password accepts alphanumeric and special characters.
After successful login, displays Dashboard.
Dashboard provides Logout.
Logout returns to Login page.
Login page displays Forgot Password link.
Login form must not expose entered password as plain text.
"""


def test_constraint_bounded_to_own_requirement_region() -> None:
    lines = [
        "Username accepts alphanumeric.",
        "Password accepts alphanumeric and special characters.",
        "Login form must not expose entered password as plain text.",
    ]
    constraints = _constraints_for_statement(
        "Username accepts alphanumeric.",
        lines,
        region_end=1,
    )
    assert constraints == []
    own_region = _constraints_for_statement(
        "Login form must not expose entered password as plain text.",
        lines,
        region_end=len(lines),
    )
    assert own_region == [
        "Login form must not expose entered password as plain text."
    ]


def test_legacy_constraint_stays_inside_own_block() -> None:
    text = """\
### REQ-A — Username
Username accepts alphanumeric characters.

### REQ-B — Password visibility
Login form must not expose entered password as plain text.
"""
    requirements = analyze_requirements(parsed(text, "provenance.md"))
    assert [requirement.id for requirement in requirements] == [
        "REQ-001",
        "REQ-002",
    ]
    assert requirements[0].constraints == []
    assert requirements[1].constraints == [
        "Login form must not expose entered password as plain text."
    ]


def test_password_masking_evidence_belongs_only_to_its_own_requirement() -> None:
    from coverage_planner import extract_evidence_atoms

    requirements = analyze_requirements(
        parsed(_SMOKE_LOGIN_TEXT, "smoke-login.md")
    )
    assert len(requirements) == 13

    masking_refs = [
        atom
        for requirement in requirements
        for atom in extract_evidence_atoms(requirement)
        if "plain text" in atom.text.lower()
    ]
    assert [(atom.requirement_ref, atom.text) for atom in masking_refs] == [
        (
            "REQ-013",
            "Login form must not expose entered password as plain text.",
        )
    ]
    for requirement in requirements[:12]:
        assert all(
            "plain text" not in atom.text.lower()
            for atom in extract_evidence_atoms(requirement)
        )


def test_constraint_extraction_anchored_to_correct_statement_not_substring() -> None:
    """When a requirement's statement is a substring of another requirement's
    source line, constraint extraction must anchor to the requirement's own
    statement line, not the first line that merely contains the statement text.
    """
    from requirement_analyzer import _constraints_for_statement

    lines = [
        "The system accepts all login types and password must be displayed as plain text for diagnostics",
        "password must not be stored without encryption",
        "password must be displayed as plain text for diagnostics",
        "constraint: password must be logged for audit",
    ]
    stmt = "password must be displayed as plain text for diagnostics"
    result = _constraints_for_statement(stmt, lines, region_end=4)
    assert "password must not be stored without encryption" not in result, (
        "Constraint from a different requirement leaked via substring match"
    )
    assert "constraint: password must be logged for audit" in result, (
        "Own requirement's constraint was not found"
    )


def test_constraint_anchored_in_full_analyzer_path_not_substring() -> None:
    """End-to-end: the legacy analyzer must compute region boundaries from the
    statement's actual source line, not from a first-occurrence substring
    match that lands on an earlier unrelated line containing the statement
    text as a substring."""
    from requirement_analyzer import analyze_requirements
    from models.input_model import ParsedInput
    text = (
        "password must not be stored without encryption\n"
        "The system accepts login and password must be displayed as plain text for diagnostics\n"
        "password must be displayed as plain text for diagnostics\n"
        "Limit password logging to audit events\n"
    )
    requirements = analyze_requirements(ParsedInput(source_type="text", source_name="test", text=text))
    target = next(
        (r for r in requirements if "displayed as plain text for diagnostics" in r.statement
         and "system accepts" not in r.statement),
        None,
    )
    assert target is not None, "Target requirement not parsed"
    assert not any(
        "must not be stored" in c
        for c in target.constraints
    ), "Constraint from earlier line leaked into requirement via substring match"
    assert any(
        "password logging" in c for c in target.constraints
    ), "Own requirement's constraint was not found"
