"""An omitted manuscript proof is assessable without inventing a proof route."""
import json
import unittest

from support import Fixture, R, TempCase, edit, locator, node_available
from paper_core import assessment, controller, finalization, publish, sources, stage1
from paper_core.authoring import create_audit, create_unit


class OmittedProofTests(TempCase):
    def make_case(self):
        fixture = Fixture(self.path("omitted"))
        (fixture.source_root / "paper.tex").write_text(
            "\\documentclass{article}\n\\newtheorem{theorem}{Theorem}\n\\begin{document}\n"
            "\\begin{theorem}\\label{thm:omitted}\nEvery bounded sequence converges.\n"
            "\\end{theorem}\nThe proof is omitted.\n\\end{document}\n", encoding="utf-8")
        fixture.capture()
        with fixture.open() as db:
            packet = fixture.packet(db)
            sources.anchor_sources(db, request={"contract_version": 3,
                "request_id": fixture.request_id(), "packet_id": packet["packet_id"],
                "anchors": [{"id": "anc_omitted", "expected_version": None,
                    "source_id": fixture.source_id, "locator": locator(start=4, end=7)}]})
        return fixture

    def definition(self):
        return {"key": "omitted", "kind": "theorem", "label": "Theorem 1",
            "statement": "Every bounded sequence converges.", "statement_anchors": ["anc_omitted"],
            "proof_anchors": [], "proof_complete": True, "source_matched": True,
            "source_note": "The supplied manuscript explicitly omits the proof; no continuation is missing."}

    def submit(self, db, fixture, prepared, mode, outcome="inconclusive"):
        self.assertTrue(prepared["prepared"], prepared)
        worker = prepared["scaffold"]
        if mode == "primary":
            for row in worker["results"]:
                if row["type"] == "source_fidelity":
                    row.update(result="matched", note="The exact statement matches the supplied passage.",
                               evidence_refs=["anc_omitted"])
                else:
                    row.update(state="complete", outcome=outcome,
                        reasoning="The manuscript supplies no proof. This claim remains unestablished by its argument.",
                        evidence_refs=["anc_omitted"])
        elif mode == "independent":
            worker["coverage_note"] = "Examined the supplied statement and explicit proof omission."
            for row in worker["judgments"]:
                row.update(state="complete", outcome=outcome,
                    reasoning="The source omits the argument, so its correctness is not established here.")
        else:
            for row in worker["integrations"]:
                row.update(decision="agree", rationale="Both examinations identify an omitted proof and retain uncertainty.")
        envelope = dict(prepared["submission_envelope_template"], request_id=fixture.request_id(),
                        reviewer="separate checker" if mode == "independent" else "coordinator")
        if mode == "independent":
            envelope.update(exposure="source_only", exposure_note="Separate source-only examination.")
        result = controller.submit_work(db, envelope_bytes=json.dumps(envelope).encode(),
                                        response_bytes=json.dumps(worker).encode())
        self.assertEqual("accepted", result["state"], result)
        return result

    def test_statement_only_helper_does_not_invent_route_or_source_issue(self):
        fixture = self.make_case()
        with fixture.open() as db:
            result = create_unit(db, self.definition())
            revision = db.max_revision()
            self.assertIsNone(result["unit"]["argument"])
            for collection in ("arguments", "groups", "proof_boundaries", "source_issues", "checks"):
                self.assertEqual([], db.heads(collection))
            self.assertTrue(create_unit(db, self.definition())["reused"])
            self.assertEqual(revision, db.max_revision())
            self.assertEqual(self.definition()["source_note"], db.head("items", "itm_omitted").body["uncertainty"])

    def test_omission_can_finish_uncertain_only_after_primary_review_and_integration(self):
        fixture = self.make_case()
        with fixture.open() as db:
            create_unit(db, self.definition())
            audit_id = create_audit(db, mode="full")["audit_id"]
            initial = assessment.derive_assessment(db, audit_id=audit_id)
            self.assertFalse(initial["progress"]["process_complete"])
            self.assertEqual([], initial["problems"])
            self.submit(db, fixture, stage1.prepare_stage(db, audit_id=audit_id), "primary")
            primary = assessment.derive_assessment(db, audit_id=audit_id)
            self.assertFalse(primary["progress"]["process_complete"])
            self.assertEqual("pending", primary["independent"]["items:itm_omitted"])
            self.submit(db, fixture, stage1.prepare_stage(db, audit_id=audit_id, stage=2, mode="independent"),
                        "independent")
            reviewed = assessment.derive_assessment(db, audit_id=audit_id)
            self.assertFalse(reviewed["progress"]["process_complete"])
            self.submit(db, fixture, stage1.prepare_stage(db, audit_id=audit_id, stage=2, mode="reconcile"),
                        "reconcile")
            done = assessment.derive_assessment(db, audit_id=audit_id)
            self.assertTrue(done["progress"]["process_complete"], done["problems"])
            self.assertEqual("conditional", done["support"]["items:itm_omitted"])
            self.assertEqual("complete", done["independent"]["items:itm_omitted"])
            self.assertNotEqual("green", done["assessments"]["items:itm_omitted"]["state"])
            self.assertEqual([], db.heads("arguments"))
            self.assertEqual(2, len(db.heads("checks")))

    def test_statement_only_supplier_remains_in_scope_without_becoming_a_route(self):
        fixture = self.make_case()
        with fixture.open() as db:
            supplier = fixture.item_edit("itm_external", "external_result", "Cited external premise",
                                         "anc_omitted", "anc_omitted")
            supplier["body"]["passages"] = [{"role": "statement", "anchor_id": "anc_omitted"}]
            fixture.apply(db, [supplier])
            definition = self.definition()
            definition["suppliers"] = [{"target": R("items", "itm_external"),
                "reason": "The manuscript attributes this premise to an external work.",
                "needed_form": {"form": "transcription", "text": "Cited external premise text"}}]
            create_unit(db, definition)
            audit_id = create_audit(db, mode="full")["audit_id"]
            result = assessment.derive_assessment(db, audit_id=audit_id)
            self.assertTrue(any(o["target"] == R("items", "itm_external") and o["kind"] == "external_source"
                                and o["required"] for o in result["obligations"]))
            self.assertFalse(any(o["target"] == R("items", "itm_external") and o["kind"] == "composition"
                                 and o["required"] for o in result["obligations"]))
            self.assertEqual([], db.heads("arguments"))
            self.assertEqual("conditional", result["support"]["items:itm_omitted"])

    @unittest.skipUnless(node_available(), "existing global Node.js is unavailable")
    def test_three_stage_delivery_preserves_the_omission_and_original_examinations(self):
        fixture = self.make_case()
        bundle, output = self.path("frozen"), self.path("report.html")
        with fixture.open() as db:
            create_unit(db, self.definition())
            audit_id = create_audit(db, mode="full")["audit_id"]
            for stage, mode in ((1, "primary"), (2, "independent"), (2, "reconcile")):
                self.submit(db, fixture, stage1.prepare_stage(db, audit_id=audit_id, stage=stage, mode=mode), mode)
            frozen = finalization.finalize_audit(db, audit_id=audit_id, output=bundle)
            self.assertEqual("release", frozen["kind"], frozen["finalization_blockers"])
            self.assertTrue(frozen["process_complete"])
            self.assertEqual(2, len(db.heads("checks")))
            revision = db.max_revision()
        report = publish.publish_frozen(bundle, output=output)
        self.assertEqual(revision, report["revision"])
        self.assertIn("The proof is omitted", output.read_text(encoding="utf-8"))
        snapshot, _ = finalization.load_finalization(bundle)
        target = snapshot["status"]["assessments"]["items:itm_omitted"]
        self.assertEqual("conditional", target["availability"])
        self.assertNotEqual("green", target["state"])
        with fixture.open(write=False) as db:
            self.assertEqual(revision, db.max_revision())
            self.assertEqual(2, len(db.heads("checks")))

    def test_favorable_statement_judgment_is_not_a_proof_and_new_route_needs_examination(self):
        fixture = self.make_case()
        with fixture.open() as db:
            create_unit(db, self.definition())
            audit_id = create_audit(db, mode="full")["audit_id"]
            self.submit(db, fixture, stage1.prepare_stage(db, audit_id=audit_id), "primary", outcome="supported")
            before = assessment.derive_assessment(db, audit_id=audit_id)
            self.assertEqual("conditional", before["support"]["items:itm_omitted"])
            old_check = db.heads("checks")[0]
            # A subsequently supplied (possibly invalid) argument is new evidence,
            # not an automatic upgrade of the earlier statement-only assessment.
            (fixture.source_root / "continuation.tex").write_text(
                "Proof of Theorem 1: boundedness implies that the limit exists.\n", encoding="utf-8")
            capture = sources.capture_sources(db, files=["continuation.tex"])
            packet = fixture.packet(db)
            sources.anchor_sources(db, request={"contract_version": 3,
                "request_id": fixture.request_id(), "packet_id": packet["packet_id"],
                "anchors": [{"id": "anc_later", "expected_version": None,
                    "source_id": capture["sources"][0]["id"], "locator": locator(start=1, end=1)}]})
            statement = db.head("items", "itm_omitted")
            fixture.apply(db, [edit("replace", "items", statement.id,
                dict(statement.body, passages=[*statement.body["passages"],
                    {"role": "proof", "anchor_id": "anc_later"}]), statement.version)])
            evidence_changed = assessment.derive_assessment(db, audit_id=audit_id)
            self.assertNotEqual("current", evidence_changed["judgments"]["checks:" + old_check.id]["freshness"])
            self.assertFalse(evidence_changed["progress"]["process_complete"])
            fixture.apply(db, [
                edit("create", "arguments", "arg_later", {"target": R("items", "itm_omitted"),
                    "label": "Later supplied proof", "origin": "source", "scope_id": "scp_omitted",
                    "final_group_id": "grp_later", "evidence_refs": ["anc_later"], "lifecycle": "registered"}),
                edit("create", "groups", "grp_later", {"argument_id": "arg_later",
                    "conclusion": R("items", "itm_omitted"), "kind": "joint", "scope_id": "scp_omitted",
                    "case_scope_ids": [], "discharges": [], "rationale": "The supplied argument.",
                    "evidence_refs": ["anc_later"]})])
            after = assessment.derive_assessment(db, audit_id=audit_id)
            self.assertFalse(after["progress"]["process_complete"])
            self.assertNotEqual("available", after["support"]["items:itm_omitted"])
            self.assertNotEqual("current", after["judgments"]["checks:" + old_check.id]["freshness"])


if __name__ == "__main__":
    import unittest
    unittest.main()
