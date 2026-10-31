"""Saved findings remain readable while scope and explicit history are disclosed."""
from copy import deepcopy
import json
import shutil
import subprocess

import support
from paper_core import projection, publish


class ReaderPresentationTests(support.TempCase):
    @staticmethod
    def ancestors(element):
        while element["parent"]:
            element = element["parent"]
            yield element

    @staticmethod
    def text(element):
        return "".join(element["text"]).strip()

    def within(self, element, ancestor):
        return any(parent is ancestor for parent in self.ancestors(element))

    def paper(self, findings=(), *, exclusions=False):
        self._paper_number = getattr(self, "_paper_number", 0) + 1
        fixture = self.fixture(f"paper_{self._paper_number}", coherent=True,
                               title="Synthetic presentation test").primary()
        with fixture.open() as db:
            if exclusions:
                audit = db.head("audits", fixture.audit_id)
                fixture.apply(db, [support.edit("replace", "audits", audit.id, dict(audit.body,
                    exclusions=[{"target": support.R("items", "itm_lem"), "source_anchor_ids": [],
                                 "reason": "Synthetic excluded lemma", "consequence": "Lemma outside requested work"}]),
                    audit.version)], mode="primary")
            edits = []
            for identity, lifecycle, category in findings:
                edits.append(support.edit("create", "findings", identity, {
                    "audit_id": fixture.audit_id, "target": support.R("groups", "grp_thm"),
                    "category": category, "lifecycle": lifecycle,
                    "description": f"Complete description for {identity}: the saved transition needs justification.",
                    "impact_reason": f"Complete impact for {identity}: the claimed bound depends on this transition.",
                    "evidence_refs": ["anc_thm_proof"], "check_refs": [], "affected_uses": [],
                    "resolution": "Saved correction." if lifecycle == "resolved" else None}))
            if edits:
                fixture.apply(db, edits, *fixture.ITEMS)
            dataset = projection.build_projection(db, audit_id=fixture.audit_id)
            # Older saved reader payloads may include explicit historical findings.
            # Use the real accepted record pins to exercise that supported presentation.
            pins = {row["ref"]["id"]: row["ref"] for row in dataset["records"]
                    if row["ref"]["collection"] == "findings"}
            dataset["details"]["item:itm_thm"]["reader"]["finding_refs"] = [
                pins[identity] for identity in dataset["summary"]["findings"]["refs"]]
            envelope = publish.render_input(db, dataset, release=False, source_identity="presentation-test")
        return envelope

    def render(self, envelope):
        node = shutil.which("node")
        if not node:
            self.skipTest("shared Node is unavailable")
        untouched = deepcopy(envelope)
        source, output = self.path("input.json"), self.path("report.html")
        source.write_text(json.dumps(envelope), encoding="utf-8")
        result = subprocess.run([node, str(support.CORE / "renderer/render_projection.mjs"), str(source), str(output)],
                                capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        receipt = json.loads(result.stdout)
        self.assertEqual(receipt["representation"]["status"], "pass")
        page = output.read_bytes()
        self.assertEqual(publish.mechanical_acceptance(page, envelope["projection"], build=envelope["build"])["failures"], [])
        self.assertEqual(envelope, untouched)
        scan = publish._Scan()
        scan.feed(page.decode("utf-8"))
        return scan

    def cards(self, scan, detail):
        return [row for row in scan.elements if "data-issue-ref" in row["attrs"]
                and any(field["attrs"].get("data-reader-detail") == detail for field in scan.elements
                        if field["attrs"].get("data-reader-field") == "description" and self.within(field, row))]

    def check_fields(self, scan, card, *, detail, index, folded):
        identity = card["attrs"]["data-issue-ref"]
        fields = [row for row in scan.elements if self.within(row, card)
                  and row["attrs"].get("data-reader-field") in ("description", "impact_reason")]
        self.assertEqual(len(fields), 2)
        for field in fields:
            self.assertEqual(field["attrs"]["data-reader-detail"], detail)
            self.assertEqual(field["attrs"]["data-reader-context"], f"finding:{index}")
            self.assertEqual(field["attrs"]["data-reader-ref"], f"findings:{identity}:1")
            expected = (f"Complete description for {identity}: the saved transition needs justification."
                        if field["attrs"]["data-reader-field"] == "description" else
                        f"Complete impact for {identity}: the claimed bound depends on this transition.")
            self.assertEqual(self.text(field), expected)
            details = [a for a in self.ancestors(field) if a["tag"] == "details" and self.within(a, card)]
            self.assertEqual(bool(details), folded)
        links = [row for row in scan.elements if row["tag"] == "a" and self.within(row, card)]
        self.assertTrue(any(row["attrs"].get("data-jump-record") == f"findings:{identity}:1" for row in links))

    def test_mixed_findings_keep_original_field_indices_and_explicit_history(self):
        envelope = self.paper([("fnd_a_history", "resolved", "proof_gap"),
                               ("fnd_b_unrated", "open", "proof_gap"),
                               ("fnd_c_unresolved", "open", "inconclusive")])
        original = envelope["projection"]["summary"]["findings"]["refs"]
        self.assertEqual(original, ["fnd_a_history", "fnd_b_unrated", "fnd_c_unresolved"])
        scan = self.render(envelope)
        scope_details = next(e for e in scan.elements if "data-proof-summary-details" in e["attrs"])
        for detail in ("summary", "item:itm_thm"):
            cards = self.cards(scan, detail)
            self.assertEqual([c["attrs"]["data-issue-ref"] for c in cards], original[1:] + original[:1])
            for card in cards:
                identity = card["attrs"]["data-issue-ref"]
                historical = identity == original[0]
                self.check_fields(scan, card, detail=detail, index=original.index(identity), folded=historical)
                self.assertFalse(self.within(card, scope_details))
                if detail == "summary":
                    self.assertLess(scan.elements.index(card), scan.elements.index(scope_details))
                history = [a for a in self.ancestors(card) if "data-proof-finding-history" in a["attrs"]]
                self.assertEqual(bool(history), historical)
                if history:
                    self.assertNotIn("open", history[0]["attrs"])
                    self.assertEqual(self.text(history[0]["children"][0]), "Earlier findings")
                else:
                    self.assertTrue(any("proof-issue-qualification" in e["attrs"].get("class", "")
                                        and self.within(e, card) for e in scan.elements))

    def test_missing_display_metadata_keeps_saved_finding_prose_outside_history(self):
        envelope = self.paper([("fnd_unknown", "open", "proof_gap")])
        envelope["projection"].pop("finding_displays")
        scan = self.render(envelope)
        self.assertFalse(any("data-proof-finding-history" in e["attrs"] for e in scan.elements))
        for detail in ("summary", "item:itm_thm"):
            cards = self.cards(scan, detail)
            self.assertEqual(len(cards), 1)
            self.check_fields(scan, cards[0], detail=detail, index=0, folded=False)
            self.assertIn("Saved assessment, not rated", self.text(cards[0]))

    def test_historical_only_and_empty_findings_have_distinct_empty_states(self):
        for historical in (True, False):
            with self.subTest(historical=historical):
                envelope = self.paper([("fnd_history", "resolved", "proof_gap")] if historical else [])
                scan = self.render(envelope)
                summary = next(e for e in scan.elements if e["attrs"].get("id") == "proof-summary")
                self.assertEqual("No findings listed." in self.text(summary), not historical)
                for detail in ("summary", "item:itm_thm"):
                    cards = self.cards(scan, detail)
                    self.assertEqual(len(cards), int(historical))
                    if historical:
                        self.check_fields(scan, cards[0], detail=detail, index=0, folded=True)
                        history = next(a for a in self.ancestors(cards[0]) if "data-proof-finding-history" in a["attrs"])
                        self.assertNotIn("open", history["attrs"])

    def test_focused_scope_reports_exact_exclusion_count_without_duplicate_markers(self):
        envelope = self.paper(exclusions=True)
        scan = self.render(envelope)
        compact = next(e for e in scan.elements if "data-reader-declared-scope" in e["attrs"])
        self.assertEqual(self.text(compact), "Declared scope: Focused. Recorded exclusions: 1. See Scope and review details below.")
        details = [e for e in scan.elements if "data-proof-summary-details" in e["attrs"]]
        self.assertEqual(len(details), 1)
        self.assertNotIn("open", details[0]["attrs"])
        self.assertFalse(self.within(compact, details[0]))
        mode = [e for e in scan.elements if "data-proof-scope-mode" in e["attrs"]]
        self.assertEqual(len(mode), 1)
        self.assertEqual(self.text(mode[0]), "focused")
        self.assertTrue(self.within(mode[0], details[0]))
        exclusions = [e for e in scan.elements if e["attrs"].get("data-proof-fact", "").startswith("exclusion.")]
        self.assertEqual(len(exclusions), 1)
        self.assertTrue(self.within(exclusions[0], details[0]))
        self.assertIn("Synthetic excluded lemma", self.text(exclusions[0]))
        self.assertIn("Lemma outside requested work", self.text(exclusions[0]))
