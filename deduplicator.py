"""Stable title-based deduplication for generated test cases."""

import hashlib
import re

from models.test_case_model import TestCase


class ScenarioDeduplicationError(ValueError):
    """Raised when a Phase 3 suite contains duplicate scenario identities."""


def deduplicate_test_cases(test_cases: list[TestCase]) -> list[TestCase]:
    """Dedupe legacy cases by fingerprint and Phase 3 cases by scenario identity."""

    unique: list[TestCase] = []
    seen_hashes: set[str] = set()
    seen_scenarios: set[str] = set()
    for test_case in test_cases:
        if test_case.scenario_ref:
            if test_case.scenario_ref in seen_scenarios:
                raise ScenarioDeduplicationError(
                    f"Duplicate scenario_ref '{test_case.scenario_ref}'."
                )
            seen_scenarios.add(test_case.scenario_ref)
            unique.append(test_case)
            continue
        fingerprint = _legacy_fingerprint(test_case)
        if fingerprint not in seen_hashes:
            seen_hashes.add(fingerprint)
            unique.append(test_case)
    return unique


def deduplicate_scenario_test_cases(test_cases: list[TestCase]) -> list[TestCase]:
    """Explicit Phase 3 alias that rejects duplicate scenario representations."""

    return deduplicate_test_cases(test_cases)


def _title_hash(title: str) -> str:
    """Create a stable SHA-256 hash from a normalized title."""

    normalized = re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _legacy_fingerprint(test_case: TestCase) -> str:
    """Preserve legacy title behavior while incorporating available source context."""

    normalized = "|".join(
        [
            test_case.requirement_ref.lower().strip(),
            re.sub(r"[^a-z0-9]+", " ", test_case.title.lower()).strip(),
            re.sub(r"[^a-z0-9]+", " ", test_case.expected_result.lower()).strip(),
        ]
    )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
