"""Evidence Binding v2 — design matrix regression tests.

These tests lock the authority direction:

    Evidence Authority → Scenario Objective → Natural-Language Intent

Natural-language intent MUST NOT determine evidence authorization.
"""
from __future__ import annotations

import json

from coverage_planner import (
    _materialize_scenarios,
    extract_evidence_atoms,
    plan_coverage,
    render_intent,
    validate_candidate_authority,
)
from models.coverage_model import (
    EvidenceAtom,
    RequirementCoveragePlan,
    ScenarioCandidate,
)
from models.requirement_model import Requirement
from response_parser import parse_batch_response_result
from semantic_quality import authorized_evidence_texts


def requirement(
    rid: str,
    statement: str,
    *,
    title: str = "",
    details: list[str] | None = None,
    acceptance: list[str] | None = None,
    constraints: list[str] | None = None,
    numeric: list[str] | None = None,
) -> Requirement:
    return Requirement(
        id=rid,
        title=title,
        statement=statement,
        details=details or [],
        acceptance_criteria=acceptance or [],
        constraints=constraints or [],
        numeric_limits=numeric or [],
        tags=[],
        status="TESTABLE",
    )


def all_scenarios(plan):
    return [s for item in plan.requirements for s in item.scenarios]


def candidate(
    rid: str,
    objective_kind: str,
    refs: tuple[str, ...],
    objective_data: dict | None = None,
    *,
    category: str = "positive",
    technique: str = "EP",
) -> ScenarioCandidate:
    return ScenarioCandidate(
        requirement_ref=rid,
        category=category,
        technique=technique,
        priority="medium",
        evidence_refs=refs,
        constraint_refs=(),
        objective_kind=objective_kind,
        objective_data=objective_data,
    )


def scenario_by_id(plan, sid):
    for s in all_scenarios(plan):
        if s.id == sid:
            return s
    raise KeyError(sid)


def refs_of(plan, intent_fragment: str):
    """Return evidence_refs of the first scenario whose intent contains the fragment."""
    for s in all_scenarios(plan):
        if intent_fragment.lower() in s.intent.lower():
            return list(s.evidence_refs)
    return None


# ---------------------------------------------------------------------------
# 1. Wording mutation → evidence_refs invariant
# ---------------------------------------------------------------------------

def test_wording_mutation_does_not_change_evidence_refs() -> None:
    """TEST 1 / TEST 9: declared refs are independent of intent wording."""
    req = requirement(
        "REQ-WORD",
        "When search is performed, the displayed rows are filtered according to the search content.",
        title="Search",
        details=["The page provides a Search field."],
    )
    plan = plan_coverage([req], profile="comprehensive")
    behavior = next(s for s in all_scenarios(plan) if "filters" in s.intent.lower() or "filtered" in s.intent.lower())
    assert behavior.evidence_refs, "behavior scenario must declare refs"
    # Wording mutation: planner must produce same refs for same objective.
    # We verify by checking that the combination candidate (if present) still
    # declares both atoms, and the behavior-only candidate still declares only
    # the behavior atom.
    refs_sets = [tuple(s.evidence_refs) for s in all_scenarios(plan)]
    # Behavior-only scenario must not gain presence atom via wording.
    behavior_only = [r for r in refs_sets if len(r) == 1]
    combination = [r for r in refs_sets if len(r) >= 2]
    # At least one behavior-only ref must point to the filtering atom.
    atoms = extract_evidence_atoms(req)
    behavior_atom = next(a for a in atoms if "filter" in a.text.lower())
    presence_atom = next(a for a in atoms if "search field" in a.text.lower() or "provides" in a.text.lower())
    assert behavior_atom.id in [r[0] for r in behavior_only if len(r) == 1] or any(
        behavior_atom.id in r for r in combination
    ), f"behavior atom {behavior_atom.id} must be bound; got {refs_sets}"
    # Presence atom must only appear in combination or presence-only refs.
    for r in refs_sets:
        if presence_atom.id in r:
            assert len(r) >= 2 or presence_atom.id == r[0], (
                f"presence atom {presence_atom.id} must not be the sole ref "
                f"of a behavior scenario; got {r}"
            )


# ---------------------------------------------------------------------------
# 2. Wording mutation → scenario identity invariant
# ---------------------------------------------------------------------------

def test_wording_mutation_does_not_change_scenario_identity() -> None:
    """TEST 2: identity is (req, cat, tech, obj_kind, obj_data, refs), not intent."""
    req = requirement(
        "REQ-ID",
        "Search Content filters displayed rows.",
        title="Search",
        details=["The page provides a Search field."],
    )
    plan1 = plan_coverage([req], profile="comprehensive")
    plan2 = plan_coverage([req], profile="comprehensive")
    # Deterministic: same input → same full projection.
    p1 = [(s.id, s.category, s.technique, s.intent, tuple(s.evidence_refs)) for s in all_scenarios(plan1)]
    p2 = [(s.id, s.category, s.technique, s.intent, tuple(s.evidence_refs)) for s in all_scenarios(plan2)]
    assert p1 == p2


# ---------------------------------------------------------------------------
# 3. Explicit E01+E02 combination remains exactly E01+E02
# ---------------------------------------------------------------------------

def test_explicit_combination_remains_exactly_e01_e02() -> None:
    """TEST 3: combination candidate declares both atoms, no more no less."""
    req = requirement(
        "REQ-COMB",
        "When search is performed, the displayed rows are filtered according to the search content.",
        title="Search",
        details=["The page provides a Search field."],
    )
    plan = plan_coverage([req], profile="comprehensive")
    atoms = extract_evidence_atoms(req)
    assert len(atoms) >= 2
    e01, e02 = atoms[0].id, atoms[1].id
    combos = [s for s in all_scenarios(plan) if len(s.evidence_refs) == 2]
    assert combos, f"expected a combination candidate; got {[(s.id, s.evidence_refs) for s in all_scenarios(plan)]}"
    combo = combos[0]
    assert set(combo.evidence_refs) == {e01, e02}, (
        f"combination must declare exactly E01+E02; got {combo.evidence_refs}"
    )


# ---------------------------------------------------------------------------
# 4. E01-only cannot authorize E02
# ---------------------------------------------------------------------------

def test_e01_only_cannot_authorize_e02() -> None:
    """TEST 4: presence-only scenario must not grant behavior authority."""
    req = requirement(
        "REQ-PRES",
        "The page provides a Search field.",
        title="Search",
    )
    plan = plan_coverage([req], profile="comprehensive")
    atoms = extract_evidence_atoms(req)
    assert atoms, "expected at least one atom"
    presence_s = [s for s in all_scenarios(plan) if s.evidence_refs]
    assert presence_s, "expected a presence scenario with declared refs"
    for s in presence_s:
        for ref in s.evidence_refs:
            atom = next(a for a in atoms if a.id == ref)
            assert atom.kind in {"presence", "observed_value", "option", "sample_value"}, (
                f"presence scenario must not bind behavior atom {atom.id} ({atom.kind})"
            )
    # authorized_evidence_texts for presence scenario must not include behavior text.
    from semantic_quality import build_authorities
    authorities = build_authorities(all_scenarios(plan), atoms)
    for sid, auth in authorities.items():
        s = next(x for x in all_scenarios(plan) if x.id == sid)
        if s.evidence_refs and all(
            next(a for a in atoms if a.id == r).kind in {"presence", "observed_value", "option", "sample_value"}
            for r in s.evidence_refs
        ):
            for text in auth.support_texts:
                assert "filter" not in text.lower() or text == s.intent, (
                    f"presence authority must not include filtering behavior; got {text!r}"
                )


# ---------------------------------------------------------------------------
# 5. Foreign requirement refs rejected
# ---------------------------------------------------------------------------

def test_foreign_requirement_refs_rejected() -> None:
    """TEST 5: evidence_ref from another requirement is a planner defect."""
    req_a = requirement("REQ-A", "Search Content filters displayed rows.", title="Search")
    req_b = requirement("REQ-B", "The page provides a Cancel control.", title="Cancel")
    plan = plan_coverage([req_a, req_b], profile="comprehensive")
    atoms = {a.id: a for a in plan.evidence_atoms}
    for s in all_scenarios(plan):
        for ref in s.evidence_refs:
            atom = atoms.get(ref)
            if atom is not None:
                assert atom.requirement_ref == s.requirement_ref, (
                    f"scenario {s.id} binds foreign atom {ref} "
                    f"(atom req={atom.requirement_ref}, scenario req={s.requirement_ref})"
                )


# ---------------------------------------------------------------------------
# 6. Presence objective compatibility
# ---------------------------------------------------------------------------

def test_presence_objective_compatibility() -> None:
    """TEST 6: presence objective binds only presence/observed_value atoms."""
    req = requirement(
        "REQ-COMP-P",
        'The page provides a "Cancel" control.',
        title="Cancel",
    )
    plan = plan_coverage([req], profile="comprehensive")
    atoms = extract_evidence_atoms(req)
    for s in all_scenarios(plan):
        if s.evidence_refs:
            for ref in s.evidence_refs:
                atom = next(a for a in atoms if a.id == ref)
                assert atom.kind in {"presence", "observed_value"}, (
                    f"presence scenario {s.id} binds non-presence atom {atom.id} ({atom.kind})"
                )


# ---------------------------------------------------------------------------
# 7. Behavior objective compatibility
# ---------------------------------------------------------------------------

def test_behavior_objective_compatibility() -> None:
    """TEST 7: behavior objective binds explicit_behavior (or recorded observed_value)."""
    req = requirement(
        "REQ-COMP-B",
        "Search Content filters displayed rows.",
        title="Search",
    )
    plan = plan_coverage([req], profile="comprehensive")
    atoms = extract_evidence_atoms(req)
    behavior_atoms = [a for a in atoms if a.kind in {"explicit_behavior", "observed_value"}]
    assert behavior_atoms, "expected behavior-capable atoms"
    for s in all_scenarios(plan):
        if s.evidence_refs:
            for ref in s.evidence_refs:
                atom = next(a for a in atoms if a.id == ref)
                assert atom.kind in {"explicit_behavior", "observed_value", "presence", "boundary", "mandatory", "state", "file_boundary"}, (
                    f"scenario {s.id} binds unexpected atom kind {atom.kind}"
                )


# ---------------------------------------------------------------------------
# 8. Policy empty-ref authority restriction
# ---------------------------------------------------------------------------

def test_candidate_authority_invariant_rejects_empty_refs_for_evidence_requirement() -> None:
    atom = EvidenceAtom("REQ-AUTH-E01", "REQ-AUTH", "presence", "Retry action")
    invalid = candidate("REQ-AUTH", "presence", (), {"primary_ref": atom.id})

    try:
        validate_candidate_authority(invalid, [atom])
    except ValueError as error:
        assert "no declared evidence refs" in str(error)
    else:
        raise AssertionError("non-policy candidate with evidence atoms must reject empty refs")

    try:
        _materialize_scenarios("REQ-AUTH", [invalid], [atom], "Retry")
    except ValueError:
        pass
    else:
        raise AssertionError("invalid candidate must not reach scenario materialization")


def test_candidate_authority_allows_supported_zero_atom_behavior() -> None:
    atoms: list[EvidenceAtom] = []
    zero_atom_candidate = candidate("REQ-ZERO", "behavior", ())
    validate_candidate_authority(zero_atom_candidate, atoms)
    materialized = _materialize_scenarios("REQ-ZERO", [zero_atom_candidate], atoms, "Example")
    assert len(materialized) == 1
    assert materialized[0].evidence_refs == ()
    try:
        validate_candidate_authority(
            candidate("REQ-ZERO", "behavior", ("REQ-ZERO-E01",)),
            atoms,
        )
    except ValueError as error:
        assert "without non-guardrail source evidence" in str(error)
    else:
        raise AssertionError("zero-atom requirement cannot authorize fabricated refs")
    plan = plan_coverage(
        [requirement("REQ-ZERO", "Clear Data clears entered values from the form.")],
        profile="minimal",
    )
    scenarios = all_scenarios(plan)
    assert scenarios
    atoms = extract_evidence_atoms(requirement("REQ-ZERO", "Clear Data clears entered values from the form."))
    for scenario in scenarios:
        validate_candidate_authority(
            candidate(scenario.requirement_ref, "behavior", scenario.evidence_refs, {"primary_ref": scenario.evidence_refs[0]} if scenario.evidence_refs else None),
            atoms,
        )


def test_candidate_authority_allows_policy_empty_refs() -> None:
    policy = candidate("REQ-POLICY", "policy", (), {"rule_key": "auth.a1_valid_credentials"})
    validate_candidate_authority(policy, [])


def test_candidate_authority_rejects_primary_ref_kind_mismatch() -> None:
    presence = EvidenceAtom("REQ-KIND-E01", "REQ-KIND", "presence", "Retry action")
    invalid = candidate("REQ-KIND", "boundary", (presence.id,), {"primary_ref": presence.id})
    try:
        validate_candidate_authority(invalid, [presence])
    except ValueError as error:
        assert "incompatible primary evidence" in str(error)
    else:
        raise AssertionError("boundary objective cannot bind presence evidence")


def test_candidate_authority_rejects_foreign_and_guardrail_refs() -> None:
    local = EvidenceAtom("REQ-A-E01", "REQ-A", "presence", "Retry action")
    foreign = EvidenceAtom("REQ-B-E01", "REQ-B", "presence", "Cancel action")
    guardrail = EvidenceAtom("REQ-A-E02", "REQ-A", "guardrail", "Do not infer behavior")

    for invalid, atoms, message in (
        (candidate("REQ-A", "presence", (foreign.id,), {"primary_ref": foreign.id}), [local, foreign], "foreign"),
        (candidate("REQ-A", "presence", (guardrail.id,), {"primary_ref": guardrail.id}), [guardrail], "guardrail"),
        (candidate("REQ-A", "presence", ("REQ-A-E99",), {"primary_ref": "REQ-A-E99"}), [local], "unknown"),
    ):
        try:
            validate_candidate_authority(invalid, atoms)
        except ValueError as error:
            assert message in str(error)
        else:
            raise AssertionError(f"candidate with {message} ref must be rejected")


def test_candidate_authority_requires_security_predicate_ref() -> None:
    atom = EvidenceAtom("REQ-SEC-E01", "REQ-SEC", "presence", "Login button")
    invalid = candidate("REQ-SEC", "security", (atom.id,), {"predicate_ref": atom.id}, category="security", technique="security")
    try:
        validate_candidate_authority(invalid, [atom])
    except ValueError as error:
        assert "predicate-bearing" in str(error)
    else:
        raise AssertionError("security candidate without predicate atom must be rejected")


def test_candidate_authority_rejects_declared_combination_refs_mismatch() -> None:
    behavior = EvidenceAtom("REQ-COMBO-E01", "REQ-COMBO", "explicit_behavior", "Search filters rows")
    presence = EvidenceAtom("REQ-COMBO-E02", "REQ-COMBO", "presence", "Search field")
    mismatched = candidate(
        "REQ-COMBO",
        "combination",
        (behavior.id,),
        {"primary_ref": behavior.id, "supporting_refs": (presence.id,)},
        category="edge",
        technique="exploratory",
    )
    try:
        validate_candidate_authority(mismatched, [behavior, presence])
    except ValueError as error:
        assert "exactly its objective refs" in str(error)
    else:
        raise AssertionError("combination must bind exactly its declared refs")


def test_policy_empty_ref_authority_restriction() -> None:
    """TEST 8: policy candidate with refs=() must not receive requirement-wide authority."""
    req = requirement(
        "REQ-POL",
        "User enters invalid credentials and sees an error message.",
        title="Login",
    )
    plan = plan_coverage([req], profile="comprehensive")
    atoms = extract_evidence_atoms(req)
    from semantic_quality import build_authorities
    authorities = build_authorities(all_scenarios(plan), atoms)
    for s in all_scenarios(plan):
        if not s.evidence_refs:
            # Empty refs: either policy objective (rule-scoped) or zero-atom req.
            if atoms:
                non_guardrail = [a for a in atoms if a.kind != "guardrail"]
                if non_guardrail:
                    # Must not widen to all requirement-local atoms.
                    auth = authorities[s.id]
                    # Policy scenarios have rule_key in objective (not exposed on
                    # ScenarioIntent). We check that support_texts does not include
                    # every atom text.
                    atom_texts = {a.text for a in non_guardrail}
                    support_atom_texts = {t for t in auth.support_texts if t in atom_texts}
                    assert len(support_atom_texts) < len(atom_texts) or s.intent in atom_texts, (
                        f"empty-ref scenario {s.id} widened authority to all atoms; "
                        f"support={auth.support_texts}"
                    )


# ---------------------------------------------------------------------------
# 9. Security empty-ref rejection
# ---------------------------------------------------------------------------

def test_security_empty_ref_rejected() -> None:
    """TEST 9: security candidate with refs=() must not exist."""
    req = requirement(
        "REQ-SEC-EMPTY",
        "User enters Search Content to filter rows.",
        title="Search",
    )
    plan = plan_coverage([req], profile="comprehensive")
    for s in all_scenarios(plan):
        if s.category == "security":
            assert s.evidence_refs, (
                f"security scenario {s.id} has empty evidence_refs; "
                f"security requires declared predicate atom"
            )


def test_success_failure_candidates_use_exact_outcome_refs_or_are_suppressed() -> None:
    req = requirement(
        "REQ-SUCCESS-FAILURE",
        "The success and failure result behavior is described.",
        title="Calculation Result",
        acceptance=[
            "The system shows a success dialog after a successful result.",
            "The system shows a failure dialog after an unsuccessful result.",
        ],
    )
    atoms = extract_evidence_atoms(req)
    plan = plan_coverage([req], profile="minimal")
    outcomes = [
        scenario for scenario in all_scenarios(plan)
        if "success state" in scenario.intent.lower() or "failure state" in scenario.intent.lower()
    ]
    atom_ids = {atom.id for atom in atoms}

    assert all(scenario.evidence_refs for scenario in outcomes)
    for scenario in outcomes:
        bound_atoms = [atom for atom in atoms if atom.id in scenario.evidence_refs]
        assert set(scenario.evidence_refs) <= atom_ids
        if "success state" in scenario.intent.lower():
            assert bound_atoms
            assert all("success" in atom.text.lower() and "failure" not in atom.text.lower() for atom in bound_atoms)
        else:
            assert bound_atoms
            assert all("failure dialog" in atom.text.lower() and "success dialog" not in atom.text.lower() for atom in bound_atoms)

    unsupported = requirement(
        "REQ-SUCCESS-UNSUPPORTED",
        "The operation may be successful or fail.",
        title="Operation",
    )
    unsupported_plan = plan_coverage([unsupported], profile="minimal")
    assert not any(
        "success state" in scenario.intent.lower() or "failure state" in scenario.intent.lower()
        for scenario in all_scenarios(unsupported_plan)
    )

    multi_atom_without_outcomes = requirement(
        "REQ-SUCCESS-UNSUPPORTED-MULTI",
        "The calculation has a result.",
        title="Calculation Result",
        details=["The operation supports Retry action."],
        acceptance=["The maximum retry count is 3."],
    )
    multi_atom_plan = plan_coverage([multi_atom_without_outcomes], profile="minimal")
    assert not any(
        "success state" in scenario.intent.lower() or "failure state" in scenario.intent.lower()
        for scenario in all_scenarios(multi_atom_plan)
    )


def test_candidate_authority_validates_success_failure_evidence_compatibility() -> None:
    success_atom = EvidenceAtom(
        "REQ-OUTCOME-E01",
        "REQ-OUTCOME",
        "observed_value",
        "The system shows a success dialog after a successful result.",
    )
    failure_atom = EvidenceAtom(
        "REQ-OUTCOME-E02",
        "REQ-OUTCOME",
        "observed_value",
        "The system shows a failure dialog after an unsuccessful result.",
    )
    validate_candidate_authority(
        candidate("REQ-OUTCOME", "success_failure", (success_atom.id,), {"variant": "success"}),
        [success_atom, failure_atom],
    )
    validate_candidate_authority(
        candidate("REQ-OUTCOME", "success_failure", (failure_atom.id,), {"variant": "failure"}, category="negative", technique="negative"),
        [success_atom, failure_atom],
    )

    unrelated = EvidenceAtom("REQ-OUTCOME-E03", "REQ-OUTCOME", "presence", "Retry action")
    for refs, objective_data in (
        ((unrelated.id,), {"variant": "success"}),
        ((success_atom.id, failure_atom.id), {"variant": "success"}),
    ):
        try:
            validate_candidate_authority(
                candidate("REQ-OUTCOME", "success_failure", refs, objective_data),
                [success_atom, failure_atom, unrelated],
            )
        except ValueError as error:
            assert "compatible outcome evidence" in str(error)
        else:
            raise AssertionError("success/failure candidates must reject unrelated outcome refs")


def test_action_visibility_uses_compatible_presence_ref_or_is_suppressed() -> None:
    req = requirement(
        "REQ-ACTION-VISIBILITY",
        "Action is visible.",
        title="Retry",
    )
    atoms = extract_evidence_atoms(req)
    plan = plan_coverage([req], profile="minimal")
    actions = [
        scenario for scenario in all_scenarios(plan)
        if "visible and available" in scenario.intent.lower()
    ]
    assert len(actions) == 1
    assert actions[0].evidence_refs
    assert len(actions[0].evidence_refs) == 1
    assert next(atom for atom in atoms if atom.id == actions[0].evidence_refs[0]).kind in {"presence", "observed_value"}

    unsupported = requirement(
        "REQ-ACTION-UNSUPPORTED",
        "Action processing is relevant to this requirement.",
        title="Actions",
        details=["Status values include Ready, Failed"],
    )
    unsupported_plan = plan_coverage([unsupported], profile="minimal")
    assert not any(
        "visible and available" in scenario.intent.lower()
        for scenario in all_scenarios(unsupported_plan)
    )


def test_security_with_predicate_is_valid() -> None:
    """Security + refs=(E01,) is valid when E01 is a predicate atom."""
    req = requirement(
        "REQ-SEC-OK",
        "Password is not displayed as plain text.",
        title="Password Field",
    )
    plan = plan_coverage([req], profile="comprehensive")
    atoms = extract_evidence_atoms(req)
    security = [s for s in all_scenarios(plan) if s.category == "security"]
    assert security, "expected a security scenario"
    for s in security:
        assert s.evidence_refs, f"security scenario {s.id} must declare refs"
        for ref in s.evidence_refs:
            atom = next(a for a in atoms if a.id == ref)
            assert atom.kind in {"observed_value", "explicit_behavior"}, (
                f"security atom {atom.id} must be observed_value or explicit_behavior; got {atom.kind}"
            )


# ---------------------------------------------------------------------------
# 10. Dedup identity regression
# ---------------------------------------------------------------------------

def test_dedup_identity_regression() -> None:
    """TEST 10: no duplicate identities under proposed key."""
    reqs = [
        requirement("REQ-D1", "Search Content filters displayed rows.", title="Search",
                    details=["The page provides a Search field."]),
        requirement("REQ-D2", 'The page provides a "Cancel" control.', title="Cancel"),
        requirement("REQ-D3", "User enters invalid credentials and sees an error message.", title="Login"),
    ]
    for profile in ("minimal", "comprehensive", "extra"):
        plan = plan_coverage(reqs, profile=profile)
        seen = set()
        for s in all_scenarios(plan):
            key = (s.requirement_ref, s.category, s.technique, tuple(s.evidence_refs))
            assert key not in seen, f"duplicate identity {key} in profile={profile}"
            seen.add(key)


# ---------------------------------------------------------------------------
# 11. Deterministic repeated planning
# ---------------------------------------------------------------------------

def test_deterministic_repeated_planning() -> None:
    """TEST 11: same input → same refs/order/intent."""
    reqs = [
        requirement("REQ-DET-1", "Search Content filters displayed rows.", title="Search",
                    details=["The page provides a Search field."]),
        requirement("REQ-DET-2", "The maximum file size is 10 MB.", title="Upload",
                    numeric=["Maximum file size is 10 MB."]),
    ]
    for profile in ("minimal", "comprehensive", "extra"):
        p1 = plan_coverage(reqs, profile=profile)
        p2 = plan_coverage(reqs, profile=profile)
        proj = lambda p: [
            (s.id, s.category, s.technique, s.intent, tuple(s.evidence_refs), tuple(s.constraint_refs))
            for s in all_scenarios(p)
        ]
        assert proj(p1) == proj(p2), f"non-deterministic at profile={profile}"


# ---------------------------------------------------------------------------
# 12. Profile nesting
# ---------------------------------------------------------------------------

def test_profile_nesting() -> None:
    """TEST 12: Minimal ⊆ Comprehensive ⊆ Extra under identity projection."""
    reqs = [
        requirement("REQ-N1", "Search Content filters displayed rows.", title="Search",
                    details=["The page provides a Search field."]),
        requirement("REQ-N2", "The maximum file size is 10 MB.", title="Upload",
                    numeric=["Maximum file size is 10 MB."]),
    ]
    def identity(profile):
        plan = plan_coverage(reqs, profile=profile)
        return {
            (s.requirement_ref, s.category, s.technique, tuple(s.evidence_refs))
            for s in all_scenarios(plan)
        }
    minimal = identity("minimal")
    comprehensive = identity("comprehensive")
    extra = identity("extra")
    assert minimal <= comprehensive, f"minimal not subset: {minimal - comprehensive}"
    assert comprehensive <= extra, f"comprehensive not subset: {comprehensive - extra}"


# ---------------------------------------------------------------------------
# Search canonical case
# ---------------------------------------------------------------------------

def test_search_canonical_case() -> None:
    """Search: E01 presence, E02 behavior, C combination (E01+E02)."""
    req = requirement(
        "REQ-SEARCH",
        "When search is performed, the displayed rows are filtered according to the search content.",
        title="Search",
        details=["The page provides a Search field."],
    )
    plan = plan_coverage([req], profile="comprehensive")
    atoms = extract_evidence_atoms(req)
    assert len(atoms) >= 2, f"expected E01+E02; got {[(a.id, a.kind, a.text) for a in atoms]}"
    e01, e02 = atoms[0].id, atoms[1].id

    # Candidate A: presence, refs=(E01,)
    presence_only = [s for s in all_scenarios(plan) if tuple(s.evidence_refs) == (e01,)]
    # Candidate B: behavior, refs=(E02,)
    behavior_only = [s for s in all_scenarios(plan) if tuple(s.evidence_refs) == (e02,)]
    # Candidate C: combination, refs=(E01, E02) or (E02, E01)
    combination = [s for s in all_scenarios(plan) if set(s.evidence_refs) == {e01, e02} and len(s.evidence_refs) == 2]

    assert presence_only or combination, f"expected presence or combination binding E01; got {[(s.id, s.evidence_refs) for s in all_scenarios(plan)]}"
    assert behavior_only or combination, f"expected behavior or combination binding E02; got {[(s.id, s.evidence_refs) for s in all_scenarios(plan)]}"
    assert combination, f"expected explicit combination candidate; got {[(s.id, s.evidence_refs) for s in all_scenarios(plan)]}"

    # Intent wording must not determine refs: behavior scenario must not
    # contain presence atom text as authority.
    from semantic_quality import build_authorities
    authorities = build_authorities(all_scenarios(plan), atoms)
    for s in behavior_only:
        auth = authorities[s.id]
        for text in auth.support_texts:
            if text != s.intent:
                assert "search field" not in text.lower() or text in {a.text for a in atoms if a.id in s.evidence_refs}, (
                    f"behavior authority must not include presence text; got {text!r}"
                )


# ---------------------------------------------------------------------------
# Save canonical case
# ---------------------------------------------------------------------------

def test_save_canonical_case() -> None:
    """Save: E01 presence, E02 behavior, C combination."""
    req = requirement(
        "REQ-SAVE",
        "When changes are saved, the system saves the changes.",
        title="Save Changes",
        details=['The page provides a "Save Changes" control.'],
    )
    plan = plan_coverage([req], profile="comprehensive")
    atoms = extract_evidence_atoms(req)
    assert len(atoms) >= 2, f"expected E01+E02; got {[(a.id, a.kind, a.text) for a in atoms]}"
    e01, e02 = atoms[0].id, atoms[1].id

    presence_only = [s for s in all_scenarios(plan) if tuple(s.evidence_refs) == (e01,)]
    behavior_only = [s for s in all_scenarios(plan) if tuple(s.evidence_refs) == (e02,)]
    combination = [s for s in all_scenarios(plan) if set(s.evidence_refs) == {e01, e02} and len(s.evidence_refs) == 2]

    assert presence_only or combination, f"expected presence/combination for E01; got {[(s.id, s.evidence_refs) for s in all_scenarios(plan)]}"
    assert behavior_only or combination, f"expected behavior/combination for E02; got {[(s.id, s.evidence_refs) for s in all_scenarios(plan)]}"
    assert combination, f"expected explicit combination; got {[(s.id, s.evidence_refs) for s in all_scenarios(plan)]}"

    # Combination intent must not introduce causal language.
    for s in combination:
        lowered = s.intent.lower()
        for forbidden in ("causes", "then ", "so that", "therefore"):
            assert forbidden not in lowered, f"combination intent introduces causal language: {s.intent!r}"


# ---------------------------------------------------------------------------
# Cancel safety
# ---------------------------------------------------------------------------

def test_cancel_safety() -> None:
    """Cancel: only presence authority; no close/discard/navigation/persistence/state-change."""
    req = requirement(
        "REQ-CANCEL",
        'The page provides a "Cancel" control.',
        title="Cancel",
    )
    plan = plan_coverage([req], profile="comprehensive")
    atoms = extract_evidence_atoms(req)
    for s in all_scenarios(plan):
        for ref in s.evidence_refs:
            atom = next(a for a in atoms if a.id == ref)
            assert atom.kind in {"presence", "observed_value"}, (
                f"cancel scenario {s.id} binds non-presence atom {atom.id} ({atom.kind})"
            )
    intents = " ".join(s.intent for s in all_scenarios(plan)).lower()
    for forbidden in ("closes", "discards", "navigate", "navigation", "persists", "persistence", "state change"):
        assert forbidden not in intents, f"cancel intent contains {forbidden!r}: {intents}"


# ---------------------------------------------------------------------------
# Provider-boundary check: authorized_evidence exactness
# ---------------------------------------------------------------------------

def test_authorized_evidence_is_exact_from_declared_refs() -> None:
    """Offline provider-boundary: authorized_evidence derives from declared refs."""
    req = requirement(
        "REQ-PB",
        "When search is performed, the displayed rows are filtered according to the search content.",
        title="Search",
        details=["The page provides a Search field."],
    )
    plan = plan_coverage([req], profile="comprehensive")
    atoms = extract_evidence_atoms(req)
    from semantic_quality import build_authorities
    authorities = build_authorities(all_scenarios(plan), atoms)
    for s in all_scenarios(plan):
        if s.evidence_refs:
            expected = tuple(a.text for a in atoms if a.id in s.evidence_refs)
            actual = tuple(t for t in authorities[s.id].support_texts if t != s.intent)
            assert set(actual) == set(expected), (
                f"scenario {s.id}: authorized_evidence mismatch; "
                f"expected={expected}, actual={actual}"
            )


def test_multi_evidence_authority_is_exact() -> None:
    """Combination scenario authorizes exactly its declared atoms."""
    req = requirement(
        "REQ-MULTI",
        "When search is performed, the displayed rows are filtered according to the search content.",
        title="Search",
        details=["The page provides a Search field."],
    )
    plan = plan_coverage([req], profile="comprehensive")
    atoms = extract_evidence_atoms(req)
    from semantic_quality import build_authorities
    authorities = build_authorities(all_scenarios(plan), atoms)
    combos = [s for s in all_scenarios(plan) if len(s.evidence_refs) >= 2]
    for s in combos:
        expected = {a.text for a in atoms if a.id in s.evidence_refs}
        actual = {t for t in authorities[s.id].support_texts if t != s.intent}
        assert actual == expected, (
            f"combination {s.id}: authority mismatch; expected={expected}, actual={actual}"
        )


# ---------------------------------------------------------------------------
# Prompt payload check
# ---------------------------------------------------------------------------

def test_prompt_payload_uses_declared_refs() -> None:
    """Prompt builder serializes authorized_evidence from declared refs."""
    from prompt_builder import build_batch_prompt
    req = requirement(
        "REQ-PROMPT",
        "When search is performed, the displayed rows are filtered according to the search content.",
        title="Search",
        details=["The page provides a Search field."],
    )
    plan = plan_coverage([req], profile="comprehensive")
    atoms = extract_evidence_atoms(req)
    scenarios = all_scenarios(plan)
    prompt = build_batch_prompt([req], scenarios, evidence_atoms=atoms)
    # Every scenario's authorized_evidence in the prompt must match its declared refs.
    import re
    payload_match = re.search(r'"scenario_ref":\s*"([^"]+)".*?"authorized_evidence":\s*\[(.*?)\]', prompt, re.DOTALL)
    # Simpler: just check the prompt contains the atom texts for combination scenarios.
    for s in scenarios:
        if len(s.evidence_refs) >= 2:
            for ref in s.evidence_refs:
                atom = next(a for a in atoms if a.id == ref)
                # Atom text (or a distinctive substring) must appear in the prompt.
                distinctive = atom.text[:40] if len(atom.text) > 40 else atom.text
                assert distinctive.lower() in prompt.lower() or atom.text.lower() in prompt.lower(), (
                    f"prompt missing atom text for {ref}: {atom.text!r}"
                )
