from models.coverage_model import CoveragePlan
from models.requirement_model import Requirement
from coverage_planner import plan_coverage


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
    for index, statement in enumerate(
        [
            "SOR is not mandatory.",
            "Do not assume this field is mandatory.",
        ],
        start=1,
    ):
        plan = plan_coverage([requirement(f"NEGATED-{index}", statement)])

        assert len(plan.requirements[0].scenarios) == 1
        assert plan.requirements[0].scenarios[0].category == "positive"


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
    assert "Confirm path" in scenarios[0].intent
    assert "Cancel path" in scenarios[1].intent


def test_success_and_failure_states_are_both_planned() -> None:
    plan = plan_coverage(
        [
            requirement(
                "CALC-017",
                "Successful result displays a success dialog; unsuccessful result displays a failure dialog.",
                title="Calculation Result",
            )
        ]
    )

    scenarios = plan.requirements[0].scenarios
    assert [scenario.category for scenario in scenarios] == ["positive", "negative"]
    assert "success state" in scenarios[0].intent
    assert "failure state" in scenarios[1].intent


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


def test_search_input_can_receive_generic_security_profile_coverage() -> None:
    plan = plan_coverage(
        [requirement("SEARCH-001", "User enters Search Content to filter rows.")],
        profile="security",
    )

    security = [
        scenario for scenario in plan.requirements[0].scenarios if scenario.category == "security"
    ]
    assert len(security) == 1
    assert "access rules" in security[0].intent
    assert "permissions" not in security[0].intent
    assert "authentication" not in security[0].intent


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
    assert len(scenarios) == 2
    assert "select/apply a billing period criterion" in intents
    assert "displayed result follows the applied criterion" in intents
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
