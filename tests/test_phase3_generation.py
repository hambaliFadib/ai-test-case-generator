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
from response_parser import ValidationError, parse_batch_response, parse_response
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


def response_for(scenarios: list[ScenarioIntent], omit: set[str] | None = None) -> str:
    omitted = omit or set()
    return json.dumps(
        [valid_item(item) for item in scenarios if item.id not in omitted]
    )


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
    return re.findall(r'"scenario_ref":\s*"([^"]+)"', prompt)


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

    mismatch = valid_item(expected[0], requirement_ref="REQ-002")
    with pytest.raises(ValidationError, match="belongs to requirement"):
        parse_batch_response(json.dumps([mismatch]), expected)

    duplicate = [valid_item(expected[0]), valid_item(expected[0])]
    with pytest.raises(ValidationError, match="duplicate scenario_ref"):
        parse_batch_response(json.dumps(duplicate), expected)


def test_strict_parser_ignores_llm_ids_until_final_assignment() -> None:
    expected = [scenario("REQ-001")]
    cases = parse_batch_response(response_for(expected), expected)

    assert cases[0].scenario_ref == "REQ-001-S01"
    assert cases[0].id == "TC-00000000-0001"


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
