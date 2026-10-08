"""Immutable, hashable wrappers for deterministic object metadata.

Frozens the planner's objective_data so it survives into ScenarioIntent on a
frozen dataclass without sacrificing ordered collection semantics or leaking
mutable references.
"""

from __future__ import annotations

from typing import Any, ItemsView, KeysView, ValuesView


class FrozenDict:
    """Immutable, hashable mapping backed by a sorted tuple-of-pairs.

    Supports only JSON-like value types (str, int, float, bool, None, list,
    tuple, and nested FrozenDict).  Keys must be sortable hashable scalars.

    Implements collections.abc.Mapping so callers use standard dict APIs
    (.keys(), .values(), .items(), x[key], get(key), len(x), x in d).
    """

    def __init__(
        self,
        data: dict[str, Any] | None = None,
    ) -> None:
        if data is None:
            self._pairs: tuple[tuple[str, Any], ...] = ()
        else:
            self._pairs = tuple(self._freeze_pair(k, v) for k, v in sorted(data.items()))
        # Ensure no shared mutable references
        assert isinstance(self._pairs, tuple)

    @staticmethod
    def _freeze_value(v: Any) -> Any:
        """Convert a single value to its immutable hashable form."""
        if v is None or isinstance(v, (str, int, float, bool)):
            return v
        if isinstance(v, dict):
            return FrozenDict(v)
        if isinstance(v, (list, tuple)):
            return tuple(FrozenDict._freeze_value(item) for item in v)
        if isinstance(v, set):
            return frozenset(v)
        raise TypeError(f"Unsupported objective_data value type: {type(v).__name__}")

    @staticmethod
    def _freeze_pair(
        k: str,
        v: Any,
    ) -> tuple[str, Any]:
        return (k, FrozenDict._freeze_value(v))

    # --- Mapping protocol ---

    def __getitem__(self, key: str) -> Any:
        for k, v in self._pairs:
            if k == key:
                return v
        raise KeyError(key)

    def __iter__(self) -> Any:
        return (k for k, _ in self._pairs)

    def __len__(self) -> int:
        return len(self._pairs)

    def keys(self) -> KeysView[str]:
        return KeysView(self)

    def values(self) -> ValuesView[Any]:
        return ValuesView(self)

    def items(self) -> ItemsView[str, Any]:
        return ItemsView(self)

    def get(self, key: str, default: Any = None) -> Any:
        try:
            return self[key]
        except KeyError:
            return default

    # --- Immutability & hashing ---

    def __contains__(self, key: Any) -> bool:
        return any(k == key for k, _ in self._pairs)

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, FrozenDict):
            return NotImplemented
        return self._pairs == other._pairs

    def __hash__(self) -> int:
        return hash(self._pairs)

    def __repr__(self) -> str:
        pairs = ", ".join(f"{k!r}: {v!r}" for k, v in self._pairs)
        return f"FrozenDict({{{pairs}}})"

    def __setitem__(self, key: str, value: Any) -> Any:
        raise TypeError("FrozenDict is immutable")

    def __delitem__(self, key: str) -> Any:
        raise TypeError("FrozenDict is immutable")


def freeze_objective_data(
    data: dict[str, Any] | None,
) -> FrozenDict | None:
    """Public wrapper: returns None or a new FrozenDict."""
    if data is None:
        return None
    return FrozenDict(data)

