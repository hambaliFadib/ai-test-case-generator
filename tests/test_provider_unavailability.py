"""Provider-unavailability handling regressions.

Provider-mocked, offline tests for structured HTTP failure
classification and the systemic-unavailability stop policy.
"""

import re

from llm_adapter import LLMError
from models.input_model import ParsedInput
from models.llm_result import LLMResult
from generation_orchestrator import generate_test_suite


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


def scenario(requirement_ref: str, sequence: int) -> dict:
    return {
        "id": f"{requirement_ref}-S{sequence:02d}",
        "scenario_ref": f"{requirement_ref}-S{sequence:02d}",
        "requirement_ref": requirement_ref,
        "category": "positive",
        "technique": "EP",
        "intent": f"Verify {requirement_ref} behavior.",
        "title": f"Verify {requirement_ref} behavior.",
        "preconditions": ["The page is open."],
        "steps": [f"Observe the {requirement_ref} value."],
        "expected_result": f"The {requirement_ref} value is displayed.",
    }


def response_for(scenarios: list[dict]) -> str:
    import json

    return json.dumps(
        [
            {
                "id": item["id"].replace("-S", "-TC-"),
                "title": item["title"],
                "category": item["category"],
                "priority": "medium",
                "preconditions": item["preconditions"],
                "steps": item["steps"],
                "expected_result": item["expected_result"],
                "technique": item["technique"],
                "requirement_ref": item["requirement_ref"],
                "scenario_ref": item["scenario_ref"],
                "language_target": "manual",
                "generated_at": "2026-10-11T00:00:00+00:00",
            }
            for item in scenarios
        ]
    )


def _success_responder(prompt: str, _: int) -> LLMResult:
    refs = prompt_scenario_refs(prompt)
    scenarios = [
        scenario(ref.rsplit("-S", 1)[0], int(ref.rsplit("-S", 1)[1]))
        for ref in refs
    ]
    return LLMResult(response_for(scenarios), "fake")


class _StatusError(RuntimeError):
    """Mimics a provider exception carrying a typed HTTP status."""

    def __init__(self, status_code: int) -> None:
        super().__init__(f"HTTP {status_code} error")
        self.status_code = status_code


def _http_error(status_code: int) -> LLMError:
    return LLMError(
        f"OpenAI request failed: HTTP {status_code} error",
        status_code=status_code,
    )


# ---------------------------------------------------------------------------
# LLMError classification
# ---------------------------------------------------------------------------


def test_llm_error_classifies_429_as_provider_unavailable() -> None:
    error = _http_error(429)
    assert error.provider_unavailable is True
    assert error.status_code == 429


def test_llm_error_classifies_5xx_as_provider_unavailable() -> None:
    for status in (500, 502, 503, 504, 524, 599):
        error = _http_error(status)
        assert error.provider_unavailable is True, status


def test_llm_error_does_not_classify_other_http_errors() -> None:
    for status in (400, 401, 403, 404, 422):
        error = _http_error(status)
        assert error.provider_unavailable is False, status


def test_llm_error_without_status_is_not_provider_unavailable() -> None:
    error = LLMError("OpenAI request failed: connection reset")
    assert error.status_code is None
    assert error.provider_unavailable is False


def test_http_status_extraction_uses_typed_metadata() -> None:
    from llm_adapter import _http_status_code

    assert _http_status_code(_StatusError(429)) == 429
    assert _http_status_code(_StatusError(503)) == 503
    assert _http_status_code(ValueError("plain")) is None

    class _ResponseError(RuntimeError):
        pass

    exc = _ResponseError("wrapped")
    exc.response = _StatusError(500)
    assert _http_status_code(exc) == 500


# ---------------------------------------------------------------------------
# Stop policy: persistent provider unavailability
# ---------------------------------------------------------------------------


def test_all_initial_429_batches_skip_backfill() -> None:
    adapter = FakeAdapter(
        lambda _prompt, _call: (_ for _ in ()).throw(_http_error(429))
    )
    # 7 requirements plan into 2 initial batches, so a fully
    # unavailable wave is systemic rather than a single batch.
    result = generate_test_suite(parsed_input(7), None, adapter=adapter)

    assert result.status == "failed"
    assert result.generated_count == 0
    assert result.coverage_percentage == 0.0
    assert result.initial_generated_count == 0
    assert result.backfill_count == 0
    assert len(result.test_cases) == 0
    assert len(result.missing_scenarios) == 7
    assert any(
        "backfill skipped: every initial batch failed with provider "
        "unavailability" in diagnostic
        for diagnostic in result.diagnostics
    )
    provider_failures = [
        diagnostic
        for diagnostic in result.diagnostics
        if diagnostic.startswith("batch generation failed")
    ]
    assert len(provider_failures) == 2


def test_all_initial_5xx_batches_skip_backfill() -> None:
    adapter = FakeAdapter(
        lambda _prompt, _call: (_ for _ in ()).throw(_http_error(503))
    )
    result = generate_test_suite(parsed_input(7), None, adapter=adapter)

    assert result.status == "failed"
    assert result.backfill_count == 0
    assert len(result.missing_scenarios) == 7


def test_unrelated_http_error_is_not_systemic() -> None:
    adapter = FakeAdapter(
        lambda _prompt, _call: (_ for _ in ()).throw(_http_error(401))
    )
    result = generate_test_suite(parsed_input(7), None, adapter=adapter)

    assert result.status == "failed"
    assert result.backfill_count > 0
    assert not any(
        "backfill skipped" in diagnostic
        for diagnostic in result.diagnostics
    )


def test_generic_runtime_error_is_not_systemic() -> None:
    adapter = FakeAdapter(
        lambda _prompt, _call: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    result = generate_test_suite(parsed_input(7), None, adapter=adapter)

    assert result.status == "failed"
    assert result.backfill_count > 0


def test_mixed_initial_wave_still_recovers_missing() -> None:
    def responder(prompt: str, call_number: int) -> LLMResult:
        if call_number == 1:
            raise _http_error(429)
        return _success_responder(prompt, call_number)

    adapter = FakeAdapter(responder)
    # 7 requirements -> 2 initial batches; batch 1 fails with 429,
    # batch 2 succeeds -> mixed wave -> backfill recovers batch 1.
    result = generate_test_suite(parsed_input(7), None, adapter=adapter)

    assert result.status == "complete"
    assert result.initial_generated_count == 1
    assert result.backfill_count >= 1
    assert result.missing_scenarios == []


def test_successful_initial_wave_skips_backfill() -> None:
    def responder(prompt: str, call_number: int) -> LLMResult:
        if call_number <= 2:
            return _success_responder(prompt, call_number)
        raise _http_error(429)

    adapter = FakeAdapter(responder)
    result = generate_test_suite(parsed_input(6), None, adapter=adapter)

    # 6 requirements -> 1 initial batch, all succeed -> no backfill.
    assert result.backfill_count == 0
    assert result.status == "complete"


def test_backfill_round_all_unavailable_prevents_next_round() -> None:
    def responder(prompt: str, call_number: int) -> LLMResult:
        # 7 requirements -> 2 initial batches. Batch 1 succeeds,
        # batch 2 fails with 5xx (mixed wave -> backfill for the
        # missing batch). The backfill round then fails entirely
        # with provider unavailability -> stop before round 2.
        if call_number == 1:
            return _success_responder(prompt, call_number)
        raise _http_error(503)

    adapter = FakeAdapter(responder)
    result = generate_test_suite(parsed_input(7), None, adapter=adapter)

    # 7 requirements -> batches of 6 and 1 scenario.
    # Batch 1 (6 cases) succeeds; batch 2 (1 case) fails
    # with 5xx -> mixed wave -> backfill recovers the single
    # missing scenario, then the backfill round fails entirely
    # with provider unavailability -> stop before round 2.
    assert result.initial_generated_count == 6
    assert result.backfill_count == 1
    assert any(
        "backfill stopped after round 1: every batch "
        "failed with provider unavailability" in diagnostic
        for diagnostic in result.diagnostics
    )
    # initial 2 batches + 1 backfill batch, then stop.
    assert len(adapter.prompts) == 3
    assert result.status == "partial"


# ---------------------------------------------------------------------------
# Existing behavior preserved
# ---------------------------------------------------------------------------


def test_transient_provider_failure_still_recovers() -> None:
    def responder(prompt: str, call_number: int):
        if call_number == 1:
            raise _http_error(429)
        return _success_responder(prompt, call_number)

    adapter = FakeAdapter(responder)
    result = generate_test_suite(parsed_input(7), None, adapter=adapter)

    assert result.status == "complete"
    assert result.initial_generated_count == 1
    assert result.backfill_count >= 1
    assert result.missing_scenarios == []


def test_semantic_rejection_still_uses_backfill_policy() -> None:
    def responder(prompt: str, call_number: int) -> LLMResult:
        refs = prompt_scenario_refs(prompt)
        if call_number == 1:
            # Return only the first scenario of the batch; the rest
            # are reported as missing and must be backfilled.
            selected = refs[:1]
            scenarios = [
                scenario(ref.rsplit("-S", 1)[0], int(ref.rsplit("-S", 1)[1]))
                for ref in selected
            ]
            return LLMResult(response_for(scenarios), "fake")
        return _success_responder(prompt, call_number)

    adapter = FakeAdapter(responder)
    result = generate_test_suite(parsed_input(7), None, adapter=adapter)

    # 7 requirements -> batches of 6 and 1 scenario; call 1
    # returns only the first scenario of batch 1, so batch 2's
    # single scenario also counts toward the initial wave.
    assert result.status == "complete"
    assert result.initial_generated_count == 2
    assert len(result.initial_missing_scenarios) == 5
    assert result.backfill_count == 1
    assert len(adapter.prompts) == 3
    assert result.missing_scenarios == []


def test_secret_sentinel_not_exposed_through_redaction_path() -> None:
    """Diagnostics flow through redact_sensitive_detail at the API boundary."""

    from security_utils import redact_sensitive_detail

    sentinel = "sk-proj-SECRET-SENTINEL-9f2a"

    class _LeakyError(RuntimeError):
        def __init__(self) -> None:
            super().__init__(f"OpenAI request failed: {sentinel}")

    adapter = FakeAdapter(
        lambda _prompt, _call: (_ for _ in ()).throw(_LeakyError())
    )
    result = generate_test_suite(parsed_input(7), None, adapter=adapter)

    # Raw diagnostics carry the provider message verbatim; the API
    # serialization path is the redaction boundary.
    redacted = [
        redact_sensitive_detail(diagnostic)
        for diagnostic in result.diagnostics
    ]
    for diagnostic in redacted:
        assert sentinel not in diagnostic
    assert "[REDACTED]" in " ".join(redacted)
