"""Focused audits retain source limits on the context their proofs consume."""
from __future__ import annotations

import re

from support import TempCase, edit, locator, node_available, run_cli
from paper_core import assessment, projection, sources


class SourceLimitContextTests(TempCase):
    def context_fixture(self, kind):
        fx = self.fixture(kind).audit()
        (fx.source_root / "context.tex").write_text(
            "Applicable context for the lemma.\nAn unrelated passage.\n", encoding="utf-8")
        (fx.source_root / "unrelated.tex").write_text("Outside the audited argument.\n", encoding="utf-8")
        with fx.open() as db:
            captured = sources.capture_sources(db, files=["context.tex", "unrelated.tex"])
            source_ids = {row["path"]: row["id"] for row in captured["sources"]}
            packet = fx.packet(db)
            sources.anchor_sources(db, request={
                "contract_version": 4, "request_id": fx.request_id(), "packet_id": packet["packet_id"],
                "anchors": [
                    {"id": name, "expected_version": None, "source_id": source_ids["context.tex"],
                     "locator": locator(start=line, end=line)}
                    for name, line in (("anc_context", 1), ("anc_unrelated", 2))]})
            if kind == "scope":
                scope = db.head("scopes", "scp_plain")
                fx.apply(db, [
                    edit("create", "scopes", "scp_context", {
                        "argument_id": None, "parent_id": None, "assumptions": [], "binders": [],
                        "conditions": [], "evidence_refs": ["anc_context"]}),
                    edit("replace", "scopes", scope.id, dict(scope.body, parent_id="scp_context"),
                         scope.version)])
            elif kind == "exact_target":
                spec = db.head("target_specs", "tgt_lem")
                fx.apply(db, [edit("replace", "target_specs", spec.id,
                    dict(spec.body, evidence_refs=spec.body["evidence_refs"] + ["anc_context"]), spec.version)])
            elif kind == "boundary":
                # One accepted review may cover more than this argument's actual boundary.
                packet = fx.packet(db)
                sources.review_sources(db, batch={
                    "contract_version": 4, "request_id": fx.request_id(), "packet_id": packet["packet_id"],
                    "edits": [edit("create", "source_reviews", "srv_context", {
                        "source_refs": [fx.pin(db, "sources", fx.source_id),
                                        fx.pin(db, "sources", source_ids["context.tex"])],
                        "anchor_refs": [fx.pin(db, "anchors", name) for name in
                                        ("anc_lem_proof", "anc_context", "anc_unrelated")],
                        "purpose": "proof_boundary", "decision": "accepted",
                        "rationale": "The lemma has a final structural continuation; another passage is separate.",
                        "reviewer": "coord"})]})
                boundary = db.head("proof_boundaries", "bnd_lem")
                fx.apply(db, [
                    edit("replace", "proof_boundaries", boundary.id, dict(boundary.body,
                        anchor_refs=boundary.body["anchor_refs"] + [fx.pin(db, "anchors", "anc_context")],
                        source_review_ref=fx.pin(db, "source_reviews", "srv_context")), boundary.version),
                    edit("create", "coverage", "cov_context", {
                        "argument_id": "arg_lem", "anchor_id": "anc_context", "start_offset": 0,
                        "end_offset": len(db.head("anchors", "anc_context").body["excerpt"]),
                        "classification": "structural", "claim_refs": [], "check_ids": [],
                        "note": "End of the written proof."})])
            else:
                raise AssertionError(kind)
        fx.complete()
        with fx.open() as db:
            self.assertTrue(assessment.derive_assessment(db, audit_id=fx.audit_id)["progress"]["process_complete"])
        return fx, source_ids

    def issue(self, fx, source_id, *, anchor_id="anc_context", issue_id="sis_context"):
        with fx.open() as db:
            packet = fx.packet(db)
            sources.review_sources(db, batch={
                "contract_version": 4, "request_id": fx.request_id(), "packet_id": packet["packet_id"],
                "edits": [edit("create", "source_issues", issue_id, {
                    "source_id": source_id, "anchor_id": anchor_id, "category": "locator_limit",
                    "description": "The captured context needs a source-boundary clarification.",
                    "lifecycle": "open", "resolution": None, "reviewer": "coord"})]})

    def assert_context_blocks(self, fx):
        with fx.open() as db:
            result = assessment.derive_assessment(db, audit_id=fx.audit_id)
            self.assertFalse(result["progress"]["process_complete"])
            self.assertEqual(result["source_limits"], [fx.pin(db, "source_issues", "sis_context")])
            report = projection.build_projection(db, audit_id=fx.audit_id)
            self.assertEqual(report["summary"]["source_limits"], ["sis_context"])
            self.assertEqual(len(report["summary"]["factual"]["source_limits"]), 1)
        output = fx.root / "blocked-release"
        receipt, _ = run_cli("release", fx.path, "--audit", fx.audit_id, "--out", output, expect=2)
        self.assertEqual(receipt["error"]["code"], "RELEASE_BLOCKED")
        self.assertFalse(output.exists())

    def test_inherited_scope_issue_blocks_report_and_release_until_resolved(self):
        fx, source_ids = self.context_fixture("scope")
        with fx.open() as db:
            before = assessment.derive_assessment(db, audit_id=fx.audit_id)
        self.issue(fx, source_ids["context.tex"])
        self.assert_context_blocks(fx)
        if node_available():
            output = fx.root / "working.html"
            run_cli("checkpoint", fx.path, "--audit", fx.audit_id, "--out", output)
            visible = re.sub(r'<script\b[^>]*>.*?</script>', "", output.read_text(encoding="utf-8"), flags=re.S)
            self.assertIn("The captured context needs a source-boundary clarification.", visible)
            self.assertIn('data-proof-source-limit="sis_context"', visible)
        with fx.open() as db:
            after = assessment.derive_assessment(db, audit_id=fx.audit_id)
            self.assertEqual(after["assessments"], before["assessments"])
            issue = db.head("source_issues", "sis_context")
            packet = fx.packet(db)
            sources.review_sources(db, batch={
                "contract_version": 4, "request_id": fx.request_id(), "packet_id": packet["packet_id"],
                "edits": [edit("replace", "source_issues", issue.id, dict(issue.body,
                    lifecycle="resolved", resolution="The surrounding setup was reviewed."), issue.version)]})
            resolved = assessment.derive_assessment(db, audit_id=fx.audit_id)
            self.assertTrue(resolved["progress"]["process_complete"])
            self.assertEqual(resolved["source_limits"], [])
            self.assertEqual(projection.build_projection(db, audit_id=fx.audit_id)["summary"]["source_limits"], [])
        if node_available():
            output = fx.root / "resolved-release"
            receipt, _ = run_cli("release", fx.path, "--audit", fx.audit_id, "--out", output)
            self.assertTrue(receipt["process_complete"])
            self.assertEqual(receipt["publication"]["state"], "published")
            self.assertTrue((output / "report.html").is_file())

    def test_exact_target_only_evidence_limits_the_focused_audit(self):
        fx, source_ids = self.context_fixture("exact_target")
        self.issue(fx, source_ids["context.tex"])
        self.assert_context_blocks(fx)

    def test_extra_reviewed_boundary_segment_limits_the_focused_audit(self):
        fx, source_ids = self.context_fixture("boundary")
        self.issue(fx, source_ids["context.tex"])
        self.assert_context_blocks(fx)

    def test_source_wide_issue_on_consumed_context_limits_the_focused_audit(self):
        fx, source_ids = self.context_fixture("scope")
        self.issue(fx, source_ids["context.tex"], anchor_id=None)
        self.assert_context_blocks(fx)

    def test_unrelated_anchor_and_source_do_not_limit_a_focused_audit(self):
        fx, source_ids = self.context_fixture("boundary")
        self.issue(fx, source_ids["context.tex"], anchor_id="anc_unrelated", issue_id="sis_other_anchor")
        self.issue(fx, source_ids["unrelated.tex"], anchor_id=None, issue_id="sis_other_source")
        with fx.open() as db:
            result = assessment.derive_assessment(db, audit_id=fx.audit_id)
            self.assertTrue(result["progress"]["process_complete"])
            self.assertEqual(result["source_limits"], [])
            self.assertEqual(projection.build_projection(db, audit_id=fx.audit_id)["summary"]["source_limits"], [])
