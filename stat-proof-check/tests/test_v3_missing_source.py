"""Unavailable promised proofs retain scope without holding up unrelated work."""
import json

from support import Fixture, R, TempCase, edit, locator
from paper_core import assessment, controller, finalization, packets, sources, stage1
from paper_core.authoring import create_audit, create_unit
from paper_core.errors import InvalidRequest


class MissingProofSourceTests(TempCase):
    def make_case(self):
        fixture = Fixture(self.path("missing-source"))
        (fixture.source_root / "paper.tex").write_text(
            "Lemma 1: Two is even.\nProof: Two equals two times one.\n"
            "Theorem 1: Every bounded sequence converges.\n"
            "The proof of Theorem 1 is in the supplement.\n", encoding="utf-8")
        fixture.capture()
        with fixture.open() as db:
            packet = fixture.packet(db)
            sources.anchor_sources(db, request={"contract_version": 3,
                "request_id": fixture.request_id(), "packet_id": packet["packet_id"],
                "anchors": [{"id": identity, "expected_version": None,
                    "source_id": fixture.source_id, "locator": locator(start=start, end=end)}
                    for identity, start, end in (("anc_ready", 1, 1), ("anc_ready_proof", 2, 2),
                                                  ("anc_missing", 3, 4))]})
        return fixture

    def definition(self, name="missing"):
        missing = name == "missing"
        return {"key": name, "kind": "theorem" if missing else "lemma",
            "label": "Theorem 1" if missing else "Lemma 1",
            "statement": "Every bounded sequence converges." if missing else "Two is even.",
            "statement_anchors": [f"anc_{name}"],
            "proof_anchors": [] if missing else ["anc_ready_proof"],
            "proof_complete": not missing, "source_matched": True, "reviewer": "coordinator",
            "source_note": "The referenced supplement proof is unavailable." if missing
                           else "The statement and complete proof match the source."}

    def finish_unit(self, db, fixture, audit_id, name, outcome):
        targets = {f"{prefix}_{name}" for prefix in ("itm", "arg", "tgt")}
        for stage, mode in ((1, "primary"), (2, "independent"), (2, "reconcile")):
            status = stage1.stage_status(db, audit_id=audit_id, stage=stage, mode=mode)
            selected = [t["id"] for t in status["tasks"]
                        if t["target"]["id"] in targets and t["id"] in status["remaining_task_ids"]]
            prepared = stage1.prepare_stage(db, audit_id=audit_id, stage=stage, mode=mode,
                                            task_ids=selected)
            self.assertTrue(prepared["prepared"], prepared)
            self.assertTrue(all(t["target"]["id"] in targets for t in prepared["manifest"]["work"]["tasks"]))
            response = prepared["scaffold"]
            reasoning = ("The supplied identity establishes evenness." if name == "ready" else
                         "The supplied proof infers convergence from boundedness without justifying this inference.")
            if mode == "primary":
                for row in response["results"]:
                    if row["type"] == "source_fidelity":
                        row.update(result="matched", note="The exact statement matches the source.",
                                   evidence_refs=[f"anc_{name}"])
                    else:
                        row.update(state="complete", outcome=outcome, reasoning=reasoning,
                                   evidence_refs=[f"anc_{name}_proof"])
            elif mode == "independent":
                response["coverage_note"] = "Examined the supplied statement and full proof in a separate context."
                for row in response["judgments"]:
                    row.update(state="complete", outcome=outcome, reasoning=reasoning)
            else:
                for row in response["integrations"]:
                    row.update(decision="agree", rationale="The saved examinations agree on the supplied inference.")
            envelope = dict(prepared["submission_envelope_template"], request_id=fixture.request_id(),
                            reviewer="separate checker" if mode == "independent" else "coordinator")
            if mode == "independent":
                envelope.update(exposure="source_only", exposure_note="Separate source-only examination.")
            result = controller.submit_work(db, envelope_bytes=json.dumps(envelope).encode(),
                                            response_bytes=json.dumps(response).encode())
            self.assertEqual("accepted", result["state"], result)

    def test_unavailable_proof_saves_one_statement_and_one_source_issue_idempotently(self):
        fixture = self.make_case()
        with fixture.open() as db:
            result = create_unit(db, self.definition())
            revision = db.max_revision()
            again = create_unit(db, self.definition())
            self.assertTrue(again["reused"])
            self.assertEqual(result["unit"], again["unit"])
            self.assertEqual(revision, db.max_revision())
            for key in ("argument", "group", "boundary"):
                self.assertIsNone(result["unit"][key])
            for collection in ("arguments", "groups", "source_reviews", "proof_boundaries", "checks"):
                self.assertEqual([], db.heads(collection))
            issues = db.heads("source_issues")
            self.assertEqual(1, len(issues))
            self.assertEqual(result["unit"]["source_issue"], issues[0].id)
            self.assertEqual({"source_id": fixture.source_id, "anchor_id": "anc_missing",
                "category": "missing_source", "description": self.definition()["source_note"],
                "lifecycle": "open", "resolution": None, "reviewer": "coordinator"}, issues[0].body)
            bad = dict(self.definition(), key="invalid_spans", proof_spans=[{
                "anchor_id": "anc_missing", "start_offset": 0, "end_offset": 1}])
            with self.assertRaisesRegex(InvalidRequest, "proof_spans requires located proof_anchors"):
                create_unit(db, bad)
            self.assertEqual(revision, db.max_revision())

    def test_assignment_context_keeps_relevant_and_source_wide_issues(self):
        fixture = self.make_case()
        with fixture.open() as db:
            create_unit(db, self.definition())
            create_unit(db, self.definition("ready"))
            audit_id = create_audit(db, mode="full")["audit_id"]
            packet = fixture.packet(db)
            sources.review_sources(db, batch=fixture.batch([
                edit("create", "source_issues", identity, {
                    "source_id": fixture.source_id, "anchor_id": anchor,
                    "category": "locator_limit", "description": "The stated source location needs attention.",
                    "lifecycle": "open", "resolution": None, "reviewer": "coordinator"})
                for identity, anchor in (("iss_ready", "anc_ready"), ("iss_file", None))], packet["packet_id"]))
            # Inspect the context builder directly because open relevant issues
            # correctly prevent normal assignment selection before packet creation.
            for mode in ("primary", "independent"):
                closure = packets._LocalClosure(db, mode, audit_id, packets.DEFAULT_WORK_BYTES)
                closure.anchors(["anc_ready", "anc_ready_proof"])
                closure.finish()
                self.assertEqual({"iss_ready", "iss_file"},
                    {r.id for r in closure.records.values() if r.collection == "source_issues"})
            ordinary = packets._Closure(db, "independent")
            ordinary.anchors(["anc_ready"])
            ordinary.finish()
            self.assertEqual({"iss_missing", "iss_ready", "iss_file"},
                {r.id for r in ordinary.records.values() if r.collection == "source_issues"})

    def test_unrelated_proof_finishes_and_recovered_continuation_needs_only_affected_work(self):
        fixture = self.make_case()
        with fixture.open() as db:
            create_unit(db, self.definition())
            create_unit(db, self.definition("ready"))
            audit_id = create_audit(db, mode="full")["audit_id"]
            initial = stage1.stage_status(db, audit_id=audit_id)
            missing_tasks = [t for t in initial["tasks"] if t["target"]["id"] == "itm_missing"]
            self.assertTrue(missing_tasks)
            self.assertTrue(all(t["blocker_ids"] for t in missing_tasks))
            self.finish_unit(db, fixture, audit_id, "ready", "supported")
            ready_checks = {r.id: r.pinned for r in db.heads("checks")}
            before = assessment.derive_assessment(db, audit_id=audit_id)
            self.assertEqual("available", before["support"]["items:itm_ready"])
            self.assertEqual("complete", before["independent"]["items:itm_ready"])
            self.assertFalse(stage1.prepare_stage(db, audit_id=audit_id)["prepared"])
            frozen = finalization.finalize_audit(db, audit_id=audit_id, output=self.path("unavailable"))
            self.assertEqual("working", frozen["kind"])
            self.assertFalse(frozen["process_complete"])
            self.assertTrue(any(b["code"] == "source_limit" for b in frozen["finalization_blockers"]))

            # Recovery uses the existing capture, record-edit and source-issue lifecycle paths.
            (fixture.source_root / "supplement.tex").write_text(
                "Proof of Theorem 1: boundedness implies that the limit exists.\n", encoding="utf-8")
            captured = sources.capture_sources(db, files=["supplement.tex"])
            source_id = captured["sources"][0]["id"]
            packet = fixture.packet(db)
            sources.anchor_sources(db, request={"contract_version": 3,
                "request_id": fixture.request_id(), "packet_id": packet["packet_id"],
                "anchors": [{"id": "anc_missing_proof", "expected_version": None,
                    "source_id": source_id, "locator": locator(start=1, end=1)}]})
            item = db.head("items", "itm_missing")
            spec = db.head("target_specs", "tgt_missing")
            fixture.apply(db, [
                edit("replace", "items", item.id, dict(item.body, uncertainty=None,
                    passages=[*item.body["passages"], {"role": "proof", "anchor_id": "anc_missing_proof"}]),
                    item.version),
                edit("replace", "target_specs", spec.id,
                    dict(spec.body, statement_ref={**R("items", item.id), "version": item.version + 1}), spec.version),
                edit("create", "arguments", "arg_missing", {"target": R("items", item.id),
                    "label": "Recovered proof of Theorem 1", "origin": "source", "scope_id": "scp_missing",
                    "final_group_id": "grp_missing", "evidence_refs": ["anc_missing_proof"], "lifecycle": "registered"}),
                edit("create", "groups", "grp_missing", {"argument_id": "arg_missing",
                    "conclusion": R("items", item.id), "kind": "joint", "scope_id": "scp_missing",
                    "case_scope_ids": [], "discharges": [], "rationale": "The supplied proof's inference.",
                    "evidence_refs": ["anc_missing_proof"]})])
            packet = fixture.packet(db)
            issue = db.head("source_issues", "iss_missing")
            sources.review_sources(db, batch=fixture.batch([
                edit("replace", "source_issues", issue.id, dict(issue.body, lifecycle="resolved",
                    resolution="The supplement continuation was captured and registered."), issue.version),
                edit("create", "source_reviews", "srv_missing", {
                    "source_refs": [fixture.pin(db, "sources", source_id)],
                    "anchor_refs": [fixture.pin(db, "anchors", "anc_missing_proof")],
                    "purpose": "proof_boundary", "decision": "accepted", "reviewer": "coordinator",
                    "rationale": "The complete supplied proof is now captured."})], packet["packet_id"]))
            fixture.apply(db, [edit("create", "proof_boundaries", "bnd_missing", {
                "target": R("items", item.id), "argument_ids": ["arg_missing"],
                "anchor_refs": [fixture.pin(db, "anchors", "anc_missing_proof")],
                "source_review_ref": fixture.pin(db, "source_reviews", "srv_missing"), "state": "complete"})])
            recovered = assessment.derive_assessment(db, audit_id=audit_id)
            self.assertEqual([], recovered["source_limits"])
            self.assertFalse(recovered["progress"]["process_complete"])
            self.assertNotEqual("available", recovered["support"]["items:itm_missing"])
            for check_id, pin in ready_checks.items():
                self.assertEqual(pin, db.head("checks", check_id).pinned)
                self.assertEqual("current", recovered["judgments"][f"checks:{check_id}"]["freshness"],
                    assessment.judgment_freshness(assessment.Snapshot(db, db.max_revision()),
                                                 db.head("checks", check_id), superseded=False))
            self.finish_unit(db, fixture, audit_id, "missing", "gap")
            done = finalization.finalize_audit(db, audit_id=audit_id, output=self.path("recovered"))
            self.assertEqual("release", done["kind"], done["finalization_blockers"])
            self.assertTrue(done["process_complete"])
            self.assertEqual("resolved", db.head("source_issues", issue.id).body["lifecycle"])
            self.assertNotEqual("available", done["status"]["assessments"]["items:itm_missing"]["availability"])
            self.assertEqual("available", done["status"]["assessments"]["items:itm_ready"]["availability"])
            self.assertEqual(1, len(db.heads("audits")))
            self.assertEqual(4, len(db.heads("checks")))


if __name__ == "__main__":
    import unittest
    unittest.main()
