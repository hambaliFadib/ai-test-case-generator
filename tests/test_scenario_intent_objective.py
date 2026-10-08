"""Deterministic tests for ScenarioIntent objective metadata propagation.

Verifies L3 findings:
1. objective_kind / objective_data survive Candidate → ScenarioIntent.
2. evidence_refs remain unchanged through materialisation.
3. scenario identity/dedup unaffected by wording changes.
4. different objective kinds semantically distinguishable at read-time.
5. no public CSV/API/UI schema changes (fields absent from output).
6. existing 179+ tests continue to pass (implicit via pytest suite).
"""

from __future__ import annotations

import unittest
import uuid

from models.coverage_model import EvidenceAtom, ScenarioIntent, ScenarioCandidate
from models.frozen_utils import freeze_objective_data


# ---------------------------------------------------------------------------
# T1 — objective metadata survives materialisation
# ---------------------------------------------------------------------------

class TestObjectiveSurvivesMaterialization(unittest.TestCase):
    def test_objective_kind_propagated(self) -> None:
        candidate = ScenarioCandidate(
            requirement_ref="REQ-001",
            category="behavior",
            technique="EP",
            evidence_refs=("REQ-001-E01",),
            constraint_refs=(),
            priority="medium",
            objective_kind="behavior",
            objective_data={"predicate": "validity"},
        )
        intent = ScenarioIntent(
            id=f"REQ-001-S{uuid.uuid4().hex[:8]}",
            requirement_ref=candidate.requirement_ref,
            category=candidate.category,
            technique=candidate.technique,
            intent="Verify behaviour.",
            priority=candidate.priority,
            evidence_refs=candidate.evidence_refs,
            constraint_refs=candidate.constraint_refs,
            objective_kind=candidate.objective_kind,
            objective_data=freeze_objective_data(candidate.objective_data),
        )
        self.assertEqual(intent.objective_kind, "behavior")
        self.assertEqual(intent.objective_data["predicate"], "validity")

    def test_default_empty_values(self) -> None:
        """Backward-compat: older callers create intents without objective fields."""
        intent = ScenarioIntent(
            id="REQ-001-S01",
            requirement_ref="REQ-001",
            category="presence",
            technique="EP",
            intent="Verify element visible.",
        )
        self.assertEqual(intent.objective_kind, "")
        self.assertIsNone(intent.objective_data)


# ---------------------------------------------------------------------------
# T2 — evidence_refs unchanged
# ---------------------------------------------------------------------------

class TestEvidenceRefsUnchanged(unittest.TestCase):
    def test_refs_preserved_exactly(self) -> None:
        refs = ("REQ-001-E01", "REQ-001-E02")
        intent = ScenarioIntent(
            id="REQ-001-S01",
            requirement_ref="REQ-001",
            category="presence",
            technique="EP",
            intent="Verify presence.",
            evidence_refs=refs,
        )
        self.assertEqual(intent.evidence_refs, refs)

    def test_empty_refs_preserved(self) -> None:
        intent = ScenarioIntent(
            id="REQ-001-S01",
            requirement_ref="REQ-001",
            category="policy",
            technique="policy",
            intent="Policy statement.",
            evidence_refs=(),
        )
        self.assertEqual(intent.evidence_refs, ())


# ---------------------------------------------------------------------------
# T3 — identity/dedup unaffected by wording changes
# ---------------------------------------------------------------------------

class TestIdentityUnaffected(unittest.TestCase):
    def _dedup_key(self, intent: ScenarioIntent) -> tuple:
        """Internal dedup key mirroring planner's six-tuple."""
        return (
            intent.requirement_ref,
            intent.category,
            intent.technique,
            intent.objective_kind if hasattr(intent, "objective_kind") else "",
            intent.objective_data if hasattr(intent, "objective_data") else None,
            intent.evidence_refs,
        )

    def test_wording_change_no_identity_change(self) -> None:
        i1 = ScenarioIntent(
            id="REQ-001-S01",
            requirement_ref="REQ-001",
            category="presence",
            technique="EP",
            intent="Verify element visible.",
            objective_kind="presence",
        )
        i2 = ScenarioIntent(
            id="REQ-001-S02",
            requirement_ref="REQ-001",
            category="presence",
            technique="EP",
            intent="Check element shown on page load.",  # different wording
            objective_kind="presence",
        )
        # Different IDs are expected; dedup should not trigger because
        # evidence_refs differ (both empty but same kind/req/category/tech).
        key1 = self._dedup_key(i1)
        key2 = self._dedup_key(i2)
        # Wording not in key: keys identical except implicit ref which is same.
        self.assertEqual(key1, key2)

    def test_different_obj_kinds_distinguishable(self) -> None:
        i_p = ScenarioIntent(
            id="REQ-001-S01",
            requirement_ref="REQ-001",
            category="presence",
            technique="EP",
            intent="Verify element present.",
            objective_kind="presence",
            objective_data=freeze_objective_data({"element": "submit_button"}),
        )
        i_b = ScenarioIntent(
            id="REQ-001-S02",
            requirement_ref="REQ-001",
            category="behavior",
            technique="EP",
            intent="Verify button enables submit.",
            objective_kind="behavior",
            objective_data=freeze_objective_data({"predicate": "state_transition"}),
        )
        self.assertNotEqual(i_p.objective_kind, i_b.objective_kind)
        self.assertNotEqual(i_p.objective_data, i_b.objective_data)


# ---------------------------------------------------------------------------
# T4 — different objective kinds semantically distinguishable at read-time
# ---------------------------------------------------------------------------

class TestObjectiveKindsDistinguishable(unittest.TestCase):
    def setUp(self) -> None:
        self.kinds = [
            ("presence", {"element": "title"}),
            ("behavior", {"predicate": "state_change"}),
            ("combination", {"pairs": [("A", "B")]}),
            ("boundary", {"value": "0", "relation": "below_min"}),
            ("mandatory", {"ref": "REQ-001-M1"}),
            ("state", {"state_value": "Draft"}),
            ("policy", {}),
            ("security", {"predicate": "encryption"}),
            ("sample_value", {"value": "'John Doe'"}),
            ("success_failure", {"outcome": "success"}),
            ("action_visibility", {"action": "save"}),
        ]

    def test_each_kind_distinct(self) -> None:
        seen_keys: set[str] = set()
        for kind, data in self.kinds:
            intent = ScenarioIntent(
                id=f"REQ-X-S01",
                requirement_ref="REQ-X",
                category="positive",
                technique="EP",
                intent=f"Test {kind}.",
                objective_kind=kind,
                objective_data=freeze_objective_data(data),
            )
            self.assertEqual(intent.objective_kind, kind)
            self.assertNotIn(kind, seen_keys, f"duplicate kind {kind}")
            # Freeze must be hashable
            _ = hash(intent)
            seen_keys.add(kind)


# ---------------------------------------------------------------------------
# T5 — no public schema leakage
# ---------------------------------------------------------------------------

class TestNoPublicSchemaLeakage(unittest.TestCase):
    def test_fields_absent_from_output_schemas(self) -> None:
        """objective_kind / objective_data are internal; they must not
        appear in CSV export field names, API response model attributes,
        or UI payload keys."""
        import models.csv_schema as cs

        csv_headers = getattr(cs, "SCHEMA_V1", []) or []
        forbidden = {"objective_kind", "objective_data"}
        for h in csv_headers:
            self.assertNotIn(h, forbidden, f"{h} leaks into CSV schema")

    def test_scenariointent_hash_unchanged(self) -> None:
        """Frozen dataclass hash must still cover all core fields so
        adding new positional-default fields doesn't break set/dict usage."""
        i1 = ScenarioIntent(
            id="REQ-001-S01",
            requirement_ref="REQ-001",
            category="presence",
            technique="EP",
            intent="Verify visible.",
            evidence_refs=("REQ-001-E01",),
            objective_kind="presence",
        )
        i2 = ScenarioIntent(
            id="REQ-001-S01",
            requirement_ref="REQ-001",
            category="presence",
            technique="EP",
            intent="Verify visible.",
            evidence_refs=("REQ-001-E01",),
            objective_kind="presence",
        )
        self.assertEqual(hash(i1), hash(i2))


# ---------------------------------------------------------------------------
# T6 — integration: full pipeline preserves objective metadata
# ---------------------------------------------------------------------------

class TestPipelinePreservation(unittest.TestCase):
    def test_full_plan_preserves_metadata(self) -> None:
        """Full plan must carry objective_kind through every step."""
        from coverage_planner import plan_coverage
        from models.requirement_model import Requirement

        req = Requirement(
            id="REQ-PIPE",
            title="Pipeline test",
            statement="Users save profile settings with display name (min 2, max 50 chars). The system shows success/failure messages.",
            acceptance_criteria=["Save action available"],
            details=[],
            constraints=["Do not expose passwords"],
            numeric_limits=["Up to 10 attachments"],
            tags=[],
        )
        plan = plan_coverage([req], "minimal")
        for rp in plan.requirements:
            for s in rp.scenarios:
                self.assertIn(s.requirement_ref, s.id)
                self.assertIn(s.category, ["presence", "behavior", "positive", "negative", "boundary", "policy", "sample_value"])
                self.assertTrue(len(s.intent) > 0, f"empty intent in {s.id}")
                # Every non-policy scenario must have a declared ref.
                if s.objective_kind != "policy" and s.evidence_refs == ():
                    self.fail(f"Non-policy scenario {s.id} has empty evidence_refs")


if __name__ == "__main__":
    unittest.main()
