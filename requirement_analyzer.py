"""Deterministic extraction of requirements from parsed input.

Markdown documents with explicit requirement IDs are parsed by requirement
block. Inputs without explicit IDs retain the legacy heuristic behavior.
"""

from __future__ import annotations

from dataclasses import dataclass
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
_BULLET_PREFIX = re.compile(r"^(?:[-*+\u2022]\s+)")
_NUMBERED_PREFIX = re.compile(r"^\d+[.)]\s+")
_CRITERIA_PREFIX = re.compile(
    r"^(?:acceptance criteria|acceptance criterion|criteria|given|when|then|and)\s*[:\-]?",
    re.IGNORECASE,
)
_NUMERIC_OR_DATE = re.compile(
    r"\b(?:number|numeric|integer|decimal|amount|price|age|count|quantity|date|time|year|month|day|range|minimum|maximum|min|max|limit|within|between)\b|\d",
    re.IGNORECASE,
)

# A structured heading must contain an explicit ID and a title. The ID shape
# follows the v1.3 specification and accepts both ASCII and Unicode dashes.
_EXPLICIT_REQUIREMENT_HEADING = re.compile(
    r"^(?P<level>#{1,6})\s+"
    r"(?P<id>[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*-\d+)"
    r"\s*(?:\u2014|\u2013|-)\s*(?P<title>.+?)\s*$"
)
_HEADING = re.compile(r"^(?P<level>#{1,6})\s+(?P<title>.+?)\s*$")
_EXPECTED_MARKER = re.compile(
    r"^(?:expected|expected result|expected behavior|acceptance criteria|acceptance criterion|criteria)\s*:?$",
    re.IGNORECASE,
)
_CONSTRAINT = re.compile(
    r"\b(?:constraint|limit|maximum|minimum|only|must not|cannot|may not|do not|don't|within|at most|at least|max\.?|min\.?)\b",
    re.IGNORECASE,
)
_NUMERIC_LIMIT = re.compile(
    r"(?:\b(?:maximum|minimum|max|min|limit|at most|at least|within|between)\b.{0,80}\d|\d.{0,80}\b(?:characters?|bytes?|kb|mb|gb|days?|hours?|minutes?|seconds?)\b)",
    re.IGNORECASE,
)
_EXCLUDED_SECTION = re.compile(
    r"\b(?:excluded|exclusion|out of scope|non-assumption|do not generate)\b",
    re.IGNORECASE,
)
_UNRESOLVED_SECTION = re.compile(
    r"\b(?:open questions?|unresolved|tbd|to be determined|unknown)\b",
    re.IGNORECASE,
)
_INFORMATIONAL_SECTION = re.compile(
    r"\b(?:summary|overview|background|context|scope)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class _StructuredBlock:
    requirement_id: str
    title: str
    source_section: str
    lines: list[str]


def analyze_requirements(parsed_input: ParsedInput) -> list[Requirement]:
    """Extract requirements while preserving explicit IDs when present."""

    if not parsed_input.text.strip():
        raise RequirementAnalysisError("Cannot analyze empty parsed input.")

    if _contains_explicit_requirements(parsed_input.text):
        requirements = _analyze_structured_requirements(parsed_input.text)
        if not requirements:
            raise RequirementAnalysisError("No valid structured requirements found in parsed input.")
        return requirements

    return _analyze_legacy_requirements(parsed_input.text)


def _contains_explicit_requirements(text: str) -> bool:
    return any(_EXPLICIT_REQUIREMENT_HEADING.match(line.strip()) for line in text.splitlines())


def _analyze_structured_requirements(text: str) -> list[Requirement]:
    blocks = _collect_structured_blocks(text)
    requirements: list[Requirement] = []
    seen_ids: set[str] = set()

    for block in blocks:
        if block.requirement_id in seen_ids:
            raise RequirementAnalysisError(
                f"Duplicate explicit requirement ID '{block.requirement_id}'."
            )
        seen_ids.add(block.requirement_id)
        requirements.append(_requirement_from_block(block))

    return requirements


def _collect_structured_blocks(text: str) -> list[_StructuredBlock]:
    blocks: list[_StructuredBlock] = []
    section_stack: list[tuple[int, str]] = []
    active_id: str | None = None
    active_title = ""
    active_section = ""
    active_level = 0
    active_lines: list[str] = []

    def flush() -> None:
        nonlocal active_id, active_title, active_section, active_level, active_lines
        if active_id is not None:
            blocks.append(
                _StructuredBlock(
                    requirement_id=active_id,
                    title=active_title,
                    source_section=active_section,
                    lines=list(active_lines),
                )
            )
        active_id = None
        active_title = ""
        active_section = ""
        active_level = 0
        active_lines = []

    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        explicit = _EXPLICIT_REQUIREMENT_HEADING.match(stripped)
        if explicit:
            flush()
            active_id = explicit.group("id")
            active_title = explicit.group("title").strip()
            active_section = " > ".join(title for _, title in section_stack)
            active_level = len(explicit.group("level"))
            continue

        heading = _HEADING.match(stripped)
        if heading:
            level = len(heading.group("level"))
            title = heading.group("title").strip()
            if active_id is not None and level > active_level:
                # Deeper headings are contextual content in the active block.
                active_lines.append(raw_line)
                continue
            if active_id is not None:
                # Equal/higher headings close the active requirement block.
                flush()
            while section_stack and section_stack[-1][0] >= level:
                section_stack.pop()
            section_stack.append((level, title))
            continue

        if active_id is not None:
            active_lines.append(raw_line)

    flush()
    return blocks


def _requirement_from_block(block: _StructuredBlock) -> Requirement:
    content_lines = _meaningful_content_lines(block.lines)
    statement = _select_statement(content_lines, block.title)
    details = [line for line in content_lines if line != statement]
    criteria = _extract_structured_criteria(block.lines)
    constraints = _unique(line for line in content_lines if _CONSTRAINT.search(line))
    numeric_limits = _unique(line for line in content_lines if _NUMERIC_LIMIT.search(line))
    status = _classify_requirement_status(block, content_lines)
    searchable = " ".join([block.title, statement, *details, *criteria])

    return Requirement(
        id=block.requirement_id,
        statement=statement,
        acceptance_criteria=criteria,
        constraints=constraints,
        source_section=block.source_section,
        has_numeric_or_date_field=bool(_NUMERIC_OR_DATE.search(searchable)),
        title=block.title,
        details=details,
        status=status,
        tags=[],
        numeric_limits=numeric_limits,
    )


def _meaningful_content_lines(lines: list[str]) -> list[str]:
    result: list[str] = []
    in_fence = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if not stripped or in_fence:
            continue
        if _HEADING.match(stripped):
            continue
        cleaned = _clean_inline_markdown(_clean_markup(stripped))
        if cleaned:
            result.append(cleaned)
    return result


def _select_statement(content_lines: list[str], title: str) -> str:
    if not content_lines:
        return title.strip()

    # Prefer prose over a bare field/value bullet as the primary statement.
    for line in content_lines:
        if len(line) >= 10 and not re.fullmatch(r"[A-Za-z0-9 _/+-]+[*:]?", line):
            return line
    return content_lines[0]


def _extract_structured_criteria(lines: list[str]) -> list[str]:
    criteria: list[str] = []
    collecting = False
    collected_any = False
    for raw_line in lines:
        stripped = raw_line.strip()
        if not stripped:
            if collecting and collected_any:
                collecting = False
            continue
        cleaned = _clean_inline_markdown(_clean_markup(stripped))
        if _EXPECTED_MARKER.match(cleaned):
            collecting = True
            collected_any = False
            continue
        if collecting:
            if _HEADING.match(stripped):
                collecting = False
                continue
            criteria.append(cleaned)
            collected_any = True
    return _unique(criteria)


def _classify_requirement_status(block: _StructuredBlock, content_lines: list[str]) -> str:
    context = " ".join([block.source_section, block.title]).strip()
    if _UNRESOLVED_SECTION.search(context):
        return "UNRESOLVED"
    if _EXCLUDED_SECTION.search(context):
        return "EXCLUDED"

    # A testable block may contain guardrails such as "do not infer".
    if _INFORMATIONAL_SECTION.search(block.title) and not content_lines:
        return "INFORMATIONAL"
    return "TESTABLE"


def _clean_inline_markdown(text: str) -> str:
    text = re.sub(r"^>\s*", "", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"__([^_]+)__", r"\1", text)
    return text.strip()


def _unique(values) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _analyze_legacy_requirements(text: str) -> list[Requirement]:
    """Run the legacy line-oriented analyzer for unstructured input."""

    lines = [line for line in text.splitlines() if line.strip()]
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
                has_numeric_or_date_field=bool(
                    _NUMERIC_OR_DATE.search(statement + " " + " ".join(criteria))
                ),
            )
        )
    return requirements


def _clean_markup(line: str) -> str:
    """Remove common Markdown/list prefixes from a source line."""

    cleaned = re.sub(r"^#{1,6}\s*", "", line)
    cleaned = re.sub(r"^(?:[-*+\u2022]\s+|\d+[.)]\s+)", "", cleaned)
    return cleaned.strip()


def _is_requirement_candidate(line: str) -> bool:
    """Return whether a source line contains an independent legacy requirement."""

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
    """Collect acceptance-criteria lines relevant to a legacy requirement."""

    statement_index = next(
        (index for index, line in enumerate(lines) if statement in _clean_markup(line)),
        0,
    )
    criteria: list[str] = []
    for line in lines[statement_index + 1 :]:
        cleaned = _clean_markup(line)
        if _is_requirement_candidate(cleaned) and cleaned != statement:
            break
        if _CRITERIA_PREFIX.match(cleaned) or re.match(
            r"^(?:-\s*)?(?:given|when|then)\b", cleaned, re.IGNORECASE
        ):
            criteria.append(_CRITERIA_PREFIX.sub("", cleaned).strip() or cleaned)
    return criteria


def _constraints_for_statement(statement: str, lines: list[str]) -> list[str]:
    """Collect nearby lines that explicitly describe legacy constraints or limits."""

    constraints: list[str] = []
    for line in lines:
        cleaned = _clean_markup(line)
        if re.search(
            r"\b(?:constraint|limit|maximum|minimum|only|must not|cannot|within)\b",
            cleaned,
            re.IGNORECASE,
        ):
            if cleaned not in constraints and (
                cleaned == statement or statement in cleaned or not constraints
            ):
                constraints.append(cleaned)
    return constraints
