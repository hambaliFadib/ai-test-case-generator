"""Shared coverage-profile resolution for the locked baseline contract.

Canonical profiles: minimal, comprehensive, extra.
Legacy aliases: balanced -> comprehensive, security -> comprehensive.
Default: comprehensive (resolved before any planning happens).
"""

from __future__ import annotations

CANONICAL_PROFILES: tuple[str, ...] = (
    "minimal",
    "comprehensive",
    "extra",
)

PROFILE_ALIASES: dict[str, str] = {
    "balanced": "comprehensive",
    "security": "comprehensive",
}

DEFAULT_PROFILE: str = "comprehensive"


def resolve_profile(value: str) -> str:
    """Resolve a user-supplied profile to its canonical name.

    Canonical names pass through, legacy aliases map to their canonical
    target, and anything else raises a ValueError that lists the canonical
    profiles.
    """

    normalized = (value or "").strip().lower()
    if normalized in CANONICAL_PROFILES:
        return normalized
    if normalized in PROFILE_ALIASES:
        return PROFILE_ALIASES[normalized]
    supported = ", ".join(CANONICAL_PROFILES)
    raise ValueError(f"Unsupported coverage profile '{value}'. Choose: {supported}.")
