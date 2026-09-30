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
    *,
    for_sizing: bool = False,
) -> str:
    """Build a bounded provider prompt or a full-context sizing equivalent."""

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
    if for_sizing:
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
        requirements_heading = "Requirements for this batch (full context for deterministic sizing only):"
    else:
        requirement_payload = [
            {
                "id": requirement.id,
            }
            for requirement in selected_requirements
        ]
        requirements_heading = "Requirements for this batch (labels only; do not use these labels to add behavior):"
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

Return ONLY a JSON array.
No Markdown fences.
No preamble.
No commentary.

Generate exactly one test case for each supplied scenario.
Do not add scenarios.
Do not omit scenarios.
Return exactly one object per supplied scenario when possible.
Each object must contain exactly:
- scenario_ref
- title
- preconditions
- steps
- expected_result

The concrete JSON shape is:
[
  {{
    "scenario_ref": "SCENARIO-EXAMPLE-S01",
    "title": "Verify valid Period Field selection",
    "preconditions": [
      "The data-entry form is open."
    ],
    "steps": [
      "Select a valid Period Field."
    ],
    "expected_result": "The selected Period Field is accepted."
  }}
]

- scenario_ref must be copied exactly from the supplied scenario plan.
- preconditions must be an array of strings.
- steps must be a non-empty array of non-empty strings.
- expected_result must be a non-empty string.
- Do not include id, category, priority, technique, requirement_ref, language_target, or generated_at.
Use only supplied requirement facts and scenario intents.
Do not invent unsupported business rules, error wording, permissions, status transitions, formulas, or dependencies.
If a scenario intent is visibility, presence, or availability-only, keep the generated steps and expected_result observational. Do not add clickable, functional, usable, input, navigation, persistence, submit/save, or downstream-outcome claims unless that behavior is explicit in the scenario intent.
Treat the supplied scenario intent as the complete semantic boundary for steps and expected_result: operationalize its stated behavior, but do not add state changes, side effects, navigation outcomes, dialog behavior, persistence behavior, or other postconditions that the intent does not state. Keep generation constraints such as "not exhaustive" or "not the only value" out of observable expected_result text. If the intent supplies a sample literal, preserve that literal in expected_result.
The requirement details are context only and must not expand the scenario intent. For example, for "Verify that Cancel keeps the user on the form.", the expected_result may state only that the user remains on the form; do not add dialog closes, discarded changes, navigation, persistence, or any other side effect. For a scenario containing the sample literal "Server Error", preserve "Server Error" in expected_result but do not state that it is non-exhaustive or not the only value.
Do not mention dialog, modal, popup, or confirmation-window behavior in steps or expected_result unless one of those words is explicitly present in the scenario intent. Words such as "Yes", "confirms", "Are you sure", or "unsaved" do not authorize a dialog assumption.
{language_instruction}

{requirements_heading}
{json.dumps(requirement_payload, ensure_ascii=False, indent=2)}

Planned scenarios for this batch:
{json.dumps(scenario_payload, ensure_ascii=False, indent=2)}
""".strip()
