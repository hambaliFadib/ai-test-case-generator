"""Coverage auditing for planned scenarios and source evidence."""

from dataclasses import dataclass, field
import re

from models.coverage_model import CoverageAudit, CoveragePlan
from models.test_case_model import TestCase


@dataclass(frozen=True)
class EvidenceCoverageAudit:
    """Deterministic comparison between source evidence and planned intents."""

    evidence_atom_ids: list[str]
    mapped_evidence_atom_ids: list[str]
    uncovered_evidence_atom_ids: list[str]
    incompatible_mapping_ids: list[str] = field(default_factory=list)
    guardrail_leak_scenario_ids: list[str] = field(default_factory=list)

    @property
    def coverage_percentage(self) -> float:
        if not self.evidence_atom_ids:
            return 100.0
        return len(self.mapped_evidence_atom_ids) / len(self.evidence_atom_ids) * 100


def audit_evidence_coverage(plan: CoveragePlan) -> EvidenceCoverageAudit:
    """Audit typed evidence mappings and keep constraints out of scenarios."""

    evidence_ids = [atom.id for atom in plan.evidence_atoms]
    atoms_by_id = {atom.id: atom for atom in plan.evidence_atoms}
    evidence_id_set = set(evidence_ids)
    mapped_ids: set[str] = set()
    incompatible: list[str] = []
    guardrail_leaks: list[str] = []
    refs_by_atom: dict[str, list[object]] = {evidence_id: [] for evidence_id in evidence_ids}

    for requirement_plan in plan.requirements:
        for scenario in requirement_plan.scenarios:
            for evidence_ref in scenario.evidence_refs:
                atom = atoms_by_id.get(evidence_ref)
                if atom is None:
                    continue
                mapped_ids.add(evidence_ref)
                refs_by_atom[evidence_ref].append(scenario)
                if atom.kind == "guardrail":
                    guardrail_leaks.append(scenario.id)
            for constraint_ref in scenario.constraint_refs:
                if constraint_ref in atoms_by_id and atoms_by_id[constraint_ref].kind == "guardrail":
                    mapped_ids.add(constraint_ref)

    guardrail_leaks = list(dict.fromkeys(guardrail_leaks))
    for atom in plan.evidence_atoms:
        if atom.kind == "guardrail":
            continue
        scenarios = refs_by_atom[atom.id]
        if not scenarios or not _compatible_mapping(atom, scenarios):
            incompatible.append(atom.id)

    mapped = [evidence_id for evidence_id in evidence_ids if evidence_id in mapped_ids]
    uncovered = [evidence_id for evidence_id in evidence_ids if evidence_id not in mapped_ids]
    return EvidenceCoverageAudit(
        evidence_atom_ids=evidence_ids,
        mapped_evidence_atom_ids=mapped,
        uncovered_evidence_atom_ids=uncovered,
        incompatible_mapping_ids=incompatible,
        guardrail_leak_scenario_ids=guardrail_leaks,
    )


def _compatible_mapping(atom, scenarios: list[object]) -> bool:
    """Apply deterministic compatibility rules for one typed evidence atom."""

    intents = [scenario.intent for scenario in scenarios]
    kind = atom.kind
    if kind == "presence":
        return all(_presence_only_intent(intent, atom.text) for intent in intents)
    if kind == "explicit_behavior":
        return any(_preserves_source_effect(atom.text, intent) for intent in intents)
    if kind == "sample_value":
        return any(
            atom.text.lower() in intent.lower() and "non-exhaustive" in intent.lower()
            for intent in intents
        )
    if kind in {"observed_value", "state", "option"}:
        return any(
            atom.text.lower() in intent.lower()
            or (
                "application provides the behavior described" in intent.lower()
                and (len(atom.text) > 1000 or _generic_source_anchor(atom.text, intent))
            )
            for intent in intents
        )
    if kind == "mandatory":
        lowered = [intent.lower() for intent in intents]
        return any("populated" in intent for intent in lowered) and any(
            "empty" in intent or "omitted" in intent for intent in lowered
        )
    if kind == "boundary":
        number = re.search(r"\d+(?:\.\d+)?", atom.text)
        return bool(number and any(number.group(0) in intent for intent in intents))
    if kind == "file_boundary":
        return any(atom.text.lower() in intent.lower() for intent in intents)
    return any(atom.text.lower() in intent.lower() for intent in intents)


def _presence_only_intent(intent: str, literal: str) -> bool:
    """Presence/control mappings may assert observation, never behavior."""

    remainder = re.sub(re.escape(literal), "", intent, flags=re.IGNORECASE)
    forbidden = re.compile(
        r"\b(?:clickable|functional|usable|available for use|allows?\s+(?:input|the user|users?)|"
        r"accepts?\s+input|navigate|navigation behavior|persist(?:s|ence)?|"
        r"downstream outcome|filters?\s+(?:rows?|results?))\b",
        re.IGNORECASE,
    )
    return not forbidden.search(remainder)


def _preserves_source_effect(source: str, intent: str) -> bool:
    """Require the meaningful subject/effect words to survive into the intent."""

    stop_words = {
        "a", "an", "and", "are", "as", "be", "by", "can", "expected", "for", "from",
        "in", "is", "it", "of", "on", "that", "the", "to", "user", "users", "was", "when",
        "with",
    }
    source_terms = {
        term.lower()
        for term in re.findall(r"[A-Za-z][A-Za-z0-9/&-]*", source)
        if term.lower() not in stop_words
    }
    intent_terms = set(re.findall(r"[a-z][a-z0-9/&-]*", intent.lower()))
    source_prefix = re.split(
        r"\b(?:is|are|keeps?|confirms?|allows?|filters?|follows?|provides?|opens?|clears?|controls?|displays?|must\s+be|can)\b",
        source,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    subject_terms = {
        term.lower()
        for term in re.findall(r"[A-Za-z][A-Za-z0-9/&-]*", source_prefix)
        if term.lower() not in stop_words
    }
    effect_terms = source_terms - subject_terms
    return bool(source_terms) and bool(effect_terms & intent_terms)


def _generic_source_anchor(source: str, intent: str) -> bool:
    source_terms = [
        term.lower()
        for term in re.findall(r"[A-Za-z][A-Za-z0-9/&-]*", source)
        if term.lower() not in {"the", "a", "an", "is", "are", "and", "of", "to"}
    ]
    intent_terms = set(re.findall(r"[a-z][a-z0-9/&-]*", intent.lower()))
    return bool(source_terms) and any(term in intent_terms for term in source_terms[:3])


def audit_coverage(
    plan: CoveragePlan,
    test_cases: list[TestCase],
) -> CoverageAudit:
    """Compare generated scenario refs with the ordered planned scenario set."""

    planned = [
        scenario.id
        for requirement_plan in plan.requirements
        for scenario in requirement_plan.scenarios
    ]
    planned_set = set(planned)
    generated = [test_case.scenario_ref for test_case in test_cases]

    seen: set[str] = set()
    duplicates: list[str] = []
    for scenario_ref in generated:
        if scenario_ref in seen and scenario_ref not in duplicates:
            duplicates.append(scenario_ref)
        seen.add(scenario_ref)

    unexpected: list[str] = []
    for scenario_ref in generated:
        if scenario_ref not in planned_set and scenario_ref not in unexpected:
            unexpected.append(scenario_ref)

    covered = {scenario_ref for scenario_ref in generated if scenario_ref in planned_set}
    missing = [scenario_ref for scenario_ref in planned if scenario_ref not in covered]
    percentage = (len(covered) / len(planned) * 100) if planned else 0.0
    return CoverageAudit(
        planned_scenario_ids=planned,
        generated_scenario_ids=generated,
        missing_scenario_ids=missing,
        unexpected_scenario_ids=unexpected,
        duplicate_scenario_ids=duplicates,
        coverage_percentage=percentage,
    )
