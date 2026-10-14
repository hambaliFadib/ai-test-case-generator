"""Deterministic, conservative coverage planning for Phase 2 — Evidence Binding v2.

Authority direction:
    Evidence Authority → Scenario Objective → Natural-Language Intent

ScenarioCandidate.evidence_refs are declared by the producing planner rule.
Natural-language intent MUST NOT determine evidence authorization.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

from baseline_planner import BaselineEvaluation, evaluate_baseline
from models.coverage_model import (
    SCENARIO_CATEGORIES,
    SCENARIO_TECHNIQUES,
    CoveragePlan,
    EvidenceAtom,
    RequirementCoveragePlan,
    ScenarioCandidate,
    ScenarioIntent,
    UnresolvedBaselineItem,
)
from models.frozen_utils import freeze_objective_data
from models.requirement_model import Requirement
from profiles import DEFAULT_PROFILE, resolve_profile

_MAXIMUM = re.compile(
    r"\b(?:maximum|max|limit|at most)\b[^\d]{0,40}(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
_MINIMUM = re.compile(
    r"\b(?:minimum|min|at least)\b[^\d]{0,40}(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
_LIMIT_AFTER_VALUE = re.compile(
    r"\b(\d+(?:\.\d+)?)[^\d]{0,40}\b(?:maximum|max|limit|minimum|min)\b",
    re.IGNORECASE,
)
_NUMBER_WITH_UNIT = re.compile(
    r"\b(\d+(?:\.\d+)?)\s*(characters?|bytes?|kb|mb|gb|days?|hours?|minutes?|seconds?)\b",
    re.IGNORECASE,
)
_MANDATORY = re.compile(
    r"\b(?:mandatory|required|must be provided|cannot be empty|not be empty)\b|[A-Za-z0-9]\*",
    re.IGNORECASE,
)
_NEGATED_MANDATORY = re.compile(
    r"\b(?:not|do not|don't|never)\b(?:\W+\w+){0,8}\W+\b(?:mandatory|required)\b",
    re.IGNORECASE,
)
_SEARCH = re.compile(r"\b(?:search|filter|filtering)\b", re.IGNORECASE)
_CONFIRMATION = re.compile(
    r"\b(?:confirmation|confirm|cancel|save changes|are you sure)\b",
    re.IGNORECASE,
)
_SUCCESS = re.compile(r"\b(?:success|successful|succeed|succeeded)\b", re.IGNORECASE)
_FAILURE = re.compile(
    r"\b(?:failure|failed|unsuccessful|error|unsuccessfully)\b", re.IGNORECASE
)
_ACTION = re.compile(
    r"\b(?:action|button|icon|download|upload|retry|recalculate|clear data)\b",
    re.IGNORECASE,
)
_SECURITY = re.compile(
    r"\b(?:security|secure|authentication|authenticated|authorization|authorized|permission|role|access control|login|sign in|password|credential|token|session|unauthorized|forbidden|privilege)\b",
    re.IGNORECASE,
)
_SECURITY_PREDICATE = re.compile(
    r"\b(?:authenticated|authentication|authorization|authorized|permission|role|access control|password|credentials?|token|session|unauthorized|forbidden|privilege|mfa|otp|lockout|plain\s+text|plaintext|displayed\s+as)\b",
    re.IGNORECASE,
)
_STATE = re.compile(
    r"\b(?:status(?:es)?|state(?:s)?|lifecycle|values include|states include)\b",
    re.IGNORECASE,
)
_BEHAVIOR_PHRASE = re.compile(
    r"\b(?:filters?\s+(?:displayed|rows|results?)|displayed\s+(?:rows?|results?)\s+(?:are\s+)?follow|"
    r"displayed\s+(?:rows?|results?)\s+(?:are\s+)?filter\w*|"
    r"system\s+saves?|saves?\s+the\s+changes|returns?\s+the\s+(?:displayed\s+)?results?|"
    r"applies?\s+(?:the\s+)?(?:selected\s+|applied\s+)?criterion)\b",
    re.IGNORECASE,
)


_USER_ACTION_PHRASE = re.compile(
    r"\b(?:the\s+|a\s+|an\s+)?(?:user|users|customer|operator|administrator|agent|tester)\s+"
    r"(?:can\s+)?(?:selects?|chooses?|clicks?|presses?|enters?|types?|fills?|inputs?|"
    r"opens?|navigates?|submits?|cancels?|confirms?|uploads?|downloads?|searches?|"
    r"filters?|saves?|deletes?|adds?|removes?|sets?|views?|logs?\s+(?:in|out))\b",
    re.IGNORECASE,
)
_PRESENCE_STATEMENT = re.compile(
    r"(?!(?:the\s+|a\s+|an\s+)?(?:user|users|customer|operator|administrator|agent|tester)\b)"
    r"(?:the\s+)?[A-Za-z][\w -]{0,40}\s+provides?\s+[^.!?]+[.!?]?",
    re.IGNORECASE,
)
_PRESENCE_STATE_STATEMENT = re.compile(
    r"(?:the\s+)?[A-Za-z][\w -]{0,40}\s+(?:is|are)\s+"
    r"(?:available|visible|present|supported)[.!]?",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class _AtomicBehavior:
    """One explicit behavior retained inside a Requirement block."""

    label: str
    source_text: str
    kind: str


def plan_coverage(
    requirements: list[Requirement],
    profile: str = DEFAULT_PROFILE,
) -> CoveragePlan:
    """Create a stable coverage plan without calling an LLM or external API."""

    resolved_profile = resolve_profile(profile)

    plans: list[RequirementCoveragePlan] = []
    evidence_atoms: list[EvidenceAtom] = []
    unresolved_baseline: list[UnresolvedBaselineItem] = []
    for requirement in requirements:
        requirement_atoms = extract_evidence_atoms(requirement)
        scenarios, evaluation, all_atoms = _scenarios_for_requirement(
            requirement, resolved_profile, requirement_atoms
        )
        evidence_atoms.extend(all_atoms)
        unresolved_baseline.extend(evaluation.unresolved)
        plans.append(
            RequirementCoveragePlan(
                requirement_ref=requirement.id,
                scenarios=scenarios,
            )
        )
    plan = CoveragePlan(
        requirements=plans,
        evidence_atoms=evidence_atoms,
        unresolved_baseline=unresolved_baseline,
    )
    from coverage_auditor import audit_evidence_coverage

    evidence_audit = audit_evidence_coverage(plan)
    gate_failures: list[str] = []
    if evidence_audit.uncovered_evidence_atom_ids:
        gate_failures.append(
            "uncovered evidence atoms: "
            + ", ".join(evidence_audit.uncovered_evidence_atom_ids)
        )
    if evidence_audit.incompatible_mapping_ids:
        gate_failures.append(
            "incompatible evidence mappings: "
            + ", ".join(evidence_audit.incompatible_mapping_ids)
        )
    if evidence_audit.guardrail_leak_scenario_ids:
        gate_failures.append(
            "guardrail-leak scenarios: "
            + ", ".join(evidence_audit.guardrail_leak_scenario_ids)
        )
    if gate_failures:
        raise ValueError("Deterministic semantic gate failed: " + "; ".join(gate_failures))
    return plan


# ---------------------------------------------------------------------------
# Objective → Intent renderer
# ---------------------------------------------------------------------------

def render_intent(
    requirement_id: str,
    objective_kind: str,
    objective_data: dict | None,
    atoms: list[EvidenceAtom],
    subject: str,
) -> str:
    """Render natural-language intent from declared objective and bound atoms.

    The renderer produces intent FROM objective_data + declared atom texts.
    It never determines which atoms are bound — refs are already declared.
    """
    if objective_data is None:
        objective_data = {}
    atoms_by_id = {a.id: a for a in atoms}

    if objective_kind == "presence":
        primary = objective_data.get("primary_ref")
        if primary and primary in atoms_by_id:
            label = _presence_label(atoms_by_id[primary].text)
            return f"Verify the explicitly described {label} is visible and available."
        refs = objective_data.get("refs") or ()
        labels = []
        for r in refs:
            if r in atoms_by_id:
                labels.append(atoms_by_id[r].text.rstrip(".").strip())
        if labels:
            return f"Verify the explicitly listed items for {subject}: {'; '.join(labels)}."
        return f"Verify the explicitly described {subject} is visible and available."

    if objective_kind == "behavior":
        primary = objective_data.get("primary_ref")
        if primary and primary in atoms_by_id:
            text = atoms_by_id[primary].text.rstrip(".").strip()
            if _USER_ACTION_PHRASE.search(text):
                return _render_behavior_intent_from_atom(text)
            return f"Verify that {text}."
        return f"Verify {subject} displays the explicitly defined behavior."

    if objective_kind == "combination":
        primary = objective_data.get("primary_ref")
        supporting = objective_data.get("supporting_refs") or ()
        primary_text = ""
        if primary and primary in atoms_by_id:
            primary_text = atoms_by_id[primary].text.rstrip(".").strip()
        intent = f"Verify that {primary_text}." if primary_text else f"Verify the documented behavior for {subject}."
        supporting_labels = []
        for r in supporting:
            if r in atoms_by_id:
                supporting_labels.append(_presence_label(atoms_by_id[r].text))
        if supporting_labels:
            intent += f" The related control is present: {'; '.join(supporting_labels)}."
        return intent

    if objective_kind == "boundary":
        value = objective_data.get("value", "")
        direction = objective_data.get("direction", "")
        unit = objective_data.get("unit", "")
        limit_direction = objective_data.get("limit_direction", "maximum")
        if direction == "below":
            verb = "rejects or prevents" if limit_direction == "minimum" else "accepts"
            return f"Verify {subject} {verb} a value of {value}{unit}, below the explicit limit."
        if direction == "exact":
            return f"Verify {subject} accepts the explicit limit value of {value}{unit}."
        if direction == "above":
            verb = "accepts" if limit_direction == "minimum" else "rejects or prevents"
            return f"Verify {subject} {verb} a value of {value}{unit}, beyond the explicit limit."
        return f"Verify the explicit boundary rule for {subject}."

    if objective_kind == "mandatory":
        field_label = objective_data.get("field_label") or subject
        variant = objective_data.get("variant", "populated")
        if variant == "populated":
            return f"Verify {field_label} accepts a valid populated value."
        return f"Verify {field_label} is rejected or prevented when it is left empty."

    if objective_kind == "state":
        state_value = objective_data.get("state_value", "")
        return f"Verify {subject} displays the explicitly defined {state_value} state."

    if objective_kind == "policy":
        policy_line = objective_data.get("policy_line", "")
        return f"Verify the explicit product policy for {subject}: {policy_line}."

    if objective_kind == "security":
        primary = objective_data.get("predicate_ref")
        if primary and primary in atoms_by_id:
            text = atoms_by_id[primary].text.rstrip(".").strip()
            return f"Verify the explicitly described security behavior for {subject}: {text}."
        return f"Verify the explicitly described security behavior for {subject}."

    if objective_kind == "file_type":
        variant = objective_data.get("variant", "accept")
        if variant == "reject":
            return f"Verify the upload rejects or prevents non-PDF or unsupported file types under {subject}."
        return f"Verify the upload accepts PDF files as explicitly required by {subject}."

    if objective_kind == "sample_value":
        refs = objective_data.get("refs") or ()
        for r in refs:
            if r in atoms_by_id:
                return (
                    f"Verify the sample value '{atoms_by_id[r].text}' is shown as a "
                    f"non-exhaustive example for {subject}."
                )
        return f"Verify the sample value is shown as a non-exhaustive example for {subject}."

    if objective_kind == "static_list":
        refs = objective_data.get("refs") or ()
        labels = [atoms_by_id[r].text for r in refs if r in atoms_by_id]
        if not labels:
            return f"Verify the explicitly listed items for {subject}."
        if len(labels) > 1:
            return f"Verify the explicitly listed items for {subject}: {'; '.join(labels)}."
        primary_text = _clean_atomic_text(labels[0]).rstrip(".")
        # Presence-only rendering takes precedence over broad lexical action cues.
        if _looks_like_presence(primary_text):
            label = _presence_label(primary_text)
            return f"Verify the explicitly described {label} is visible and available."
        # Behavior-scenario rendering: extract the observable action from the atom.
        if _looks_like_behavior(primary_text):
            return _render_behavior_intent_from_atom(primary_text)
        return f"Verify the explicitly listed items for {subject}: {primary_text}."

    if objective_kind == "no_results":
        return f"Verify {subject} displays the empty result state as explicitly described."

    if objective_kind == "action_visibility":
        return f"Verify the explicitly described {subject} is visible and available."

    if objective_kind == "success_failure":
        variant = objective_data.get("variant", "success")
        if variant == "success":
            return f"Verify {subject} displays the explicitly defined success state."
        return f"Verify {subject} displays the explicitly defined failure state."

    return f"Verify the application provides the behavior described for {subject}."


def _presence_label(atom_text: str) -> str:
    """Extract a short noun label from presence-only text."""
    text = atom_text.strip().rstrip(".")
    match = re.match(r"^the page provides\s+(.+)$", text, re.IGNORECASE)
    if match:
        return match.group(1).strip().strip('"')
    # "Dashboard provides Logout" → strip subject prefix for the label.
    match = re.match(r"^[\w ]+\s+provides?\s+(.+)$", text, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return atom_text.strip()


def _looks_like_behavior(text: str) -> bool:
    """Return True when *text* supports an executable user/system action.

    Presence statements (for example, "The system provides Logout.") are not
    behavior scenarios unless the source also states an explicit action.
    """
    t = text.strip().lower()
    if _looks_like_presence(text):
        return False
    if re.search(r"^(?:after\s+|if\s+)", t):
        return True
    if _USER_ACTION_PHRASE.search(t):
        return True
    return bool(
        re.search(
            r"\b(?:accepts?|displays?|shows?|allows?|rejects?|returns?|"
            r"filters?|saves?|submits?|prevents?|applies?|opens?|closes?)\b",
            t,
        )
    )


def _looks_like_presence(text: str) -> bool:
    """Return True for source wording that only asserts presence or visibility.

    A "provides" sentence describes a capability/control being present; it
    does not by itself authorize an execution or state-transition scenario.
    """
    t = text.strip()
    return bool(
        _PRESENCE_STATEMENT.fullmatch(t)
        or _PRESENCE_STATE_STATEMENT.fullmatch(t)
    )


def _render_behavior_intent_from_atom(atom_text: str) -> str:
    """Build an executable, well-formed intent sentence from a behavior atom.

    Preserves entity capitalization (e.g. "Dashboard"). Detects several common
    atom structures so the wrapped intent stays grammatical.
    """
    clean = _clean_atomic_text(atom_text).rstrip(".")

    # Pattern A: "After X, display/show/return(s) Y" → "Given X, verify Y."
    m = re.match(
        r"(?:after\s|After\s)(.+),\s*(.+)", clean, re.IGNORECASE
    )
    if m:
        condition = m.group(1)
        action = m.group(2)
        # Convert "displays Dashboard" → "the Dashboard is displayed"
        m_show = re.match(r"(?:displays?|shows?|reveals)\s+(.+)", action, re.IGNORECASE)
        if m_show:
            target = m_show.group(1)
            return f"Given {condition}, verify that the {target} is displayed."
        return f"Given {condition}, verify {action}."

    # Pattern B: "If X, display/show/return(s) Y" → "When X, verify Y."
    m = re.match(r"(?:if\s|If\s)(.+),\s*(.+)", clean, re.IGNORECASE)
    if m:
        condition = m.group(1)
        action = m.group(2)
        m_show = re.match(r"(?:displays?|shows?|reveals)\s+(.+)", action, re.IGNORECASE)
        if m_show:
            target = m_show.group(1)
            return f"When {condition}, verify that the {target} is displayed."
        return f"When {condition}, verify {action}."

    # Pattern C (credential-special case): "The system accepts valid
    # username[+valid password] and allows login" → credential submission.
    # Checked first so the generic Pattern C below does not swallow it.
    m = re.match(
        r"(?:the\s+system\s+)?accepts?\s+valid\s+username[\s+]*valid\s+password"
        r"\s+and\s+allows?\s+(.+)",
        clean,
        re.IGNORECASE,
    )
    if m:
        outcome = m.group(1)
        return (
            f"Submit valid username and valid password as the username and "
            f"password credentials; verify that {outcome} is allowed."
        )
    # Pattern C (generic): "The system accepts X and allows Y" → submission
    # of X and verification of Y. The accepted-value group is rendered
    # verbatim as the submission target so no credential type is
    # invented when the evidence does not mention credentials.
    m = re.match(
        r"(?:the\s+system\s+)?(?:accepts?|accept)\s+(.+?)\s+and\s+allows?\s+(.+)",
        clean,
        re.IGNORECASE,
    )
    if m:
        accepted = m.group(1)
        outcome = m.group(2)
        return f"Submit {accepted} and verify that {outcome} is allowed."

    # Fallback: lowercase first char only, wrap normally.
    if len(clean) > 1 and clean[0].isupper():
        clean = clean[0].lower() + clean[1:]
    elif len(clean) == 1:
        clean = clean.lower()
    return f"Verify that {clean}."


def _normalize_objective_data(objective_data: dict | None) -> tuple:
    """Deterministic normalization of objective_data for dedup identity."""
    if not objective_data:
        return ()
    items = []
    for key in sorted(objective_data.keys()):
        value = objective_data[key]
        if isinstance(value, (list, tuple)):
            items.append((key, tuple(str(v) for v in value)))
        else:
            items.append((key, str(value)))
    return tuple(items)


def _candidate_identity(c: ScenarioCandidate) -> tuple:
    """Proposed dedup identity: (requirement_ref, category, technique,
    objective_kind, normalized_objective_data, evidence_refs)."""
    return (
        c.requirement_ref,
        c.category,
        c.technique,
        c.objective_kind,
        _normalize_objective_data(c.objective_data),
        c.evidence_refs,
    )


def _is_security_predicate_atom(atom: EvidenceAtom) -> bool:
    """Security predicate recognition: predicate flag + kind in {observed_value, explicit_behavior}."""
    return (
        atom.kind in {"observed_value", "explicit_behavior"}
        and bool(_SECURITY_PREDICATE.search(atom.text))
    )


def _find_atom_by_normalized(atoms: list[EvidenceAtom], text: str) -> EvidenceAtom | None:
    normalized = _normalize_evidence(text)
    for atom in atoms:
        if _normalize_evidence(atom.text) == normalized:
            return atom
    return None


# ---------------------------------------------------------------------------
# Producer: atomic behaviors → ScenarioCandidate
# ---------------------------------------------------------------------------

def _atomic_candidates(
    behaviors: list[_AtomicBehavior],
    atoms: list[EvidenceAtom],
    subject: str,
) -> list[ScenarioCandidate]:
    """Convert atomic behaviors into declared-binding candidates."""
    candidates: list[ScenarioCandidate] = []
    constraint_refs = tuple(a.id for a in atoms if a.kind == "guardrail")
    for behavior in behaviors:
        label = behavior.label
        if behavior.kind in {"limit", "state"}:
            continue
        atom = _find_atom_by_normalized(atoms, behavior.source_text)
        ref = atom.id if atom else None
        req_ref = atom.requirement_ref if atom else ""
        if atom is None:
            continue
        if behavior.kind == "file_type":
            candidates.append(
                ScenarioCandidate(
                    requirement_ref=req_ref,
                    category="positive",
                    technique="EP",
                    priority="high",
                    evidence_refs=(ref,) if ref else (),
                    constraint_refs=constraint_refs,
                    objective_kind="file_type",
                    objective_data={"primary_ref": ref} if ref else None,
                )
            )
            candidates.append(
                ScenarioCandidate(
                    requirement_ref=req_ref,
                    category="negative",
                    technique="negative",
                    priority="high",
                    evidence_refs=(ref,) if ref else (),
                    constraint_refs=constraint_refs,
                    objective_kind="file_type",
                    objective_data={"primary_ref": ref, "variant": "reject"} if ref else None,
                )
            )
        elif behavior.kind == "confirmation":
            candidates.append(
                ScenarioCandidate(
                    requirement_ref=req_ref,
                    category="positive",
                    technique="EP",
                    priority="medium",
                    evidence_refs=(ref,) if ref else (),
                    constraint_refs=constraint_refs,
                    objective_kind="presence",
                    objective_data={"primary_ref": ref} if ref else None,
                )
            )
        elif behavior.kind == "confirmation_behavior":
            candidates.append(
                ScenarioCandidate(
                    requirement_ref=req_ref,
                    category="positive",
                    technique="EP",
                    priority="high",
                    evidence_refs=(ref,) if ref else (),
                    constraint_refs=constraint_refs,
                    objective_kind="behavior",
                    objective_data={"primary_ref": ref} if ref else None,
                )
            )
        elif behavior.kind in {"action", "control", "tab"}:
            candidates.append(
                ScenarioCandidate(
                    requirement_ref=req_ref,
                    category="positive",
                    technique="EP",
                    priority="medium",
                    evidence_refs=(ref,) if ref else (),
                    constraint_refs=constraint_refs,
                    objective_kind="presence",
                    objective_data={"primary_ref": ref} if ref else None,
                )
            )
        elif behavior.kind == "behavior":
            if atom.kind not in {"explicit_behavior", "observed_value"}:
                continue
            if _is_no_result_evidence(behavior.source_text):
                category, priority = "negative", "medium"
            else:
                category, priority = "positive", "medium"
            candidates.append(
                ScenarioCandidate(
                    requirement_ref=req_ref,
                    category=category,
                    technique="EP",
                    priority=priority,
                    evidence_refs=(ref,),
                    constraint_refs=constraint_refs,
                    objective_kind="behavior",
                    objective_data={"primary_ref": ref},
                )
            )
    return candidates


# ---------------------------------------------------------------------------
# Producer: _scenarios_for_requirement → ScenarioCandidate list
# ---------------------------------------------------------------------------

def _scenarios_for_requirement(
    requirement: Requirement,
    profile: str,
    evidence_atoms: list[EvidenceAtom],
) -> tuple[list[ScenarioIntent], BaselineEvaluation, list[EvidenceAtom]]:
    if requirement.status != "TESTABLE":
        return [], BaselineEvaluation(), evidence_atoms

    text = _requirement_text(requirement)
    subject = _subject(requirement)
    atomic_behaviors = _extract_atomic_behaviors(requirement)
    has_confirmation_children = any(
        item.kind in {"confirmation", "confirmation_behavior"} for item in atomic_behaviors
    )
    non_guardrail = [a for a in evidence_atoms if a.kind != "guardrail"]
    constraint_refs = tuple(a.id for a in evidence_atoms if a.kind == "guardrail")
    zero_atom_requirement = len(non_guardrail) == 0

    candidates: list[ScenarioCandidate] = []

    # a. Atomic candidates
    candidates.extend(_atomic_candidates(atomic_behaviors, evidence_atoms, subject))

    # b. Mandatory
    if _is_mandatory(text):
        mandatory_atom = next((a for a in evidence_atoms if a.kind == "mandatory"), None)
        mref = mandatory_atom.id if mandatory_atom else None
        if mref:
            candidates.append(
                ScenarioCandidate(
                    requirement_ref=requirement.id,
                    category="positive",
                    technique="EP",
                    priority="high",
                    evidence_refs=(mref,),
                    constraint_refs=constraint_refs,
                    objective_kind="mandatory",
                    objective_data={"field_label": subject, "variant": "populated", "primary_ref": mref},
                )
            )
            candidates.append(
                ScenarioCandidate(
                    requirement_ref=requirement.id,
                    category="negative",
                    technique="negative",
                    priority="high",
                    evidence_refs=(mref,),
                    constraint_refs=constraint_refs,
                    objective_kind="mandatory",
                    objective_data={"field_label": subject, "variant": "empty", "primary_ref": mref},
                )
            )

    # c. BVA / boundary
    limit = _explicit_limit(requirement, text)
    if limit is not None:
        value, direction, unit = limit
        boundary_atom = next((a for a in evidence_atoms if a.kind == "boundary"), None)
        bref = boundary_atom.id if boundary_atom else None
        if bref:
            below, exact, above = _boundary_values(value, direction)
            for val, dirn, prio in ((below, "below", "medium"), (exact, "exact", "high"), (above, "above", "high")):
                candidates.append(
                    ScenarioCandidate(
                        requirement_ref=requirement.id,
                        category="boundary",
                        technique="BVA",
                        priority=prio,
                        evidence_refs=(bref,),
                        constraint_refs=constraint_refs,
                        objective_kind="boundary",
                        objective_data={
                            "value": val, "direction": dirn, "unit": unit,
                            "limit_direction": direction, "primary_ref": bref,
                        },
                    )
                )

    # d. State
    if _STATE.search(text):
        for state_atom in (a for a in evidence_atoms if a.kind == "state"):
            candidates.append(
                ScenarioCandidate(
                    requirement_ref=requirement.id,
                    category="positive",
                    technique="EP",
                    priority="medium",
                    evidence_refs=(state_atom.id,),
                    constraint_refs=constraint_refs,
                    objective_kind="state",
                    objective_data={"state_value": state_atom.text, "primary_ref": state_atom.id},
                )
            )

    # Confirmation path (synthesized presence atoms when source names Confirm+Cancel)
    if (
        _CONFIRMATION.search(text)
        and _has_confirm_and_cancel(text)
        and not has_confirmation_children
    ):
        control_atoms = [
            a for a in evidence_atoms
            if a.kind in {"presence", "observed_value"} and _CONFIRMATION.search(a.text)
        ]
        if not control_atoms:
            synthesized = []
            for label in ("Confirm", "Cancel"):
                if re.search(rf"\b{label}\b", text, re.IGNORECASE):
                    synth_id = f"{requirement.id}-E{len(evidence_atoms) + len(synthesized) + 1:02d}"
                    synthesized.append(
                        EvidenceAtom(
                            id=synth_id,
                            requirement_ref=requirement.id,
                            kind="presence",
                            text=f"{label} action",
                        )
                    )
            control_atoms = synthesized
            evidence_atoms = [*evidence_atoms, *synthesized]
        for atom in control_atoms:
            candidates.append(
                ScenarioCandidate(
                    requirement_ref=requirement.id,
                    category="positive",
                    technique="EP",
                    priority="high",
                    evidence_refs=(atom.id,),
                    constraint_refs=constraint_refs,
                    objective_kind="presence",
                    objective_data={"primary_ref": atom.id},
                )
            )

    # Success and failure outcomes require explicit outcome evidence atoms.
    if _SUCCESS.search(text) and _FAILURE.search(text):
        for variant, pattern in (("success", _SUCCESS), ("failure", _FAILURE)):
            variant_atoms = [
                atom for atom in non_guardrail
                if pattern.search(atom.text)
                and _is_success_failure_outcome(atom.text, variant)
                and any(
                    behavior.kind == "behavior"
                    and _normalize_evidence(behavior.source_text) == _normalize_evidence(atom.text)
                    for behavior in atomic_behaviors
                )
            ]
            if variant_atoms:
                candidates.append(
                    ScenarioCandidate(
                        requirement_ref=requirement.id,
                        category="positive" if variant == "success" else "negative",
                        technique="EP" if variant == "success" else "negative",
                        priority="high",
                        evidence_refs=tuple(atom.id for atom in variant_atoms),
                        constraint_refs=constraint_refs,
                        objective_kind="success_failure",
                        objective_data={"variant": variant},
                    )
                )

    # Action-only visibility fallback requires explicit presence evidence.
    if not candidates and _ACTION.search(text):
        action_atoms = [
            atom for atom in non_guardrail
            if atom.kind in {"presence", "observed_value"}
            and _ACTION.search(atom.text)
        ]
        if len(action_atoms) == 1:
            atom = action_atoms[0]
            candidates.append(
                ScenarioCandidate(
                    requirement_ref=requirement.id,
                    category="positive",
                    technique="EP",
                    priority="medium",
                    evidence_refs=(atom.id,),
                    constraint_refs=constraint_refs,
                    objective_kind="action_visibility",
                    objective_data={"primary_ref": atom.id},
                )
            )
    elif not candidates and zero_atom_requirement and _supports_zero_atom_behavior(requirement):
        candidates.append(
            ScenarioCandidate(
                requirement_ref=requirement.id,
                category="positive",
                technique="EP",
                priority="medium",
                evidence_refs=(),
                constraint_refs=constraint_refs,
                objective_kind="behavior",
                objective_data=None,
            )
        )

    # Baseline policy candidates
    evaluation = evaluate_baseline(requirement, evidence_atoms, subject)
    for cat, tech, _intent, prio in evaluation.policy_candidates:
        rule_key_match = re.search(r"policy for [^:]+: (.+)\.$", _intent)
        policy_line = rule_key_match.group(1) if rule_key_match else _intent
        candidates.append(
            ScenarioCandidate(
                requirement_ref=requirement.id,
                category=cat,
                technique=tech,
                priority=prio,
                evidence_refs=(),
                constraint_refs=constraint_refs,
                objective_kind="policy",
                objective_data={"rule_key": "", "policy_line": policy_line},
            )
        )

    # f. Backfill via declared-ref set arithmetic
    candidates = [
        candidate for candidate in candidates
        if candidate.objective_kind != "behavior"
        or candidate.evidence_refs
        or not non_guardrail
    ]
    candidates = _ensure_evidence_candidates(
        requirement, candidates, evidence_atoms, subject, constraint_refs
    )

    # g/h. Comprehensive/Extra combination candidates
    if profile in ("comprehensive", "extra"):
        candidates = _add_combination_candidates(
            candidates, evidence_atoms, subject, constraint_refs, zero_atom_requirement
        )

    # i. Security candidates
    if profile in ("comprehensive", "extra"):
        if _SECURITY.search(text):
            predicate_atoms = [a for a in non_guardrail if _is_security_predicate_atom(a)]
            for atom in predicate_atoms:
                candidates.append(
                    ScenarioCandidate(
                        requirement_ref=requirement.id,
                        category="security",
                        technique="security",
                        priority="high",
                        evidence_refs=(atom.id,),
                        constraint_refs=constraint_refs,
                        objective_kind="security",
                        objective_data={"predicate_ref": atom.id},
                    )
                )

    # Second backfill pass after comprehensive/extra additions
    candidates = _ensure_evidence_candidates(
        requirement, candidates, evidence_atoms, subject, constraint_refs
    )

    scenarios = _materialize_scenarios(requirement.id, candidates, evidence_atoms, subject)
    return scenarios, evaluation, evidence_atoms


# ---------------------------------------------------------------------------
# Combination construction
# ---------------------------------------------------------------------------

def _add_combination_candidates(
    candidates: list[ScenarioCandidate],
    evidence_atoms: list[EvidenceAtom],
    subject: str,
    constraint_refs: tuple[str, ...],
    zero_atom_requirement: bool,
) -> list[ScenarioCandidate]:
    """Explicit combination candidates: presence/observed_value + explicit_behavior.

    Locked matrix: presence/observed_value + explicit_behavior allowed via
    explicit planner op (co-observation only). Renderer must not introduce
    causal connectives.
    """
    if zero_atom_requirement:
        return candidates
    non_guardrail = [a for a in evidence_atoms if a.kind != "guardrail"]
    behavior_atoms = [a for a in non_guardrail if a.kind == "explicit_behavior"]
    presence_atoms = [a for a in non_guardrail if a.kind in {"presence", "observed_value"}]
    if not behavior_atoms or not presence_atoms:
        return candidates
    primary = behavior_atoms[0]
    supporting = tuple(a.id for a in presence_atoms)
    combo = ScenarioCandidate(
        requirement_ref=primary.requirement_ref,
        category="edge",
        technique="exploratory",
        priority="low",
        evidence_refs=(primary.id, *supporting),
        constraint_refs=constraint_refs,
        objective_kind="combination",
        objective_data={
            "primary_ref": primary.id,
            "supporting_refs": supporting,
            "relationship": "coobservation",
        },
    )
    if _candidate_identity(combo) not in {_candidate_identity(c) for c in candidates}:
        candidates.append(combo)
    return candidates


# ---------------------------------------------------------------------------
# Backfill via declared-ref set arithmetic
# ---------------------------------------------------------------------------

def _ensure_evidence_candidates(
    requirement: Requirement,
    candidates: list[ScenarioCandidate],
    evidence_atoms: list[EvidenceAtom],
    subject: str,
    constraint_refs: tuple[str, ...],
) -> list[ScenarioCandidate]:
    """Add the smallest declared-binding candidates for atoms not yet referenced.

    Unmatched calculation uses declared-ref set arithmetic, not lexical matching.
    """
    declared_refs: set[str] = set()
    for c in candidates:
        declared_refs.update(c.evidence_refs)

    unmatched = [
        a for a in evidence_atoms
        if a.kind != "guardrail" and a.id not in declared_refs
    ]
    if not unmatched:
        return candidates

    sample_atoms = [a for a in unmatched if a.kind == "sample_value"]
    for atom in sample_atoms:
        candidates.append(
            ScenarioCandidate(
                requirement_ref=requirement.id,
                category="positive",
                technique="EP",
                priority="medium",
                evidence_refs=(atom.id,),
                constraint_refs=constraint_refs,
                objective_kind="sample_value",
                objective_data={"refs": (atom.id,)},
            )
        )
    unmatched = [a for a in unmatched if a not in sample_atoms]
    if not unmatched:
        return candidates

    static_atoms = [
        a for a in unmatched
        if a.kind in {"observed_value", "option", "state", "presence"}
    ]
    if static_atoms:
        candidates.append(
            ScenarioCandidate(
                requirement_ref=requirement.id,
                category="positive",
                technique="EP",
                priority="medium",
                evidence_refs=tuple(a.id for a in static_atoms),
                constraint_refs=constraint_refs,
                objective_kind="static_list",
                objective_data={"refs": tuple(a.id for a in static_atoms)},
            )
        )
        unmatched = [a for a in unmatched if a not in static_atoms]

    for atom in unmatched:
        if atom.kind == "guardrail":
            continue
        if atom.kind == "mandatory":
            candidates.append(
                ScenarioCandidate(
                    requirement_ref=requirement.id,
                    category="positive",
                    technique="EP",
                    priority="high",
                    evidence_refs=(atom.id,),
                    constraint_refs=constraint_refs,
                    objective_kind="mandatory",
                    objective_data={"field_label": subject, "variant": "populated", "primary_ref": atom.id},
                )
            )
            candidates.append(
                ScenarioCandidate(
                    requirement_ref=requirement.id,
                    category="negative",
                    technique="negative",
                    priority="high",
                    evidence_refs=(atom.id,),
                    constraint_refs=constraint_refs,
                    objective_kind="mandatory",
                    objective_data={"field_label": subject, "variant": "empty", "primary_ref": atom.id},
                )
            )
            continue
        if atom.kind == "boundary":
            candidates.append(
                ScenarioCandidate(
                    requirement_ref=requirement.id,
                    category="boundary",
                    technique="BVA",
                    priority="high",
                    evidence_refs=(atom.id,),
                    constraint_refs=constraint_refs,
                    objective_kind="boundary",
                    objective_data={"value": "", "direction": "rule", "unit": "", "primary_ref": atom.id},
                )
            )
            continue
        if atom.kind == "file_boundary":
            candidates.append(
                ScenarioCandidate(
                    requirement_ref=requirement.id,
                    category="positive",
                    technique="EP",
                    priority="high",
                    evidence_refs=(atom.id,),
                    constraint_refs=constraint_refs,
                    objective_kind="file_type",
                    objective_data={"primary_ref": atom.id},
                )
            )
            continue
        if (
            atom.kind == "explicit_behavior"
            or _BEHAVIOR_PHRASE.search(atom.text)
            or _classify_atomic_behavior(atom.text, _context_mode(atom.text), "source") == "behavior"
        ):
            candidates.append(
                ScenarioCandidate(
                    requirement_ref=requirement.id,
                    category="positive",
                    technique="EP",
                    priority="medium",
                    evidence_refs=(atom.id,),
                    constraint_refs=constraint_refs,
                    objective_kind="behavior",
                    objective_data={"primary_ref": atom.id},
                )
            )
        else:
            candidates.append(
                ScenarioCandidate(
                    requirement_ref=requirement.id,
                    category="positive",
                    technique="EP",
                    priority="medium",
                    evidence_refs=(atom.id,),
                    constraint_refs=constraint_refs,
                    objective_kind="presence",
                    objective_data={"primary_ref": atom.id},
                )
            )
    return candidates


# ---------------------------------------------------------------------------
# Materialization: ScenarioCandidate → ScenarioIntent
# ---------------------------------------------------------------------------

def validate_candidate_authority(
    candidate: ScenarioCandidate,
    atoms: list[EvidenceAtom],
) -> None:
    """Reject candidates whose declared authority is invalid for their objective."""
    atoms_by_id = {atom.id: atom for atom in atoms}
    requirement_atoms = [
        atom for atom in atoms if atom.requirement_ref == candidate.requirement_ref
    ]
    non_guardrail = [atom for atom in requirement_atoms if atom.kind != "guardrail"]

    if candidate.objective_kind != "policy" and non_guardrail and not candidate.evidence_refs:
        raise ValueError(
            f"Candidate '{candidate.objective_kind}' for requirement "
            f"'{candidate.requirement_ref}' has no declared evidence refs."
        )
    if candidate.objective_kind != "policy" and not non_guardrail and candidate.evidence_refs:
        raise ValueError(
            f"Candidate '{candidate.objective_kind}' for requirement "
            f"'{candidate.requirement_ref}' declares refs without non-guardrail source evidence."
        )

    declared_atoms: list[EvidenceAtom] = []
    for ref in candidate.evidence_refs:
        atom = atoms_by_id.get(ref)
        if atom is None:
            raise ValueError(f"Candidate declares unknown evidence ref '{ref}'.")
        if atom.requirement_ref != candidate.requirement_ref:
            raise ValueError(f"Candidate declares foreign evidence ref '{ref}'.")
        if atom.kind == "guardrail":
            raise ValueError(f"Candidate declares guardrail evidence ref '{ref}'.")
        declared_atoms.append(atom)

    if candidate.objective_kind == "security":
        predicate_ref = (candidate.objective_data or {}).get("predicate_ref")
        if (
            not declared_atoms
            or not predicate_ref
            or predicate_ref not in candidate.evidence_refs
            or not any(_is_security_predicate_atom(atom) for atom in declared_atoms)
        ):
            raise ValueError(
                f"Security candidate for requirement '{candidate.requirement_ref}' "
                "requires a declared predicate-bearing evidence ref."
            )

    if candidate.objective_kind == "action_visibility":
        if not declared_atoms or any(atom.kind not in {"presence", "observed_value"} for atom in declared_atoms):
            raise ValueError(
                f"Action-visibility candidate for requirement '{candidate.requirement_ref}' "
                "requires compatible presence evidence."
            )

    if candidate.objective_kind == "success_failure":
        variant = (candidate.objective_data or {}).get("variant")
        declared_refs = set(candidate.evidence_refs)
        if declared_refs != {atom.id for atom in declared_atoms}:
            raise ValueError(
                f"Success/failure candidate for requirement '{candidate.requirement_ref}' "
                "must bind exactly its declared outcome atoms."
            )
        outcome = _SUCCESS if variant == "success" else _FAILURE if variant == "failure" else None
        if (
            outcome is None
            or not declared_atoms
            or any(not outcome.search(atom.text) for atom in declared_atoms)
            or any(not re.search(r"\b(?:dialog|message|state|result)\b", atom.text, re.IGNORECASE) for atom in declared_atoms)
            or any(not _is_success_failure_outcome(atom.text, variant) for atom in declared_atoms)
        ):
            raise ValueError(
                f"Success/failure candidate for requirement '{candidate.requirement_ref}' "
                "requires compatible outcome evidence."
            )

    if candidate.objective_kind == "combination":
        objective_data = candidate.objective_data or {}
        required_refs = {
            objective_data.get("primary_ref"),
            *(objective_data.get("supporting_refs") or ()),
        }
        required_refs.discard(None)
        if not required_refs or set(candidate.evidence_refs) != required_refs:
            raise ValueError(
                f"Combination candidate for requirement '{candidate.requirement_ref}' "
                "must declare exactly its objective refs."
            )

    objective_data = candidate.objective_data or {}
    primary_ref = objective_data.get("primary_ref") or objective_data.get("predicate_ref")
    expected_kinds = {
        "boundary": {"boundary"},
        "mandatory": {"mandatory"},
        "state": {"state"},
        "presence": {"presence", "observed_value", "option"},
        "behavior": {"explicit_behavior", "observed_value"},
        "file_type": {"file_boundary"},
        "action_visibility": {"presence", "observed_value"},
    }
    if candidate.objective_kind in expected_kinds and non_guardrail:
        primary_atom = atoms_by_id.get(primary_ref) if primary_ref else None
        if not primary_ref or primary_ref not in candidate.evidence_refs:
            raise ValueError(
                f"Candidate '{candidate.objective_kind}' for requirement "
                f"'{candidate.requirement_ref}' must declare its primary evidence ref."
            )
        compatible_kind = primary_atom is not None and primary_atom.kind in expected_kinds[candidate.objective_kind]
        source_behavior = (
            candidate.objective_kind == "behavior"
            and primary_atom is not None
            and _classify_atomic_behavior(
                primary_atom.text,
                _context_mode(primary_atom.text),
                "source",
            ) == "behavior"
        )
        if not compatible_kind and not source_behavior:
            raise ValueError(
                f"Candidate '{candidate.objective_kind}' for requirement "
                f"'{candidate.requirement_ref}' declares incompatible primary evidence."
            )


def _materialize_scenarios(
    requirement_id: str,
    candidates: list[ScenarioCandidate],
    evidence_atoms: list[EvidenceAtom],
    subject: str,
) -> list[ScenarioIntent]:
    """Convert declared candidates to ScenarioIntents.

    - Validates declared authority before rendering or materialization.
    - Renders intent from objective_kind/objective_data + bound atoms.
    - Copies candidate.evidence_refs and constraint_refs verbatim.
    - Dedups by (requirement_ref, category, technique, objective_kind,
      normalized_objective_data, evidence_refs).
    - Never calls _atom_matches_candidate to derive refs.
    """
    scenarios: list[ScenarioIntent] = []
    seen: set[tuple] = set()
    for candidate in candidates:
        validate_candidate_authority(candidate, evidence_atoms)
        if candidate.category not in SCENARIO_CATEGORIES:
            raise ValueError(f"Unsupported scenario category '{candidate.category}'.")
        if candidate.technique not in SCENARIO_TECHNIQUES:
            raise ValueError(f"Unsupported scenario technique '{candidate.technique}'.")
        identity = _candidate_identity(candidate)
        if identity in seen:
            continue
        seen.add(identity)
        intent = render_intent(
            requirement_id,
            candidate.objective_kind,
            candidate.objective_data,
            evidence_atoms,
            subject,
        )
        scenario_id = f"{requirement_id}-S{len(scenarios) + 1:02d}"
        scenarios.append(
            ScenarioIntent(
                id=scenario_id,
                requirement_ref=candidate.requirement_ref or requirement_id,
                category=candidate.category,
                technique=candidate.technique,
                intent=intent,
                priority=candidate.priority,
                evidence_refs=candidate.evidence_refs,
                constraint_refs=candidate.constraint_refs,
                objective_kind=candidate.objective_kind,
                objective_data=freeze_objective_data(candidate.objective_data),
            )
        )
    return scenarios


# ---------------------------------------------------------------------------
# Evidence atom extraction
# ---------------------------------------------------------------------------

def extract_evidence_atoms(requirement: Requirement) -> list[EvidenceAtom]:
    """Extract explicit, requirement-local testable evidence in source order."""

    if requirement.status != "TESTABLE":
        return []
    atoms: list[EvidenceAtom] = []
    seen: set[tuple[str, str]] = set()
    mode = _context_mode(requirement.statement)
    sources = (
        ("statement", [requirement.statement]),
        ("acceptance", requirement.acceptance_criteria),
        ("details", requirement.details),
        ("constraints", requirement.constraints),
    )

    for source_name, values in sources:
        for raw_value in values:
            value = _clean_atomic_text(raw_value)
            if not value or not value.strip("- "):
                continue
            positive_values, guardrail_values = _split_guardrail_clauses(value)
            for guardrail in guardrail_values:
                key = ("guardrail", _normalize_evidence(guardrail))
                if key not in seen:
                    seen.add(key)
                    atoms.append(
                        EvidenceAtom(
                            id=f"{requirement.id}-E{len(atoms) + 1:02d}",
                            requirement_ref=requirement.id,
                            kind="guardrail",
                            text=guardrail,
                        )
                    )
            if _is_atomic_parent(value):
                mode = _context_mode(value) or mode
                continue

            for positive_value in positive_values:
                if not positive_value:
                    continue
                sample_values = _sample_values(positive_value)
                inline_items = _inline_evidence_items(positive_value)
                values_to_classify = sample_values or inline_items or [positive_value]
                for evidence_value in values_to_classify:
                    if sample_values:
                        evidence_mode = "sample"
                    else:
                        evidence_mode = mode
                    if inline_items and re.search(
                        r"\b(?:status|state|states)\b", positive_value, re.IGNORECASE
                    ):
                        evidence_mode = "state"
                    elif inline_items:
                        evidence_mode = "option"
                    kind = _classify_evidence(evidence_value, evidence_mode, source_name)
                    if kind is None:
                        continue
                    key = (kind, _normalize_evidence(evidence_value))
                    if key in seen:
                        continue
                    seen.add(key)
                    atoms.append(
                        EvidenceAtom(
                            id=f"{requirement.id}-E{len(atoms) + 1:02d}",
                            requirement_ref=requirement.id,
                            kind=kind,
                            text=evidence_value,
                        )
                    )

    if (
        requirement.status == "TESTABLE"
        and _is_mandatory(requirement.statement)
        and not any(atom.kind == "mandatory" for atom in atoms)
    ):
        atoms.append(
            EvidenceAtom(
                id=f"{requirement.id}-E{len(atoms) + 1:02d}",
                requirement_ref=requirement.id,
                kind="mandatory",
                text=f"{_subject(requirement)} is mandatory",
            )
        )

    return atoms


def _classify_evidence(value: str, mode: str | None, source_name: str) -> str | None:
    """Classify one source line without promoting guardrails to behavior."""

    lowered = value.lower()
    if _is_guardrail_text(value):
        return "guardrail"
    if _is_negated_mandatory(value):
        return None
    if _is_explicit_mandatory(value):
        return "mandatory"
    if _MAXIMUM.search(value) or _MINIMUM.search(value) or _LIMIT_AFTER_VALUE.search(value):
        return "boundary"
    if "only pdf" in lowered or "pdf only" in lowered:
        return "file_boundary"
    if _is_sample_text(value):
        return "sample_value"
    if _looks_like_presence(value):
        return "presence"
    if (
        "opens a modal" in lowered
        or _is_confirmation_behavior(value)
        or _is_functional_evidence(value)
        or _BEHAVIOR_PHRASE.search(value)
    ):
        return "explicit_behavior"
    if mode == "state":
        return "state"
    if mode == "sample":
        return "sample_value"
    if mode == "option":
        return "option"
    if _is_presence_control(value):
        return "presence"
    if re.search(r"\btry\s+again\b", value, re.IGNORECASE) and re.search(r"\bretry\b", value, re.IGNORECASE):
        return "explicit_behavior"
    if _is_action_label(value):
        return "presence"
    if mode in {"action", "control", "tab"}:
        return "presence"
    return "observed_value"


def _inline_evidence_items(value: str) -> list[str]:
    """Split explicit inline value lists while retaining source order."""

    match = re.search(
        r"\b(?:states?|status(?:es)?|options?|values?)\s+include\s+(.+)$",
        value,
        re.IGNORECASE,
    )
    if not match:
        return []
    listed = match.group(1).strip().rstrip(".")
    listed = re.sub(r",?\s+and\s+", ", ", listed, flags=re.IGNORECASE)
    return [item.strip(" `") for item in listed.split(",") if item.strip(" `")]


def _is_explicit_mandatory(value: str) -> bool:
    return bool(
        re.search(
            r"\b(?:mandatory|required|must be provided|cannot be empty|not be empty)\b",
            value,
            re.IGNORECASE,
        )
    ) and not _NEGATED_MANDATORY.search(value)


def _is_negated_mandatory(value: str) -> bool:
    return bool(_NEGATED_MANDATORY.search(value))


def _normalize_evidence(value: str) -> str:
    normalized = re.sub(r"[^\w]+", " ", value.lower(), flags=re.UNICODE)
    return re.sub(r"\s+", " ", normalized).strip()


def _evidence_core_phrase(value: str) -> str:
    core = value.lower().strip().rstrip(".")
    core = re.sub(r"^(?:the|a|an)\s+", "", core)
    core = re.split(
        r"\s+(?:is|are|was|were|displays?|shows?|provides?|contains?|includes?|filters?|opens?|allows?|is available|are available|follows?)\b",
        core,
        maxsplit=1,
    )[0]
    return re.sub(r"\s+", " ", core).strip(" `:-")


def _extract_atomic_behaviors(requirement: Requirement) -> list[_AtomicBehavior]:
    """Extract independently testable, source-backed behaviors in stable order."""

    behaviors: list[_AtomicBehavior] = []
    seen: set[str] = set()
    mode = _context_mode(requirement.statement)

    sources = (
        ("acceptance", requirement.acceptance_criteria),
        ("details", requirement.details),
        ("constraints", requirement.constraints),
    )
    for source_name, values in sources:
        for raw_value in values:
            value = _clean_atomic_text(raw_value)
            if not value:
                continue
            if _is_atomic_parent(value):
                mode = _context_mode(value) or mode
                continue
            positive_values, _ = _split_guardrail_clauses(value)
            for positive_value in positive_values:
                kind = _classify_atomic_behavior(positive_value, mode, source_name)
                if kind is None:
                    continue
                key = _normalize_behavior(positive_value, kind)
                if key in seen:
                    continue
                seen.add(key)
                behaviors.append(
                    _AtomicBehavior(
                        label=_atomic_label(positive_value, kind),
                        source_text=positive_value,
                        kind=kind,
                    )
                )

    value = _clean_atomic_text(requirement.statement)
    if value and not _is_atomic_parent(value) and not _is_guardrail_text(value):
        kind = _classify_atomic_behavior(value, _context_mode(value), "statement")
        if kind in {"behavior", "confirmation_behavior", "file_type", "control", "action", "tab"}:
            key = _normalize_behavior(value, kind)
            if key not in seen:
                seen.add(key)
                behaviors.append(
                    _AtomicBehavior(
                        label=_atomic_label(value, kind),
                        source_text=value,
                        kind=kind,
                    )
                )

    return behaviors


def _clean_atomic_text(value: str) -> str:
    cleaned = re.sub(r"^\s*[-*+•]\s*", "", value or "")
    cleaned = cleaned.strip().strip("`")
    return re.sub(r"\s+", " ", cleaned).strip()


def _is_guardrail_text(value: str) -> bool:
    lowered = value.lower().strip().rstrip(".")
    return lowered.startswith(
        (
            "do not ",
            "don't ",
            "must not ",
            "the generator ",
            "if implementation ",
            "the exact eligibility ",
            "treat this as ",
            "treat these as ",
        )
    ) or bool(
        re.search(
            r"\b(?:not\s+(?:fully|completely|sufficiently)\s+defined|"
            r"not\s+available\s+in\s+(?:the\s+)?supplied\s+evidence|"
            r"not\s+sufficiently\s+supported|must\s+not\s+be\s+invented|"
            r"do\s+not\s+infer)\b",
            lowered,
        )
    )


def _split_guardrail_clauses(value: str) -> tuple[list[str], list[str]]:
    """Split a supported positive clause from a trailing guardrail clause."""

    if _NEGATED_MANDATORY.search(value):
        return [], [value]
    parts = re.split(
        r"\s+(?:,\s*)?but\s+|\s*;\s*",
        value,
        maxsplit=1,
        flags=re.IGNORECASE,
    )
    if len(parts) == 2 and _is_guardrail_text(parts[1]):
        return [parts[0].strip(" ,")], [parts[1].strip()]
    if _is_guardrail_text(value):
        return [], [value]
    return [value], []


def _is_sample_text(value: str) -> bool:
    return bool(re.search(r"\b(?:sample|example)\b", value, re.IGNORECASE))


def _sample_values(value: str) -> list[str]:
    if not _is_sample_text(value):
        return []
    match = re.search(r"\bsample\s+(.+?)\s+message\b", value, re.IGNORECASE)
    if match:
        return [match.group(1).strip(" `:;,.\")")]
    match = re.search(r"\bsample\s+value\s*(?:is|:)?\s*(.+)$", value, re.IGNORECASE)
    if match:
        return [match.group(1).strip(" `:;,.\")")]
    match = re.search(r"\bexample\s*(?:is|:)?\s*(.+)$", value, re.IGNORECASE)
    if match:
        return [match.group(1).strip(" `:;,.\")")]
    return [value]


def _is_confirmation_behavior(value: str) -> bool:
    return bool(
        re.search(
            r"\b(?:cancel|yes|confirm|ok)\b.*\b(?:keeps?|confirms?|leaves?|discard(?:s|ing)?|stays?)\b",
            value,
            re.IGNORECASE,
        )
    )


def _context_mode(value: str) -> str | None:
    lowered = value.lower()
    if "sample value" in lowered or "example" in lowered:
        return "sample"
    if "option" in lowered or "values include" in lowered:
        return "option"
    if "information may include" in lowered or "fields include" in lowered:
        return "static"
    if "confirmation" in lowered or "are you sure" in lowered:
        return "confirmation"
    if re.search(r"\btabs?\b", lowered):
        return "tab"
    if _STATE.search(value):
        return "state"
    if "action button" in lowered or "action" in lowered:
        return "action"
    if "control" in lowered or "table" in lowered and "provide" in lowered:
        return "control"
    return None


def _is_atomic_parent(value: str) -> bool:
    normalized = value.strip().rstrip(".").lower()
    return value.rstrip().endswith(":") or bool(
        re.search(r"\bprovides?\s+.+\bactions?\b$", normalized)
    ) or bool(_SUCCESS.search(value) and _FAILURE.search(value) and not re.search(r";", value)) or normalized in {
        "expected",
        "expected behavior",
        "expected result",
    }


def _is_atomic_guardrail(value: str) -> bool:
    return _is_guardrail_text(value)


def _classify_atomic_behavior(
    value: str,
    mode: str | None,
    source_name: str,
) -> str | None:
    lowered = value.lower()
    if _is_guardrail_text(value):
        return None
    if _looks_like_presence(value):
        return "control"
    if _MAXIMUM.search(value) or _MINIMUM.search(value) or _LIMIT_AFTER_VALUE.search(value):
        return "limit"
    if "only pdf" in lowered or "pdf only" in lowered:
        return "file_type"
    if _is_confirmation_behavior(value):
        return "confirmation_behavior"
    if _is_functional_evidence(value):
        return "behavior"
    if (
        ("done" in lowered and ("close" in lowered or "continue" in lowered))
        or ("try again" in lowered and "retry" in lowered)
        or "opens a modal" in lowered
    ):
        return "behavior"
    if (
        lowered in {"cancel", "yes", "confirm", "ok"}
        or "cancel keeps" in lowered
        or "yes confirms" in lowered
    ):
        return "confirmation"
    if _is_presence_control(value):
        return "control"
    if mode == "state":
        return "state"
    if mode == "tab":
        return "tab"
    if "search content" in lowered:
        return "control"
    if _is_action_label(value):
        return "action"
    if mode in {"action", "control"} and not _is_atomic_parent(value):
        return "control"
    if source_name == "acceptance" and _looks_like_behavior(value):
        return "behavior"
    return None


def _is_action_label(value: str) -> bool:
    return bool(
        re.search(
            r"\b(?:action|button|icon|download|upload|retry|recalculate|clear data|approval|settings|sorting|filter|advanced search)\b",
            value,
            re.IGNORECASE,
        )
    )


def _is_functional_evidence(value: str) -> bool:
    return bool(
        _USER_ACTION_PHRASE.search(value)
        or re.search(
            r"(?:\buser(?:s)?\s+can\b|\bis\s+used\s+to\b|\bcontrols?\s+\w|\bfilters?\s+(?:displayed|rows|results?)\b|\bdisplayed\s+(?:rows?|results?)\b.{0,50}\bfollow(?:s)?\b|\bresult\s+follows?\b|\breturns?\s+(?:the\s+)?(?:displayed\s+)?results?\b|\bapplies?\s+(?:the\s+)?(?:selected\s+|applied\s+)?criterion\b|\bmust\s+be\s+accessible\b|\bis\s+accessible\b|\bno\s+matching\b|\bno\s+results?\b|\bempty\s+(?:result|state)\b|\bclear\s+data\b.{0,80}\b(?:entered|selected|values?)\b|\bclears?\s+(?:entered|selected|values?)\b)",
            value,
            re.IGNORECASE,
        )
    )


def _is_success_failure_outcome(value: str, variant: str) -> bool:
    outcome = _SUCCESS if variant == "success" else _FAILURE
    return bool(
        outcome.search(value)
        and re.search(r"\b(?:dialog|message|state|result)\b", value, re.IGNORECASE)
        and re.search(r"\b(?:displays?|shows?|renders?|presents?)\b", value, re.IGNORECASE)
    )


def _is_no_result_evidence(value: str) -> bool:
    return bool(
        re.search(
            r"\b(?:no\s+matching|no\s+results?|empty\s+(?:result|state)|empty-state)\b",
            value,
            re.IGNORECASE,
        )
    )


def _is_presence_control(value: str) -> bool:
    normalized = value.strip().rstrip(".:*").strip().lower()
    if normalized in {
        "search content",
        "advanced search",
        "column settings",
        "billing period filter",
        "download list",
        "upload usage",
        "approval",
        "retry",
        "recalculate",
        "usage list",
        "batch list",
    }:
        return True
    return bool(re.match(r"^column-level .*(?:icon|control)$", normalized))


def _functional_intent(source_text: str) -> str:
    lowered = source_text.lower()
    if "advanced search" in lowered and "accessible" in lowered:
        return "Verify Advanced Search is accessible from the list/result page."
    if "displayed rows" in lowered and "follow" in lowered:
        return "Verify that displayed rows are expected to follow the applied search result."
    if "done" in lowered and ("close" in lowered or "continue" in lowered):
        return "Verify Done allows the user to close or continue from the success result."
    if "try again" in lowered and "retry" in lowered:
        return "Verify Try Again is available to retry the operation."
    return f"Verify that {source_text.rstrip('.').strip()}."


def _atomic_label(value: str, kind: str) -> str:
    label = value.strip().rstrip(".:*").strip()
    return label


def _normalize_behavior(value: str, kind: str) -> str:
    lowered = re.sub(r"[^a-z0-9 ]+", " ", value.lower())
    normalized = re.sub(r"\s+", " ", lowered).strip()
    return f"{kind}:{normalized}"


def _requirement_text(requirement: Requirement) -> str:
    return " ".join(
        [
            requirement.title,
            requirement.statement,
            *requirement.details,
            *requirement.acceptance_criteria,
            *requirement.constraints,
            *requirement.numeric_limits,
            *requirement.tags,
        ]
    ).strip()


def _supports_zero_atom_behavior(requirement: Requirement) -> bool:
    sources = (
        requirement.statement,
        *requirement.acceptance_criteria,
        *requirement.details,
        *requirement.constraints,
    )
    return any(
        not _is_atomic_parent(source)
        and not _is_guardrail_text(source)
        and _classify_atomic_behavior(source, _context_mode(source), "source") == "behavior"
        for source in sources
    )


def _is_mandatory(text: str) -> bool:
    """Recognize affirmative mandatory wording without treating guardrails as requirements."""

    for line in text.splitlines() or [text]:
        if _NEGATED_MANDATORY.search(line):
            continue
        if _is_explicit_mandatory(line):
            return True
    return False


def _subject(requirement: Requirement) -> str:
    if requirement.title.strip():
        return requirement.title.strip()

    statement = re.sub(r"\s+", " ", requirement.statement).strip().rstrip(".")
    patterns = (
        r"\b(?:enter|enters)\s+(.+?)(?:\s+to\b|$)",
        r"^(?:the|a|an)\s+(.+?)\s+(?:displays|display|shows|provides|contains)\b",
        r"^(.+?)\s+(?:is|are|has|have|filters|filter|accepts|rejects|includes|include|maximum|minimum|max|min|limit)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, statement, re.IGNORECASE)
        if match:
            subject = match.group(1).strip(" `:-")
            if subject:
                return subject
    if len(statement) > 80:
        return statement[:77].rstrip() + "..."
    return statement or requirement.id


def _explicit_limit(
    requirement: Requirement,
    text: str,
) -> tuple[float, str, str] | None:
    sources = [*requirement.numeric_limits, *requirement.constraints, text]
    for source in sources:
        maximum = _MAXIMUM.search(source)
        minimum = _MINIMUM.search(source)
        if maximum:
            value = float(maximum.group(1))
            unit_match = _NUMBER_WITH_UNIT.search(source)
            unit = f" {unit_match.group(2)}" if unit_match else ""
            return value, "maximum", unit
        if minimum:
            value = float(minimum.group(1))
            unit_match = _NUMBER_WITH_UNIT.search(source)
            unit = f" {unit_match.group(2)}" if unit_match else ""
            return value, "minimum", unit
        after_value = _LIMIT_AFTER_VALUE.search(source)
        if after_value:
            value = float(after_value.group(1))
            direction = "minimum" if re.search(
                r"\b(?:minimum|min)\b", after_value.group(0), re.IGNORECASE
            ) else "maximum"
            unit_match = _NUMBER_WITH_UNIT.search(source)
            unit = f" {unit_match.group(2)}" if unit_match else ""
            return value, direction, unit
    return None


def _boundary_values(value: float, direction: str) -> tuple[str, str, str]:
    if value.is_integer():
        exact = int(value)
        return str(exact - 1), str(exact), str(exact + 1)
    exact_text = f"{value:g}"
    return f"{value - 1:g}", exact_text, f"{value + 1:g}"


def _has_confirm_and_cancel(text: str) -> bool:
    return bool(re.search(r"\bconfirm(?:ed|ation)?\b", text, re.IGNORECASE)) and bool(
        re.search(r"\bcancel(?:led|s)?\b", text, re.IGNORECASE)
    )


def _explicit_states(requirement: Requirement) -> list[str]:
    states: list[str] = []
    for atom in extract_evidence_atoms(requirement):
        if atom.kind == "state":
            value = atom.text
            if value.lower() not in {item.lower() for item in states}:
                states.append(value)
    return states


# ---------------------------------------------------------------------------
# _atom_matches_candidate — DEMOTED
# ---------------------------------------------------------------------------

def _atom_matches_candidate(atom: EvidenceAtom, intent: str, subject: str) -> bool:
    """DEPRECATED: post-render consistency check only.

    This function MUST NOT derive evidence_refs. Refs are declared by
    ScenarioCandidate producers. This function may only be used as an optional
    post-render sanity assertion that a declared atom's text still appears in
    the rendered intent. It never adds, removes, or authorizes refs.
    """
    if atom.kind == "guardrail":
        return False
    intent_normalized = intent.lower()
    atom_text = atom.text.rstrip(".").strip()
    atom_normalized = atom_text.lower()
    if atom_normalized and re.search(
        rf"(?<!\w){re.escape(atom_normalized)}(?!\w)", intent_normalized
    ):
        return True
    return False
