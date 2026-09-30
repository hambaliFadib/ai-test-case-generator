from models.coverage_model import ScenarioIntent
from models.requirement_model import Requirement
from prompt_builder import build_batch_prompt


def test_batch_prompt_uses_exact_trace_ids_and_only_referenced_requirements() -> None:
    first = Requirement(
        id="REQ-001",
        title="Period Field",
        statement="Period Field is mandatory.",
    )
    second = Requirement(
        id="UNREFERENCED-001",
        title="Not in this batch",
        statement="This requirement must not be sent in this batch.",
    )
    scenario = ScenarioIntent(
        id="REQ-001-S01",
        requirement_ref="REQ-001",
        category="positive",
        technique="EP",
        intent="Verify Period Field accepts a valid populated value.",
    )

    prompt = build_batch_prompt([first, second], [scenario])

    assert "REQ-001" in prompt
    assert "REQ-001-S01" in prompt
    assert "Not in this batch" not in prompt
    assert "This requirement must not be sent in this batch." not in prompt
    assert "Generate exactly one test case for each supplied scenario." in prompt
    assert "Do not add scenarios." in prompt
    assert "Do not omit scenarios." in prompt
    assert "scenario_ref must be copied exactly" in prompt
    assert '"scenario_ref"' in prompt
    assert '"title"' in prompt
    assert '"preconditions"' in prompt
    assert '"steps"' in prompt
    assert '"expected_result"' in prompt
    assert "Do not include id, category, priority, technique, requirement_ref, language_target, or generated_at." in prompt
    assert "keep the generated steps and expected_result observational" in prompt
    assert "unless that behavior is explicit in the scenario intent" in prompt
    assert "Treat the supplied scenario intent as the complete semantic boundary" in prompt
    assert "Keep generation constraints such as \"not exhaustive\" or \"not the only value\"" in prompt
    assert "preserve that literal in expected_result" in prompt
    assert "the requirement details are context only" in prompt.lower()
    assert "do not add dialog closes, discarded changes, navigation, persistence" in prompt.lower()
    assert "preserve \"server error\" in expected_result" in prompt.lower()
    assert "do not mention dialog, modal, popup, or confirmation-window behavior" in prompt.lower()


def test_batch_prompt_has_no_legacy_global_coverage_quotas() -> None:
    requirement = Requirement(
        id="REQ-TABLE-001",
        title="Table",
        statement="The table displays Customer Number.",
    )
    scenario = ScenarioIntent(
        id="REQ-TABLE-001-S01",
        requirement_ref="REQ-TABLE-001",
        category="positive",
        technique="EP",
        intent="Verify the table displays Customer Number.",
    )

    prompt = build_batch_prompt([requirement], [scenario]).lower()

    assert "at least 2 positive" not in prompt
    assert "at least 2 negative" not in prompt
    assert "at least 1 edge" not in prompt
    assert "authentication bypass" not in prompt
    assert "injection" not in prompt


def test_batch_prompt_supports_output_language_validation() -> None:
    requirement = Requirement(id="REQ-TABLE-001", title="Table", statement="The table displays values.")
    scenario = ScenarioIntent(
        id="REQ-TABLE-001-S01",
        requirement_ref="REQ-TABLE-001",
        category="positive",
        technique="EP",
        intent="Verify the table displays values.",
    )

    prompt = build_batch_prompt([requirement], [scenario], output_language="id")

    assert "Bahasa Indonesia" in prompt
