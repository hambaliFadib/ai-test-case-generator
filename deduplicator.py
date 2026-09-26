"""Stable title-based deduplication for generated test cases."""

import hashlib
import re

from models.test_case_model import TestCase


def deduplicate_test_cases(test_cases: list[TestCase]) -> list[TestCase]:
    """Remove duplicate test cases using a normalized title hash, preserving order."""

    unique: list[TestCase] = []
    seen_hashes: set[str] = set()
    for test_case in test_cases:
        title_hash = _title_hash(test_case.title)
        if title_hash not in seen_hashes:
            seen_hashes.add(title_hash)
            unique.append(test_case)
    return unique


def _title_hash(title: str) -> str:
    """Create a stable SHA-256 hash from a normalized title."""

    normalized = re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
