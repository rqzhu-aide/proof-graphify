"""Primary comparison packets make changed saved wording visible without asserting fidelity."""
from support import R, TempCase, edit
from test_work_packets import selection, task
from paper_core import packets
from paper_core.canonical import canonical_bytes


class SourceComparisonContextTests(TempCase):
    def setUp(self):
        super().setUp()
        self.fx = self.fixture().primary()

    def prepare(self, db, target, **limits):
        assigned = task("compare_saved_statement", target, "source_fidelity", action="compare_source")
        return packets.prepare_assignment(db, audit_id="aud_1", mode="primary",
                                          selection=selection((assigned,)), **limits)

    def test_repaired_statement_shows_old_and_new_text_plus_source(self):
        with self.fx.open() as db:
            old = db.head("items", "itm_lem")
            corrected = {"form": "verbatim", "text": "Corrected saved mathematical assertion"}
            self.fx.apply(db, [edit("replace", "items", old.id, dict(old.body, statement=corrected), old.version)])
            prepared = self.prepare(db, old.ref)
            view = prepared["packet"]["source_comparisons"][0]
            self.assertEqual(corrected, view["saved_statement"])
            self.assertEqual({"ref": old.pinned, "statement": old.body["statement"]}, view["previous_statement"])
            self.assertEqual([db.head("anchors", "anc_lem").pinned], view["source_anchor_refs"])
            self.assertNotIn("matched", view)
            self.assertEqual(len(canonical_bytes(prepared["packet"])), prepared["size"]["worker_bytes"])

    def test_exact_target_comparison_resolves_its_own_saved_statement_versions(self):
        with self.fx.open() as db:
            item, spec = db.head("items", "itm_lem"), db.head("target_specs", "tgt_lem")
            corrected = {"form": "verbatim", "text": "Revised target assertion"}
            self.fx.apply(db, [edit("replace", "items", item.id, dict(item.body, statement=corrected), item.version),
                edit("replace", "target_specs", spec.id, dict(spec.body,
                    statement_ref=dict(item.pinned, version=item.version + 1), scope_id="scp_plain"), spec.version)], mode="primary")
            view = self.prepare(db, spec.ref)["packet"]["source_comparisons"][0]
            self.assertEqual(corrected, view["saved_statement"])
            self.assertEqual(item.body["statement"], view["previous_statement"]["statement"])
            self.assertEqual(spec.pinned, view["previous_statement"]["ref"])
            self.assertEqual(R("scopes", "scp_plain"), view["scope_ref"])

    def test_unchanged_wording_does_not_get_an_invented_difference(self):
        with self.fx.open() as db:
            item = db.head("items", "itm_lem")
            self.fx.apply(db, [edit("replace", "items", item.id, dict(item.body, caption="A different caption"), item.version)])
            self.assertIsNone(self.prepare(db, item.ref)["packet"]["source_comparisons"][0]["previous_statement"])

    def test_proof_idea_is_retained_for_authors_and_primary_but_omitted_from_blind_packets(self):
        idea = "AUTHOR OUTLINE: use the saved lower bound and monotonicity."
        with self.fx.open() as db:
            item = db.head("items", "itm_lem")
            self.fx.apply(db, [edit("replace", "items", item.id, dict(item.body, proof_idea=idea), item.version)])
            authored = db.head("items", item.id)
            author = packets.get_packet(db, targets=[item.ref], mode="author")
            primary = self.prepare(db, item.ref)["packet"]
            for packet in (author, primary):
                row = next(row for row in packet["records"] if row["ref"]["id"] == item.id)
                self.assertEqual(row["body"]["proof_idea"], idea)
            blind = packets.get_packet(db, targets=[item.ref], mode="independent")
            row = next(row for row in blind["records"] if row["ref"]["id"] == item.id)
            self.assertEqual(row["body"], {k: v for k, v in authored.body.items() if k != "proof_idea"})
            self.assertNotIn(idea, canonical_bytes(blind).decode("utf-8"))
            self.assertEqual(db.head("items", item.id), authored)
            extended = packets.get_packet(db, extend=blind["packet_id"], request={
                "targets": [R("items", "itm_thm")], "source_anchor_ids": [], "source_paths": [],
                "reason": "Include the dependent source statement."})
            self.assertNotIn(idea, canonical_bytes(extended).decode("utf-8"))
            row["body"]["proof_idea"] = idea
            self.assertTrue(any("proof idea" in error for error in packets.blinding_violations(blind)))
            self.assertEqual(db.head("items", item.id), authored)

    def test_primary_comparison_view_is_forbidden_in_blind_packets(self):
        self.assertTrue(packets.blinding_violations({"records": [], "source_comparisons": []}))
        with self.fx.open() as db:
            selected = selection((task("blind_composition", R("arguments", "arg_lem"), "composition", role="independent"),))
            prepared = packets.prepare_assignment(db, audit_id="aud_1", mode="independent", selection=selected)
            self.assertNotIn("source_comparisons", prepared["packet"])
