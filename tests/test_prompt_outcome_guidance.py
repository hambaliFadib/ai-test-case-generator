"""Prompt outcome-guidance regressions.

Provider-free tests: build real plans from the canonical synthetic login
input, then assert the batch prompt carries observable-outcome guidance and
that synthetic model responses for the six previously missing scenarios pass
the existing semantic-quality validator without weakening any rule.
"""

import importlib.util
import sys
from pathlib import Path

from models.coverage_model import EvidenceAtom, ScenarioIntent
from models.input_model import ParsedInput
from models.requirement_model import Requirement
from models.test_case_model import TestCase
from prompt_builder import build_batch_prompt
from semantic_quality import build_authorities, validate_content

_REPO_ROOT = Path(__file__).resolve().parent.parent
_FIXTURE_PATH = _REPO_ROOT / "tests" / "test_coverage_planner.py"


def _smoke_login_text() -> str:
    spec = importlib.util.spec_from_file_location(
        "_smoke_fixture", _FIXTURE_PATH
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["_smoke_fixture"] = module
    spec.loader.exec_module(module)
    return module._SMOKE_LOGIN_TEXT


def _planned_scenarios():
    from coverage_planner import plan_coverage
    from requirement_analyzer import analyze_requirements

    requirements = analyze_requirements(
        ParsedInput("markdown", "smoke-login.md", _smoke_login_text())
    )
    plan = plan_coverage(requirements, profile="minimal")
    scenarios = [
        scenario
        for requirement_plan in plan.requirements
        for scenario in requirement_plan.scenarios
    ]
    return requirements, plan, scenarios


def _authority_for(scenario_id: str):
    _requirements, plan, scenarios = _planned_scenarios()
    authorities = build_authorities(scenarios, plan.evidence_atoms)
    return authorities[scenario_id]


def _case(scenario_id: str, steps: list[str], expected_result: str) -> dict:
    authority = _authority_for(scenario_id)
    scenario = authority.scenario
    return {
        "scenario_id": scenario_id,
        "category": scenario.category,
        "steps": steps,
        "expected_result": expected_result,
        "title": scenario.intent,
        "preconditions": [],
        "violation": validate_content(
            title=scenario.intent,
            preconditions=[],
            steps=steps,
            expected_result=expected_result,
            authority=authority,
        ),
    }


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------


def test_prompt_contains_observable_outcome_guidance() -> None:
    _requirements, _plan, scenarios = _planned_scenarios()
    requirements_by_id = {
        requirement.id: requirement
        for requirement in _requirements
    }
    applicable = [
        scenario
        for scenario in scenarios
        if scenario.objective_kind in {"static_list", "mandatory"}
    ]
    assert applicable, "expected applicable static_list/mandatory scenarios"
    prompt = build_batch_prompt(
        [requirements_by_id[s.requirement_ref] for s in applicable],
        applicable,
    )
    assert "OBSERVABLE OUTCOME GUIDANCE" in prompt
    assert (
        "expected_result must express the observable outcome" in prompt
    )
    assert (
        "not merely repeat the action in the steps" in prompt
    )
    assert "Do not borrow literals, controls, entities" in prompt
    assert "Never invent a form-submission result" in prompt
    assert "Do not expose or repeat an actual password value" in prompt


def test_prompt_guidance_present_for_each_objective_kind() -> None:
    _requirements, _plan, scenarios = _planned_scenarios()
    requirements_by_id = {
        requirement.id: requirement
        for requirement in _requirements
    }
    kinds = {scenario.objective_kind for scenario in scenarios}
    for kind in sorted(kinds):
        selected = [
            scenario
            for scenario in scenarios
            if scenario.objective_kind == kind
        ]
        prompt = build_batch_prompt(
            [requirements_by_id[s.requirement_ref] for s in selected],
            selected,
        )
        assert "OBSERVABLE OUTCOME GUIDANCE" in prompt, kind


def test_prompt_prohibits_borrowing_other_requirements_evidence() -> None:
    first = Requirement(
        id="REQ-001",
        title="Login Form",
        statement="The login form provides a username field.",
    )
    second = Requirement(
        id="REQ-002",
        title="Dashboard",
        statement="After login, the Dashboard is displayed.",
    )
    scenario = ScenarioIntent(
        id="REQ-001-S01",
        requirement_ref="REQ-001",
        category="positive",
        technique="EP",
        intent="Verify the login form provides a username field.",
    )
    prompt = build_batch_prompt([first, second], [scenario])
    assert (
        "Do not borrow literals, controls, entities, field names, messages, "
        "or capabilities from other scenarios or other requirements in this batch"
        in prompt
    )


# ---------------------------------------------------------------------------
# Synthetic responses for the six previously missing scenarios
# ---------------------------------------------------------------------------


def test_req003_valid_login_expresses_supported_outcome() -> None:
    case = _case(
        "REQ-003-S01",
        [
            "Enter a valid username and a valid password.",
            "Submit the valid username and valid password as the username "
            "and password credentials.",
        ],
        "Login is allowed for valid username and valid password.",
    )
    assert case["violation"] is None, case["violation"]


def test_req003_foreign_login_button_literal_is_rejected() -> None:
    # The quoted "Login" button label belongs to REQ-002's evidence.
    # REQ-003's own evidence contains the ordinary word "login",
    # which must not authorize the foreign quoted control literal.
    case = _case(
        "REQ-003-S01",
        ["Enter a valid username and a valid password.", 'Click the "Login" button.'],
        "Login is allowed for valid username and valid password.",
    )
    assert case["violation"] is not None
    assert "literal 'Login'" in case["violation"]


def test_req003_does_not_authorize_dashboard_or_logout() -> None:
    authority = _authority_for("REQ-003-S01")
    assert "dashboard" not in authority.support.lower()
    assert "logout" not in authority.support.lower()
    dashboard_case = _case(
        "REQ-003-S01",
        ["Enter a valid username and a valid password."],
        "The Dashboard is displayed.",
    )
    assert dashboard_case["violation"] is not None
    assert "dashboard" in dashboard_case["violation"]


def test_req005_s02_empty_username_rejected_without_foreign_literal() -> None:
    case = _case(
        "REQ-005-S02",
        ["Leave the Username field empty."],
        "The empty required Username value is rejected.",
    )
    assert case["violation"] is None, case["violation"]
    foreign_login = _case(
        "REQ-005-S02",
        ["Click the \"Login\" button with an empty Username field."],
        "The empty required Username value is rejected.",
    )
    assert foreign_login["violation"] is not None
    assert "literal 'Login'" in foreign_login["violation"]


def test_req006_s02_empty_password_rejected() -> None:
    case = _case(
        "REQ-006-S02",
        ["Leave the Password field empty."],
        "The empty required Password value is prevented.",
    )
    assert case["violation"] is None, case["violation"]


def test_req007_s01_alphanumeric_accepted_without_submission_claim() -> None:
    case = _case(
        "REQ-007-S01",
        ["Enter an alphanumeric value into the username field."],
        "The alphanumeric username value is accepted.",
    )
    assert case["violation"] is None, case["violation"]
    # The parser-level provider-boundary check rejects the unrelated
    # submission workflow that the forensic audit observed.
    from response_parser import _validate_provider_boundary

    authority = _authority_for("REQ-007-S01")
    submission_error = _validate_provider_boundary(
        {
            "steps": ["Enter an alphanumeric username and submit the login form."],
            "expected_result": "The login form submission is accepted.",
        },
        0,
        authority.scenario,
    )
    assert submission_error is not None
    assert "submission outcome" in submission_error


def test_req008_s01_character_acceptance_without_login_workflow() -> None:
    case = _case(
        "REQ-008-S01",
        ["Enter an alphanumeric value with a special character into the password field."],
        "The password value containing alphanumeric and special characters is accepted.",
    )
    assert case["violation"] is None, case["violation"]


def test_req013_s01_masking_outcome_is_observable() -> None:
    case = _case(
        "REQ-013-S01",
        ["Enter a password into the password field."],
        "The entered password is masked and is not displayed as plain text.",
    )
    assert case["violation"] is None, case["violation"]


def test_req013_s01_source_supported_masking_formulation_passes() -> None:
    case = _case(
        "REQ-013-S01",
        ["Enter a password into the password field."],
        "The entered password is not displayed as plain text on the login form.",
    )
    assert case["violation"] is None, case["violation"]


def test_req013_s01_vague_expected_result_still_rejected() -> None:
    case = _case(
        "REQ-013-S01",
        ["Enter a password into the password field."],
        "The password is handled correctly.",
    )
    assert case["violation"] == "expected_result does not state an observable outcome"


def test_req013_masking_guidance_conditioned_on_own_evidence() -> None:
    _requirements, _plan, scenarios = _planned_scenarios()
    requirements_by_id = {
        requirement.id: requirement
        for requirement in _requirements
    }
    masking_scenarios = [
        scenario
        for scenario in scenarios
        if scenario.requirement_ref == "REQ-013"
    ]
    prompt = build_batch_prompt(
        [requirements_by_id[s.requirement_ref] for s in masking_scenarios],
        masking_scenarios,
        evidence_atoms=_plan.evidence_atoms,
    )
    assert "REQ-013-S01" in prompt
    assert "not displayed as plain text" in prompt
    # Password scenario must get password-specific guidance line.
    pw_guidance_lines = [
        line for line in prompt.splitlines() if line.startswith("- REQ-013-S01:")
    ]
    assert pw_guidance_lines, "Expected masking guidance for password scenario"
    assert "password" in " ".join(pw_guidance_lines).lower(), (
        "Password scenario must receive password-specific masking guidance"
    )


def test_sibling_batch_gains_no_masking_guidance() -> None:
    _requirements, _plan, scenarios = _planned_scenarios()
    requirements_by_id = {
        requirement.id: requirement
        for requirement in _requirements
    }
    siblings = [
        scenario
        for scenario in scenarios
        if scenario.requirement_ref != "REQ-013"
    ]
    prompt = build_batch_prompt(
        [requirements_by_id[s.requirement_ref] for s in siblings],
        siblings,
        evidence_atoms=_plan.evidence_atoms,
    )
    assert not any(
        line.startswith("- REQ-") for line in prompt.splitlines()
    )
    assert "REQ-013-S01" not in prompt
    # Global guidance must not assume all sensitive values are passwords.
    assert "password is not displayed" not in prompt.lower(), (
        "Global guidance must not reference password masking specifically"
    )


# ---------------------------------------------------------------------------
# Masking guidance hardening — password-specific only for password + plain text
# ---------------------------------------------------------------------------


def test_non_password_plain_text_gets_neutral_guidance_not_password_masking() -> None:
    """A non-password requirement mentioning 'plain text' in evidence must
    receive neutral obfuscation guidance, not password-specific masking."""
    req = Requirement(
        id="REQ-NOPW",
        title="API error redaction",
        statement="API response must not expose internal error details as plain text.",
        status="TESTABLE",
        details=[],
        acceptance_criteria=[],
        constraints=[],
    )
    atom = EvidenceAtom(
        id="REQ-NOPW-E01",
        requirement_ref="REQ-NOPW",
        kind="observed_value",
        text="internal error details must not be exposed as plain text",
    )
    scenario = ScenarioIntent(
        id="REQ-NOPW-S01",
        requirement_ref="REQ-NOPW",
        category="security",
        technique="negative",
        priority="medium",
        intent=(
            "Verify the explicitly listed item for API error redaction: "
            "internal error details must not be exposed as plain text."
        ),
        evidence_refs=("REQ-NOPW-E01",),
        objective_kind="static_list",
        objective_data={"refs": ("REQ-NOPW-E01",)},
    )
    prompt = build_batch_prompt(
        [req],
        [scenario],
        evidence_atoms=[atom],
    )
    # Must NOT receive password-specific masking guidance (scenario-specific line).
    # The MASKED/NON-DISCLOSED OUTCOME GUIDANCE section contains "password masking"
    # as standard boilerplate; only the injected scenario-specific line matters.
    scenario_guidance_lines = [
        line for line in prompt.splitlines() if line.startswith("- REQ-NOPW-S01:")
    ]
    assert scenario_guidance_lines, "Expected at least one masking guidance line"
    scenario_guidance = " ".join(scenario_guidance_lines).lower()
    assert "password" not in scenario_guidance, (
        "Non-password plain text requirement must not receive password-masking guidance"
    )
    # Must receive neutral obfuscation guidance
    assert scenario_guidance_lines, "Expected masking guidance line for scenario"
    combined_guidance = "\n".join(scenario_guidance_lines)
    assert "not rendered in cleartext" in combined_guidance, (
        "Non-password plain text requirement must receive neutral obfuscation guidance"
    )


def test_password_must_display_as_plain_text_does_not_trigger_masking() -> None:
    """Evidence requiring a password to be displayed as plain text must NOT
    trigger password-masking guidance — only evidence requiring non-disclosure
    triggers masking guidance. """
    req = Requirement(
        id="REQ-DISP-PT",
        title="Diagnostic password display",
        statement="For diagnostic purposes, the entered password must be "
        "displayable as plain text so operators can verify input.",
        status="TESTABLE",
        details=[],
        acceptance_criteria=[],
        constraints=[],
    )
    atom = EvidenceAtom(
        id="REQ-DISP-PT-E01",
        requirement_ref="REQ-DISP-PT",
        kind="observed_value",
        text="password must be displayed as plain text for diagnostic verification",
    )
    scenario = ScenarioIntent(
        id="REQ-DISP-PT-S01",
        requirement_ref="REQ-DISP-PT",
        category="positive",
        technique="EP",
        priority="medium",
        intent=(
            "Verify the explicitly listed item for diagnostic password display: "
            "the entered password must be displayed as plain text for "
            "diagnostic verification."
        ),
        evidence_refs=("REQ-DISP-PT-E01",),
        objective_kind="static_list",
        objective_data={"refs": ("REQ-DISP-PT-E01",)},
    )
    prompt = build_batch_prompt(
        [req],
        [scenario],
        evidence_atoms=[atom],
    )
    # Must NOT receive password-masking guidance line (which mentions masking or
    # "not displayed as plain text").
    scenario_guidance_lines = [
        line for line in prompt.splitlines() if line.startswith("- REQ-DISP-PT-S01:")
    ]
    assert not scenario_guidance_lines, (
        "Evidence requiring display as plain text must not trigger "
        "masking/non-disclosure guidance"
    )


def test_sibling_scenario_without_masking_evidence_gains_no_guidance() -> None:
    """A sibling scenario whose authorized evidence does not mention 'not',
    'plain text', or 'password' together must not receive any masking guidance."""
    req = Requirement(
        id="REQ-SIB",
        title="Login form navigation",
        statement="The login form must be navigable via keyboard.",
        status="TESTABLE",
        details=[],
        acceptance_criteria=[],
        constraints=[],
    )
    atom = EvidenceAtom(
        id="REQ-SIB-E01",
        requirement_ref="REQ-SIB",
        kind="observed_value",
        text="login form is navigable via keyboard and displays a login button",
    )
    scenario = ScenarioIntent(
        id="REQ-SIB-S01",
        requirement_ref="REQ-SIB",
        category="positive",
        technique="EP",
        priority="low",
        intent="Verify keyboard navigation on the login form.",
        evidence_refs=("REQ-SIB-E01",),
        objective_kind="static_list",
        objective_data={"refs": ("REQ-SIB-E01",)},
    )
    prompt = build_batch_prompt(
        [req],
        [scenario],
        evidence_atoms=[atom],
    )
    scenario_guidance_lines = [
        line for line in prompt.splitlines() if line.startswith("- REQ-SIB-S01:")
    ]
    assert not scenario_guidance_lines, (
        "Scenario without masking/negation evidence must not receive masking guidance"
    )


# ---------------------------------------------------------------------------
# Gate invariants remain enforced
# ---------------------------------------------------------------------------


def test_non_observable_expected_result_still_rejected() -> None:
    case = _case(
        "REQ-003-S01",
        ["Enter a valid username and a valid password."],
        "The system handles the credentials correctly.",
    )
    assert case["violation"] == "expected_result does not state an observable outcome"


def test_unsupported_foreign_entity_still_rejected() -> None:
    case = _case(
        "REQ-007-S01",
        ["Enter an alphanumeric username value."],
        "The username value is accepted and the dashboard is displayed.",
    )
    assert case["violation"] is not None
    assert "dashboard" in case["violation"]


def test_masking_evidence_exclusive_to_req013() -> None:
    _requirements, plan, scenarios = _planned_scenarios()
    authorities = build_authorities(scenarios, plan.evidence_atoms)
    masking_atoms = {
        atom.id
        for atom in plan.evidence_atoms
        if "plain text" in atom.text.lower()
    }
    assert masking_atoms, "expected masking atom in plan"
    for scenario in scenarios:
        if scenario.requirement_ref == "REQ-013":
            continue
        assert not (set(scenario.evidence_refs) & masking_atoms), scenario.id
        authority = authorities[scenario.id]
        assert "plain text" not in authority.support.lower(), scenario.id


def test_action_only_intent_not_given_invented_outcome() -> None:
    scenario = ScenarioIntent(
        id="REQ-ACT-S01",
        requirement_ref="REQ-ACT",
        category="positive",
        technique="EP",
        intent="Verify the user submits by clicking \"Login\".",
    )
    requirement = Requirement(
        id="REQ-ACT",
        title="Submit",
        statement="The user submits by clicking \"Login\".",
    )
    authority = build_authorities([scenario], [])[scenario.id]
    invented = validate_content(
        title=scenario.intent,
        preconditions=[],
        steps=["Click the \"Login\" button."],
        expected_result="Login succeeds and the session is created.",
        authority=authority,
    )
    assert invented is not None


def test_presence_only_intent_not_given_state_transition() -> None:
    scenario = ScenarioIntent(
        id="REQ-PRES-S01",
        requirement_ref="REQ-PRES",
        category="positive",
        technique="EP",
        intent="Verify the explicitly listed item for User Login is present.",
    )
    requirement = Requirement(
        id="REQ-PRES",
        title="Login",
        statement="User Login",
    )
    authority = build_authorities([scenario], [])[scenario.id]
    transitioned = validate_content(
        title=scenario.intent,
        preconditions=[],
        steps=["Observe the \"User Login\" item."],
        expected_result="The \"User Login\" item is present and the dashboard is displayed.",
        authority=authority,
    )
    assert transitioned is not None
    assert "dashboard" in transitioned


# ---------------------------------------------------------------------------
# TestCase round-trip (schema unchanged)
# ---------------------------------------------------------------------------


def test_validated_case_round_trips_through_test_case_model() -> None:
    authority = _authority_for("REQ-013-S01")
    scenario = authority.scenario
    case = TestCase(
        id="TC-SMOKE-0001",
        title=scenario.intent,
        category=scenario.category,
        priority="medium",
        preconditions=["The login page is open."],
        steps=["Enter a password into the password field."],
        expected_result="The entered password is masked and is not displayed as plain text.",
        technique=scenario.technique,
        requirement_ref=scenario.requirement_ref,
        scenario_ref=scenario.id,
        language_target="manual",
        generated_at="2026-10-11T00:00:00+00:00",
    )
    assert case.scenario_ref == "REQ-013-S01"
    assert case.requirement_ref == "REQ-013"


# ---------------------------------------------------------------------------
# REQ-003-S01 intent rendering: credential submission + allowed outcome
# ---------------------------------------------------------------------------


def test_req003_intent_expresses_credential_submission_and_allowed_outcome() -> None:
    authority = _authority_for("REQ-003-S01")
    intent = authority.scenario.intent
    assert "submit" in intent.lower(), intent
    assert "valid username" in intent.lower(), intent
    assert "valid password" in intent.lower(), intent
    assert "credential" in intent.lower(), intent
    assert "allowed" in intent.lower(), intent
    # The intent must not invent a UI control, a named submit control,
    # an error message, or a downstream transition.
    assert "button" not in intent.lower(), intent
    assert "dashboard" not in intent.lower(), intent
    assert "logout" not in intent.lower(), intent


def test_req003_generic_credential_submission_passes_full_pipeline() -> None:
    from response_parser import _validate_batch_content

    authority = _authority_for("REQ-003-S01")
    scenario = authority.scenario
    item = {
        "scenario_ref": "REQ-003-S01",
        "title": "Verify login is allowed for valid credentials",
        "preconditions": [],
        "steps": [
            "Submit valid username and valid password as the username "
            "and password credentials.",
        ],
        "expected_result": "Login is allowed for valid username and valid password.",
    }
    assert (
        _validate_batch_content(item, 0, scenario, authority) is None
    )


def test_req003_vague_step_without_concrete_target_still_rejected() -> None:
    case = _case(
        "REQ-003-S01",
        ["Attempt to log in."],
        "Login is allowed for valid username and valid password.",
    )
    assert case["violation"] is not None
    assert "lacks a concrete target" in case["violation"]


def test_req003_foreign_login_button_literal_rejected() -> None:
    # The quoted "Login" control literal belongs to REQ-002's evidence.
    # REQ-003's own evidence contains the bare word "login" only; a
    # bare-word occurrence must not authorize the quoted control literal.
    foreign_login = _case(
        "REQ-003-S01",
        ["Click the \"Login\" button."],
        "Login is allowed for valid username and valid password.",
    )
    assert foreign_login["violation"] is not None
    assert "literal 'Login'" in foreign_login["violation"]


def test_req003_invented_dashboard_outcome_still_rejected() -> None:
    case = _case(
        "REQ-003-S01",
        ["Submit valid username and valid password as credentials."],
        "Login is allowed and the Dashboard is displayed.",
    )
    assert case["violation"] is not None
    assert "dashboard" in case["violation"]


def test_req003_invented_logout_transition_still_rejected() -> None:
    case = _case(
        "REQ-003-S01",
        ["Submit valid username and valid password as credentials."],
        "Login is allowed and logout returns to the Login page.",
    )
    assert case["violation"] is not None
    assert "logout" in case["violation"]


def test_req003_unsupported_dialog_mechanism_still_rejected() -> None:
    # The rendered intent authorizes a generic credential submission,
    # not a specific UI mechanism. A dialog confirmation window is
    # not stated by REQ-003's own evidence.
    from response_parser import _validate_provider_boundary

    authority = _authority_for("REQ-003-S01")
    scenario = authority.scenario
    boundary = _validate_provider_boundary(
        {
            "steps": [
                "Submit valid username and valid password as credentials.",
            ],
            "expected_result": "A dialog confirmation window is displayed.",
        },
        0,
        scenario,
    )
    assert boundary is not None
    assert "dialog behavior" in boundary


def test_req003_generic_credential_submission_is_authorized() -> None:
    from response_parser import _validate_provider_boundary

    authority = _authority_for("REQ-003-S01")
    scenario = authority.scenario
    authorized = _validate_provider_boundary(
        {
            "steps": [
                "Submit valid username and valid password as the username "
                "and password credentials.",
            ],
            "expected_result": "Login is allowed for valid username and valid password.",
        },
        0,
        scenario,
    )
    assert authorized is None, authorized


def test_req003_foreign_login_button_literal_rejected_when_not_authorized() -> None:
    # The quoted "Login" control literal belongs to REQ-002's evidence.
    # A scenario whose own evidence does not contain the word "login"
    # (REQ-005-S02) must reject the foreign literal.
    foreign_login = _case(
        "REQ-005-S02",
        ["Click the \"Login\" button with an empty Username field."],
        "The empty required Username value is rejected.",
    )
    assert foreign_login["violation"] is not None
    assert "literal 'Login'" in foreign_login["violation"]


def test_req003_masking_evidence_exclusive_to_req013() -> None:
    _requirements, plan, scenarios = _planned_scenarios()
    masking_atoms = {
        atom.id
        for atom in plan.evidence_atoms
        if "plain text" in atom.text.lower()
    }
    assert masking_atoms, "expected masking atom in plan"
    for scenario in scenarios:
        if scenario.requirement_ref == "REQ-013":
            continue
        assert not (set(scenario.evidence_refs) & masking_atoms), scenario.id


def test_req003_cross_field_and_foreign_literal_contracts_intact() -> None:
    # REQ-005-S02: cross-field password claim rejected.
    cross_field = _case(
        "REQ-005-S02",
        ["Leave the Username field empty."],
        "The empty required Password value is rejected.",
    )
    assert cross_field["violation"] is not None
    assert "password" in cross_field["violation"]
    # REQ-006-S02: foreign Login literal rejected.
    foreign_login = _case(
        "REQ-006-S02",
        ["Click the \"Login\" button with an empty Password field."],
        "The empty required Password value is prevented.",
    )
    assert foreign_login["violation"] is not None
    assert "literal 'Login'" in foreign_login["violation"]
