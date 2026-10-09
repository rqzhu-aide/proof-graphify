from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HERE = Path(__file__).resolve().parent
fixtures = load("reconciliation_fixture", HERE / "test_challenge_evidence.py")
submission = load("reconciliation_submission", HERE.parent / "scripts/proofcheck_reconcile.py")
pc = fixtures.proofcheck
read = fixtures.read_json
write = fixtures.write_json


class ReconciliationSubmissionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ExplicitJudgmentTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.ledger = self.fixture.ledger_path
        self.review_path = self.fixture.base / "reconciliation.json"

    def prepare(self, verdict="verified"):
        initial, ref = self.fixture.record(self.fixture.response(verdict))
        response = self.fixture.response()
        review = {"reconciliation_schema_version": 1, "unit_id": "lem:a", "status": "agreed",
                  "reconciled_verdict": "verified", "conclusions": response["conclusions"],
                  "disagreements": [], "resolution": "", "issue_assessments": []}
        if verdict != "verified":
            review.update(status="resolved", disagreements=["The original reviewer regarded reflexivity as needing an external theorem."],
                          resolution="Proof line 5 is the reflexive identity for every real x, requiring no external theorem.")
        write(self.review_path, review)
        return review, ref

    def submit(self, *, cli=False):
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            if cli:
                args = pc.build_parser().parse_args(["submit-reconciliation", "--root", str(self.root), "--review", str(self.review_path)])
                result = args.func(args)
            else:
                result = submission.cmd_submit_reconciliation(argparse.Namespace(root=self.root, review=self.review_path), vars(pc))
        self.assertEqual(0, result)
        return json.loads(stream.getvalue())

    def test_agreement_preserves_initial_and_primary_and_is_idempotent(self):
        _, ref = self.prepare()
        original = (self.root / ref["artifact"]).read_bytes()
        primary = pc.primary_challenge_snapshot(read(self.ledger))
        receipt = self.submit(cli=True)
        check = read(self.ledger)["independent_check"]
        self.assertEqual("agreed", check["status"])
        self.assertEqual([], pc.challenge_semantic_freshness_errors(self.root, "lem:a", check, []))
        self.assertEqual([], pc.challenge_artifact_binding_errors(Path(receipt["artifact"]), "lem:a", check))
        self.assertEqual(primary, pc.primary_challenge_snapshot(read(self.ledger)))
        self.assertEqual(original, (self.root / ref["artifact"]).read_bytes())
        before = pc.audit_state_manifest(self.root)
        self.assertEqual("unchanged", self.submit()["status"])
        self.assertEqual(before, pc.audit_state_manifest(self.root))

    def test_resolved_disagreement_preserves_the_different_first_judgment(self):
        _, ref = self.prepare("gap")
        before = (self.root / ref["artifact"]).read_bytes()
        self.submit()
        check = read(self.ledger)["independent_check"]
        self.assertEqual("gap", check["challenger_verdict"])
        self.assertEqual("verified", check["reconciled_verdict"])
        self.assertEqual("resolved", check["status"])
        self.assertEqual(before, (self.root / ref["artifact"]).read_bytes())

    def test_unresolved_never_completes_then_retains_history_on_resolution(self):
        review, ref = self.prepare("gap")
        resolved_review = json.loads(json.dumps(review))
        review.update(status="unresolved", reconciled_verdict="not_checked", resolution="")
        review["conclusions"] = self.fixture.response("gap")["conclusions"]
        write(self.review_path, review)
        receipt = self.submit()
        first_path = Path(receipt["artifact"])
        first_bytes = first_path.read_bytes()
        check = read(self.ledger)["independent_check"]
        self.assertEqual("disagreed", check["status"])
        errors = []
        pc.validate_independent_check(check, True, errors, current_contract=True)
        self.assertTrue(any("agreed or resolved" in e for e in errors), errors)
        self.assertEqual("unchanged", self.submit()["status"])
        write(self.review_path, resolved_review)
        final_path = Path(self.submit()["artifact"])
        self.assertIn(first_path.name, final_path.read_text(encoding="utf-8"))
        self.assertEqual(first_bytes, first_path.read_bytes())
        self.assertEqual(ref, read(self.ledger)["independent_check"]["initial_response"])

    def test_missing_judgment_bad_anchor_and_bad_disagreement_do_not_publish(self):
        review, _ = self.prepare()
        before = pc.audit_state_manifest(self.root)
        for change, expected in (
            (lambda x: x["conclusions"][0].pop("statement_status"), "statement_status"),
            (lambda x: x["conclusions"][0]["source_refs"][0].update(start_line=500), "source lines"),
            (lambda x: x.update(status="resolved"), "disagreements"),
            (lambda x: x.update(conclusions=[]), "every packet conclusion"),
        ):
            with self.subTest(expected=expected):
                changed = json.loads(json.dumps(review))
                change(changed)
                write(self.review_path, changed)
                with self.assertRaisesRegex(ValueError, expected):
                    self.submit()
                self.assertEqual(before, pc.audit_state_manifest(self.root))

    def test_reconciliation_cannot_change_primary_judgment(self):
        review, _ = self.prepare()
        review.update(status="resolved", reconciled_verdict="gap",
                      disagreements=["The reviewer now considers the reflexivity step a proof gap."],
                      resolution="The revised review calls the statement unestablished, but the primary ledger has not been revised.")
        review["conclusions"] = self.fixture.response("gap")["conclusions"]
        write(self.review_path, review)
        before = pc.audit_state_manifest(self.root)
        with self.assertRaisesRegex(ValueError, "revise and validate the primary ledger"):
            self.submit()
        self.assertEqual(before, pc.audit_state_manifest(self.root))

    def test_changed_first_response_cannot_be_restamped(self):
        _, ref = self.prepare()
        path = self.root / ref["artifact"]
        initial = read(path)
        initial["response"]["conclusions"][0]["decisive_reason"] = "Different initial reasoning supplied after reconciliation began."
        write(path, initial)
        before = pc.audit_state_manifest(self.root)
        with self.assertRaisesRegex(ValueError, "the original response cannot be rebound"):
            self.submit()
        self.assertEqual(before, pc.audit_state_manifest(self.root))

    def test_concurrent_change_is_preserved_and_aborts_submission(self):
        self.prepare()
        acquire = pc.acquire_migration_update_lock
        progress_path = self.root / "PROGRESS.json"
        before_ledger = self.ledger.read_bytes()
        def concurrent(root, command):
            progress = read(progress_path)
            progress["next_action"] = "Another reviewer deliberately changed the progress instruction."
            write(progress_path, progress)
            return acquire(root, command)
        with mock.patch.object(pc, "acquire_migration_update_lock", side_effect=concurrent):
            with self.assertRaisesRegex(ValueError, "changed during submission"):
                self.submit()
        self.assertEqual(before_ledger, self.ledger.read_bytes())
        self.assertIn("Another reviewer", read(progress_path)["next_action"])
        self.assertFalse(pc.migration_update_lock_path(self.root).exists())

    def test_failed_second_publication_rolls_back_both_files(self):
        self.prepare()
        before = pc.audit_state_manifest(self.root)
        replace = pc.os.replace
        failed = False
        def fail_once(source, destination):
            nonlocal failed
            if not failed and Path(destination) == self.ledger and str(source).endswith(".tmp"):
                failed = True
                raise OSError("injected ledger publication failure")
            return replace(source, destination)
        with mock.patch.object(pc.os, "replace", side_effect=fail_once):
            with self.assertRaisesRegex(OSError, "injected ledger publication failure"):
                self.submit()
        self.assertEqual(before, pc.audit_state_manifest(self.root))

    def test_stale_source_fails_before_any_publication(self):
        self.prepare()
        source = self.fixture.fixture.paper
        source.write_text(source.read_text(encoding="utf-8") + "\nChanged source.\n", encoding="utf-8")
        before = pc.audit_state_manifest(self.root)
        with self.assertRaises(ValueError):
            self.submit()
        self.assertEqual(before, pc.audit_state_manifest(self.root))

    def test_unresolved_retry_rejects_changed_judgment_or_context(self):
        review, _ = self.prepare("gap")
        review.update(status="unresolved", reconciled_verdict="not_checked", resolution="")
        write(self.review_path, review)
        self.submit()
        original = read(self.ledger)
        for field, value in (("disagreements", ["A different reservation was entered after submission."]),
                             ("status", "agreed"), ("challenge_context_sha256", "0" * 64)):
            with self.subTest(field=field):
                changed = json.loads(json.dumps(original))
                changed["independent_check"][field] = value
                write(self.ledger, changed)
                before = pc.audit_state_manifest(self.root)
                with self.assertRaisesRegex(ValueError, "Existing unresolved"):
                    self.submit()
                self.assertEqual(before, pc.audit_state_manifest(self.root))

    def test_destination_appearing_before_transaction_is_not_overwritten(self):
        self.prepare()
        before = self.ledger.read_bytes()
        transaction = pc.transactional_write_texts
        appeared = []
        def concurrent(writes, **kwargs):
            destination = kwargs["expected_absent"][0]
            destination.write_text("Another publisher's new evidence.\n", encoding="utf-8")
            appeared.append(destination)
            return transaction(writes, **kwargs)
        with mock.patch.object(pc, "transactional_write_texts", side_effect=concurrent):
            with self.assertRaisesRegex(FileExistsError, "already exists"):
                self.submit()
        self.assertEqual(before, self.ledger.read_bytes())
        self.assertEqual("Another publisher's new evidence.\n", appeared[0].read_text(encoding="utf-8"))
        self.assertFalse(pc.migration_update_lock_path(self.root).exists())

    def test_external_evidence_outside_audit_uses_reviewed_hash(self):
        external = self.fixture.base / "external-source.txt"
        external.write_text("Exact external theorem statement.\n", encoding="utf-8")
        digest = pc.sha256_file(external)
        path = self.root / "audit/03_dependencies/DEPENDENCY_REGISTRY.json"
        registry = read(path)
        registry["external_results"] = [{"id": "ext:theorem", "source_evidence": [{"file": str(external), "sha256": digest}]}]
        write(path, registry)
        packet = {"dependencies": {"external_results": [{"id": "ext:theorem", "source_evidence": [{"sha256": digest}]}]}}
        guards = submission.external_evidence_guards(self.root, packet, SimpleNamespace(**vars(pc)))
        self.assertEqual({external: digest}, guards)
        external.write_text("Changed external assumptions.\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "external source differs"):
            submission.external_evidence_guards(self.root, packet, SimpleNamespace(**vars(pc)))


if __name__ == "__main__":
    unittest.main()
