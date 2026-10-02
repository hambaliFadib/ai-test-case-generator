"""Guard the persisted UI validation fixture against metric-semantics drift.

The UI partial-result fixture must stay producible by the real coverage
auditor. This harness rebuilds domain objects from the fixture and runs the
production audit_coverage() over them.
"""

import json
from pathlib import Path

from coverage_auditor import audit_coverage
from models.coverage_model import CoveragePlan, RequirementCoveragePlan, ScenarioIntent
from models.test_case_model import TestCase

FIXTURE = Path(__file__).parent / "fixtures" / "ui_partial_result_mock.json"


def _load_fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _build_plan_and_cases(fixture: dict) -> tuple[CoveragePlan, list[TestCase]]:
    case_refs = [case["scenario_ref"] for case in fixture["test_cases"]]
    unexpected = set(fixture["unexpected_scenarios"])
    covered = [ref for ref in dict.fromkeys(case_refs) if ref not in unexpected]
    planned_ids = covered + list(fixture["missing_scenarios"])
    requirement_refs = {case["scenario_ref"]: case["requirement_ref"] for case in fixture["test_cases"]}
    scenarios_by_req: dict[str, list[ScenarioIntent]] = {}
    for scenario_id in planned_ids:
        req_ref = requirement_refs.get(scenario_id, "REQ-000")
        scenarios_by_req.setdefault(req_ref, []).append(
            ScenarioIntent(
                id=scenario_id,
                requirement_ref=req_ref,
                category="positive",
                technique="EP",
                intent=f"Verify {scenario_id}",
            )
        )
    plan = CoveragePlan(
        requirements=[
            RequirementCoveragePlan(requirement_ref=req_ref, scenarios=scenarios)
            for req_ref, scenarios in scenarios_by_req.items()
        ]
    )
    cases = [
        TestCase(
            id=case["id"],
            title=case["title"],
            category=case["category"],
            priority=case["priority"],
            preconditions=case["preconditions"],
            steps=case["steps"],
            expected_result=case["expected_result"],
            technique=case["technique"],
            requirement_ref=case["requirement_ref"],
            language_target=case["language_target"],
            generated_at=case["generated_at"],
            scenario_ref=case["scenario_ref"],
        )
        for case in fixture["test_cases"]
    ]
    return plan, cases


def test_fixture_metrics_satisfy_backend_invariants() -> None:
    fixture = _load_fixture()
    plan, cases = _build_plan_and_cases(fixture)

    assert fixture["requirement_count"] == fixture["testable_requirement_count"] + fixture["excluded_requirement_count"]
    assert fixture["generated_count"] == len(fixture["test_cases"])
    assert fixture["scenario_count"] == 205

    audit = audit_coverage(plan, cases)
    planned = len(audit.planned_scenario_ids)
    covered = planned - len(audit.missing_scenario_ids)

    assert planned == fixture["scenario_count"]
    assert covered == 199
    assert set(audit.missing_scenario_ids) == set(fixture["missing_scenarios"])
    assert len(audit.missing_scenario_ids) == 6
    assert set(audit.unexpected_scenario_ids) == set(fixture["unexpected_scenarios"])
    assert len(audit.unexpected_scenario_ids) == 1
    assert audit.duplicate_scenario_ids == []
    assert covered + len(audit.unexpected_scenario_ids) == len(cases)
    assert abs(audit.coverage_percentage - 199 / 205 * 100) < 1e-9
    assert round(audit.coverage_percentage, 2) == round(fixture["coverage_percentage"], 2)
    assert round(audit.coverage_percentage, 2) == 97.07


def test_fixture_partial_status_is_justified() -> None:
    fixture = _load_fixture()
    assert fixture["status"] == "partial"
    assert fixture["initial_generated_count"] == 196
    assert fixture["generated_count"] > fixture["initial_generated_count"]
    assert fixture["backfill_count"] == 1
    assert len(fixture["missing_scenarios"]) == 6
    assert len(fixture["unexpected_scenarios"]) == 1
    assert fixture["duplicate_scenarios"] == []
