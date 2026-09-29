"""Deterministic, conservative coverage planning for Phase 2."""

from __future__ import annotations

from dataclasses import dataclass
import re

from models.coverage_model import (
    SCENARIO_CATEGORIES,
    SCENARIO_TECHNIQUES,
    CoveragePlan,
    RequirementCoveragePlan,
    ScenarioIntent,
)
from models.requirement_model import Requirement


SUPPORTED_PROFILES: tuple[str, ...] = (
    "minimal",
    "balanced",
    "comprehensive",
    "security",
)

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
    profile: str = "balanced",
) -> CoveragePlan:
    """Create a stable coverage plan without calling an LLM or external API."""

    if profile not in SUPPORTED_PROFILES:
        supported = ", ".join(SUPPORTED_PROFILES)
        raise ValueError(f"Unsupported coverage profile '{profile}'. Choose: {supported}.")

    plans: list[RequirementCoveragePlan] = []
    for requirement in requirements:
        scenarios = _scenarios_for_requirement(requirement, profile)
        plans.append(
            RequirementCoveragePlan(
                requirement_ref=requirement.id,
                scenarios=scenarios,
            )
        )
    return CoveragePlan(requirements=plans)


def _scenarios_for_requirement(
    requirement: Requirement,
    profile: str,
) -> list[ScenarioIntent]:
    if requirement.status != "TESTABLE":
        return []

    text = _requirement_text(requirement)
    subject = _subject(requirement)
    atomic_behaviors = _extract_atomic_behaviors(requirement)
    atomic_candidates = _atomic_candidates(atomic_behaviors)
    has_confirmation_children = any(
        item.kind == "confirmation" for item in atomic_behaviors
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

    if _SUCCESS.search(text) and _FAILURE.search(text):
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
        or (_SUCCESS.search(text) and _FAILURE.search(text))
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

    if profile == "comprehensive":
        candidates = _add_comprehensive_source_backed_case(candidates, text, subject)

    if profile == "security" and (_SECURITY.search(text) or _SEARCH.search(text)):
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

    return _materialize_scenarios(requirement.id, candidates)


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
            if _is_atomic_guardrail(value):
                continue

            kind = _classify_atomic_behavior(value, mode, source_name)
            if kind is None:
                continue
            key = _normalize_behavior(value, kind)
            if key in seen:
                continue
            seen.add(key)
            behaviors.append(
                _AtomicBehavior(
                    label=_atomic_label(value, kind),
                    source_text=value,
                    kind=kind,
                )
            )

    # A standalone statement may itself name an explicit functional behavior
    # or file-type rule. Generic display/action sentences remain on the
    # existing planner path so they do not become redundant atomic scenarios.
    value = _clean_atomic_text(requirement.statement)
    if value and not _is_atomic_parent(value) and not _is_atomic_guardrail(value):
        kind = _classify_atomic_behavior(value, _context_mode(value), "statement")
        if kind in {"behavior", "file_type"}:
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
            if label.lower().startswith("cancel"):
                candidates.append(
                    (
                        "edge",
                        "exploratory",
                        "Verify the Cancel path follows the explicitly described behavior.",
                        "medium",
                    )
                )
            else:
                candidates.append(
                    (
                        "positive",
                        "EP",
                        "Verify the Confirm path follows the explicitly described behavior.",
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


def _context_mode(value: str) -> str | None:
    lowered = value.lower()
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
    return value.rstrip().endswith(":") or normalized in {
        "expected",
        "expected behavior",
        "expected result",
    }


def _is_atomic_guardrail(value: str) -> bool:
    lowered = value.lower().strip()
    return lowered.startswith(
        (
            "do not ",
            "don't ",
            "the generator ",
            "if implementation ",
            "the exact eligibility ",
            "treat this as ",
            "information that ",
        )
    ) or "not defined" in lowered


def _classify_atomic_behavior(
    value: str,
    mode: str | None,
    source_name: str,
) -> str | None:
    lowered = value.lower()
    if _MAXIMUM.search(value) or _MINIMUM.search(value) or _LIMIT_AFTER_VALUE.search(value):
        return "limit"
    if "only pdf" in lowered or "pdf only" in lowered:
        return "file_type"
    if (
        lowered in {"cancel", "yes", "confirm", "ok"}
        or "cancel keeps" in lowered
        or "yes confirms" in lowered
    ):
        return "confirmation"
    if _is_presence_control(value):
        return "control"
    if _is_functional_evidence(value):
        return "behavior"
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
            r"\b(?:user can|users can|system |page |displayed |the user|accepts|rejects|follows|select|apply|provides)\b",
            value,
            re.IGNORECASE,
        )
    )


def _is_functional_evidence(value: str) -> bool:
    return bool(
        re.search(
            r"(?:\buser(?:s)?\s+can\b|\bis\s+used\s+to\b|\bcontrols?\b|\bfilters?\s+(?:displayed|rows|results?)\b|\bdisplayed\s+(?:rows?|results?)\b.{0,50}\bfollow(?:s)?\b|\bresult\s+follows?\b|\breturns?\s+(?:the\s+)?(?:displayed\s+)?results?\b|\bapplies?\s+(?:the\s+)?(?:selected\s+|applied\s+)?criterion\b|\bmust\s+be\s+accessible\b|\bis\s+accessible\b|\bno\s+matching\b|\bno\s+results?\b|\bempty\s+(?:result|state)\b)",
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
    return f"Verify that {source_text}."


def _atomic_label(value: str, kind: str) -> str:
    label = value.strip().rstrip(".:*").strip()
    if kind == "search" and "search content" in label.lower():
        return "Search Content"
    if kind == "confirmation":
        lowered = label.lower()
        if lowered.startswith("cancel"):
            return "Cancel"
        return "Confirm"
    return label


def _normalize_behavior(value: str, kind: str) -> str:
    lowered = re.sub(r"[^a-z0-9 ]+", " ", value.lower())
    normalized = re.sub(r"\s+", " ", lowered).strip()
    if kind == "confirmation":
        if normalized.startswith("cancel"):
            return "confirmation cancel"
        if normalized.startswith("yes") or normalized in {"confirm", "ok"}:
            return "confirmation confirm"
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
        if _MANDATORY.search(line):
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
    text = _requirement_text(requirement)
    states: list[str] = []
    if not _STATE.search(text):
        return states
    for match in re.finditer(
        r"(?:Approved|Rejected|Draft|In Progress|Completed|Canceled|Terminate|Awaiting Approval|Success|Failed|Running|Schedule)",
        text,
        re.IGNORECASE,
    ):
        state = match.group(0)
        if state.lower() not in {item.lower() for item in states}:
            states.append(state)
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


def _materialize_scenarios(
    requirement_id: str,
    candidates: list[tuple[str, str, str, str]],
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
            )
        )
    return scenarios
