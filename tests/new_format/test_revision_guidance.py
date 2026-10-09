"""Behavioral checks for the mapping and exact-statement recovery recipes.

Authored comparison judgments are synthetic protocol evidence, not a test of
scientific accuracy. Scope semantics are covered by the existing support tests.
"""
import copy
import json

from support import R, TempCase, edit, run_cli, write_json
from paper_core import controller, review
from paper_core.assessment import derive_full
from paper_core.canonical import canonical_bytes


class RevisionGuidanceTests(TempCase):
    def test_owner_item_cli_packet_authorizes_mapping_of_its_argument(self):
        fixture = self.fixture().audit()
        with fixture.open() as db:
            original = fixture.packet(db, "items:itm_lem", mode="independent")
            response = {"packet_id": original["packet_id"],
                "covered_targets": [R("items", "itm_lem")],
                "coverage_note": "Synthetic examination of the entire captured proof.",
                "exposure_report": {"status": "none_known", "note": ""},
                "judgments": [{"target": {"source_anchor_id": "anc_lem_proof",
                    "description": "The complete written lemma proof"}, "kind": "composition",
                    "state": "complete", "outcome": "inconclusive",
                    "reasoning": "Synthetic fixture leaves a mathematical step unresolved.",
                    "evidence_refs": ["anc_lem_proof"], "conditions": [],
                    "next_action": None, "supersedes": None}]}
            original_bytes = canonical_bytes(response)
            saved = review.submit_review(db, submission={"contract_version": 4,
                "request_id": fixture.request_id(), "packet_id": original["packet_id"],
                "reviewer": "checker-A", "qualification_id": "qua_r1", "exposure": "source_only",
                "exposure_note": "Synthetic isolated reviewer fixture."}, response_bytes=original_bytes)
            self.assertEqual("needs_revision", saved["state"])

        context_path, help_path = self.path("mapping-context.json"), self.path("mapping-help.json")
        run_cli("get", fixture.path, "--target", "items:itm_lem", "--mode", "primary", "--out", context_path)
        context = json.loads(context_path.read_text(encoding="utf-8"))
        self.assertIn(R("arguments", "arg_lem"),
                      [{"collection": row["ref"]["collection"], "id": row["ref"]["id"]}
                       for row in context["records"]])
        self.assertNotEqual(original["packet_id"], context["packet_id"])
        run_cli("review", "mapping-template", fixture.path, "--response", saved["response_id"],
                "--packet", context["packet_id"], "--out", help_path)
        mapping = json.loads(help_path.read_text(encoding="utf-8"))["template"]
        self.assertEqual([0], [row["judgment_index"] for row in mapping["entries"]])
        mapping["reviewer"] = "coordinator"
        mapping["entries"][0].update(target=R("arguments", "arg_lem"),
                                      rationale="The source proof belongs to this canonical argument.")
        mapping_path = write_json(self.path("mapping.json"), mapping)
        mapped, _ = run_cli("review", "map", fixture.path, "--response", saved["response_id"],
                            "--mapping", mapping_path)
        self.assertEqual("accepted", mapped["state"], mapped)
        with fixture.open() as db:
            check = db.head("checks", mapped["checks"][0]["check_id"])
            self.assertEqual(R("arguments", "arg_lem"), check.body["target"])
            self.assertEqual("inconclusive", check.body["outcome"])
            stored = db.head("responses", saved["response_id"])
            self.assertEqual(original_bytes, db.get_blob(stored.body["original_blob"]))

    def test_atomic_statement_correction_replaces_reuse_with_new_direct_comparison(self):
        fixture = self.fixture().audit(independent_required=False)
        target = R("target_specs", "tgt_lem")
        with fixture.open() as db:
            packet = fixture.packet(db, *fixture.ITEMS, mode="primary")
            review.compare(db, batch=fixture.batch([edit("create", "observations", "obs_prior", {
                "target": R("items", "itm_lem"), "result": "matched", "reviewer": "primary-1",
                "note": "Synthetic comparison of the original exact statement and setup.",
                "evidence_refs": ["anc_lem"]})], packet["packet_id"]))
            prior = db.head("observations", "obs_prior")
            spec = db.head("target_specs", target["id"])
            fixture.apply(db, [edit("replace", "target_specs", spec.id,
                dict(spec.body, fidelity_ref=prior.pinned), spec.version),
                fixture.check_edit("chk_local", R("groups", "grp_lem"), "derivation"),
                fixture.check_edit("chk_consumer", R("uses", "use_lem_thm"), "application")],
                *fixture.ITEMS, mode="primary")
            satisfied = controller.prepare_work(db, audit_id=fixture.audit_id, mode="primary", focus=target)
            self.assertFalse(satisfied["prepared"], satisfied)
            before = derive_full(db, audit_id=fixture.audit_id)[1]
            for cid in ("chk_local", "chk_consumer"):
                self.assertEqual("current", before["judgments"]["checks:" + cid]["freshness"])

            item, spec = db.head("items", "itm_lem"), db.head("target_specs", target["id"])
            corrected = {"form": "verbatim", "text": db.head("anchors", "anc_lem").body["excerpt"]}
            item_pin = dict(item.pinned, version=item.version + 1)
            fixture.apply(db, [edit("replace", "items", item.id,
                dict(item.body, statement=corrected), item.version),
                edit("replace", "target_specs", spec.id, dict(spec.body,
                    statement_ref=item_pin, fidelity_ref=None, evidence_refs=["anc_lem"]), spec.version)],
                "items:itm_lem", mode="author")
            self.assertEqual(spec.version + 1, db.head("target_specs", spec.id).version)
            self.assertEqual(item_pin, db.head("target_specs", spec.id).body["statement_ref"])
            self.assertEqual(prior, db.head("observations", prior.id))
            changed = derive_full(db, audit_id=fixture.audit_id)[1]
            for cid in ("chk_local", "chk_consumer"):
                self.assertNotEqual("current", changed["judgments"]["checks:" + cid]["freshness"])

            prepared = controller.prepare_work(db, audit_id=fixture.audit_id, mode="primary", focus=target)
            self.assertTrue(prepared["prepared"], prepared)
            self.assertEqual([target], [row["target"] for row in prepared["manifest"]["work"]["tasks"]])
            view = prepared["packet"]["source_comparisons"][0]
            self.assertEqual(corrected, view["saved_statement"])
            self.assertEqual([db.head("anchors", "anc_lem").pinned], view["source_anchor_refs"])
            response = copy.deepcopy(prepared["scaffold"])
            response["results"][0].update(result="matched",
                note="Synthetic renewed comparison of the corrected saved text and unchanged setup.",
                evidence_refs=["anc_lem"])
            envelope = {"contract_version": 4, "request_id": fixture.request_id(),
                "packet_id": prepared["packet_id"], "rebase_packet_id": None, "reviewer": "primary-1",
                "qualification_id": None, "exposure": None, "exposure_note": ""}
            submitted = controller.submit_work(db, envelope_bytes=canonical_bytes(envelope),
                                               response_bytes=canonical_bytes(response))
            self.assertEqual("accepted", submitted["state"], submitted)
            self.assertEqual(2, len(db.heads("observations")))
            self.assertEqual(prior, db.head("observations", prior.id))
            renewed = next(row for row in db.heads("observations") if row.id != prior.id)
            self.assertEqual(target, renewed.body["target"])
            self.assertEqual("matched", renewed.body["result"])
            satisfied = controller.prepare_work(db, audit_id=fixture.audit_id, mode="primary", focus=target)
            self.assertFalse(satisfied["prepared"], satisfied)
            after = derive_full(db, audit_id=fixture.audit_id)[1]
            for cid in ("chk_local", "chk_consumer"):
                self.assertNotEqual("current", after["judgments"]["checks:" + cid]["freshness"])
            self.assertFalse(after["progress"]["process_complete"])
