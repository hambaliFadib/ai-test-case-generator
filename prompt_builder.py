"""Build strict, QA-oriented prompts for test-case generation."""

import json

from models.coverage_model import ScenarioIntent
from models.requirement_model import Requirement
from models.test_case_model import TestCase


def build_prompt(
    requirements: list[Requirement],
    language_target: str = "manual",
    output_language: str = "en",
) -> str:
    """Build a provider-neutral prompt that requests only contract-compliant JSON."""

    if not requirements:
        raise ValueError("At least one requirement is required to build a generation prompt.")
    if language_target not in TestCase.LANGUAGES:
        supported = ", ".join(TestCase.LANGUAGES)
        raise ValueError(f"Unsupported language target '{language_target}'. Choose: {supported}.")

    if output_language == "id":
        language_instruction = """LANGUAGE INSTRUCTION:
Write the following fields in Bahasa Indonesia:
- title
- steps (each step)
- expected_result
- preconditions (if any)

Keep these fields in English regardless:
- id (format: TC-YYYYMMDD-XXXX)
- category (positive/negative/boundary/edge/security)
- priority (high/medium/low)
- technique (EP/BVA/negative/exploratory/security)
- requirement_ref (REQ-XXX)
- language_target (manual)
- generated_at (ISO timestamp)"""
    else:
        language_instruction = """LANGUAGE INSTRUCTION:
Write all fields in English."""

    requirement_payload = [
        {
            "id": requirement.id,
            "statement": requirement.statement,
            "acceptance_criteria": requirement.acceptance_criteria,
            "constraints": requirement.constraints,
            "source_section": requirement.source_section,
            "has_numeric_or_date_field": requirement.has_numeric_or_date_field,
        }
        for requirement in requirements
    ]
    fields = ", ".join(TestCase.required_fields())
    return f"""You are an expert QA engineer generating a complete, traceable test suite.

Apply these test design techniques:
- Equivalence Partitioning (EP)
- Boundary Value Analysis (BVA)
- Negative Testing
- Edge Case Identification
- Basic Security testing: injection, authentication bypass, and empty input

Coverage requirements:
- At least 2 positive cases per requirement.
- At least 2 negative cases per requirement.
- At least 1 boundary case when a numeric or date field exists.
- At least 1 edge case per requirement.

Return ONLY a valid JSON array. Do not use Markdown fences, a preamble, explanations, or trailing commentary.
Each object must contain exactly these fields: {fields}.
Use these strict values:
- category: positive, negative, boundary, edge, security
- priority: high, medium, low
- technique: EP, BVA, negative, exploratory, security
- language_target: python, javascript, typescript, java, manual
Use language_target='{language_target}' for every object.
Use the source requirement ID in requirement_ref, or REQ-UNTRACED only when no trace is possible.
Use IDs in the format TC-YYYYMMDD-0001 and make every ID unique.
preconditions and steps must be JSON arrays of strings; steps must contain at least one item.
expected_result must be a non-empty string. generated_at must be an ISO 8601 timestamp.

{language_instruction}

Requirements:
{json.dumps(requirement_payload, ensure_ascii=False, indent=2)}
""".strip()


def build_batch_prompt(
    requirements: list[Requirement],
    scenarios: list[ScenarioIntent],
    language_target: str = "manual",
    output_language: str = "en",
) -> str:
    """Build a bounded prompt for exactly the supplied scenario intents."""

    if not requirements:
        raise ValueError("At least one requirement is required to build a batch prompt.")
    if not scenarios:
        raise ValueError("At least one scenario is required to build a batch prompt.")
    if language_target not in TestCase.LANGUAGES:
        supported = ", ".join(TestCase.LANGUAGES)
        raise ValueError(f"Unsupported language target '{language_target}'. Choose: {supported}.")
    if output_language not in ("en", "id"):
        raise ValueError("Unsupported output language. Choose: en, id.")

    known_requirements = {requirement.id: requirement for requirement in requirements}
    missing = sorted(
        {
            scenario.requirement_ref
            for scenario in scenarios
            if scenario.requirement_ref not in known_requirements
        }
    )
    if missing:
        raise ValueError(
            "Scenarios reference unknown requirement(s): " + ", ".join(missing)
        )

    selected_requirements = [
        requirement
        for requirement in requirements
        if requirement.id in {scenario.requirement_ref for scenario in scenarios}
    ]
    requirement_payload = [
        {
            "id": requirement.id,
            "title": requirement.title,
            "statement": requirement.statement,
            "details": requirement.details,
            "acceptance_criteria": requirement.acceptance_criteria,
            "constraints": requirement.constraints,
            "source_section": requirement.source_section,
            "numeric_limits": requirement.numeric_limits,
        }
        for requirement in selected_requirements
    ]
    scenario_payload = [
        {
            "scenario_ref": scenario.id,
            "requirement_ref": scenario.requirement_ref,
            "category": scenario.category,
            "technique": scenario.technique,
            "intent": scenario.intent,
            "priority": scenario.priority,
        }
        for scenario in scenarios
    ]
    language_instruction = (
        "Write generated natural-language fields in Bahasa Indonesia."
        if output_language == "id"
        else "Write generated natural-language fields in English."
    )
    return f"""You are an expert QA engineer generating traceable test-case content.

Generate exactly one test case for each supplied scenario.
Do not add scenarios.
Do not omit scenarios.
Use the exact requirement_ref and scenario_ref supplied for each test case.
Every object must contain all existing test-case fields plus scenario_ref.
The supplied scenario_ref is required and must be copied exactly; do not invent or omit it.
The supplied id is not the final application ID and may be replaced after coverage is finalized.
Use only supplied requirement facts and scenario intents.
Do not invent unsupported business rules, error wording, permissions, status transitions, formulas, or dependencies.
{language_instruction}

Requirements for this batch:
{json.dumps(requirement_payload, ensure_ascii=False, indent=2)}

Planned scenarios for this batch:
{json.dumps(scenario_payload, ensure_ascii=False, indent=2)}
""".strip()
