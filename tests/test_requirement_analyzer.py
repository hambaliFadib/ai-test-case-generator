from pathlib import Path

import pytest

from models.input_model import ParsedInput
from requirement_analyzer import RequirementAnalysisError, analyze_requirements


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
