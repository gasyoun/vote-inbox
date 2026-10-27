# -*- coding: utf-8 -*-
"""The decision-pack contract is enforced, not described (bughunt 27.10.2026, finding 3).

Six of the nine packs committed to this repo violated schema/decisions-pack.schema.json
while AGENTS.md told every agent to validate against it. These tests pin the contract:
every committed pack must validate, and the schema must actually reject the shapes the
emitter is NOT allowed to produce.
"""
import json
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "schema" / "decisions-pack.schema.json"
PACKS = sorted((ROOT / "decisions").glob("*/pack-*.json"))

try:
    import jsonschema

    HAVE_JSONSCHEMA = True
except ImportError:  # pragma: no cover
    HAVE_JSONSCHEMA = False


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def errors_for(pack, schema):
    validator = jsonschema.Draft7Validator(schema)
    return [e.message for e in validator.iter_errors(pack)]


@unittest.skipUnless(HAVE_JSONSCHEMA, "jsonschema not installed (pip install -r requirements-dev.txt)")
class CommittedPacksTest(unittest.TestCase):
    """The failing-before/passing-after pin for finding 3."""

    @classmethod
    def setUpClass(cls):
        cls.schema = load(SCHEMA_PATH)

    def test_packs_exist(self):
        self.assertGreaterEqual(len(PACKS), 1, "no decisions/*/pack-*.json found")

    def test_every_committed_pack_validates(self):
        for path in PACKS:
            with self.subTest(pack=str(path.relative_to(ROOT))):
                self.assertEqual(errors_for(load(path), self.schema), [])

    def test_decided_matches_non_null_items(self):
        for path in PACKS:
            with self.subTest(pack=str(path.relative_to(ROOT))):
                pack = load(path)
                non_null = sum(1 for i in pack["items"] if i.get("decision"))
                self.assertEqual(pack["decided"], non_null, "decided must equal the non-null count")

    def test_item_ids_are_unique(self):
        for path in PACKS:
            with self.subTest(pack=str(path.relative_to(ROOT))):
                ids = [i["id"] for i in load(path)["items"]]
                self.assertEqual(len(ids), len(set(ids)), "duplicate card ids in a pack")


@unittest.skipUnless(HAVE_JSONSCHEMA, "jsonschema not installed")
class SchemaShapeTest(unittest.TestCase):
    """The schema must reject what the emitter must not produce."""

    @classmethod
    def setUpClass(cls):
        cls.schema = load(SCHEMA_PATH)

    def base(self, **over):
        pack = {
            "sheet_id": "s",
            "pack": 1,
            "generated": "2026-09-05T10:07:11.700Z",
            "decided": 1,
            "items": [{"id": "D01", "decision": "approve"}],
        }
        pack.update(over)
        return pack

    def test_iso_generated_is_accepted(self):
        self.assertEqual(errors_for(self.base(), self.schema), [])

    def test_legacy_dd_mm_yyyy_generated_is_accepted(self):
        self.assertEqual(errors_for(self.base(generated="05-09-2026"), self.schema), [])

    def test_arbitrary_generated_is_rejected(self):
        self.assertTrue(errors_for(self.base(generated="5 September 2026"), self.schema))

    def test_unknown_top_level_key_is_rejected(self):
        self.assertTrue(errors_for(self.base(mystery=1), self.schema))

    def test_unknown_item_key_is_rejected(self):
        self.assertTrue(errors_for(self.base(items=[{"id": "D01", "decision": "approve", "mystery": 1}]), self.schema))

    def test_decision_enum_is_closed(self):
        self.assertTrue(errors_for(self.base(items=[{"id": "D01", "decision": "maybe"}]), self.schema))

    def test_null_decision_is_allowed(self):
        self.assertEqual(errors_for(self.base(decided=0, items=[{"id": "D01", "decision": None}]), self.schema), [])

    def test_note_with_html_is_rejected(self):
        self.assertTrue(
            errors_for(self.base(items=[{"id": "D01", "decision": "reject", "note": "<b>x</b>"}]), self.schema)
        )

    def test_reviewed_at_and_timings_are_accepted(self):
        """v0.23.0 emits reviewedAt; sheets emit time totals — the schema must follow the emitter."""
        pack = self.base(reviewedAt="2026-09-05T10:07:11.700Z", time_total_seconds=42)
        pack["items"] = [{"id": "D01", "decision": "approve", "time_seconds": 3.5}]
        self.assertEqual(errors_for(pack, self.schema), [])

    def test_pack_size_is_optional(self):
        """The browser upload path omits pack_size; consumers use len(items)."""
        self.assertNotIn("pack_size", self.schema.get("required", []))


if __name__ == "__main__":
    unittest.main()
