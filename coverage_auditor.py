"""Coverage auditing for planned scenarios and source evidence — Evidence Binding v2.

Replaces lexical intent-matching with objective/evidence compatibility and
locality enforcement. Compatibility is validated at candidate construction
time in coverage_planner; the auditor verifies declared bindings are
requirement-local, guardrail-free, and cover all non-guardrail atoms.
"""

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
    """Audit declared evidence mappings and keep constraints out of scenarios.

    Checks:
    - Every declared evidence_ref resolves to an existing atom (locality).
    - Guardrail atoms never appear in evidence_refs.
    - Every non-guardrail atom is mapped by at least one scenario.
    - No foreign-requirement refs (atom.requirement_ref == scenario.requirement_ref).
    """

    evidence_ids = [atom.id for atom in plan.evidence_atoms]
    atoms_by_id = {atom.id: atom for atom in plan.evidence_atoms}
    mapped_ids: set[str] = set()
    incompatible: list[str] = []
    guardrail_leaks: list[str] = []
    refs_by_atom: dict[str, list[object]] = {evidence_id: [] for evidence_id in evidence_ids}

    for requirement_plan in plan.requirements:
        for scenario in requirement_plan.scenarios:
            for evidence_ref in scenario.evidence_refs:
                atom = atoms_by_id.get(evidence_ref)
                if atom is None:
                    # Unknown ref: treat as incompatible (planner defect).
                    incompatible.append(evidence_ref)
                    continue
                if atom.requirement_ref != scenario.requirement_ref:
                    # Foreign requirement evidence: planner defect.
                    incompatible.append(evidence_ref)
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
        if not scenarios:
            # Uncovered atom: planner defect.
            incompatible.append(atom.id)

    mapped = [evidence_id for evidence_id in evidence_ids if evidence_id in mapped_ids]
    uncovered = [evidence_id for evidence_id in evidence_ids if evidence_id not in mapped_ids]
    return EvidenceCoverageAudit(
        evidence_atom_ids=evidence_ids,
        mapped_evidence_atom_ids=mapped,
        uncovered_evidence_atom_ids=uncovered,
        incompatible_mapping_ids=list(dict.fromkeys(incompatible)),
        guardrail_leak_scenario_ids=guardrail_leaks,
    )


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
