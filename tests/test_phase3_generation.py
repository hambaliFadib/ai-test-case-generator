import json
import re
from types import SimpleNamespace

import pytest

from coverage_auditor import audit_coverage
from deduplicator import ScenarioDeduplicationError, deduplicate_scenario_test_cases
from generation_orchestrator import generate_test_suite
from generation_utils import is_truncated
from models.coverage_model import CoveragePlan, RequirementCoveragePlan, ScenarioIntent
from models.input_model import ParsedInput
from models.llm_result import LLMResult
from models.test_case_model import TestCase
from llm_adapter import AnthropicAdapter, LLMAdapter, OpenAIAdapter
from response_parser import (
    ValidationError,
    parse_batch_response,
    parse_batch_response_result,
    parse_response,
)
from validator import TestCaseValidationError, validate_batch_traceability, validate_traceability


def scenario(requirement_ref: str, number: int = 1) -> ScenarioIntent:
    return ScenarioIntent(
        id=f"{requirement_ref}-S{number:02d}",
        requirement_ref=requirement_ref,
        category="positive",
        technique="EP",
        intent=f"Verify source-backed scenario {number}.",
    )


def valid_item(item_scenario: ScenarioIntent, *, requirement_ref: str | None = None) -> dict[str, object]:
    return {
        "id": "llm-generated-id",
        "title": f"Case for {item_scenario.id}",
        "category": item_scenario.category,
        "priority": item_scenario.priority,
        "preconditions": [],
        "steps": ["Perform the source-backed action."],
        "expected_result": "The source-backed behavior is satisfied.",
        "technique": item_scenario.technique,
        "requirement_ref": requirement_ref or item_scenario.requirement_ref,
        "language_target": "manual",
        "generated_at": "2026-01-01T00:00:00+00:00",
        "scenario_ref": item_scenario.id,
    }


def minimal_item(item_scenario: ScenarioIntent, **overrides: object) -> dict[str, object]:
    item: dict[str, object] = {
        "scenario_ref": item_scenario.id,
        "title": f"Case for {item_scenario.id}",
        "preconditions": [],
        "steps": ["Perform the source-backed action."],
        "expected_result": "The source-backed behavior is satisfied.",
    }
    item.update(overrides)
    return item


def response_for(scenarios: list[ScenarioIntent], omit: set[str] | None = None) -> str:
    omitted = omit or set()
    return json.dumps(
        [valid_item(item) for item in scenarios if item.id not in omitted]
    )


def minimal_response_for(
    scenarios: list[ScenarioIntent],
    invalid_scenario_id: str | None = None,
) -> str:
    payload = []
    for item_scenario in scenarios:
        item = minimal_item(item_scenario)
        if item_scenario.id == invalid_scenario_id:
            del item["expected_result"]
        payload.append(item)
    return json.dumps(payload)


class FakeAdapter:
    def __init__(self, responder) -> None:
        self.responder = responder
        self.prompts: list[str] = []

    def generate_result(self, prompt: str) -> LLMResult:
        self.prompts.append(prompt)
        response = self.responder(prompt, len(self.prompts))
        if isinstance(response, Exception):
            raise response
        return response


def prompt_scenario_refs(prompt: str) -> list[str]:
    planned = prompt.split("Planned scenarios for this batch:", 1)[-1]
    return re.findall(r'"scenario_ref":\s*"([^"]+)"', planned)


def parsed_input(requirement_count: int) -> ParsedInput:
    lines: list[str] = []
    for index in range(1, requirement_count + 1):
        lines.extend(
            [
                f"### REQ-{index:03d} — Requirement {index}",
                "The page displays a source-backed value.",
                "",
            ]
        )
    return ParsedInput("markdown", "phase3.md", "\n".join(lines))


def test_llm_result_and_legacy_adapter_compatibility() -> None:
    class LegacyAdapter(LLMAdapter):
        def generate(self, prompt: str) -> str:
            return f"legacy:{prompt}"

    adapter = LegacyAdapter()
    assert adapter.generate("x") == "legacy:x"
    result = adapter.generate_result("x")
    assert isinstance(result, LLMResult)
    assert result.text == "legacy:x"
    assert result.model == ""
    assert is_truncated(LLMResult("{}", "fake", finish_reason="length")) is True
    assert is_truncated(LLMResult("{}", "fake", finish_reason=None)) is False


def test_provider_result_mapping_handles_metadata_and_missing_usage() -> None:
    anthropic = object.__new__(AnthropicAdapter)
    anthropic._model = "configured-anthropic"
    anthropic._client = SimpleNamespace(
        messages=SimpleNamespace(
            create=lambda **_: SimpleNamespace(
                content=[SimpleNamespace(text="anthropic text")],
                model="claude-fake",
                stop_reason="end_turn",
                usage=SimpleNamespace(input_tokens=11, output_tokens=7),
            )
        )
    )
    result = anthropic.generate_result("prompt")
    assert result == LLMResult("anthropic text", "claude-fake", "end_turn", 11, 7)

    openai = object.__new__(OpenAIAdapter)
    openai._model = "configured-openai"
    openai._client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=lambda **_: SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(content="openai text"),
                            finish_reason="stop",
                        )
                    ],
                    model="gpt-fake",
                    usage=None,
                )
            )
        )
    )
    result = openai.generate_result("prompt")
    assert result == LLMResult("openai text", "gpt-fake", "stop", None, None)


def test_strict_batch_parser_requires_and_validates_scenario_refs() -> None:
    expected = [scenario("REQ-001")]
    missing = valid_item(expected[0])
    del missing["scenario_ref"]
    with pytest.raises(ValidationError, match="scenario_ref"):
        parse_batch_response(json.dumps([missing]), expected)

    unknown = valid_item(expected[0])
    unknown["scenario_ref"] = "REQ-001-S99"
    with pytest.raises(ValidationError, match="unknown or unplanned"):
        parse_batch_response(json.dumps([unknown]), expected)

    provider_metadata = valid_item(expected[0], requirement_ref="REQ-002")
    provider_metadata.update(
        {
            "category": "security",
            "priority": "high",
            "technique": "security",
            "language_target": "python",
            "id": "provider-id",
            "generated_at": "provider-time",
        }
    )
    materialized = parse_batch_response(json.dumps([provider_metadata]), expected)
    assert materialized[0].requirement_ref == "REQ-001"
    assert materialized[0].category == "positive"
    assert materialized[0].priority == "medium"
    assert materialized[0].technique == "EP"
    assert materialized[0].language_target == "manual"

    duplicate = [valid_item(expected[0]), valid_item(expected[0])]
    with pytest.raises(ValidationError, match="duplicate scenario_ref"):
        parse_batch_response(json.dumps(duplicate), expected)


def test_strict_parser_ignores_llm_ids_until_final_assignment() -> None:
    expected = [scenario("REQ-001")]
    cases = parse_batch_response(response_for(expected), expected)

    assert cases[0].scenario_ref == "REQ-001-S01"
    assert cases[0].id == "TC-00000000-0001"


def test_minimal_provider_failure_shape_is_materialized_with_application_metadata() -> None:
    expected = [scenario("REQ-MINIMAL-001")]
    cases = parse_batch_response(
        json.dumps([minimal_item(expected[0])]),
        expected,
        language_target="python",
    )

    assert cases[0].requirement_ref == "REQ-MINIMAL-001"
    assert cases[0].scenario_ref == "REQ-MINIMAL-001-S01"
    assert cases[0].category == "positive"
    assert cases[0].technique == "EP"
    assert cases[0].priority == "medium"
    assert cases[0].language_target == "python"
    assert cases[0].id == "TC-00000000-0001"
    assert cases[0].generated_at


def test_batch_item_content_errors_are_salvaged_without_dropping_siblings() -> None:
    expected = [scenario("REQ-001", index) for index in range(1, 6)]
    payload = [minimal_item(item) for item in expected]
    payload[3].pop("expected_result")

    from response_parser import parse_batch_response_result

    parsed = parse_batch_response_result(json.dumps(payload), expected)

    assert [case.scenario_ref for case in parsed.test_cases] == [
        "REQ-001-S01", "REQ-001-S02", "REQ-001-S03", "REQ-001-S05"
    ]
    assert parsed.invalid_scenario_ids == ["REQ-001-S04"]
    assert len(parsed.item_errors) == 1
    assert "expected_result" in parsed.item_errors[0]


def test_empty_steps_are_item_local_but_unknown_refs_are_batch_fatal() -> None:
    expected = [scenario("REQ-001", 1), scenario("REQ-001", 2)]
    payload = [minimal_item(expected[0], steps=[]), minimal_item(expected[1])]

    from response_parser import parse_batch_response_result

    parsed = parse_batch_response_result(json.dumps(payload), expected)
    assert [case.scenario_ref for case in parsed.test_cases] == ["REQ-001-S02"]

    unknown = minimal_item(expected[1], scenario_ref="REQ-999-S01")
    with pytest.raises(ValidationError, match="unknown or unplanned"):
        parse_batch_response_result(json.dumps([unknown]), expected)


def test_provider_boundary_rejects_dialog_side_effect_not_in_cancel_intent() -> None:
    expected = [
        ScenarioIntent(
            id="REQ-CANCEL-001-S01",
            requirement_ref="REQ-CANCEL-001",
            category="positive",
            technique="EP",
            intent="Verify that Cancel keeps the user on the form.",
        )
    ]
    response = json.dumps(
        [
            minimal_item(
                expected[0],
                steps=["Click Cancel."],
                expected_result=(
                    "The user remains on the form, and the confirmation dialog closes."
                ),
            )
        ]
    )

    parsed = parse_batch_response_result(response, expected)

    assert parsed.test_cases == []
    assert parsed.invalid_scenario_ids == ["REQ-CANCEL-001-S01"]
    assert "unsupported" in parsed.item_errors[0].lower()


def test_provider_boundary_rejects_unstated_unchanged_state_on_cancel() -> None:
    expected = [
        ScenarioIntent(
            id="REQ-CANCEL-001-S01",
            requirement_ref="REQ-CANCEL-001",
            category="positive",
            technique="EP",
            intent="Verify that Cancel keeps the user on the form.",
        )
    ]
    response = json.dumps(
        [
            minimal_item(
                expected[0],
                steps=["Click Cancel."],
                expected_result="The user remains on the form without any changes.",
            )
        ]
    )

    parsed = parse_batch_response_result(response, expected)

    assert parsed.test_cases == []
    assert parsed.invalid_scenario_ids == ["REQ-CANCEL-001-S01"]
    assert "unsupported state-change" in parsed.item_errors[0]


def test_provider_boundary_keeps_sample_literal_and_hides_non_exhaustive_constraint() -> None:
    expected = [
        ScenarioIntent(
            id="REQ-SAMPLE-001-S01",
            requirement_ref="REQ-SAMPLE-001",
            category="positive",
            technique="EP",
            intent=(
                "Verify the sample value 'Server Error' is shown as a "
                "non-exhaustive example for Result Details."
            ),
        )
    ]
    response = json.dumps(
        [
            minimal_item(
                expected[0],
                steps=["Observe the Result Details rows."],
                expected_result=(
                    "A row shows 'Server Error' as an example message, "
                    "indicating it is non-exhaustive."
                ),
            )
        ]
    )

    parsed = parse_batch_response_result(response, expected)

    assert parsed.test_cases == []
    assert parsed.invalid_scenario_ids == ["REQ-SAMPLE-001-S01"]
    assert "generation-constraint" in parsed.item_errors[0]


def test_provider_boundary_requires_sample_literal_in_observable_expected_result() -> None:
    expected = [
        ScenarioIntent(
            id="REQ-SAMPLE-001-S01",
            requirement_ref="REQ-SAMPLE-001",
            category="positive",
            technique="EP",
            intent="Verify the sample value 'Server Error' is shown for Result Details.",
        )
    ]
    response = json.dumps(
        [
            minimal_item(
                expected[0],
                steps=["Observe the Result Details rows."],
                expected_result="A failure message is shown in the Result Details.",
            )
        ]
    )

    parsed = parse_batch_response_result(response, expected)

    assert parsed.test_cases == []
    assert parsed.invalid_scenario_ids == ["REQ-SAMPLE-001-S01"]
    assert "sample literal" in parsed.item_errors[0]


def test_provider_boundary_accepts_only_the_cancel_intent_outcome() -> None:
    expected = [
        ScenarioIntent(
            id="REQ-CANCEL-001-S01",
            requirement_ref="REQ-CANCEL-001",
            category="positive",
            technique="EP",
            intent="Verify that Cancel keeps the user on the form.",
        )
    ]
    response = json.dumps(
        [
            minimal_item(
                expected[0],
                steps=["Click Cancel."],
                expected_result="The user remains on the form.",
            )
        ]
    )

    parsed = parse_batch_response_result(response, expected)

    assert [case.expected_result for case in parsed.test_cases] == [
        "The user remains on the form."
    ]


def test_provider_boundary_allows_prevented_save_as_mandatory_empty_operationalization() -> None:
    expected = [
        ScenarioIntent(
            id="REQ-EMPTY-001-S02",
            requirement_ref="REQ-EMPTY-001",
            category="negative",
            technique="negative",
                intent="Verify Period Field is rejected or prevented when it is left empty.",
        )
    ]
    response = json.dumps(
        [
            minimal_item(
                expected[0],
                steps=["Leave Period Field empty and attempt to save."],
                expected_result="Saving is prevented while Period Field is empty.",
            )
        ]
    )

    parsed = parse_batch_response_result(response, expected)

    assert [case.expected_result for case in parsed.test_cases] == [
        "Saving is prevented while Period Field is empty."
    ]


def test_prompt_contract_excludes_application_owned_fields() -> None:
    expected = [scenario("REQ-001")]
    minimal = parse_batch_response(json.dumps([minimal_item(expected[0])]), expected)
    assert minimal[0].generated_at
    assert minimal[0].id.startswith("TC-")


def test_traceability_validator_rejects_untraced_and_duplicates() -> None:
    expected = [scenario("REQ-001")]
    cases = parse_batch_response(response_for(expected), expected)
    invalid = TestCase(
        id=cases[0].id,
        title=cases[0].title,
        category=cases[0].category,
        priority=cases[0].priority,
        preconditions=[],
        steps=["step"],
        expected_result="result",
        technique="EP",
        requirement_ref="REQ-UNTRACED",
        language_target="manual",
        generated_at="2026-01-01T00:00:00+00:00",
        scenario_ref="REQ-001-S01",
    )
    with pytest.raises(TestCaseValidationError, match="REQ-UNTRACED"):
        validate_batch_traceability([invalid], expected)

    duplicate = replace_test_case_id(cases[0], "TC-00000000-0002")
    with pytest.raises(TestCaseValidationError, match="duplicate scenario_ref"):
        validate_traceability(
            cases + [duplicate],
            {"REQ-001"},
            {"REQ-001-S01"},
            {"REQ-001-S01": "REQ-001"},
        )


def test_coverage_audit_reports_missing_unexpected_and_duplicates() -> None:
    first = scenario("REQ-001", 1)
    second = scenario("REQ-001", 2)
    plan = CoveragePlan([RequirementCoveragePlan("REQ-001", [first, second])])
    cases = parse_batch_response(response_for([first]), [first])
    duplicate = replace_test_case_id(cases[0], "TC-00000000-0002")
    unexpected = replace_scenario_ref(cases[0], "REQ-999-S01")
    audit = audit_coverage(plan, [cases[0], duplicate, unexpected])

    assert audit.coverage_percentage == 50.0
    assert audit.missing_scenario_ids == [second.id]
    assert audit.unexpected_scenario_ids == ["REQ-999-S01"]
    assert audit.duplicate_scenario_ids == [first.id]


def replace_scenario_ref(test_case: TestCase, scenario_ref: str) -> TestCase:
    return TestCase(
        id=test_case.id,
        title=test_case.title,
        category=test_case.category,
        priority=test_case.priority,
        preconditions=test_case.preconditions,
        steps=test_case.steps,
        expected_result=test_case.expected_result,
        technique=test_case.technique,
        requirement_ref=test_case.requirement_ref,
        language_target=test_case.language_target,
        generated_at=test_case.generated_at,
        scenario_ref=scenario_ref,
    )


def replace_test_case_id(test_case: TestCase, test_case_id: str) -> TestCase:
    return TestCase(
        id=test_case_id,
        title=test_case.title,
        category=test_case.category,
        priority=test_case.priority,
        preconditions=test_case.preconditions,
        steps=test_case.steps,
        expected_result=test_case.expected_result,
        technique=test_case.technique,
        requirement_ref=test_case.requirement_ref,
        language_target=test_case.language_target,
        generated_at=test_case.generated_at,
        scenario_ref=test_case.scenario_ref,
    )


def test_scenario_aware_deduplication_does_not_merge_same_title_across_scenarios() -> None:
    first = TestCase(
        "TC-20260101-0001", "Same title", "positive", "medium",
        [], ["step"], "result", "EP", "REQ-001", "manual",
        "2026-01-01T00:00:00+00:00", "REQ-001-S01",
    )
    second = TestCase(
        "TC-20260101-0002", "Same title", "positive", "medium",
        [], ["step"], "result", "EP", "REQ-001", "manual",
        "2026-01-01T00:00:00+00:00", "REQ-001-S02",
    )
    assert len(deduplicate_scenario_test_cases([first, second])) == 2
    with pytest.raises(ScenarioDeduplicationError):
        deduplicate_scenario_test_cases([first, first])


def test_orchestrator_full_success_orders_cases_and_assigns_final_ids() -> None:
    adapter = FakeAdapter(lambda prompt, _: LLMResult(
        response_for([scenario(ref.rsplit("-S", 1)[0], int(ref.rsplit("-S", 1)[1])) for ref in prompt_scenario_refs(prompt)]),
        "fake",
    ))

    result = generate_test_suite(parsed_input(10), None, adapter=adapter)

    assert result.status == "complete"
    assert result.scenario_count == 10
    assert result.generated_count == 10
    assert result.coverage_percentage == 100.0
    assert result.missing_scenarios == []
    assert result.backfill_count == 0
    assert [case.scenario_ref for case in result.test_cases] == [
        f"REQ-{index:03d}-S01" for index in range(1, 11)
    ]
    assert [case.id for case in result.test_cases] == [
        f"TC-{result.test_cases[0].id[3:11]}-{index:04d}"
        for index in range(1, 11)
    ]


def test_orchestrator_backfills_only_missing_scenarios_and_stops_when_complete() -> None:
    remaining = 8

    def responder(prompt: str, call_number: int) -> LLMResult:
        nonlocal remaining
        refs = prompt_scenario_refs(prompt)
        scenarios = [scenario(ref.rsplit("-S", 1)[0], int(ref.rsplit("-S", 1)[1])) for ref in refs]
        if call_number <= 2:
            selected = scenarios[:remaining]
            remaining -= len(selected)
            return LLMResult(response_for(selected), "fake")
        return LLMResult(response_for(scenarios), "fake")

    adapter = FakeAdapter(responder)
    result = generate_test_suite(parsed_input(10), None, adapter=adapter)

    assert result.status == "complete"
    assert result.initial_generated_count == 8
    assert result.initial_missing_scenarios == [
        f"REQ-{index:03d}-S01" for index in range(9, 11)
    ]
    assert result.backfill_count == 1
    assert len(adapter.prompts) == 3
    assert all(ref in adapter.prompts[2] for ref in ("REQ-009-S01", "REQ-010-S01"))
    assert all(ref not in adapter.prompts[2] for ref in ("REQ-001-S01", "REQ-008-S01"))


def test_orchestrator_salvages_invalid_item_and_backfills_only_that_scenario() -> None:
    invalid_id = "REQ-005-S01"

    def responder(prompt: str, call_number: int) -> LLMResult:
        refs = prompt_scenario_refs(prompt)
        scenarios = [
            scenario(ref.rsplit("-S", 1)[0], int(ref.rsplit("-S", 1)[1]))
            for ref in refs
        ]
        if call_number == 1:
            return LLMResult(minimal_response_for(scenarios, invalid_id), "fake")
        assert [item.id for item in scenarios] == [invalid_id]
        return LLMResult(minimal_response_for(scenarios), "fake")

    adapter = FakeAdapter(responder)
    result = generate_test_suite(parsed_input(5), None, adapter=adapter)

    assert result.status == "complete"
    assert result.initial_generated_count == 4
    assert result.initial_missing_scenarios == [invalid_id]
    assert result.backfill_count == 1
    assert [case.scenario_ref for case in result.test_cases] == [
        f"REQ-{index:03d}-S01" for index in range(1, 6)
    ]
    assert invalid_id in " ".join(result.diagnostics)


def test_orchestrator_persistent_missing_is_partial_and_backfill_is_bounded() -> None:
    def responder(prompt: str, _: int) -> LLMResult:
        refs = prompt_scenario_refs(prompt)
        scenarios = [scenario(ref.rsplit("-S", 1)[0], int(ref.rsplit("-S", 1)[1])) for ref in refs]
        return LLMResult(response_for(scenarios[:-1]), "fake")

    adapter = FakeAdapter(responder)
    result = generate_test_suite(parsed_input(10), None, adapter=adapter)

    assert result.status == "partial"
    assert result.missing_scenarios == ["REQ-010-S01"]
    assert result.backfill_count == 2
    assert result.coverage_percentage == 90.0


def test_orchestrator_truncation_does_not_accept_parseable_json() -> None:
    def responder(prompt: str, call_number: int) -> LLMResult:
        refs = prompt_scenario_refs(prompt)
        scenarios = [scenario(ref.rsplit("-S", 1)[0], int(ref.rsplit("-S", 1)[1])) for ref in refs]
        if call_number == 1:
            return LLMResult(response_for(scenarios), "fake", finish_reason="length")
        return LLMResult(response_for(scenarios), "fake")

    adapter = FakeAdapter(responder)
    result = generate_test_suite(parsed_input(3), None, adapter=adapter)

    assert result.status == "complete"
    assert result.initial_generated_count == 0
    assert result.initial_missing_scenarios == [
        "REQ-001-S01", "REQ-002-S01", "REQ-003-S01"
    ]
    assert result.backfill_count == 1


def test_orchestrator_provider_failure_leaves_missing_scenarios_visible() -> None:
    def responder(prompt: str, call_number: int):
        if call_number == 1:
            return RuntimeError("provider unavailable")
        refs = prompt_scenario_refs(prompt)
        scenarios = [scenario(ref.rsplit("-S", 1)[0], int(ref.rsplit("-S", 1)[1])) for ref in refs]
        return LLMResult(response_for(scenarios), "fake")

    result = generate_test_suite(parsed_input(3), None, adapter=FakeAdapter(responder))

    assert result.status == "complete"
    assert result.initial_generated_count == 0
    assert result.backfill_count == 1


def test_orchestrator_no_valid_cases_is_failed() -> None:
    adapter = FakeAdapter(lambda prompt, _: LLMResult("[]", "fake"))
    result = generate_test_suite(parsed_input(2), None, adapter=adapter)

    assert result.status == "failed"
    assert result.generated_count == 0
    assert result.coverage_percentage == 0.0


def test_fifteen_of_191_regression_is_not_silent_and_can_backfill() -> None:
    initial_batch_count = 32
    remaining = 15

    def responder(prompt: str, call_number: int) -> LLMResult:
        nonlocal remaining
        refs = prompt_scenario_refs(prompt)
        scenarios = [scenario(ref.rsplit("-S", 1)[0], int(ref.rsplit("-S", 1)[1])) for ref in refs]
        if call_number <= initial_batch_count:
            selected = scenarios[:remaining]
            remaining -= len(selected)
            return LLMResult(response_for(selected), "fake")
        return LLMResult(response_for(scenarios), "fake")

    adapter = FakeAdapter(responder)
    result = generate_test_suite(parsed_input(191), None, adapter=adapter)

    assert result.initial_generated_count == 15
    assert len(result.initial_missing_scenarios) == 176
    assert result.initial_missing_scenarios[0] == "REQ-016-S01"
    assert result.status == "complete"
    assert result.generated_count == 191
    assert result.coverage_percentage == 100.0
    assert result.missing_scenarios == []
    backfill_prompts = adapter.prompts[initial_batch_count:]
    assert len(backfill_prompts) == 30
    for prompt in backfill_prompts:
        refs = prompt_scenario_refs(prompt)
        assert len(refs) <= 8
        assert len({ref.rsplit("-S", 1)[0] for ref in refs}) <= 6
        assert len(prompt) <= 30000


def test_legacy_parser_remains_compatible_without_scenario_ref() -> None:
    raw = json.dumps(
        [
            {
                "id": "llm-id",
                "title": "Legacy case",
                "category": "positive",
                "priority": "medium",
                "preconditions": [],
                "steps": ["step"],
                "expected_result": "result",
                "technique": "EP",
                "requirement_ref": "REQ-001",
                "language_target": "manual",
                "generated_at": "2026-01-01T00:00:00+00:00",
            }
        ]
    )
    cases = parse_response(raw)
    assert cases[0].scenario_ref == ""
