"""Phase 4 production-path tests using fake generation results only."""

from dataclasses import replace
from pathlib import Path
import csv
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

import main
from csv_exporter import export_to_csv, export_traceable_to_csv
from models.coverage_model import GenerationResult
from models.input_model import ParsedInput
from models.test_case_model import TestCase
from web.app import app
import web.router as web_router


client = TestClient(app)


def make_case(index: int, scenario_ref: str = "REQ-001-S01") -> TestCase:
    return TestCase(
        id=f"TC-20260929-{index:04d}",
        title="Traceable generated case",
        category="positive",
        priority="medium",
        preconditions=[],
        steps=["Perform the documented action."],
        expected_result="The documented behavior is satisfied.",
        technique="EP",
        requirement_ref=scenario_ref.rsplit("-S", 1)[0],
        language_target="manual",
        generated_at="2026-09-29T00:00:00+00:00",
        scenario_ref=scenario_ref,
    )


def result(
    status: str = "complete",
    *,
    requirement_count: int = 1,
    scenario_count: int = 1,
    generated_count: int = 1,
    missing: list[str] | None = None,
    cases: list[TestCase] | None = None,
    batch_count: int = 1,
    backfill_count: int = 0,
) -> GenerationResult:
    generated = cases if cases is not None else [
        make_case(index, f"REQ-{index:03d}-S01")
        for index in range(1, generated_count + 1)
    ]
    return GenerationResult(
        status=status,
        requirement_count=requirement_count,
        testable_requirement_count=requirement_count,
        excluded_requirement_count=0,
        scenario_count=scenario_count,
        generated_count=generated_count,
        coverage_percentage=(generated_count / scenario_count * 100) if scenario_count else 0.0,
        batch_count=batch_count,
        backfill_count=backfill_count,
        missing_scenarios=list(missing or []),
        test_cases=generated,
        diagnostics=["fake diagnostic"] if status == "failed" else [],
    )


def test_cli_complete_and_profile_use_orchestrator(monkeypatch, capsys) -> None:
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(main, "resolve_input", lambda **_: ParsedInput("text", "inline", "source"))
    monkeypatch.setattr(main, "load_settings", lambda **_: type("Settings", (), {"provider": "fake", "model": "fake-model"})())
    monkeypatch.setattr(
        main,
        "generate_test_suite",
        lambda parsed_input, settings, **kwargs: calls.append(kwargs) or result(),
    )
    monkeypatch.setattr(main, "export_traceable_to_csv", lambda cases, path: Path(path))

    with TemporaryDirectory() as temp_dir:
        exit_code = main.main(["--text", "source", "--output", str(Path(temp_dir) / "suite.csv"), "--profile", "security"])

    assert exit_code == 0
    assert calls[0]["profile"] == "comprehensive"
    assert "Status: complete" in capsys.readouterr().out


def test_cli_default_profile_partial_and_failed_exit_codes(monkeypatch, capsys) -> None:
    calls: list[str] = []
    outcomes = iter([
        result("partial", scenario_count=2, generated_count=1, missing=["REQ-002-S01"]),
        result("failed", generated_count=0, cases=[]),
    ])
    monkeypatch.setattr(main, "resolve_input", lambda **_: ParsedInput("text", "inline", "source"))
    monkeypatch.setattr(main, "load_settings", lambda **_: type("Settings", (), {"provider": "fake", "model": "fake-model"})())
    monkeypatch.setattr(main, "generate_test_suite", lambda parsed_input, settings, **kwargs: calls.append(kwargs["profile"]) or next(outcomes))

    assert main.main(["--text", "source"]) == 2
    assert main.main(["--text", "source"]) == 1
    assert calls == ["comprehensive", "comprehensive"]
    assert "Missing scenario count: 1" in capsys.readouterr().out


def test_web_complete_partial_failed_and_default_profile(monkeypatch) -> None:
    calls: list[str] = []
    outcomes = iter([
        result(),
        result("partial", scenario_count=2, generated_count=1, missing=["REQ-002-S01"]),
        result("failed", generated_count=0, cases=[]),
    ])
    monkeypatch.setattr(web_router, "load_settings", lambda **_: type("Settings", (), {})())
    monkeypatch.setattr(
        web_router,
        "generate_test_suite",
        lambda parsed_input, settings, **kwargs: calls.append(kwargs["profile"]) or next(outcomes),
    )

    complete = client.post("/api/generate/text", json={"text": "source"})
    partial = client.post("/api/generate/text", json={"text": "source", "profile": "minimal"})
    failed = client.post("/api/generate/text", json={"text": "source"})

    assert complete.status_code == 200
    assert complete.json()["status"] == "complete"
    assert complete.json()["scenario_count"] == 1
    assert complete.json()["test_cases"][0]["scenario_ref"] == "REQ-001-S01"
    assert partial.status_code == 200
    assert partial.json()["status"] == "partial"
    assert partial.json()["missing_scenarios"] == ["REQ-002-S01"]
    assert partial.json()["coverage_percentage"] < 100
    assert failed.status_code == 500
    assert failed.json()["status"] == "failed"
    assert calls == ["comprehensive", "minimal", "comprehensive"]


def test_web_rejects_invalid_profile_and_preserves_markdown_upload(monkeypatch) -> None:
    seen: list[str] = []
    monkeypatch.setattr(web_router, "load_settings", lambda **_: type("Settings", (), {})())
    monkeypatch.setattr(
        web_router,
        "generate_test_suite",
        lambda parsed_input, settings, **kwargs: seen.append(parsed_input.text) or result(),
    )

    invalid = client.post("/api/generate/text", json={"text": "source", "profile": "unknown"})
    uploaded = client.post(
        "/api/generate/file",
        files={"file": ("requirements.md", b"### REQ-001 - Source\nThe page displays a value.")},
    )

    assert invalid.status_code == 400
    assert "minimal" in invalid.json()["detail"]
    assert uploaded.status_code == 200
    assert seen == ["### REQ-001 - Source\nThe page displays a value."]


def test_traceable_export_preserves_scenario_refs_and_legacy_export_remains() -> None:
    first = make_case(1, "REQ-001-S01")
    second = replace(make_case(2, "REQ-001-S02"), title=first.title)
    with TemporaryDirectory() as temp_dir:
        traceable_path = export_traceable_to_csv([first, second], Path(temp_dir) / "traceable.csv")
        legacy_path = export_to_csv([first, second], Path(temp_dir) / "legacy.csv")
        traceable_rows = list(csv.DictReader(traceable_path.open(encoding="utf-8", newline="")))
        legacy_header = legacy_path.read_text(encoding="utf-8").splitlines()[0]

    assert "scenario_ref" in traceable_rows[0]
    assert [row["scenario_ref"] for row in traceable_rows] == ["REQ-001-S01", "REQ-001-S02"]
    assert "requirement_ref" in traceable_rows[0]
    assert "scenario_ref" not in legacy_header


def test_pgn_sized_fake_result_is_presented_truthfully() -> None:
    complete = result(
        requirement_count=97,
        scenario_count=191,
        generated_count=191,
        batch_count=17,
    )
    partial = result(
        "partial",
        requirement_count=97,
        scenario_count=191,
        generated_count=15,
        missing=[f"REQ-{index:03d}-S01" for index in range(16, 192)],
        batch_count=17,
    )

    complete_payload = web_router._serialize_result(complete, "comprehensive")
    partial_payload = web_router._serialize_result(partial, "comprehensive")

    assert (complete_payload["requirement_count"], complete_payload["scenario_count"]) == (97, 191)
    assert complete_payload["status"] == "complete"
    assert complete_payload["coverage_percentage"] == 100.0
    assert partial_payload["status"] == "partial"
    assert partial_payload["generated_count"] == 15
    assert len(partial_payload["missing_scenarios"]) == 176
    assert partial_payload["coverage_percentage"] < 100.0


def test_ui_contains_phase4_coverage_contract() -> None:
    html = Path("web/static/index.html").read_text(encoding="utf-8")
    js = Path("web/static/js/app.js").read_text(encoding="utf-8")
    bundle = html + js
    for token in ("coverage_percentage", "scenario_count", "generated_count", "missing_scenarios", "status", "scenario_ref"):
        assert token in bundle
    assert "v1.3.1" in html


def test_web_test_client_dependency_is_declared_for_dev_installs() -> None:
    requirements = Path("requirements-dev.txt").read_text(encoding="utf-8")
    assert "httpx" in requirements.lower()


def test_cli_and_web_redact_credential_shaped_failure_details(monkeypatch, capsys) -> None:
    diagnostic = "provider failed: Authorization: Bearer fake-bearer-token OPENAI_API_KEY=sk-test-secret-value"
    monkeypatch.setattr(main, "resolve_input", lambda **_: ParsedInput("text", "inline", "source"))
    monkeypatch.setattr(main, "load_settings", lambda **_: type("Settings", (), {"provider": "fake", "model": "fake-model"})())
    monkeypatch.setattr(
        main,
        "generate_test_suite",
        lambda parsed_input, settings, **kwargs: GenerationResult(
            status="failed",
            requirement_count=1,
            testable_requirement_count=1,
            excluded_requirement_count=0,
            scenario_count=1,
            generated_count=0,
            coverage_percentage=0.0,
            batch_count=1,
            backfill_count=0,
            diagnostics=[diagnostic],
        ),
    )

    main.main(["--text", "source"])
    captured = capsys.readouterr()

    assert "fake-bearer-token" not in captured.err
    assert "sk-test-secret-value" not in captured.err
    assert "[REDACTED]" in captured.err
    assert "fake-bearer-token" not in web_router._redact(diagnostic)
    assert "sk-test-secret-value" not in web_router._redact(diagnostic)
