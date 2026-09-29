from models.coverage_model import ScenarioIntent
from models.requirement_model import Requirement
from prompt_builder import build_batch_prompt


def test_batch_prompt_uses_exact_trace_ids_and_only_referenced_requirements() -> None:
    first = Requirement(
        id="CALC-CREATE-001",
        title="Billing Cycle",
        statement="Billing Cycle is mandatory.",
    )
    second = Requirement(
        id="UNREFERENCED-001",
        title="Not in this batch",
        statement="This requirement must not be sent in this batch.",
    )
    scenario = ScenarioIntent(
        id="CALC-CREATE-001-S01",
        requirement_ref="CALC-CREATE-001",
        category="positive",
        technique="EP",
        intent="Verify Billing Cycle accepts a valid populated value.",
    )

    prompt = build_batch_prompt([first, second], [scenario])

    assert "CALC-CREATE-001" in prompt
    assert "CALC-CREATE-001-S01" in prompt
    assert "Not in this batch" not in prompt
    assert "Generate exactly one test case for each supplied scenario." in prompt
    assert "Do not add scenarios." in prompt
    assert "Do not omit scenarios." in prompt
    assert "Use the exact requirement_ref and scenario_ref" in prompt


def test_batch_prompt_has_no_legacy_global_coverage_quotas() -> None:
    requirement = Requirement(
        id="MU-001",
        title="Table",
        statement="The table displays Customer Number.",
    )
    scenario = ScenarioIntent(
        id="MU-001-S01",
        requirement_ref="MU-001",
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
    requirement = Requirement(id="MU-001", title="Table", statement="The table displays values.")
    scenario = ScenarioIntent(
        id="MU-001-S01",
        requirement_ref="MU-001",
        category="positive",
        technique="EP",
        intent="Verify the table displays values.",
    )

    prompt = build_batch_prompt([requirement], [scenario], output_language="id")

    assert "Bahasa Indonesia" in prompt
