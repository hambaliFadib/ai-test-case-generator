from models.coverage_model import CoveragePlan, EvidenceAtom
from models.input_model import ParsedInput
from models.requirement_model import Requirement

from coverage_planner import _is_mandatory, plan_coverage
from requirement_analyzer import analyze_requirements


def requirement(
    requirement_id: str,
    statement: str,
    *,
    title: str = "",
    status: str = "TESTABLE",
    details: list[str] | None = None,
    acceptance_criteria: list[str] | None = None,
    constraints: list[str] | None = None,
) -> Requirement:
    return Requirement(
        id=requirement_id,
        statement=statement,
        title=title,
        status=status,
        details=details or [],
        acceptance_criteria=acceptance_criteria or [],
        constraints=constraints or [],
    )


def test_simple_display_gets_one_positive_scenario() -> None:
    plan = plan_coverage(
        [requirement("MU-001", "The table displays Customer Number.", title="Table")]
    )

    scenarios = plan.requirements[0].scenarios
    assert len(scenarios) == 1
    assert scenarios[0].category == "positive"
    assert scenarios[0].id == "MU-001-S01"
    assert not any(scenario.category == "security" for scenario in scenarios)


def test_statement_supplies_specific_subject_when_title_is_empty() -> None:
    plan = plan_coverage([requirement("REQ-001", "Billing Cycle is mandatory.")])

    assert "Billing Cycle" in plan.requirements[0].scenarios[0].intent


def test_non_testable_statuses_get_zero_scenarios() -> None:
    requirements = [
        requirement("INFO-001", "Background context.", status="INFORMATIONAL"),
        requirement("EX-001", "Do not generate this.", status="EXCLUDED"),
        requirement("OPEN-001", "Behavior is unresolved.", status="UNRESOLVED"),
    ]

    plan = plan_coverage(requirements)

    assert [item.requirement_ref for item in plan.requirements] == [
        "INFO-001",
        "EX-001",
        "OPEN-001",
    ]
    assert [item.scenarios for item in plan.requirements] == [[], [], []]


def test_mandatory_field_gets_valid_and_empty_scenarios() -> None:
    plan = plan_coverage(
        [requirement("CALC-001", "Billing Cycle is mandatory.", title="Billing Cycle")]
    )

    scenarios = plan.requirements[0].scenarios
    assert [scenario.category for scenario in scenarios] == ["positive", "negative"]
    assert "valid populated value" in scenarios[0].intent
    assert "left empty" in scenarios[1].intent
    assert not any(scenario.category == "security" for scenario in scenarios)


def test_negated_mandatory_wording_is_not_treated_as_mandatory() -> None:
    assert not _is_mandatory("SOR is not mandatory.")
    assert not _is_mandatory("Do not assume this field is mandatory.")


def test_maximum_255_gets_bva_values() -> None:
    plan = plan_coverage(
        [requirement("PB-011", "Remark has a maximum of 255 characters.", title="Remark")]
    )

    scenarios = plan.requirements[0].scenarios
    assert len(scenarios) == 3
    assert all(scenario.category == "boundary" for scenario in scenarios)
    assert all(scenario.technique == "BVA" for scenario in scenarios)
    assert [value for value in ("254", "255", "256") if any(value in scenario.intent for scenario in scenarios)] == [
        "254",
        "255",
        "256",
    ]


def test_upload_maximum_10mb_gets_bva_values() -> None:
    plan = plan_coverage(
        [requirement("MU-020", "Max 10MB.", title="Upload")],
        profile="minimal",
    )

    intents = [scenario.intent for scenario in plan.requirements[0].scenarios]
    assert len(intents) == 3
    assert any("9 MB" in intent for intent in intents)
    assert any("10 MB" in intent for intent in intents)
    assert any("11 MB" in intent for intent in intents)


def test_functional_search_plans_only_explicit_behavior_without_invented_semantics() -> None:
    plan = plan_coverage(
        [requirement("MU-003", "Search Content filters displayed rows.", title="Search")],
        profile="minimal",
    )

    intents = " ".join(scenario.intent for scenario in plan.requirements[0].scenarios).lower()
    assert len(plan.requirements[0].scenarios) == 1
    assert "filters displayed rows" in intents
    assert "no matching" not in intents
    assert "wildcard" not in intents
    assert "case sensitivity" not in intents
    assert "fuzzy" not in intents


def test_confirmation_plans_confirm_and_cancel() -> None:
    plan = plan_coverage(
        [
            requirement(
                "CALC-014",
                "Confirmation provides Confirm and Cancel actions.",
                title="Confirmation",
            )
        ]
    )

    scenarios = plan.requirements[0].scenarios
    assert len(scenarios) == 2
    assert "Confirm" in scenarios[0].intent
    assert "Cancel" in scenarios[1].intent
    assert all(scenario.evidence_refs for scenario in scenarios)


def test_success_and_failure_states_are_only_planned_when_supported_by_atoms() -> None:
    plan = plan_coverage(
        [
            requirement(
                "CALC-017",
                "The success and failure result behavior is described.",
                title="Calculation Result",
                acceptance_criteria=[
                    "The system shows a success dialog after a successful result.",
                    "The system shows a failure dialog after an unsuccessful result.",
                ],
            )
        ]
    )

    scenarios = plan.requirements[0].scenarios
    outcomes = [scenario for scenario in scenarios if "success state" in scenario.intent or "failure state" in scenario.intent]
    assert [scenario.category for scenario in outcomes] == ["positive", "negative"]
    assert all(scenario.evidence_refs for scenario in outcomes)
    assert all(
        any(
            atom.id in scenario.evidence_refs
            and ("success" if "success state" in scenario.intent else "failure") in atom.text.lower()
            for atom in plan.evidence_atoms
        )
        for scenario in outcomes
    )


def test_explicit_status_values_get_state_scenarios_without_transitions() -> None:
    plan = plan_coverage(
        [
            requirement(
                "MU-004",
                "Status values include Approved, Awaiting Approval, and Rejected.",
                title="Usage Status Values",
            )
        ]
    )

    scenarios = plan.requirements[0].scenarios
    assert [scenario.intent for scenario in scenarios] == [
        "Verify Usage Status Values displays the explicitly defined Approved state.",
        "Verify Usage Status Values displays the explicitly defined Awaiting Approval state.",
        "Verify Usage Status Values displays the explicitly defined Rejected state.",
    ]
    assert all("transition" not in scenario.intent.lower() for scenario in scenarios)


def test_search_input_without_security_evidence_gets_no_security_scenario() -> None:
    """Evidence Binding v2: security requires declared predicate atoms.

    A generic security intent cannot manufacture its own authority.
    """
    plan = plan_coverage(
        [requirement("SEARCH-001", "User enters Search Content to filter rows.")],
        profile="security",
    )

    security = [
        scenario for scenario in plan.requirements[0].scenarios if scenario.category == "security"
    ]
    assert len(security) == 0


def test_security_profile_only_adds_security_for_security_relevant_surface() -> None:
    plan = plan_coverage(
        [
            requirement("MU-001", "The table displays Customer Number.", title="Table"),
            requirement("AUTH-001", "Only authenticated users can access the page.", title="Access"),
        ],
        profile="security",
    )

    assert not any(scenario.category == "security" for scenario in plan.requirements[0].scenarios)
    assert any(scenario.category == "security" for scenario in plan.requirements[1].scenarios)


def test_planner_is_deterministic_and_preserves_requirement_ids() -> None:
    requirements = [
        requirement("CALC-CREATE-001", "Billing Cycle is mandatory.", title="Billing Cycle"),
        requirement("RATE-006", "Search Content filters displayed rows.", title="Search"),
    ]

    first = plan_coverage(requirements, profile="minimal")
    second = plan_coverage(requirements, profile="minimal")

    assert first == second
    assert [scenario.id for item in first.requirements for scenario in item.scenarios] == [
        "CALC-CREATE-001-S01",
        "CALC-CREATE-001-S02",
        "RATE-006-S01",
    ]


def test_invalid_profile_fails_clearly() -> None:
    try:
        plan_coverage([], profile="unknown")
    except ValueError as exc:
        assert "Unsupported coverage profile" in str(exc)
    else:
        raise AssertionError("Invalid coverage profile did not fail")


def test_atomic_controls_are_planned_independently() -> None:
    plan = plan_coverage(
        [
            requirement(
                "GLOBAL-UI-001",
                "Where shown, list/result tables provide:",
                details=[
                    "Column Settings",
                    "Advanced Search",
                    "Search Content",
                    "column-level filter icon",
                    "column-level sorting control",
                    "footer information",
                ],
            )
        ]
    )

    intents = [scenario.intent for scenario in plan.requirements[0].scenarios]
    joined = " ".join(intents).lower()
    for label in (
        "column settings",
        "advanced search",
        "search content",
        "filter icon",
        "sorting control",
        "footer information",
    ):
        assert label in joined
    assert any("Column Settings is visible and available" in intent for intent in intents)
    assert not any("Column Settings is available for navigation" in intent for intent in intents)
    assert len(intents) >= 6
    assert not any("provides the behavior described" in intent for intent in intents)


def test_atomic_actions_remain_distinct_without_status_assumptions() -> None:
    plan = plan_coverage(
        [requirement("CALC-DETAIL-004", "The result section provides:", details=["Retry", "Recalculate"])]
    )

    intents = [scenario.intent for scenario in plan.requirements[0].scenarios]
    assert any("Retry" in intent for intent in intents)
    assert any("Recalculate" in intent for intent in intents)
    assert not any(
        term in " ".join(intents).lower()
        for term in ("failed records", "successful records", "status eligibility")
    )


def test_atomic_file_type_and_size_constraints_are_both_covered() -> None:
    plan = plan_coverage(
        [
            requirement(
                "MU-020",
                "The upload is restricted.",
                details=["Only PDF is allowed", "Max 10MB"],
                constraints=["Only PDF is allowed", "Max 10MB"],
            )
        ]
    )

    intents = [scenario.intent for scenario in plan.requirements[0].scenarios]
    joined = " ".join(intents).lower()
    assert "accepts pdf files" in joined
    assert "non-pdf" in joined
    assert all(value in joined for value in ("9 mb", "10 mb", "11 mb"))


def test_atomic_tabs_preserve_each_explicit_navigation_item() -> None:
    plan = plan_coverage(
        [
            requirement(
                "MU-001",
                "Monitoring Usage provides two primary tabs:",
                details=["Usage List", "Batch List"],
            )
        ]
    )

    intents = " ".join(scenario.intent for scenario in plan.requirements[0].scenarios)
    assert "Usage List" in intents
    assert "Batch List" in intents
    assert "invented" not in intents.lower()


def test_atomic_parent_sentence_does_not_add_redundant_scenario() -> None:
    plan = plan_coverage(
        [
            requirement(
                "RATE-002",
                "The page provides:",
                details=["Download List", "Column Settings", "Search Content"],
            )
        ]
    )

    intents = [scenario.intent for scenario in plan.requirements[0].scenarios]
    assert not any("page provides" in intent.lower() for intent in intents)
    assert not any("provides the behavior described" in intent.lower() for intent in intents)


def test_atomic_behavior_repeated_across_fields_is_deduplicated() -> None:
    plan = plan_coverage(
        [
            requirement(
                "SEARCH-001",
                "Search Content filters displayed rows.",
                details=["Search Content"],
                acceptance_criteria=["Search Content filters displayed rows."],
            )
        ],
        profile="minimal",
    )

    scenarios = plan.requirements[0].scenarios
    assert len(scenarios) == 2
    assert scenarios[0].id == "SEARCH-001-S01"
    assert scenarios[1].id == "SEARCH-001-S02"


def test_atomic_similar_controls_remain_distinct() -> None:
    plan = plan_coverage(
        [
            requirement(
                "SEARCH-002",
                "The page provides:",
                details=["Search Content", "Advanced Search"],
            )
        ],
        profile="minimal",
    )

    intents = " ".join(scenario.intent for scenario in plan.requirements[0].scenarios)
    assert intents.count("Search Content") == 1
    assert "Advanced Search" in intents
    assert len(plan.requirements[0].scenarios) == 2


def test_atomic_planning_is_deterministic() -> None:
    requirements = [
        requirement(
            "ATOMIC-001",
            "The page provides:",
            details=["Search Content", "Retry", "Recalculate"],
        )
    ]

    first = plan_coverage(requirements)
    second = plan_coverage(requirements)
    assert first == second


def test_search_control_presence_does_not_infer_search_results() -> None:
    plan = plan_coverage(
        [requirement("ATOMIC-SEARCH-PRESENCE", "The page provides:", details=["Search Content"])],
        profile="minimal",
    )

    scenarios = plan.requirements[0].scenarios
    assert len(scenarios) == 1
    assert "Search Content" in scenarios[0].intent
    assert "match" not in scenarios[0].intent.lower()
    assert "no-result" not in scenarios[0].intent.lower()


def test_functional_search_uses_only_explicit_search_facts() -> None:
    plan = plan_coverage(
        [
            requirement(
                "ATOMIC-SEARCH-FUNCTIONAL",
                "Where Search Content is available:",
                details=[
                    "user can enter search content",
                    "displayed rows are expected to follow the applied search result",
                ],
            )
        ]
    )

    intents = " ".join(scenario.intent for scenario in plan.requirements[0].scenarios).lower()
    assert "user can enter search content" in intents
    assert "displayed rows are expected to follow" in intents
    assert "no matching" not in intents
    assert "empty result" not in intents


def test_billing_period_control_presence_stays_presence_only() -> None:
    plan = plan_coverage(
        [requirement("ATOMIC-BILLING-PRESENCE", "The page provides:", details=["Billing Period filter"])],
        profile="minimal",
    )

    scenarios = plan.requirements[0].scenarios
    assert len(scenarios) == 1
    assert "Billing Period filter" in scenarios[0].intent
    assert "match" not in scenarios[0].intent.lower()


def test_billing_period_functional_acceptance_is_not_duplicated() -> None:
    plan = plan_coverage(
        [
            requirement(
                "ATOMIC-BILLING-FUNCTIONAL",
                "A Billing Period filter is available on Rating List.",
                details=[
                    "Expected:",
                    "user can select/apply a Billing Period criterion",
                    "the displayed result follows the applied criterion",
                ],
                acceptance_criteria=[
                    "user can select/apply a Billing Period criterion",
                    "the displayed result follows the applied criterion",
                ],
            )
        ],
        profile="minimal",
    )

    scenarios = plan.requirements[0].scenarios
    intents = " ".join(scenario.intent for scenario in scenarios).lower()
    # Evidence Binding v2: every non-guardrail atom gets declared coverage.
    # The statement atom "A Billing Period filter is available..." is also
    # covered by a static_list backfill candidate.
    assert len(scenarios) == 3
    assert "select/apply a billing period criterion" in intents
    assert "displayed result follows the applied criterion" in intents
    assert "billing period filter is available" in intents
    assert "no matching" not in intents


def test_search_behavior_does_not_cross_into_presence_only_requirement() -> None:
    plan = plan_coverage(
        [
            requirement("ATOMIC-SEARCH-BEHAVIOR", "Search Content filters displayed rows."),
            requirement("ATOMIC-SEARCH-PRESENCE-2", "The page provides:", details=["Search Content"]),
        ]
    )

    behavior_intent = plan.requirements[0].scenarios[0].intent.lower()
    presence_intent = plan.requirements[1].scenarios[0].intent.lower()
    assert "filters displayed rows" in behavior_intent
    assert "visible and available" in presence_intent
    assert "filters displayed rows" not in presence_intent


def test_column_settings_presence_and_functional_behavior_are_distinct() -> None:
    presence = plan_coverage(
        [requirement("ATOMIC-COLUMNS-PRESENCE", "The page provides:", details=["Column Settings"])]
    )
    functional = plan_coverage(
        [requirement("ATOMIC-COLUMNS-FUNCTIONAL", "Column Settings controls column visibility.")]
    )

    assert "visible and available" in presence.requirements[0].scenarios[0].intent
    assert "controls column visibility" in functional.requirements[0].scenarios[0].intent


def test_explicit_no_result_evidence_can_create_negative_coverage() -> None:
    plan = plan_coverage(
        [requirement("ATOMIC-EMPTY-RESULT", "Search displays an empty result state when no matching rows exist.")],
        profile="minimal",
    )

    scenarios = plan.requirements[0].scenarios
    assert len(scenarios) == 1
    assert scenarios[0].category == "negative"
    assert "empty result state" in scenarios[0].intent.lower()


# ---------------------------------------------------------------------------
# Analyzer provenance regression (Evidence Binding v2 smoke regression)
# ---------------------------------------------------------------------------

_SMOKE_LOGIN_TEXT = """\
User Login

The system provides a login form with:
- Username
- Password

The user submits by clicking "Login".
The system accepts valid username+valid password and allows login.
If username/password combination invalid, displays "Invalid username or password".
Username required.
Password required.
Username accepts alphanumeric.
Password accepts alphanumeric and special characters.
After successful login, displays Dashboard.
Dashboard provides Logout.
Logout returns to Login page.
Login page displays Forgot Password link.
Login form must not expose entered password as plain text.
"""


def test_minimal_plan_after_provenance_fix() -> None:
    from models.input_model import ParsedInput
    from requirement_analyzer import analyze_requirements

    requirements = analyze_requirements(
        ParsedInput("markdown", "smoke-login.md", _SMOKE_LOGIN_TEXT)
    )
    assert len(requirements) == 13

    plan = plan_coverage(requirements, profile="minimal")
    scenarios = [
        scenario
        for requirement_plan in plan.requirements
        for scenario in requirement_plan.scenarios
    ]
    scenario_ids = [scenario.id for scenario in scenarios]
    assert len(scenarios) == 15
    assert "REQ-005-S03" not in scenario_ids
    assert "REQ-006-S03" not in scenario_ids

    masking_refs = {
        scenario.id: scenario.evidence_refs
        for scenario in scenarios
        if any(
            atom.id in scenario.evidence_refs
            and "plain text" in atom.text.lower()
            for atom in plan.evidence_atoms
        )
    }
    assert list(masking_refs) == ["REQ-013-S01"]

    for scenario in scenarios:
        if scenario.requirement_ref != "REQ-013":
            assert not any(
                atom.id in scenario.evidence_refs
                and "plain text" in atom.text.lower()
                for atom in plan.evidence_atoms
            )


# ---------------------------------------------------------------------------
# Intent-shaping regressions — evidence-grounded rendering
# ---------------------------------------------------------------------------

def test_req003_valid_login_preserves_outcome_without_dashboard() -> None:
    """REQ-003 preserves valid-login outcome; no Dashboard leakage."""
    plan = plan_coverage(
        [requirement("REQ-003", "The system accepts valid username+valid password and allows login.")],
        profile="minimal",
    )
    intent = plan.requirements[0].scenarios[0].intent.lower()
    # The intent expresses the generic credential submission and the
    # allowed-login outcome, without naming a UI control.
    assert "submit" in intent
    assert "credential" in intent
    assert "valid username" in intent
    assert "valid password" in intent
    assert "allowed" in intent
    assert "dashboard" not in intent
    assert "logout" not in intent
    assert "button" not in intent


def test_system_action_verbs_are_rendered_as_behavior() -> None:
    statements = [
        "The system validates the email address.",
        "The system creates a record.",
        "The system updates the record.",
        "The system sends a notification.",
    ]
    for index, statement in enumerate(statements, start=1):
        plan = plan_coverage(
            [requirement(f"SYS-ACTION-{index:03d}", statement)],
            profile="minimal",
        )
        intent = " ".join(
            scenario.intent for scenario in plan.requirements[0].scenarios
        ).lower()
        assert statement.rstrip(".").lower() in intent
        assert "explicitly listed items" not in intent


def test_unlisted_system_predicates_are_rendered_as_behavior() -> None:
    statements = [
        "The system processes a payment.",
        "The system publishes an update.",
        "The system synchronizes records.",
    ]
    for index, statement in enumerate(statements, start=1):
        plan = plan_coverage(
            [requirement(f"SYS-FALLBACK-{index:03d}", statement)],
            profile="minimal",
        )
        scenarios = plan.requirements[0].scenarios
        assert scenarios
        intent = " ".join(scenario.intent for scenario in scenarios).lower()
        assert statement.rstrip(".").lower() in intent
        assert "explicitly listed items" not in intent


def test_modal_system_predicates_are_rendered_as_behavior() -> None:
    statements = [
        "The system must process a payment.",
        "The system should publish an update.",
        "The system can synchronize records.",
        "The system does not process an invalid payment.",
        "The system can be configured to use single sign-on.",
        "The system must be able to process payments.",
    ]
    for index, statement in enumerate(statements, start=1):
        plan = plan_coverage(
            [requirement(f"SYS-MODAL-{index:03d}", statement)],
            profile="minimal",
        )
        scenarios = plan.requirements[0].scenarios
        assert scenarios
        intent = " ".join(scenario.intent for scenario in scenarios).lower()
        assert statement.rstrip(".").lower() in intent
        assert "explicitly listed items" not in intent


def test_negated_provides_statement_checks_control_absence() -> None:
    plan = plan_coverage(
        [
            requirement(
                "NEG-PROVIDES-001",
                "The system does not provide a Delete button.",
            )
        ],
        profile="minimal",
    )
    scenarios = plan.requirements[0].scenarios
    assert scenarios
    intent = " ".join(scenario.intent.lower() for scenario in scenarios)
    assert "delete button" in intent
    assert "is absent" in intent
    assert "visible and available" not in intent
    assert "not visible or available" not in intent


def test_possessive_ui_subject_remains_presence_only() -> None:
    plan = plan_coverage(
        [
            requirement(
                "POSSESSIVE-PRESENCE-001",
                "The user's dashboard provides Logout.",
            )
        ],
        profile="minimal",
    )
    scenarios = plan.requirements[0].scenarios
    assert scenarios
    intent = " ".join(scenario.intent.lower() for scenario in scenarios)
    assert "logout" in intent
    assert "visible and available" in intent
    assert "explicitly listed items" not in intent


def test_unlisted_system_predicate_allows_punctuation_in_object() -> None:
    statement = "The system processes a payment of $12.50."
    plan = plan_coverage(
        [requirement("SYS-FALLBACK-CURRENCY-001", statement)],
        profile="minimal",
    )
    scenarios = plan.requirements[0].scenarios
    assert scenarios
    intent = " ".join(scenario.intent for scenario in scenarios).lower()
    assert "processes a payment of $12.50" in intent
    assert "explicitly listed items" not in intent


def test_conditional_provides_sentence_keeps_behavior_intent() -> None:
    plan = plan_coverage(
        [
            requirement(
                "PROVIDES-BEHAVIOR-001",
                "The system provides search results after the user submits a query.",
            )
        ],
        profile="minimal",
    )
    scenarios = plan.requirements[0].scenarios
    assert scenarios
    intent = " ".join(scenario.intent for scenario in scenarios).lower()
    assert "after the user submits a query" in intent
    assert "visible and available" not in intent


def test_provides_sentence_with_numeric_limit_keeps_boundary_coverage() -> None:
    plan = plan_coverage(
        [
            requirement(
                "PROVIDES-LIMIT-001",
                "The form provides a maximum of 10 characters.",
            )
        ],
        profile="minimal",
    )
    scenarios = plan.requirements[0].scenarios
    intents = " ".join(scenario.intent.lower() for scenario in scenarios)
    assert len(scenarios) == 3
    assert all(scenario.category == "boundary" for scenario in scenarios)
    assert all(value in intents for value in ("9 characters", "10 characters", "11 characters"))


def test_req009_dashboard_visibility_no_form_steps() -> None:
    """REQ-009 verifies Dashboard visibility without inventing form submission."""
    plan = plan_coverage(
        [requirement("REQ-009", "After successful login, displays Dashboard.")],
        profile="minimal",
    )
    scenario = plan.requirements[0].scenarios[0]
    intent = scenario.intent
    # Login is precondition; Dashboard is verification target.
    assert "successful login" in intent.lower()
    assert "dashboard" in intent.lower()
    assert "password" not in intent.lower()
    assert "type" not in intent.lower()


def test_req010_logout_presence_only() -> None:
    """REQ-010 checks presence only; does not assert logout transition."""
    plan = plan_coverage(
        [requirement("REQ-010", "Dashboard provides Logout.")],
        profile="minimal",
    )
    intent = plan.requirements[0].scenarios[0].intent
    assert "visible and available" in intent
    assert "logout" in intent.lower()
    # Must NOT assert what Logout does (transition belongs to REQ-011).
    assert "returns" not in intent.lower() or "login page" not in intent.lower()


def test_req011_returns_to_login_no_dashboard_claim() -> None:
    """REQ-011 verifies return-to-login without introducing unsupported Dashboard claims."""
    plan = plan_coverage(
        [requirement("REQ-011", "Logout returns to Login page.")],
        profile="minimal",
    )
    intent = plan.requirements[0].scenarios[0].intent
    intent_lower = intent.lower()
    assert "login page" in intent_lower
    assert "logout" in intent_lower
    # Must NOT introduce a Dashboard assertion into its title/steps/result.
    assert "dashboard" not in intent_lower


def test_req001_not_promoted_to_fabricated_test() -> None:
    """REQ-001 source ('User Login') doesn't specify product behaviour or observable result."""
    plan = plan_coverage(
        [requirement("REQ-001", "User Login")],
        profile="minimal",
    )
    scenario = plan.requirements[0].scenarios[0]
    intent = scenario.intent.lower()
    # No fabricated functional keywords — no login-form, no password, no dashboard,
    # no navigation, no authentication verb we haven't seen in evidence.
    forbidden = ("login form", "enter password", "dashboard", "navigate", "click")
    for phrase in forbidden:
        assert phrase not in intent, f"Fabricated phrase found: '{phrase}' in '{intent}'"


def test_static_list_with_multiple_evidence_refs_preserves_all_labels() -> None:
    """Multi-ref static_list must render ALL evidence labels, not just the first.

    Regression guard: render_intent() must check len(labels) > 1 *before*
    applying behavior/presence single-label rendering, so no evidence is lost.
    """
    req = requirement(
        "REQ-001",
        "Login page must display the following elements.",
        details=["Username field", "Password field", "Login button"],
    )
    plan = plan_coverage([req], profile="minimal")
    # The multi-label static_list scenario is the one with >1 evidence ref.
    multi_ref_scenarios = [
        s for rp in plan.requirements for s in rp.scenarios
        if s.objective_kind == "static_list"
        and len(s.objective_data.get("refs") or ()) > 1
    ]
    assert len(multi_ref_scenarios) == 1, f"Expected 1 multi-ref scenario, got {len(multi_ref_scenarios)}"
    scenario = multi_ref_scenarios[0]
    intent = scenario.intent
    # Every evidence label must appear in the rendered intent.
    assert "Username field" in intent, f"Missing 'Username field' in: {intent}"
    assert "Password field" in intent, f"Missing 'Password field' in: {intent}"
    # The first label (statement) should also be present.
    assert "Login page must display the following elements" in intent, (
        f"Missing statement label in: {intent}"
    )


def test_static_list_evidence_order_preserved_not_alphabetized() -> None:
    """render_intent() must preserve refs order from objective_data, not sort."""
    from coverage_planner import render_intent

    # Atoms deliberately ordered so alphabetical sorting differs from refs order.
    atom_b = EvidenceAtom(id="atom-B", requirement_ref="REQ-Z", kind="label", text="Zebra text")
    atom_a = EvidenceAtom(id="atom-A", requirement_ref="REQ-Z", kind="label", text="Apple text")
    atoms = [atom_b, atom_a]
    # refs in non-alphabetical, non-ID order: B then A
    intent = render_intent(
        "REQ-Z",
        "static_list",
        {"refs": ("atom-B", "atom-A")},
        atoms,
        "subject Z",
    )
    assert "Zebra text" in intent
    assert "Apple text" in intent
    # Zebra (atom-B) must appear before Apple (atom-A) — refs order preserved.
    assert intent.index("Zebra text") < intent.index("Apple text"), (
        f"Evidence order not preserved in: {intent}"
    )


def test_req002_no_invented_system_outcome() -> None:
    """REQ-002 identifies an action but defines no independent resulting behaviour."""
    req = requirement("REQ-002", 'The user submits by clicking "Login".')
    plan = plan_coverage([req], profile="minimal")
    scenario = plan.requirements[0].scenarios[0]
    intent = scenario.intent.lower()
    # Must not invent success state, error, password-behavior, or navigation.
    forbidden = {"accepted", "rejected", "error", "invalid", "success", "redirected"}
    assert not any(word in intent for word in forbidden), (
        f"REQ-002 intent invented system outcome: '{intent}'"
    )


def test_all_15_scenarios_correct_evidence_ownership() -> None:
    """Every scenario's evidence_refs are requirement-local."""
    requirements = analyze_requirements(
        ParsedInput("markdown", "smoke-login.md", _SMOKE_LOGIN_TEXT)
    )
    plan = plan_coverage(requirements, profile="minimal")
    all_scenarios = []
    for rp in plan.requirements:
        all_scenarios.extend(rp.scenarios)
    atoms_by_id = {a.id: a for a in plan.evidence_atoms}
    for s in all_scenarios:
        for eid in s.evidence_refs:
            atom = atoms_by_id.get(eid)
            assert atom is not None, f"{s.id} references unknown atom {eid}"
            assert atom.requirement_ref == s.requirement_ref, (
                f"{s.id} has foreign evidence atom {eid} from {atom.requirement_ref}"
            )


def test_masking_evidence_exclusive_to_req013() -> None:
    """Password masking evidence remains exclusive to REQ-013."""
    requirements = analyze_requirements(
        ParsedInput("markdown", "smoke-login.md", _SMOKE_LOGIN_TEXT)
    )
    plan = plan_coverage(requirements, profile="minimal")
    all_scenarios = []
    for rp in plan.requirements:
        all_scenarios.extend(rp.scenarios)
    atoms_by_id = {a.id: a for a in plan.evidence_atoms}
    masking_atoms = {
        a.id
        for a in plan.evidence_atoms
        if "plain text" in a.text.lower()
    }
    for s in all_scenarios:
        if s.requirement_ref == "REQ-013":
            continue
        for eid in s.evidence_refs:
            assert eid not in masking_atoms, (
                f"{s.id} leaked masking atom {eid}"
            )



def test_user_selects_period_is_planned_as_explicit_behavior() -> None:
    plan = plan_coverage(
        [requirement("V133-ACTION-001", "The user selects a period.")],
        profile="minimal",
    )

    scenarios = plan.requirements[0].scenarios
    assert len(scenarios) == 1
    assert scenarios[0].objective_kind == "behavior"
    assert "user selects a period" in scenarios[0].intent.lower()
    assert scenarios[0].evidence_refs
    assert any(
        atom.id in scenarios[0].evidence_refs
        and atom.kind == "explicit_behavior"
        for atom in plan.evidence_atoms
    )


def test_system_provides_logout_is_planned_as_presence_not_behavior() -> None:
    plan = plan_coverage(
        [requirement("V133-PRESENCE-001", "The system provides Logout.")],
        profile="minimal",
    )

    scenarios = plan.requirements[0].scenarios
    assert len(scenarios) == 1
    assert scenarios[0].objective_kind == "presence"
    assert "logout" in scenarios[0].intent.lower()
    assert "visible and available" in scenarios[0].intent.lower()
    assert "provides the behavior described" not in scenarios[0].intent.lower()
    assert scenarios[0].evidence_refs
    assert any(
        atom.id in scenarios[0].evidence_refs
        and atom.kind == "presence"
        for atom in plan.evidence_atoms
    )


def test_conditional_provides_results_is_planned_as_behavior_not_presence() -> None:
    req = requirement(
        "V133-CONDITIONAL-PROVIDES",
        "The system provides search results after the user submits a query.",
        title="Search",
    )
    plan = plan_coverage([req], profile="minimal")
    scenarios = plan.requirements[0].scenarios

    assert any(s.objective_kind == "behavior" for s in scenarios)
    assert not any(
        s.objective_kind == "presence"
        and "visible and available" in s.intent.lower()
        for s in scenarios
    )
    assert any(
        atom.kind == "explicit_behavior"
        and atom.id in scenarios[0].evidence_refs
        for atom in plan.evidence_atoms
    )


def test_provides_sentence_with_numeric_limit_keeps_boundary_coverage() -> None:
    req = requirement(
        "V133-PROVIDES-LIMIT",
        "The page provides a Search field with a maximum of 10 characters.",
        title="Search",
    )
    plan = plan_coverage([req], profile="minimal")
    scenarios = plan.requirements[0].scenarios

    assert len(scenarios) == 3
    assert all(s.category == "boundary" and s.technique == "BVA" for s in scenarios)
    assert not any(s.objective_kind == "presence" for s in scenarios)


def test_common_system_verbs_are_planned_as_behavior() -> None:
    examples = (
        ("V133-VERB-VALIDATES", "The system validates the email address."),
        ("V133-VERB-CREATES", "The system creates a report."),
        ("V133-VERB-UPDATES", "The system updates a record."),
        ("V133-VERB-SENDS", "The system sends the notification."),
    )
    for req_id, statement in examples:
        plan = plan_coverage(
            [requirement(req_id, statement, title="System action")],
            profile="minimal",
        )
        scenarios = plan.requirements[0].scenarios
        assert any(s.objective_kind == "behavior" for s in scenarios), (
            f"Expected behavior scenario for {statement!r}; got "
            f"{[(s.objective_kind, s.intent) for s in scenarios]}"
        )
        assert not any(
            s.objective_kind == "static_list"
            for s in scenarios
        ), f"System action should not fall back to static_list: {statement!r}"
