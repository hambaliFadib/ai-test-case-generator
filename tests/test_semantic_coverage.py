from coverage_auditor import audit_evidence_coverage
from coverage_planner import plan_coverage
from models.coverage_model import CoveragePlan, EvidenceAtom, RequirementCoveragePlan, ScenarioIntent
from models.requirement_model import Requirement


def make_requirement(
    requirement_id: str,
    statement: str,
    *,
    title: str = "",
    details: list[str] | None = None,
    acceptance_criteria: list[str] | None = None,
    constraints: list[str] | None = None,
) -> Requirement:
    return Requirement(
        id=requirement_id,
        statement=statement,
        title=title,
        details=details or [],
        acceptance_criteria=acceptance_criteria or [],
        constraints=constraints or [],
    )


def scenario_text(plan, requirement_id: str) -> str:
    requirement_plan = next(
        item for item in plan.requirements if item.requirement_ref == requirement_id
    )
    return " ".join(scenario.intent for scenario in requirement_plan.scenarios)


def test_static_schema_and_action_atoms_are_complete_and_aggregated() -> None:
    requirements = [
        make_requirement(
            "SEM-001",
            "The visible columns include:",
            details=["No", "Row ID", "Customer Number", "Status", "Action", "Created At", "Remark"],
        ),
        make_requirement(
            "SEM-002",
            "The footer provides:",
            details=["Cancel", "Clear Data", "Save Changes"],
        ),
    ]

    plan = plan_coverage(requirements)
    audit = audit_evidence_coverage(plan)

    assert audit.uncovered_evidence_atom_ids == []
    assert all(value.lower() in scenario_text(plan, "SEM-001").lower() for value in [
        "No", "Row ID", "Customer Number", "Status", "Action", "Created At", "Remark",
    ])
    assert all(value.lower() in scenario_text(plan, "SEM-002").lower() for value in [
        "Cancel", "Clear Data", "Save Changes",
    ])


def test_presence_only_action_does_not_invent_behavior_or_cross_requirement_facts() -> None:
    plan = plan_coverage(
        [
            make_requirement("SEM-003", "The page provides:", details=["Cancel"]),
            make_requirement("SEM-004", "Cancel keeps the user on the form."),
        ]
    )

    presence = scenario_text(plan, "SEM-003").lower()
    assert "visible and available" in presence
    assert not any(term in presence for term in ("navigate", "discard", "save", "close"))
    assert "keeps the user on the form" not in presence


def test_observed_states_options_and_samples_are_all_source_backed() -> None:
    plan = plan_coverage(
        [
            make_requirement(
                "SEM-005",
                "Status values include Submitted, Approved, Rejected, and Re-submitted.",
                title="Approval History",
            ),
            make_requirement(
                "SEM-006",
                "Visible options include:",
                title="Component",
                details=["Usage", "Service Agreement", "Late Charge Calculation"],
            ),
            make_requirement(
                "SEM-008",
                "A visible sample value is:",
                title="Format Usage Type",
                details=["Final/Need Calculated"],
            ),
        ]
    )

    assert all(
        value.lower() in scenario_text(plan, "SEM-005").lower()
        for value in ("Submitted", "Approved", "Rejected", "Re-submitted")
    )
    assert all(
        value.lower() in scenario_text(plan, "SEM-006").lower()
        for value in ("Usage", "Service Agreement", "Late Charge Calculation")
    )
    sample = scenario_text(plan, "SEM-008")
    assert "Final/Need Calculated" in sample
    assert "only" not in sample.lower()


def test_no_substring_collision_between_calculate_and_recalculate() -> None:
    plan = plan_coverage(
        [
            make_requirement(
                "SEM-007",
                "Visible Action values include:",
                title="Log Actions",
                details=["Retry", "Recalculate", "Calculate"],
            )
        ]
    )
    text = scenario_text(plan, "SEM-007")
    assert "Retry" in text
    assert "Recalculate" in text
    assert "Calculate" in text


def test_guardrails_are_not_promoted_to_evidence_or_behavior() -> None:
    plan = plan_coverage(
        [
            make_requirement(
                "SEM-009",
                "Search Content filters displayed rows.",
                constraints=["Do not infer exact behavior.", "The exact eligibility conditions are not defined."],
            )
        ]
    )
    text = scenario_text(plan, "SEM-009").lower()
    assert "filters displayed rows" in text
    assert "do not infer exact behavior" not in text
    assert "eligibility conditions" not in text


def _semantic_blocker_requirements() -> list[Requirement]:
    return [
        make_requirement("SEM-010", "Displayed rows follow the applied search result."),
        make_requirement(
            "SEM-011",
            "The visible columns include:",
            details=["No", "Row ID", "Customer Number", "Customer Name", "Account Number", "Status", "Action"],
        ),
        make_requirement(
            "SEM-012",
            "The summary columns include:",
            details=["No", "Usage", "Succeed", "Progress", "Failed", "Status", "Action"],
        ),
        make_requirement(
            "SEM-013",
            "The history information includes:",
            details=["Row ID", "Total Row", "Total Progress", "Generated Date", "Status", "Download Failed Data"],
        ),
        make_requirement(
            "SEM-014",
            "The result columns include:",
            details=["No", "Row ID", "Customer Number", "Customer Name", "Account Number", "Status", "Action"],
        ),
        make_requirement(
            "SEM-015",
            "The form provides:",
            details=["Format Usage Type", "upload area", "file/link input", "Download Template", "Cancel", "Upload"],
        ),
        make_requirement("SEM-016", "A visible sample value is:", details=["Final/Need Calculated"]),
        make_requirement(
            "SEM-017",
            "Upload states include:",
            details=["upload in progress", "upload completed", "failed upload", "file delete/remove", "Try Again"],
        ),
        make_requirement(
            "SEM-018",
            "Status values include SUBMITTED, APPROVED, REJECTED, and RE-SUBMITTED.",
        ),
        make_requirement(
            "SEM-019",
            "The calculation columns include:",
            details=["No", "Calculation Code", "Customer", "Succeed", "Progress", "Status", "Type", "Action"],
        ),
        make_requirement(
            "SEM-020",
            "The create form provides:",
            details=["Cancel", "Clear Data", "Save Changes"],
        ),
        make_requirement(
            "SEM-021",
            "The form provides:",
            details=["Billing Cycle", "Billing Period", "Calculation Type", "Service Type", "SOR", "Cost Center", "Cancel", "Confirm"],
        ),
        make_requirement("SEM-023", "Try Again is available to retry the operation."),
        make_requirement(
            "SEM-024",
            "The detail columns include:",
            details=["No", "Action", "Type", "Calculate At", "Calculate By", "Remark"],
        ),
        make_requirement(
            "SEM-025",
            "The result actions include:",
            details=["Retry", "Recalculate", "Calculate"],
        ),
        make_requirement(
            "SEM-026",
            "The source categories include:",
            details=["Rating", "Rating and Billing"],
        ),
        make_requirement(
            "SEM-027",
            "The list columns include:",
            details=["No", "Init Code", "SOR", "Billing Cycle", "Billing Period", "Status", "Action"],
        ),
        make_requirement(
            "SEM-028",
            "Visible options include:",
            details=["Usage", "Service Agreement", "Late Charge Calculation"],
        ),
        make_requirement(
            "SEM-029",
            "The detail form provides:",
            details=["No", "Customer Number", "Customer Name", "Customer Type ID", "Billing Cycle", "Billing Period", "Action"],
        ),
    ]


def test_source_backed_semantic_blockers_have_planned_coverage() -> None:
    requirements = _semantic_blocker_requirements()
    plan = plan_coverage(requirements)
    audit = audit_evidence_coverage(plan)
    by_id = {item.requirement_ref: item for item in plan.requirements}

    required_terms = {
        "SEM-010": ["follow the applied search result"],
        "SEM-011": ["No", "Row ID", "Customer Number", "Customer Name", "Account Number", "Status", "Action"],
        "SEM-012": ["No", "Usage", "Succeed", "Progress", "Failed", "Status", "Action"],
        "SEM-013": ["Row ID", "Total Row", "Total Progress", "Generated Date", "Status", "Download Failed Data"],
        "SEM-014": ["No", "Row ID", "Customer Number", "Customer Name", "Account Number", "Status", "Action"],
        "SEM-015": ["Format Usage Type", "upload area", "file/link input", "Download Template", "Cancel", "Upload"],
        "SEM-016": ["Final/Need Calculated"],
        "SEM-017": ["upload in progress", "upload completed", "failed upload", "file delete/remove", "Try Again"],
        "SEM-018": ["SUBMITTED", "APPROVED", "REJECTED", "RE-SUBMITTED"],
        "SEM-019": ["No", "Calculation Code", "Customer", "Succeed", "Progress", "Status", "Type", "Action"],
        "SEM-020": ["Cancel", "Clear Data", "Save Changes"],
        "SEM-021": ["Billing Cycle", "Billing Period", "Calculation Type", "Service Type", "SOR", "Cost Center", "Cancel", "Confirm"],
        "SEM-023": ["Try Again", "retry the operation"],
        "SEM-024": ["No", "Action", "Type", "Calculate At", "Calculate By", "Remark"],
        "SEM-025": ["Retry", "Recalculate", "Calculate"],
        "SEM-026": ["Rating", "Rating and Billing"],
        "SEM-027": ["No", "Init Code", "SOR", "Billing Cycle", "Billing Period", "Status", "Action"],
        "SEM-028": ["Usage", "Service Agreement", "Late Charge Calculation"],
        "SEM-029": ["No", "Customer Number", "Customer Name", "Customer Type ID", "Billing Cycle", "Billing Period", "Action"],
    }

    assert len(requirements) == 19
    assert audit.uncovered_evidence_atom_ids == []
    assert set(required_terms) <= set(by_id)
    for requirement_id, terms in required_terms.items():
        text = scenario_text(plan, requirement_id).lower()
        assert all(term.lower() in text for term in terms), requirement_id

    search_text = scenario_text(plan, "SEM-010").lower()
    assert "sorted" not in search_text
    assert "wildcard" not in search_text
    assert "case sensitivity" not in search_text


def _semantic_regression_plan():
    requirements = [
        make_requirement("SEM-FUNC-001", "Clear Data clears entered values from the form."),
        make_requirement("SEM-FUNC-002", "Clear Data clears selected values from the form."),
        make_requirement(
            "SEM-FUNC-003",
            "Cancel keeps the user on the form and Yes confirms leaving and discarding unsaved data.",
        ),
        make_requirement(
            "SEM-FUNC-004",
            "A sample value 'Server Error' is shown for Result Details.",
        ),
        make_requirement(
            "SEM-GUARD-001",
            "The result list provides an overflow menu.",
            constraints=["Exact options are not fully defined."],
        ),
        make_requirement(
            "SEM-GUARD-002",
            "Advanced Search is accessible from the list/result page.",
            constraints=["The exact field definitions are not fully defined."],
        ),
        make_requirement("SEM-PRES-001", "The page provides:", details=["Search Content"]),
        make_requirement("SEM-PRES-002", "The page provides:", details=["Download List"]),
        make_requirement(
            "SEM-FUNC-005",
            "Users can select/apply a period criterion and the displayed result follows the applied criterion.",
        ),
    ]
    return plan_coverage(requirements)


def _requirement_scenarios(plan, requirement_id: str) -> list[str]:
    requirement_plan = next(
        item for item in plan.requirements if item.requirement_ref == requirement_id
    )
    return [scenario.intent for scenario in requirement_plan.scenarios]


def test_functional_effects_and_literals_are_preserved() -> None:
    plan = _semantic_regression_plan()
    clear_form = " ".join(_requirement_scenarios(plan, "SEM-FUNC-001")).lower()
    clear_selection = " ".join(_requirement_scenarios(plan, "SEM-FUNC-002")).lower()
    confirmation = " ".join(_requirement_scenarios(plan, "SEM-FUNC-003"))
    sample = " ".join(_requirement_scenarios(plan, "SEM-FUNC-004"))

    for text in (clear_form, clear_selection):
        assert "clear" in text
        assert "entered" in text or "selected" in text
        assert "default" not in text
        assert "blank" not in text
    assert "Yes" in confirmation
    assert "Confirm is visible" not in confirmation
    assert "leaving and discarding" in confirmation
    assert "Cancel keeps the user on the form" in confirmation
    assert "Server Error" in sample
    assert "only" not in sample.lower()


def test_guardrails_never_become_scenarios() -> None:
    plan = _semantic_regression_plan()
    overflow_menu = " ".join(_requirement_scenarios(plan, "SEM-GUARD-001")).lower()
    advanced_search = " ".join(_requirement_scenarios(plan, "SEM-GUARD-002")).lower()
    assert "options inside the overflow menu" not in overflow_menu
    assert "field definitions" not in advanced_search
    assert "accessible from the list/result page" in advanced_search


def test_presence_only_controls_do_not_gain_functionality() -> None:
    plan = _semantic_regression_plan()
    for requirement_id in ("SEM-PRES-001", "SEM-PRES-002"):
        text = " ".join(_requirement_scenarios(plan, requirement_id)).lower()
        assert "visible and available" in text
        assert not any(
            term in text
            for term in ("functional", "clickable", "usable", "allows input", "select/apply")
        )
    rate_functional = " ".join(_requirement_scenarios(plan, "SEM-FUNC-005")).lower()
    assert "select/apply a period criterion" in rate_functional
    assert "displayed result follows the applied criterion" in rate_functional


def test_typed_audit_rejects_functional_mapping_for_presence_evidence() -> None:
    atom = EvidenceAtom("SEM-E01", "SEM", "presence", "Search Content")
    scenario = ScenarioIntent(
        "SEM-S01",
        "SEM",
        "positive",
        "EP",
        "Verify Search Content allows input and filters rows.",
        evidence_refs=(atom.id,),
    )
    plan = CoveragePlan(
        requirements=[RequirementCoveragePlan("SEM", [scenario])],
        evidence_atoms=[atom],
    )

    audit = audit_evidence_coverage(plan)
    assert audit.uncovered_evidence_atom_ids == []
    assert audit.incompatible_mapping_ids == ["SEM-E01"]


def test_mixed_positive_guardrail_sentence_preserves_positive_clause() -> None:
    plan = plan_coverage(
        [
            make_requirement(
                "MIXED-001",
                "Additional scheduler fields are visible, but their labels/behavior are not sufficiently supported.",
            )
        ]
    )
    text = scenario_text(plan, "MIXED-001").lower()
    assert "additional scheduler fields are visible" in text
    assert "labels/behavior" not in text
    assert audit_evidence_coverage(plan).guardrail_leak_scenario_ids == []


def test_guardrail_phrase_variants_are_constraints() -> None:
    plan = plan_coverage(
        [
            make_requirement(
                "GUARDRAIL-001",
                "The page provides Search Content.",
                constraints=[
                    "Exact options are not fully defined.",
                    "Exact fields are not completely defined.",
                    "Eligibility is not sufficiently supported.",
                    "The behavior is not available in supplied evidence.",
                    "These details must not be invented.",
                    "Do not infer defaults.",
                ],
            )
        ]
    )
    assert not any(
        "not fully defined" in scenario.intent.lower()
        or "must not be invented" in scenario.intent.lower()
        for scenario in plan.requirements[0].scenarios
    )
    assert audit_evidence_coverage(plan).guardrail_leak_scenario_ids == []


def test_literal_label_collision_keeps_yes_and_confirm_distinct() -> None:
    plan = plan_coverage(
        [
            make_requirement(
                "LABELS-001",
                "The confirmation dialog provides:",
                details=["Yes", "Confirm"],
            )
        ]
    )
    text = scenario_text(plan, "LABELS-001")
    assert "Yes is visible and available" in text
    assert "Confirm is visible and available" in text
