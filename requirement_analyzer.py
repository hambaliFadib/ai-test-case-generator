"""Deterministic extraction of testable requirements from parsed input."""

import re

from models.input_model import ParsedInput
from models.requirement_model import Requirement


class RequirementAnalysisError(ValueError):
    """Raised when parsed input cannot be analyzed."""


_REQUIREMENT_PREFIX = re.compile(
    r"^(?:REQ[- ]?\d+\s*[:.)-]?|requirement\s+\d+\s*[:.)-]?|\d+[.)])\s*(.+)$",
    re.IGNORECASE,
)
_USER_STORY = re.compile(r"\bas a\b.+\bi want\b.+\bso that\b", re.IGNORECASE)
_KEYWORD_START = re.compile(
    r"^(?:User|System|As a|Given|When|Then|Fitur|Sistem|Pengguna)\b",
    re.IGNORECASE,
)
_BULLET_PREFIX = re.compile(r"^(?:[-*+•]\s+)")
_NUMBERED_PREFIX = re.compile(r"^\d+[.)]\s+")
_CRITERIA_PREFIX = re.compile(
    r"^(?:acceptance criteria|acceptance criterion|criteria|given|when|then|and)\s*[:\-]?",
    re.IGNORECASE,
)
_GENERIC_HEADING = re.compile(
    r"^(?:requirements?|acceptance criteria|constraints?|overview|description|notes?)$",
    re.IGNORECASE,
)
_NUMERIC_OR_DATE = re.compile(
    r"\b(?:number|numeric|integer|decimal|amount|price|age|count|quantity|date|time|year|month|day|range|minimum|maximum|min|max|limit|within|between)\b|\d",
    re.IGNORECASE,
)


def analyze_requirements(parsed_input: ParsedInput) -> list[Requirement]:
    """Extract normalized requirements, acceptance criteria, and constraints."""

    if not parsed_input.text.strip():
        raise RequirementAnalysisError("Cannot analyze empty parsed input.")

    lines = [line for line in parsed_input.text.splitlines() if line.strip()]
    candidates: list[tuple[str, str]] = []
    current_section = ""
    for raw_line in lines:
        stripped_line = raw_line.strip()
        if stripped_line.startswith("#"):
            current_section = re.sub(r"^#{1,6}\s*", "", stripped_line).strip()
            continue

        statement = _strip_requirement_marker(stripped_line)
        if _is_requirement_candidate(stripped_line) and len(statement) >= 10:
            candidates.append((statement, current_section))

    if not candidates:
        fallback = " ".join(_strip_requirement_marker(line.strip()) for line in lines).strip()
        if len(fallback) >= 10:
            candidates = [(fallback, current_section)]
        else:
            raise RequirementAnalysisError("No valid requirements found in parsed input.")

    requirements: list[Requirement] = []
    for index, (statement, section) in enumerate(candidates, start=1):
        criteria = _criteria_for_candidate(lines, statement)
        constraints = _constraints_for_statement(statement, lines)
        requirements.append(
            Requirement(
                id=f"REQ-{index:03d}",
                statement=statement,
                acceptance_criteria=criteria,
                constraints=constraints,
                source_section=section,
                has_numeric_or_date_field=bool(_NUMERIC_OR_DATE.search(statement + " " + " ".join(criteria))),
            )
        )
    return requirements


def _clean_markup(line: str) -> str:
    """Remove common Markdown/list prefixes from a source line."""

    cleaned = re.sub(r"^#{1,6}\s*", "", line)
    cleaned = re.sub(r"^(?:[-*+•]\s+|\d+[.)]\s+)", "", cleaned)
    return cleaned.strip()


def _is_requirement_candidate(line: str) -> bool:
    """Return whether a source line contains an independent requirement."""

    content = _strip_requirement_marker(line)
    has_structure = bool(_BULLET_PREFIX.match(line) or _NUMBERED_PREFIX.match(line))
    is_complete_sentence = bool(re.search(r"[.!?。！？]\s*$", content))
    if _REQUIREMENT_PREFIX.match(content) or _USER_STORY.search(content):
        return True
    if _KEYWORD_START.match(content) or has_structure or is_complete_sentence:
        return True
    return bool(re.search(r"\b(?:must|shall|should|required to)\b", content, re.IGNORECASE))


def _strip_requirement_marker(line: str) -> str:
    """Remove only a structural list or requirement-number marker."""

    without_marker = _BULLET_PREFIX.sub("", line, count=1)
    without_marker = _NUMBERED_PREFIX.sub("", without_marker, count=1)
    return _REQUIREMENT_PREFIX.sub(r"\1", without_marker, count=1).strip()


def _criteria_for_candidate(lines: list[str], statement: str) -> list[str]:
    """Collect acceptance-criteria lines relevant to a requirement."""

    statement_index = next(
        (index for index, line in enumerate(lines) if statement in _clean_markup(line)),
        0,
    )
    criteria: list[str] = []
    for line in lines[statement_index + 1 :]:
        cleaned = _clean_markup(line)
        if _is_requirement_candidate(cleaned) and cleaned != statement:
            break
        if _CRITERIA_PREFIX.match(cleaned) or re.match(r"^(?:-\s*)?(?:given|when|then)\b", cleaned, re.IGNORECASE):
            criteria.append(_CRITERIA_PREFIX.sub("", cleaned).strip() or cleaned)
    return criteria


def _constraints_for_statement(statement: str, lines: list[str]) -> list[str]:
    """Collect nearby lines that explicitly describe constraints or limits."""

    constraints: list[str] = []
    for line in lines:
        cleaned = _clean_markup(line)
        if re.search(r"\b(?:constraint|limit|maximum|minimum|only|must not|cannot|within)\b", cleaned, re.IGNORECASE):
            if cleaned not in constraints and (cleaned == statement or statement in cleaned or not constraints):
                constraints.append(cleaned)
    return constraints
