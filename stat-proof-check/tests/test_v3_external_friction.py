"""External suppliers authored through the ordinary template need no spec backfill."""
from copy import deepcopy
import json

from support import R, TempCase, edit, locator, run_cli, write_json
from paper_core import assessment, finalization, review, sources, stage1


class ExternalAuthoringFlowTests(TempCase):
    def external_fixture(self, *, available=True, form="transcription"):
        fixture = self.fixture().audit(independent_required=False)
        anchor = "anc_thm_proof"
        with fixture.open() as db:
            if available:
                (fixture.source_root / "external.txt").write_text(
                    "Under uniform integrability, the sequence converges in mean.\n", encoding="utf-8")
                captured = sources.capture_sources(db, files=["external.txt"])
                packet = fixture.packet(db)
                sources.anchor_sources(db, request={"contract_version": 4, "request_id": fixture.request_id(),
                    "packet_id": packet["packet_id"], "anchors": [{"id": "anc_external", "expected_version": None,
                    "source_id": captured["sources"][0]["id"], "locator": locator(start=1, end=1)}]})
                anchor = "anc_external"
            packet = fixture.packet(db)
        template_path = self.path("external-template.json")
        run_cli("template", fixture.path, "--packet", packet["packet_id"], "--collection", "items",
                "--id", "itm_external", "--out", template_path)
        batch = json.loads(template_path.read_text(encoding="utf-8"))["template"]
        batch["edits"][0]["body"].update(kind="external_result", label="Cited convergence theorem",
            caption="The external statement", statement={"form": form,
            "text": "Under uniform integrability, the sequence converges in mean."},
            passages=[{"role": "statement", "anchor_id": anchor}], aliases=[], uncertainty=None,
            origin="source", owner_id=None, scope_id=None)
        batch_path = write_json(self.path("external-batch.json"), batch)
        run_cli("apply", fixture.path, "--batch", batch_path)
        with fixture.open() as db:
            fixture.apply(db, [edit("create", "uses", "use_external", {
                "from": R("items", "itm_external"), "to": R("items", "itm_thm"), "type": "dependency",
                "group_id": "grp_thm", "reason": "Uses the cited conclusion under its stated hypothesis.",
                "needed_form": {"form": "transcription", "text": "The sequence converges in mean."},
                "substitutions": [], "evidence_refs": ["anc_thm_proof"], "regime": None, "uncertainty": None})])
            self.assertFalse(any(s.body["target"] == R("items", "itm_external") for s in db.heads("target_specs")))
        fixture.primary()
        return fixture, anchor

    def examine_external(self, fixture, anchor, *, outcome="supported", compare=True):
        with fixture.open() as db:
            prep = stage1.prepare_stage(db, audit_id=fixture.audit_id, focus=R("items", "itm_external"))
        self.assertTrue(prep["prepared"], prep)
        response = deepcopy(prep["scaffold"])
        tasks = {t["id"]: t for t in prep["manifest"]["work"]["tasks"]}
        rows = []
        for row in response["results"]:
            if row["type"] == "source_fidelity":
                if not compare or tasks[row["task_id"]]["target"]["collection"] == "target_specs":
                    continue
                row.update(result="matched", note="The stored transcription matches the captured statement.",
                           evidence_refs=[anchor])
            else:
                row.update(state="complete", outcome=outcome, reasoning=(
                    "Inspected the cited statement and its hypothesis." if outcome == "supported" else
                    "The external publication is unavailable; the attributed statement remains unverified."),
                    evidence_refs=[anchor])
            rows.append(row)
        response["results"] = rows
        path = write_json(self.path(f"response-{prep['packet_id']}.json"), response)
        result, _ = run_cli("stage1", "examine", fixture.path, "--packet", prep["packet_id"],
            "--reviewer", "primary", "--response", path)
        self.assertEqual("accepted", result["state"], result)
        return result

    def observe(self, db, fixture, anchor, result):
        packet = fixture.packet(db, "items:itm_external", mode="primary")
        review.compare(db, batch=fixture.batch([edit("create", "observations", f"obs_{fixture.request_id()}", {
            "target": R("items", "itm_external"), "result": result, "reviewer": "primary",
            "note": "Synthetic source comparison.", "evidence_refs": [anchor]})], packet["packet_id"]))

    def test_supported_template_supplier_reuses_saved_math_without_specs_or_more_work(self):
        fixture, anchor = self.external_fixture()
        receipt = self.examine_external(fixture, anchor)
        with fixture.open() as db:
            before_revision = db.max_revision()
            before_checks = [(r.pinned, deepcopy(r.body)) for r in db.heads("checks")]
            original_submission = db.work_submission(receipt["request_id"])
            original_bytes = db.get_blob(original_submission["response_sha256"])
            first = assessment.derive_assessment(db, audit_id=fixture.audit_id)
            self.assertEqual("available", first["support"]["items:itm_external"])
            self.assertEqual("available", first["support"]["items:itm_thm"])
            self.assertTrue(first["progress"]["process_complete"])
            self.assertFalse(stage1.prepare_stage(db, audit_id=fixture.audit_id)["prepared"])
            again = assessment.derive_assessment(db, audit_id=fixture.audit_id)
            self.assertEqual(first["progress"], again["progress"])
            self.assertEqual(first["judgments"], again["judgments"])
            self.assertEqual(before_revision, db.max_revision())
            self.assertEqual(before_checks, [(r.pinned, r.body) for r in db.heads("checks")])
            self.assertEqual(original_bytes, db.get_blob(db.work_submission(receipt["request_id"])["response_sha256"]))
            self.assertFalse(any(s.body["target"] == R("items", "itm_external") for s in db.heads("target_specs")))
            frozen = finalization.finalize_audit(db, audit_id=fixture.audit_id, output=self.path("frozen"))
            self.assertEqual("release", frozen["kind"])

    def test_unavailable_source_finishes_conditionally_without_extra_assignments(self):
        fixture, anchor = self.external_fixture(available=False)
        self.examine_external(fixture, anchor, outcome="inconclusive")
        with fixture.open() as db:
            result = assessment.derive_assessment(db, audit_id=fixture.audit_id)
            self.assertEqual("conditional", result["support"]["items:itm_external"])
            self.assertEqual("conditional", result["support"]["items:itm_thm"])
            self.assertTrue(result["progress"]["process_complete"])
            self.assertFalse(stage1.prepare_stage(db, audit_id=fixture.audit_id)["prepared"])

    def test_inspected_verbatim_statement_is_an_exact_external_target(self):
        fixture, anchor = self.external_fixture(form="verbatim")
        self.examine_external(fixture, anchor)
        with fixture.open() as db:
            result = assessment.derive_assessment(db, audit_id=fixture.audit_id)
            self.assertEqual("available", result["support"]["items:itm_external"])
            self.assertTrue(result["progress"]["process_complete"])

    def test_support_requires_a_current_successful_source_comparison(self):
        fixture, anchor = self.external_fixture()
        self.examine_external(fixture, anchor, compare=False)
        with fixture.open() as db:
            self.assertEqual("conditional", assessment.derive_assessment(db, audit_id=fixture.audit_id)["support"]["items:itm_external"])
            self.observe(db, fixture, anchor, "matched")
            self.assertEqual("available", assessment.derive_assessment(db, audit_id=fixture.audit_id)["support"]["items:itm_external"])
            self.observe(db, fixture, anchor, "needs_attention")
            self.assertEqual("conditional", assessment.derive_assessment(db, audit_id=fixture.audit_id)["support"]["items:itm_external"])

    def assert_changed_external_loses_support(self, change):
        fixture, anchor = self.external_fixture()
        self.examine_external(fixture, anchor)
        with fixture.open() as db:
            if change == "statement":
                item = db.head("items", "itm_external")
                body = deepcopy(item.body)
                body["statement"]["text"] = "Without any assumptions, the sequence converges uniformly."
                fixture.apply(db, [edit("replace", "items", item.id, body, item.version)])
            else:
                (fixture.source_root / "external.txt").write_text("A materially different external statement.\n", encoding="utf-8")
                sources.capture_sources(db, files=["external.txt"])
            result = assessment.derive_assessment(db, audit_id=fixture.audit_id)
            self.assertEqual("conditional", result["support"]["items:itm_external"])
            self.assertFalse(result["progress"]["process_complete"])

    def test_changed_statement_cannot_inherit_saved_support(self):
        self.assert_changed_external_loses_support("statement")

    def test_changed_source_cannot_inherit_saved_support(self):
        self.assert_changed_external_loses_support("source")

    def test_synopsis_does_not_become_an_exact_external_target(self):
        fixture, anchor = self.external_fixture(form="synopsis")
        self.examine_external(fixture, anchor)
        with fixture.open() as db:
            self.assertEqual("conditional", assessment.derive_assessment(db, audit_id=fixture.audit_id)["support"]["items:itm_external"])

    def test_explicit_different_spec_remains_authoritative(self):
        fixture, anchor = self.external_fixture()
        with fixture.open() as db:
            fixture.apply(db, [edit("create", "target_specs", "tgt_external", {
                "target": R("items", "itm_external"), "statement_ref": None,
                "statement": {"form": "transcription", "text": "The sequence converges uniformly."},
                "scope_id": None, "evidence_refs": [anchor], "state": "registered", "fidelity_ref": None})])
        self.examine_external(fixture, anchor)
        with fixture.open() as db:
            result = assessment.derive_assessment(db, audit_id=fixture.audit_id)
            check = next(j for j in result["judgments"].values() if j["kind"] == "external_source")
            self.assertEqual("current", check["freshness"])
            self.assertEqual("supported", check["outcome"])
            self.assertEqual("conditional", result["support"]["items:itm_external"])
