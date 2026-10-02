"""Deterministic, conservative coverage planning for Phase 2."""

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
    ScenarioIntent,
    UnresolvedBaselineItem,
)
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
_STATE = re.compile(
    r"\b(?:status(?:es)?|state(?:s)?|lifecycle|values include|states include)\b",
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
        evidence_atoms.extend(requirement_atoms)
        scenarios, evaluation = _scenarios_for_requirement(
            requirement, resolved_profile, requirement_atoms
        )
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
    # Keep the planning gate local and deterministic.  A silently dropped atom
    # is a planner defect, not something to defer to batching or the provider.
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


def _scenarios_for_requirement(
    requirement: Requirement,
    profile: str,
    evidence_atoms: list[EvidenceAtom],
) -> tuple[list[ScenarioIntent], BaselineEvaluation]:
    if requirement.status != "TESTABLE":
        return [], BaselineEvaluation()

    text = _requirement_text(requirement)
    subject = _subject(requirement)
    atomic_behaviors = _extract_atomic_behaviors(requirement)
    atomic_candidates = _atomic_candidates(atomic_behaviors)
    has_confirmation_children = any(
        item.kind in {"confirmation", "confirmation_behavior"} for item in atomic_behaviors
    )
    candidates: list[tuple[str, str, str, str]] = []

    candidates.extend(atomic_candidates)

    if _is_mandatory(text):
        candidates.extend(
            [
                (
                    "positive",
                    "EP",
                    f"Verify {subject} accepts a valid populated value.",
                    "high",
                ),
                (
                    "negative",
                    "negative",
                    f"Verify {subject} is rejected or prevented when it is left empty.",
                    "high",
                ),
            ]
        )

    limit = _explicit_limit(requirement, text)
    if limit is not None:
        value, direction, unit = limit
        below, exact, above = _boundary_values(value, direction)
        below_verb = "rejects or prevents" if direction == "minimum" else "accepts"
        above_verb = "accepts" if direction == "minimum" else "rejects or prevents"
        candidates.extend(
            [
                (
                    "boundary",
                    "BVA",
                    f"Verify {subject} {below_verb} a value of {below}{unit}, below the explicit limit.",
                    "medium",
                ),
                (
                    "boundary",
                    "BVA",
                    f"Verify {subject} accepts the explicit limit value of {exact}{unit}.",
                    "high",
                ),
                (
                    "boundary",
                    "BVA",
                    f"Verify {subject} {above_verb} a value of {above}{unit}, beyond the explicit limit.",
                    "high",
                ),
            ]
        )

    if (
        _CONFIRMATION.search(text)
        and _has_confirm_and_cancel(text)
        and not has_confirmation_children
    ):
        candidates.extend(
            [
                (
                    "positive",
                    "EP",
                    f"Verify the Confirm path for {subject} proceeds as explicitly described.",
                    "high",
                ),
                (
                    "edge",
                    "exploratory",
                    f"Verify the Cancel path for {subject} follows the explicitly described behavior.",
                    "medium",
                ),
            ]
        )

    if _SUCCESS.search(requirement.statement) and _FAILURE.search(requirement.statement):
        candidates.extend(
            [
                (
                    "positive",
                    "EP",
                    f"Verify {subject} displays the explicitly defined success state.",
                    "high",
                ),
                (
                    "negative",
                    "negative",
                    f"Verify {subject} displays the explicitly defined failure state.",
                    "high",
                ),
            ]
        )

    if _STATE.search(text):
        states = _explicit_states(requirement)
        for state in states:
            candidates.append(
                (
                    "positive",
                    "EP",
                    f"Verify {subject} displays the explicitly defined {state} state.",
                    "medium",
                )
            )

    if not candidates and _ACTION.search(text):
        candidates.append(
            (
                "positive",
                "EP",
                f"Verify the explicitly described {subject} is visible and available.",
                "medium",
            )
        )
    elif not candidates:
        candidates.append(
            (
                "positive",
                "EP",
                f"Verify the application provides the behavior described for {subject}.",
                "medium",
            )
        )
    elif _ACTION.search(text) and not (
        _is_mandatory(text)
        or limit is not None
        or _SEARCH.search(text)
        or _CONFIRMATION.search(text)
        or (_SUCCESS.search(requirement.statement) and _FAILURE.search(requirement.statement))
        or _STATE.search(text)
        or atomic_behaviors
    ):
        # Action-only requirements remain a single visibility/access scenario.
        candidates = [
            (
                "positive",
                "EP",
                f"Verify the explicitly described {subject} is visible and available.",
                "medium",
            )
        ]

    should_render_evidence = any(
        atom.kind in {"explicit_behavior", "presence", "mandatory", "boundary", "file_boundary"}
        for atom in evidence_atoms
    ) or (
        sum(len(atom.text) for atom in evidence_atoms) <= 2_000
        and any(
            atom.kind in {"observed_value", "sample_value", "option", "state"}
            for atom in evidence_atoms
        )
    )
    if evidence_atoms and should_render_evidence and any(
        "application provides the behavior described" in intent
        for _, _, intent, _ in candidates
    ):
        candidates = [
            candidate
            for candidate in candidates
            if "application provides the behavior described" not in candidate[2]
        ]

    evaluation = evaluate_baseline(requirement, evidence_atoms, subject)
    candidates.extend(evaluation.policy_candidates)

    if profile in ("comprehensive", "extra"):
        candidates = _add_comprehensive_source_backed_case(candidates, text, subject)
        if _SECURITY.search(text) or _SEARCH.search(text):
            security_intent = (
                f"Verify {subject} handles supplied input safely without adding unspecified access rules."
                if _SEARCH.search(text) and not _SECURITY.search(text)
                else f"Verify the explicitly described security behavior for {subject}."
            )
            candidates.append(
                (
                    "security",
                    "security",
                    security_intent,
                    "high",
                )
            )
        candidates = _add_deeper_source_backed_candidate(
            candidates, evidence_atoms, subject
        )
    if profile == "extra":
        candidates = _add_extra_exploratory_candidate(candidates, evidence_atoms, subject)

    candidates = _ensure_evidence_candidates(
        requirement,
        candidates,
        evidence_atoms,
        subject,
    )
    scenarios = _materialize_scenarios(requirement.id, candidates, evidence_atoms, subject)
    return scenarios, evaluation


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

    # A title-only ``Mandatory.`` statement is a real constraint on the
    # requirement even though the field name lives in the title.
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
    if _NEGATED_MANDATORY.search(value):
        return None
    if _is_explicit_mandatory(value):
        return "mandatory"
    if _MAXIMUM.search(value) or _MINIMUM.search(value) or _LIMIT_AFTER_VALUE.search(value):
        return "boundary"
    if "only pdf" in lowered or "pdf only" in lowered:
        return "file_boundary"
    if _is_sample_text(value):
        return "sample_value"
    if "opens a modal" in lowered or _is_confirmation_behavior(value) or _is_functional_evidence(value):
        return "explicit_behavior"
    if mode == "state":
        return "state"
    if mode == "sample":
        return "sample_value"
    if mode == "option":
        return "option"
    if _is_presence_control(value) or _is_action_label(value):
        return "presence"
    if mode in {"action", "control", "tab"}:
        return "presence"
    # A non-heading, non-guardrail list item is still explicit evidence.  It
    # is intentionally represented as static data rather than as behavior.
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


def _normalize_evidence(value: str) -> str:
    normalized = re.sub(r"[^\w]+", " ", value.lower(), flags=re.UNICODE)
    return re.sub(r"\s+", " ", normalized).strip()


def _ensure_evidence_candidates(
    requirement: Requirement,
    candidates: list[tuple[str, str, str, str]],
    evidence_atoms: list[EvidenceAtom],
    subject: str,
) -> list[tuple[str, str, str, str]]:
    """Add the smallest source-backed candidates for atoms not yet represented."""

    unmatched = [
        atom
        for atom in evidence_atoms
        if not any(_atom_matches_candidate(atom, intent, subject) for _, _, intent, _ in candidates)
    ]
    sample_atoms = [atom for atom in unmatched if atom.kind == "sample_value"]
    for atom in sample_atoms:
        candidates.append(
            (
                "positive",
                "EP",
                f"Verify the sample value '{atom.text}' is shown as a non-exhaustive example for {subject}.",
                "medium",
            )
        )
    unmatched = [atom for atom in unmatched if atom not in sample_atoms]
    if not unmatched:
        return candidates

    static_atoms = [
        atom
        for atom in unmatched
        if atom.kind in {"observed_value", "option", "state", "presence"}
    ]
    if static_atoms:
        labels = "; ".join(atom.text for atom in static_atoms)
        candidates.append(
            (
                "positive",
                "EP",
                f"Verify the explicitly listed items for {subject}: {labels}.",
                "medium",
            )
        )
        unmatched = [atom for atom in unmatched if atom not in static_atoms]

    for atom in unmatched:
        if atom.kind == "guardrail":
            continue
        if atom.kind == "mandatory":
            candidates.append(
                (
                    "positive",
                    "EP",
                    f"Verify {subject} accepts a valid populated value for the explicit mandatory rule.",
                    "high",
                )
            )
            continue
        if atom.kind == "boundary":
            candidates.append(
                (
                    "boundary",
                    "BVA",
                    f"Verify the explicit boundary rule for {subject}: {atom.text}.",
                    "high",
                )
            )
            continue
        if atom.kind == "file_boundary":
            candidates.append(
                (
                    "positive",
                    "EP",
                    f"Verify the explicitly required file rule for {subject}: {atom.text}.",
                    "high",
                )
            )
            continue
        candidates.append(
            (
                "positive",
                "EP",
                f"Verify that {atom.text.rstrip('.').strip()}.",
                "medium",
            )
        )
    return candidates


def _atom_matches_candidate(atom: EvidenceAtom, intent: str, subject: str) -> bool:
    if atom.kind == "guardrail":
        return False
    intent_normalized = intent.lower()
    atom_text = atom.text.rstrip(".").strip()
    atom_normalized = atom_text.lower()
    if (
        subject
        and "application provides the behavior described" in intent_normalized
        and re.search(rf"(?<!\w){re.escape(subject.lower().strip())}(?!\w)", intent_normalized)
    ):
        return True
    if atom_normalized and re.search(
        rf"(?<!\w){re.escape(atom_normalized)}(?!\w)", intent_normalized
    ):
        return True
    if atom.kind == "mandatory":
        if subject:
            subject_normalized = subject.lower().strip()
            if subject_normalized and re.search(
                rf"(?<!\w){re.escape(subject_normalized)}(?!\w)", intent_normalized
            ):
                return True
        field = re.sub(
            r"\b(?:is|are|not|do not|don't|mandatory|required|must be provided)\b",
            " ",
            atom_normalized,
        )
        field = re.sub(r"\s+", " ", field).strip(" .`*:-")
        return bool(field and re.search(rf"(?<!\w){re.escape(field)}(?!\w)", intent_normalized))
    if atom.kind in {"explicit_behavior", "presence"}:
        core = _evidence_core_phrase(atom.text)
        if core and re.search(rf"(?<!\w){re.escape(core)}(?!\w)", intent_normalized):
            return True
        if subject:
            subject_normalized = subject.lower().strip()
            if subject_normalized and re.search(
                rf"(?<!\w){re.escape(subject_normalized)}(?!\w)", intent_normalized
            ):
                return True
    if atom.kind == "boundary":
        number = re.search(r"\d+(?:\.\d+)?", atom.text)
        return bool(number and number.group(0) in intent_normalized)
    return False


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

    # A standalone statement may itself name an explicit functional behavior
    # or file-type rule. Generic display/action sentences remain on the
    # existing planner path so they do not become redundant atomic scenarios.
    value = _clean_atomic_text(requirement.statement)
    if value and not _is_atomic_parent(value) and not _is_guardrail_text(value):
        kind = _classify_atomic_behavior(value, _context_mode(value), "statement")
        if kind in {"behavior", "confirmation_behavior", "file_type"}:
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


def _atomic_candidates(
    behaviors: list[_AtomicBehavior],
) -> list[tuple[str, str, str, str]]:
    candidates: list[tuple[str, str, str, str]] = []
    for behavior in behaviors:
        label = behavior.label
        if behavior.kind in {"limit", "state"}:
            continue
        if behavior.kind == "file_type":
            candidates.extend(
                [
                    (
                        "positive",
                        "EP",
                        f"Verify the upload accepts PDF files as explicitly required by {label}.",
                        "high",
                    ),
                    (
                        "negative",
                        "negative",
                        f"Verify the upload rejects or prevents non-PDF or unsupported file types under {label}.",
                        "high",
                    ),
                ]
            )
        elif behavior.kind == "confirmation":
            candidates.append(
                (
                    "positive",
                    "EP",
                    f"Verify the explicitly described {label} is visible and available.",
                    "medium",
                )
            )
        elif behavior.kind == "confirmation_behavior":
            candidates.append(
                (
                    "positive",
                    "EP",
                    _functional_intent(behavior.source_text),
                    "high",
                )
            )
        elif behavior.kind in {"action", "control", "tab"}:
            suffix = "is available for navigation" if behavior.kind == "tab" else "is visible and available"
            candidates.append(
                (
                    "positive",
                    "EP",
                    f"Verify the explicitly described {label} {suffix}.",
                    "medium",
                )
            )
        elif behavior.kind == "behavior":
            source_text = behavior.source_text.rstrip(".").strip()
            if _is_no_result_evidence(source_text):
                category, technique, priority = "negative", "negative", "medium"
            else:
                category, technique, priority = "positive", "EP", "medium"
            candidates.append(
                (
                    category,
                    technique,
                    _functional_intent(source_text),
                    priority,
                )
            )
    return candidates


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
    ) or bool(_SUCCESS.search(value) and _FAILURE.search(value)) or normalized in {
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


def _looks_like_behavior(value: str) -> bool:
    return bool(
        re.search(
            r"\b(?:user can|users can|system |page |display(?:s|ed)? |the user|accepts|rejects|follows|select|apply|provides)\b",
            value,
            re.IGNORECASE,
        )
    )


def _is_functional_evidence(value: str) -> bool:
    return bool(
        re.search(
            r"(?:\buser(?:s)?\s+can\b|\bis\s+used\s+to\b|\bcontrols?\s+\w|\bfilters?\s+(?:displayed|rows|results?)\b|\bdisplayed\s+(?:rows?|results?)\b.{0,50}\bfollow(?:s)?\b|\bresult\s+follows?\b|\breturns?\s+(?:the\s+)?(?:displayed\s+)?results?\b|\bapplies?\s+(?:the\s+)?(?:selected\s+|applied\s+)?criterion\b|\bmust\s+be\s+accessible\b|\bis\s+accessible\b|\bno\s+matching\b|\bno\s+results?\b|\bempty\s+(?:result|state)\b|\bclear\s+data\b.{0,80}\b(?:entered|selected|values?)\b|\bclears?\s+(?:entered|selected|values?)\b)",
            value,
            re.IGNORECASE,
        )
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


def _is_mandatory(text: str) -> bool:
    """Recognize affirmative mandatory wording without treating guardrails as requirements."""

    for line in text.splitlines() or [text]:
        if _NEGATED_MANDATORY.search(line):
            continue
        # A trailing asterisk on a control listed inside another requirement
        # is presence evidence, not a mandatory rule for the whole block.  The
        # explicit wording belongs to the field's own requirement block.
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
        if direction == "maximum":
            return str(exact - 1), str(exact), str(exact + 1)
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


def _add_comprehensive_source_backed_case(
    candidates: list[tuple[str, str, str, str]],
    text: str,
    subject: str,
) -> list[tuple[str, str, str, str]]:
    if _SEARCH.search(text) or _ACTION.search(text):
        candidate = (
            "edge",
            "exploratory",
            f"Verify the explicitly described edge behavior for {subject} without assuming unspecified semantics.",
            "low",
        )
        if candidate not in candidates:
            candidates.append(candidate)
    return candidates


def _add_deeper_source_backed_candidate(
    candidates: list[tuple[str, str, str, str]],
    evidence_atoms: list[EvidenceAtom],
    subject: str,
) -> list[tuple[str, str, str, str]]:
    kinds = {atom.kind for atom in evidence_atoms if atom.kind != "guardrail"}
    if len(kinds) < 2:
        return candidates
    candidate = (
        "edge",
        "exploratory",
        f"Verify the explicitly described aspects of {subject} remain consistent with each other without assuming unspecified semantics.",
        "low",
    )
    if candidate not in candidates:
        candidates.append(candidate)
    return candidates


def _add_extra_exploratory_candidate(
    candidates: list[tuple[str, str, str, str]],
    evidence_atoms: list[EvidenceAtom],
    subject: str,
) -> list[tuple[str, str, str, str]]:
    atoms = [atom for atom in evidence_atoms if atom.kind != "guardrail"]
    if len(atoms) < 3:
        return candidates
    candidate = (
        "edge",
        "exploratory",
        f"Verify combinations limited to the explicitly described aspects of {subject} without assuming unspecified semantics.",
        "low",
    )
    if candidate not in candidates:
        candidates.append(candidate)
    return candidates


def _materialize_scenarios(
    requirement_id: str,
    candidates: list[tuple[str, str, str, str]],
    evidence_atoms: list[EvidenceAtom],
    subject: str,
) -> list[ScenarioIntent]:
    scenarios: list[ScenarioIntent] = []
    seen: set[tuple[str, str, str]] = set()
    for category, technique, intent, priority in candidates:
        if category not in SCENARIO_CATEGORIES:
            raise ValueError(f"Unsupported scenario category '{category}'.")
        if technique not in SCENARIO_TECHNIQUES:
            raise ValueError(f"Unsupported scenario technique '{technique}'.")
        identity = (category, technique, intent)
        if identity in seen:
            continue
        seen.add(identity)
        scenario_id = f"{requirement_id}-S{len(scenarios) + 1:02d}"
        scenarios.append(
            ScenarioIntent(
                id=scenario_id,
                requirement_ref=requirement_id,
                category=category,
                technique=technique,
                intent=intent,
                priority=priority,
                evidence_refs=tuple(
                    atom.id
                    for atom in evidence_atoms
                    if _atom_matches_candidate(atom, intent, subject)
                ),
                constraint_refs=tuple(
                    atom.id for atom in evidence_atoms if atom.kind == "guardrail"
                ),
            )
        )
    return scenarios
