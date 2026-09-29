"""Coverage auditing for planned and generated scenario references."""

from models.coverage_model import CoverageAudit, CoveragePlan
from models.test_case_model import TestCase


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
