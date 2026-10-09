"""Common math diagnostics remain derived, located, and outside scientific records."""
import copy
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from support import TempCase, node_available
from paper_core import math_render, publish


class MathDisplayMetadataTests(unittest.TestCase):
    def projection(self):
        unsupported = r"$\privateDisplayMacro{x}$"
        item = {"ref": {"collection": "items", "id": "itm_private", "version": 7},
                "body": {field: unsupported for field in publish.FRAGMENT_FIELDS}}
        item["body"].update(statement={"form": "verbatim", "text": unsupported},
                            needed_form={"form": "verbatim", "text": unsupported},
                            conditions=["ordinary prose", unsupported, unsupported],
                            excerpt=unsupported, locator=unsupported)
        return {"records": [item, copy.deepcopy(item)], "snapshot_revision": 9,
                "audit_id": "aud_private"}

    def test_field_paths_versions_and_counts_follow_saved_fields_once(self):
        projection = self.projection()
        before = copy.deepcopy(projection)
        diagnostics = []
        fragments = publish.display_fragments(projection, diagnostics)
        self.assertEqual(before, projection)
        self.assertEqual(publish.display_fragments(projection), fragments)
        self.assertEqual(len(publish.FRAGMENT_FIELDS) + 1, len(diagnostics))
        paths = {row["field_path"] for row in diagnostics}
        self.assertIn("statement.text", paths)
        self.assertIn("needed_form.text", paths)
        self.assertIn("conditions/1", paths)
        self.assertIn("conditions/2", paths)
        self.assertNotIn("excerpt", paths)
        self.assertNotIn("locator", paths)
        for row in diagnostics:
            self.assertEqual(("items", "itm_private", 7),
                (row["collection"], row["record_id"], row["record_version"]))
            self.assertEqual(row["kind"], row["classification"])
        summary = publish.summarize_math_diagnostics(diagnostics)
        self.assertEqual(len(diagnostics), summary["total"])
        self.assertTrue(summary["nonblocking"])
        self.assertFalse(summary["messages_truncated"])
        self.assertNotIn("itm_private", " ".join(summary["messages"]))

    def test_repeated_expressions_in_one_field_count_separately_and_notes_are_bounded(self):
        projection = self.projection()
        projection["records"] = projection["records"][:1]
        projection["records"][0]["body"] = {"reason": r"$\privateA$ and $\privateA$"}
        diagnostics = []
        publish.display_fragments(projection, diagnostics)
        self.assertEqual([0, 1], [row["expression_index"] for row in diagnostics])
        summary = publish.summarize_math_diagnostics(diagnostics)
        self.assertEqual(2, summary["groups"][0]["count"])
        entries = [{**diagnostics[0], "reason": f"Display failure {i}."} for i in range(8)]
        summary = publish.summarize_math_diagnostics(entries)
        self.assertEqual(8, summary["total"])
        self.assertEqual(5, len(summary["messages"]))
        self.assertTrue(summary["messages_truncated"])
        self.assertTrue(summary["groups_truncated"])

    def test_live_and_frozen_inputs_share_full_derived_display_metadata(self):
        projection = self.projection()
        snapshot = {"paper": {"title": "Math display"}, "projection": projection,
                    "revision": 9, "audit_id": "aud_private", "source_identity": "source",
                    "kind": "working", "producer": "producer", "process_complete": True,
                    "representation_settled": True, "finalization_blockers": [],
                    "finalization_blocker_count": 0}
        before = copy.deepcopy(snapshot)
        with patch.object(publish, "paper_record", return_value=SimpleNamespace(body=snapshot["paper"])):
            live = publish.render_input(None, projection, release=False, source_identity="source")
        frozen = publish.frozen_render_input(snapshot, snapshot_sha256="digest")
        self.assertEqual(live["display"], frozen["display"])
        self.assertEqual(before, snapshot)
        json.dumps(frozen)


@unittest.skipUnless(node_available(), "existing global Node.js is unavailable")
class MathPublicationReceiptTests(TempCase):
    def test_live_and_frozen_receipts_keep_located_facts_without_scientific_mutation(self):
        from paper_core import finalization, projection as projections
        fixture = self.fixture("math-receipts").audit(independent_required=False).primary()
        with fixture.open() as db:
            current = db.head("checks", "chk_comp_thm")
            from support import edit
            fixture.apply(db, [edit("create", "checks", "chk_display_thm",
                dict(current.body, reasoning=r"Reasoning $\privatePublicationMacro{x}$.",
                     conditions=[r"Assume $\mathcal{\alpha}$."], supersedes=current.pinned))],
                *fixture.ITEMS, mode="primary")
            projection = projections.build_projection(db, audit_id=fixture.audit_id)
            before = copy.deepcopy(projection)
            live = publish.publish_report(db, projection=projection, output=self.path("live.html"))
            self.assertEqual(before, projection)
            self.assertTrue(live["receipt"]["math_diagnostics"])
            self.assertEqual("pass", live["receipt"]["python_acceptance"]["status"])
        bundle = self.path("frozen")
        with fixture.open(write=False) as db:
            finalization.finalize_audit(db, audit_id=fixture.audit_id, output=bundle)
        snapshot_path = bundle / finalization.SNAPSHOT_NAME
        frozen_before = snapshot_path.read_bytes()
        frozen = publish.publish_frozen(bundle, output=self.path("frozen.html"))
        receipt = frozen["receipt"]
        self.assertEqual(live["receipt"]["math_diagnostics"], receipt["math_diagnostics"])
        self.assertEqual(receipt["math_diagnostics"], receipt["renderer"]["math_diagnostics"])
        self.assertEqual(len(receipt["math_diagnostics"]), receipt["math_diagnostic_summary"]["total"])
        self.assertEqual(frozen_before, snapshot_path.read_bytes())
        page = self.path("frozen.html").read_text(encoding="utf-8")
        self.assertIn("Math display notes", page)
        self.assertIn("privatePublicationMacro", page)


if __name__ == "__main__":
    unittest.main()
