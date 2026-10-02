"""Locked BASELINE-CONTRACT-REVISION v2 tests.

Covers canonical profile resolution, baseline applicability and evidence
gates, UnresolvedBaselineItem semantics, subset/determinism invariants, and
the no-invention boundary.
"""

from dataclasses import asdict
import inspect
import json
import re

from fastapi.testclient import TestClient
import pytest

import coverage_planner
from baseline_planner import (
    BASELINE_DOMAINS,
    DISPOSITION_RETAINED,
    STATUS_APPLICABLE_UNRESOLVED,
    BaselineEvaluation,
    evaluate_baseline,
)
from coverage_planner import extract_evidence_atoms, plan_coverage
from generation_orchestrator import generate_test_suite
from main import build_argument_parser
from models.coverage_model import UnresolvedBaselineItem
from models.input_model import ParsedInput
from models.llm_result import LLMResult
from models.requirement_model import Requirement
from profiles import (
    CANONICAL_PROFILES,
    DEFAULT_PROFILE,
    PROFILE_ALIASES,
    resolve_profile,
)
from web.app import app
import web.router as web_router


client = TestClient(app)


def requirement(
    requirement_id: str,
    statement: str,
    *,
    title: str = "",
    status: str = "TESTABLE",
    details: list[str] | None = None,
    acceptance: list[str] | None = None,
    constraints: list[str] | None = None,
    numeric_limits: list[str] | None = None,
) -> Requirement:
    return Requirement(
        id=requirement_id,
        statement=statement,
        title=title,
        status=status,
        details=details or [],
        acceptance_criteria=acceptance or [],
        constraints=constraints or [],
        tags=[],
        numeric_limits=numeric_limits or [],
    )


def evaluate(req: Requirement) -> BaselineEvaluation:
    return evaluate_baseline(
        req, extract_evidence_atoms(req), req.title or req.statement
    )


def auth_materialized(evaluation: BaselineEvaluation) -> set[str]:
    return {
        rule_key
        for rule_key, _ in evaluation.materialized
        if rule_key.startswith("auth.")
    }


def auth_unresolved_keys(evaluation: BaselineEvaluation) -> list[str]:
    return [
        item.rule_key
        for item in evaluation.unresolved
        if item.rule_key.startswith("auth.")
    ]


def corpus() -> list[Requirement]:
    return [
        requirement("N-001", "The login form validates credentials.", title="Login"),
        requirement(
            "N-002",
            "User enters invalid credentials and sees an error message.",
            title="Sign In",
        ),
        requirement(
            "N-003",
            "Only authenticated users can access the dashboard.",
            title="Access",
        ),
        requirement(
            "N-004",
            "The create form provides:",
            title="Create Form",
            details=["Save Changes", "Cancel"],
        ),
        requirement("N-005", "Billing Cycle is mandatory.", title="Billing Cycle"),
        requirement(
            "N-006", "Search Content filters displayed rows.", title="Search"
        ),
        requirement(
            "N-007",
            "The upload is restricted.",
            title="Upload",
            details=["Only PDF is allowed", "Max 10MB"],
        ),
        requirement(
            "N-008",
            "Status values include Submitted, Approved, and Rejected.",
            title="Usage Status",
        ),
        requirement(
            "N-009",
            "Confirmation provides Confirm and Cancel actions.",
            title="Confirmation",
        ),
        requirement(
            "N-010",
            "Monitoring Usage provides two primary tabs:",
            title="Monitoring",
            details=["Usage List", "Batch List"],
        ),
        requirement(
            "N-011",
            "The API returns a success response for valid requests.",
            title="API",
        ),
        requirement(
            "N-012",
            "Validation displays an error message for missing fields.",
            title="Validation",
        ),
        requirement(
            "N-013", "Try Again is available to retry the operation.", title="Result"
        ),
        requirement("N-014", "The table displays Customer Number.", title="Table"),
        requirement(
            "N-015",
            "The detail page shows a failure dialog when the process fails.",
            title="Detail",
        ),
    ]


def identities(plan) -> list[tuple[str, str, str]]:
    return [
        (scenario.category, scenario.technique, scenario.intent)
        for requirement_plan in plan.requirements
        for scenario in requirement_plan.scenarios
    ]


def echo_adapter():
    class EchoAdapter:
        def generate_result(self, prompt: str) -> LLMResult:
            planned = prompt.split("Planned scenarios for this batch:", 1)[-1]
            scenarios = json.loads(planned)
            items = []
            for scenario in scenarios:
                ref = scenario["scenario_ref"]
                if scenario.get("category") == "security":
                    items.append(
                        {
                            "scenario_ref": ref,
                            "title": f"Verify credential rejection for {ref}",
                            "preconditions": ["The login form is open."],
                            "steps": [
                                "Enter wrong credentials and check the "
                                f"\"Login\" response for {ref}."
                            ],
                            "expected_result": (
                                "The \"Login\" form does not accept wrong "
                                "credentials and shows an error message."
                            ),
                        }
                    )
                else:
                    items.append(
                        {
                            "scenario_ref": ref,
                            "title": f"Case for {ref}",
                            "preconditions": [],
                            "steps": [f"Check the \"Result\" field for {ref}."],
                            "expected_result": (
                                "The \"Result\" field displays the "
                                "source-backed value."
                            ),
                        }
                    )
            return LLMResult(json.dumps(items), "fake")

    return EchoAdapter()


def auth_parsed_input() -> ParsedInput:
    text = (
        "### REQ-AUTH-001 — Login\n"
        "User enters invalid credentials and sees an error message."
    )
    return ParsedInput("markdown", "auth.md", text)


# 1. auth baseline applicability
def test_auth_baseline_applicability() -> None:
    login = requirement(
        "AUTH-APPLICABLE", "The login form validates credentials.", title="Login"
    )
    evaluation = evaluate(login)

    unresolved = auth_unresolved_keys(evaluation)
    assert unresolved  # applicable and retained, never dropped
    assert "auth.a4_invalid_credentials" in unresolved
    assert "auth.a11_logout" in evaluation.not_applicable  # out of scope
    materialized = auth_materialized(evaluation)
    assert not (materialized & set(unresolved))

    plain = requirement("TABLE-001", "The table displays Customer Number.", title="Table")
    plain_evaluation = evaluate(plain)
    assert auth_unresolved_keys(plain_evaluation) == []
    assert auth_materialized(plain_evaluation) == set()
    assert not any(
        key.startswith("auth.")
        for key in (
            [*plain_evaluation.not_applicable]
            + [key for key, _ in plain_evaluation.materialized]
        )
    )


# 2. generic invalid credentials -> A4 only
def test_generic_invalid_credentials_materialize_a4_only() -> None:
    req = requirement(
        "AUTH-GENERIC",
        "User enters invalid credentials and sees an error message.",
        title="Login",
    )
    evaluation = evaluate(req)

    assert auth_materialized(evaluation) == {"auth.a4_invalid_credentials"}
    unresolved = set(auth_unresolved_keys(evaluation))
    assert "auth.a2_invalid_username" in unresolved
    assert "auth.a3_invalid_password" in unresolved
    # never silently dropped
    assert unresolved == {
        "auth.a1_valid_credentials",
        "auth.a2_invalid_username",
        "auth.a3_invalid_password",
        "auth.a5_empty_username",
        "auth.a6_empty_password",
        "auth.a7_empty_both_fields",
        "auth.a8_boundary_input",
        "auth.a9_locked_account",
        "auth.a10_session_behavior",
        "auth.a12_mfa",
    }

    plan = plan_coverage([req])
    intents = " ".join(scenario.intent for scenario in plan.requirements[0].scenarios)
    assert "invalid credentials" in intents
    assert "username" not in intents.lower()
    assert "password" not in intents.lower()


# 3. field-specific evidence -> A2/A3
def test_field_specific_evidence_materializes_a2_and_a3() -> None:
    req = requirement(
        "AUTH-FIELDS",
        "The login form validates credentials.",
        title="Login",
        details=[
            "An unknown username is rejected.",
            "An incorrect password is rejected.",
        ],
    )
    evaluation = evaluate(req)

    assert auth_materialized(evaluation) == {
        "auth.a2_invalid_username",
        "auth.a3_invalid_password",
    }
    unresolved = set(auth_unresolved_keys(evaluation))
    assert "auth.a4_invalid_credentials" in unresolved  # no generic evidence
    assert "auth.a2_invalid_username" not in unresolved
    assert "auth.a3_invalid_password" not in unresolved

    plan = plan_coverage([req])
    covered = {
        atom_id
        for scenario in plan.requirements[0].scenarios
        for atom_id in scenario.evidence_refs
    }
    field_atoms = [
        atom.id
        for atom in extract_evidence_atoms(req)
        if "rejected" in atom.text
    ]
    assert field_atoms and all(atom_id in covered for atom_id in field_atoms)


# 4. empty-field evidence
def test_empty_field_evidence_materializes_a5_and_a6() -> None:
    req = requirement(
        "AUTH-EMPTY",
        "The login form validates input.",
        title="Login",
        details=["Username is mandatory.", "Password cannot be empty."],
    )
    evaluation = evaluate(req)

    assert auth_materialized(evaluation) == {
        "auth.a5_empty_username",
        "auth.a6_empty_password",
    }
    unresolved = set(auth_unresolved_keys(evaluation))
    assert "auth.a7_empty_both_fields" in unresolved  # not one combined atom

    no_evidence = requirement(
        "AUTH-EMPTY-NONE", "The login form validates input.", title="Login"
    )
    empty_unresolved = set(auth_unresolved_keys(evaluate(no_evidence)))
    assert {"auth.a5_empty_username", "auth.a6_empty_password"} <= empty_unresolved


# 5. boundary evidence
def test_boundary_evidence_materializes_a8() -> None:
    req = requirement(
        "AUTH-BOUNDARY",
        "Login validates the username field.",
        title="Login",
        constraints=["Username has a maximum of 20 characters."],
    )
    evaluation = evaluate(req)

    assert "auth.a8_boundary_input" in auth_materialized(evaluation)
    assert "auth.a8_boundary_input" not in auth_unresolved_keys(evaluation)

    plan = plan_coverage([req])
    boundary_scenarios = [
        scenario
        for scenario in plan.requirements[0].scenarios
        if scenario.category == "boundary"
    ]
    assert boundary_scenarios
    assert any("20" in scenario.intent for scenario in boundary_scenarios)


# 6. locked account evidence/policy
def test_locked_account_evidence_policy_and_gap() -> None:
    with_evidence = requirement(
        "AUTH-LOCK-EVIDENCE",
        "The login service rejects repeated failures.",
        title="Login",
        constraints=["Accounts lock after 5 failed attempts."],
    )
    evidence_evaluation = evaluate(with_evidence)
    assert "auth.a9_locked_account" in auth_materialized(evidence_evaluation)
    assert "auth.a9_locked_account" not in auth_unresolved_keys(evidence_evaluation)

    without = requirement(
        "AUTH-LOCK-GAP", "The login service validates credentials.", title="Login"
    )
    gap_evaluation = evaluate(without)
    lock_items = [
        item
        for item in gap_evaluation.unresolved
        if item.rule_key == "auth.a9_locked_account"
    ]
    assert len(lock_items) == 1
    assert lock_items[0].requires_policy is True
    assert lock_items[0].status == STATUS_APPLICABLE_UNRESOLVED

    with_policy = requirement(
        "AUTH-LOCK-POLICY",
        "The login service validates credentials.",
        title="Login",
        constraints=["Account lockout is not configured."],
    )
    policy_evaluation = evaluate(with_policy)
    assert "auth.a9_locked_account" not in auth_unresolved_keys(policy_evaluation)
    assert "auth.a9_locked_account" in policy_evaluation.not_applicable
    assert "auth.a9_locked_account" not in auth_materialized(policy_evaluation)

    plan = plan_coverage([with_policy])
    intents = " ".join(scenario.intent for scenario in plan.requirements[0].scenarios)
    assert "after 5" not in intents


# 7. session evidence/policy
def test_session_evidence_policy_and_gap() -> None:
    with_evidence = requirement(
        "AUTH-SESSION-EVIDENCE",
        "User signs in successfully.",
        title="Login",
        constraints=["The session stays valid until the user signs out."],
    )
    evidence_evaluation = evaluate(with_evidence)
    assert "auth.a10_session_behavior" in auth_materialized(evidence_evaluation)
    assert "auth.a10_session_behavior" not in auth_unresolved_keys(
        evidence_evaluation
    )
    assert "session.behavior" in evidence_evaluation.not_applicable

    without = requirement(
        "AUTH-SESSION-GAP", "User signs in to the account.", title="Login"
    )
    gap_evaluation = evaluate(without)
    session_items = [
        item
        for item in gap_evaluation.unresolved
        if item.rule_key == "auth.a10_session_behavior"
    ]
    assert len(session_items) == 1
    assert session_items[0].requires_policy is True
    assert session_items[0].reason


# 8. MFA evidence/policy
def test_mfa_evidence_policy_and_gap() -> None:
    without = requirement(
        "AUTH-MFA-GAP", "User signs in to the account.", title="Login"
    )
    gap_evaluation = evaluate(without)
    mfa_items = [
        item
        for item in gap_evaluation.unresolved
        if item.rule_key == "auth.a12_mfa"
    ]
    assert len(mfa_items) == 1
    assert mfa_items[0].requires_policy is True

    with_evidence = requirement(
        "AUTH-MFA-EVIDENCE",
        "User signs in to the account.",
        title="Login",
        details=["Login requires a one-time password (OTP)."],
    )
    evidence_evaluation = evaluate(with_evidence)
    assert "auth.a12_mfa" in auth_materialized(evidence_evaluation)
    assert "auth.a12_mfa" not in auth_unresolved_keys(evidence_evaluation)

    with_policy = requirement(
        "AUTH-MFA-POLICY",
        "User signs in to the account.",
        title="Login",
        constraints=["MFA is not required for this product."],
    )
    policy_evaluation = evaluate(with_policy)
    assert "auth.a12_mfa" not in auth_unresolved_keys(policy_evaluation)
    assert "auth.a12_mfa" in policy_evaluation.not_applicable

    plan = plan_coverage([with_evidence])
    intents = " ".join(scenario.intent for scenario in plan.requirements[0].scenarios)
    assert "requested" not in intents.lower()


# 9. no-invention corpus scan
FORBIDDEN_INVENTIONS = re.compile(
    r"\b(?:401|403|404|429|500|502|503)\b"
    r"|\b[45]\d{2}\b"
    r"|\b\d+\s+(?:attempts?|minutes?|seconds?|hours?|days?)\b"
    r"|\b(?:locks?|locked)\s+after\b"
    r"|\bexpires?\s+(?:after|in)\b"
    r"|\bsession\s+expires?\b"
    r"|\bmfa\s+is\s+(?:requested|required)\b"
    r"|\botp\s+is\s+requested\b"
    r"|\b(?:two|2)[-\s]?factor\s+is\s+requested\b",
    re.IGNORECASE,
)


def test_no_invented_product_semantics_in_corpus() -> None:
    scanned = 0
    for profile in CANONICAL_PROFILES:
        plan = plan_coverage(corpus(), profile=profile)
        texts = [
            scenario.intent
            for requirement_plan in plan.requirements
            for scenario in requirement_plan.scenarios
        ]
        texts.extend(item.reason for item in plan.unresolved_baseline)
        texts.extend(item.dimension for item in plan.unresolved_baseline)
        for text in texts:
            assert text.strip()
            match = FORBIDDEN_INVENTIONS.search(text)
            assert match is None, f"invented semantics in {profile}: {text!r}"
            scanned += 1
    assert scanned > 100


# 10. Minimal subset Comprehensive subset Extra
def test_minimal_subset_of_comprehensive_subset_of_extra() -> None:
    minimal = identities(plan_coverage(corpus(), profile="minimal"))
    comprehensive = identities(plan_coverage(corpus(), profile="comprehensive"))
    extra = identities(plan_coverage(corpus(), profile="extra"))

    assert set(minimal) <= set(comprehensive)
    assert set(comprehensive) <= set(extra)
    assert len(minimal) < len(comprehensive) < len(extra)


# 11. security only in Comprehensive/Extra
def test_security_only_in_comprehensive_and_extra() -> None:
    for profile, expected in (
        ("minimal", False),
        ("comprehensive", True),
        ("extra", True),
    ):
        plan = plan_coverage(corpus(), profile=profile)
        has_security = any(
            scenario.category == "security" or scenario.technique == "security"
            for requirement_plan in plan.requirements
            for scenario in requirement_plan.scenarios
        )
        assert has_security is expected, profile


# 12. no duplicate intents
def test_no_duplicate_scenario_identities() -> None:
    for profile in CANONICAL_PROFILES:
        plan = plan_coverage(corpus(), profile=profile)
        scenario_ids = [
            scenario.id
            for requirement_plan in plan.requirements
            for scenario in requirement_plan.scenarios
        ]
        assert len(scenario_ids) == len(set(scenario_ids))
        for requirement_plan in plan.requirements:
            seen = [
                (scenario.category, scenario.technique, scenario.intent)
                for scenario in requirement_plan.scenarios
            ]
            assert len(seen) == len(set(seen)), (profile, requirement_plan)


# 13. deterministic planning
def test_deterministic_planning_and_ubi_order() -> None:
    table_order = [
        rule.rule_key for domain in BASELINE_DOMAINS for rule in domain.rules
    ]
    for profile in CANONICAL_PROFILES:
        first = plan_coverage(corpus(), profile=profile)
        second = plan_coverage(corpus(), profile=profile)
        assert repr(first) == repr(second)
        assert first == second

        for index, requirement_plan in enumerate(first.requirements):
            assert requirement_plan.requirement_ref == corpus()[index].id
            for sequence, scenario in enumerate(requirement_plan.scenarios, start=1):
                assert scenario.id == f"{requirement_plan.requirement_ref}-S{sequence:02d}"

        first_keys = [item.rule_key for item in first.unresolved_baseline]
        second_keys = [item.rule_key for item in second.unresolved_baseline]
        assert first_keys == second_keys
        # requirement order first, then fixed rule-table order within each
        # requirement; never interleaved by dict/set iteration.
        position_by_key = {key: index for index, key in enumerate(table_order)}
        for requirement_plan in first.requirements:
            keys_for_requirement = [
                item.rule_key
                for item in first.unresolved_baseline
                if item.requirement_ref == requirement_plan.requirement_ref
            ]
            positions = [position_by_key[key] for key in keys_for_requirement]
            assert positions == sorted(positions)
        requirement_order = [
            item.requirement_ref for item in first.unresolved_baseline
        ]
        expected_order = []
        for requirement in corpus():
            count = sum(
                1
                for item in first.unresolved_baseline
                if item.requirement_ref == requirement.id
            )
            expected_order.extend([requirement.id] * count)
        assert requirement_order == expected_order


# 14. balanced == comprehensive
def test_balanced_alias_matches_comprehensive() -> None:
    requirements = corpus()
    alias_plan = plan_coverage(requirements, profile="balanced")
    canonical_plan = plan_coverage(requirements, profile="comprehensive")
    assert alias_plan == canonical_plan
    assert repr(alias_plan) == repr(canonical_plan)
    assert resolve_profile("balanced") == "comprehensive"


# 15. security alias == comprehensive
def test_security_alias_matches_comprehensive() -> None:
    requirements = corpus()
    alias_plan = plan_coverage(requirements, profile="security")
    canonical_plan = plan_coverage(requirements, profile="comprehensive")
    assert alias_plan == canonical_plan
    assert repr(alias_plan) == repr(canonical_plan)
    assert resolve_profile("security") == "comprehensive"


# 16. default comprehensive
def test_default_profile_is_comprehensive_everywhere() -> None:
    assert DEFAULT_PROFILE == "comprehensive"
    assert set(CANONICAL_PROFILES) == {"minimal", "comprehensive", "extra"}
    assert set(PROFILE_ALIASES) == {"balanced", "security"}

    assert plan_coverage(corpus()) == plan_coverage(corpus(), profile="comprehensive")

    default_args = build_argument_parser().parse_args(["--text", "source"])
    assert default_args.profile == "comprehensive"
    for alias in ("balanced", "security"):
        alias_args = build_argument_parser().parse_args(
            ["--text", "source", "--profile", alias]
        )
        assert alias_args.profile == "comprehensive"
    with pytest.raises(SystemExit):
        build_argument_parser().parse_args(["--text", "source", "--profile", "unknown"])

    assert web_router.TextGenerationRequest(text="source").profile == "comprehensive"

    assert (
        inspect.signature(generate_test_suite).parameters["profile"].default
        == DEFAULT_PROFILE
    )

    with pytest.raises(ValueError) as excinfo:
        resolve_profile("unknown")
    message = str(excinfo.value)
    assert "Unsupported coverage profile" in message
    for canonical in CANONICAL_PROFILES:
        assert canonical in message


# 17. UBI contract
def test_ubi_contract_fields_and_traceability() -> None:
    req = requirement(
        "AUTH-UBI-001",
        "User enters invalid credentials and sees an error message.",
        title="Login",
    )
    plan = plan_coverage([req])

    assert plan.unresolved_baseline, "expected retained UBIs"
    for item in plan.unresolved_baseline:
        assert isinstance(item, UnresolvedBaselineItem)
        assert item.requirement_ref == "AUTH-UBI-001"
        assert item.rule_key
        assert item.dimension
        assert item.status == STATUS_APPLICABLE_UNRESOLVED
        assert item.disposition == DISPOSITION_RETAINED
        assert item.reason
        assert isinstance(item.evidence_refs, tuple)
        assert isinstance(item.requires_policy, bool)
        for ref in item.evidence_refs:
            assert re.fullmatch(r"[A-Za-z0-9-]+-E\d{2}", ref), ref

    covering = [
        scenario
        for scenario in plan.requirements[0].scenarios
        if "invalid credentials" in scenario.intent
    ]
    assert covering
    for scenario in covering:
        assert scenario.requirement_ref == "AUTH-UBI-001"
        assert scenario.id.startswith("AUTH-UBI-001-S")
        assert scenario.evidence_refs
        assert isinstance(scenario.constraint_refs, tuple)

    # UBIs never receive scenario IDs and never enter the scenario list
    scenario_ids = {
        scenario.id
        for requirement_plan in plan.requirements
        for scenario in requirement_plan.scenarios
    }
    assert scenario_ids
    for item in plan.unresolved_baseline:
        assert not set(item.evidence_refs) & scenario_ids


# 18. UBI does not affect coverage/generated_count/status
def test_ubi_does_not_affect_coverage_or_status() -> None:
    result = generate_test_suite(
        auth_parsed_input(), None, profile="comprehensive", adapter=echo_adapter()
    )

    assert result.unresolved_baseline
    assert result.status == "complete"
    assert result.scenario_count == 2
    assert result.generated_count == result.scenario_count
    assert result.generated_count == len(result.test_cases)
    assert result.coverage_percentage == 100.0
    assert result.missing_scenarios == []

    scenario_refs = {case.scenario_ref for case in result.test_cases}
    for item in result.unresolved_baseline:
        assert item.rule_key not in scenario_refs
        for ref in item.evidence_refs:
            assert ref not in scenario_refs
            assert "-S" not in ref


# 19. serialized unresolved_baseline
def test_serialized_unresolved_baseline() -> None:
    result = generate_test_suite(
        auth_parsed_input(), None, profile="comprehensive", adapter=echo_adapter()
    )
    payload = web_router._serialize_result(result, "comprehensive")

    assert payload["profile"] == "comprehensive"
    assert payload["generated_count"] == result.generated_count
    assert payload["coverage_percentage"] == result.coverage_percentage
    serialized = payload["unresolved_baseline"]
    assert serialized
    assert serialized[0]["rule_key"].startswith("auth.")
    for item in serialized:
        assert set(item) == {
            "requirement_ref",
            "rule_key",
            "dimension",
            "status",
            "disposition",
            "reason",
            "evidence_refs",
            "requires_policy",
        }
        assert item["requirement_ref"] == "REQ-AUTH-001"
        assert item["status"] == STATUS_APPLICABLE_UNRESOLVED
    json.dumps(serialized)  # must be JSON-serializable

    original = web_router.generate_test_suite
    original_load = web_router.load_settings
    web_router.load_settings = lambda **_: type(
        "Settings", (), {"provider": "fake", "model": "fake"}
    )()
    try:
        for alias in ("balanced", "security"):
            web_router.generate_test_suite = (
                lambda parsed_input, settings, **kwargs: result
            )
            response = client.post(
                "/api/generate/text", json={"text": "source", "profile": alias}
            )
            assert response.status_code == 200
            body = response.json()
            assert body["profile"] == "comprehensive"
            assert body["unresolved_baseline"]
            assert body["unresolved_baseline"][0]["rule_key"]
            assert body["generated_count"] == result.generated_count
    finally:
        web_router.generate_test_suite = original
        web_router.load_settings = original_load


# 20. failed result has empty unresolved_baseline
def test_failed_result_has_empty_unresolved_baseline() -> None:
    class FailingAdapter:
        def generate_result(self, prompt: str) -> LLMResult:
            raise RuntimeError("provider unavailable")

    result = generate_test_suite(
        auth_parsed_input(),
        None,
        profile="comprehensive",
        adapter=FailingAdapter(),
    )
    assert result.status == "failed"
    assert result.unresolved_baseline == []

    early_failure = generate_test_suite(
        ParsedInput("markdown", "empty.md", ""),
        None,
        profile="comprehensive",
        adapter=echo_adapter(),
    )
    assert early_failure.unresolved_baseline == []


# 21. semantic gate remains intact
def test_semantic_gate_remains_intact(monkeypatch) -> None:
    plan = plan_coverage(corpus(), profile="comprehensive")
    assert plan.unresolved_baseline  # UBIs coexist with a passing gate
    from coverage_auditor import audit_evidence_coverage

    audit = audit_evidence_coverage(plan)
    assert audit.uncovered_evidence_atom_ids == []
    assert audit.incompatible_mapping_ids == []
    assert audit.guardrail_leak_scenario_ids == []

    original = coverage_planner._ensure_evidence_candidates

    def skip_backfill(requirement, candidates, evidence_atoms, subject):
        return candidates

    monkeypatch.setattr(
        coverage_planner, "_ensure_evidence_candidates", skip_backfill
    )
    try:
        plan_coverage(
            [requirement("GATE-001", "The table displays Customer Number.", title="Table")]
        )
    except ValueError as exc:
        assert "Deterministic semantic gate failed" in str(exc)
        assert "uncovered evidence atoms" in str(exc)
    else:
        raise AssertionError("semantic gate did not fire for dropped evidence")
    finally:
        monkeypatch.setattr(
            coverage_planner, "_ensure_evidence_candidates", original
        )
