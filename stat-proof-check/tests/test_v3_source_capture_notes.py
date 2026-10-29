"""Capture-note selection must respect the saved scientific record boundaries."""
import copy
import unittest

import support  # Use the suite's existing package bootstrap.
from paper_core import publish


def ref(collection, identity, version=1):
    return {"collection": collection, "id": identity, "version": version}


class SourceCaptureNotesTests(unittest.TestCase):
    def projection(self):
        source = {"ref": ref("sources", "src", 1), "body": {"path": "old.pdf"}}
        anchor = {"ref": ref("anchors", "anc"), "body": {"source_id": "src", "source_version": 1,
                  "locator": {"page": 2, "label": "(3.6)"}, "limitation": " Saved capture note. "}}
        return {"records": [source, anchor,
                {"ref": ref("sources", "src", 2), "body": {"path": "new.pdf"}}],
                "details": {"item": {"sections": [{"kind": "sources", "record_refs": [anchor["ref"]]}]}}}

    def test_exact_pins_only_and_no_mutation(self):
        p = self.projection()
        unselected = copy.deepcopy(p["records"][1])
        unselected["ref"] = ref("anchors", "outside")
        p["records"].append(unselected)
        before = copy.deepcopy(p)
        notes = publish._source_capture_notes(p)
        self.assertEqual(1, len(notes))
        self.assertEqual("old.pdf", notes[0]["source_path"])
        self.assertEqual(" Saved capture note. ", notes[0]["description"])
        self.assertEqual([ref("anchors", "anc")], notes[0]["anchor_refs"])
        self.assertEqual(before, p)
        notes[0]["locator"]["page"] = 999
        self.assertEqual(before, p)

    def test_canonical_locator_dedup_retains_every_anchor(self):
        p = self.projection()
        duplicate = copy.deepcopy(p["records"][1])
        duplicate["ref"] = ref("anchors", "other")
        duplicate["body"]["locator"] = {"label": "(3.6)", "page": 2}
        p["records"].append(duplicate)
        p["details"]["item"]["sections"][0]["record_refs"].extend([duplicate["ref"], duplicate["ref"]])
        notes = publish._source_capture_notes(p)
        self.assertEqual(1, len(notes))
        self.assertEqual([ref("anchors", "anc"), ref("anchors", "other")], notes[0]["anchor_refs"])
        duplicate["body"]["locator"]["page"] = 3
        self.assertEqual(2, len(publish._source_capture_notes(p)))
        duplicate["body"]["locator"]["page"] = 2
        duplicate["body"]["source_version"] = 2
        self.assertEqual(2, len(publish._source_capture_notes(p)))

    def test_missing_source_stays_unknown_and_blank_notes_are_omitted(self):
        p = self.projection()
        p["records"].pop(0)
        self.assertIsNone(publish._source_capture_notes(p)[0]["source_path"])
        p["records"][0]["body"]["limitation"] = " \n "
        self.assertEqual([], publish._source_capture_notes(p))


if __name__ == "__main__":
    unittest.main()
