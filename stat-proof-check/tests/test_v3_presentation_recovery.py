"""Phase 3 recovery keeps publication outcomes and visible scope truthful."""
import json
import re
import unittest
from pathlib import Path
from unittest import mock

from support import PROOFCHECK, TempCase, node_available, run_wrapper, sha
from paper_core import finalization, publish, staging
from paper_core.errors import PublicationError


@unittest.skipUnless(node_available(), "existing global Node.js is unavailable")
class PresentationRecoveryTests(TempCase):
    WORKING_LIMIT = "This working report does not establish completion of the promised audit scope."

    def frozen(self, name="case"):
        fixture = self.fixture(name).audit(independent_required=False).primary()
        bundle = self.path(name + "-frozen")
        with fixture.open(write=False) as db:
            finalization.finalize_audit(db, audit_id=fixture.audit_id, output=bundle)
        return fixture, bundle

    def science(self, fixture, bundle):
        paths = [fixture.path, *fixture.source_root.rglob("*"), *bundle.iterdir()]
        return {str(path): sha(path.read_bytes()) for path in paths if path.is_file()}

    def prior_pair(self, bundle, name="report.html"):
        output = self.path(name)
        result = publish.publish_frozen(bundle, output=output)
        receipt = Path(result["build_receipt_path"])
        self.assert_published_pair(result)
        return output, receipt, (output.read_bytes(), receipt.read_bytes())

    def assert_published_pair(self, result):
        saved = json.loads(Path(result["build_receipt_path"]).read_text(encoding="utf-8"))
        self.assertEqual("published", result["state"])
        self.assertEqual(result["receipt"], saved)
        self.assertEqual(result["artifact_sha256"], sha(Path(result["output_path"]).read_bytes()))
        self.assertEqual(result["artifact_sha256"], saved["artifact_sha256"])
        self.assertEqual(saved["artifact_sha256"], saved["renderer"]["artifact_sha256"])
        self.assertEqual(result["snapshot_sha256"], saved["snapshot_sha256"])
        self.assertEqual("pass", saved["renderer"]["python_acceptance"]["status"])

    def assert_retained(self, error, output, receipt, prior):
        self.assertEqual("PUBLICATION_FAILED", error.code)
        self.assertTrue(error.records[-1]["prior_output_retained"])
        self.assertTrue(error.records[-1]["prior_receipt_retained"])
        self.assertEqual(prior, (output.read_bytes(), receipt.read_bytes()))

    def test_cleanup_error_after_real_commits_is_success_with_warning(self):
        fixture, bundle = self.frozen()
        output, receipt, prior = self.prior_pair(bundle)
        saved_science = self.science(fixture, bundle)
        with mock.patch.object(staging, "_cleanup", side_effect=PermissionError("cleanup denied")), \
             mock.patch.object(publish, "render_payload", wraps=publish.render_payload) as render:
            result = publish.publish_frozen(bundle, output=output)
        self.assertEqual(1, render.call_count)
        self.assert_published_pair(result)
        self.assertNotEqual(prior[1], receipt.read_bytes(), "a new matching receipt was committed")
        warnings = [row for row in result["warnings"] if row["code"] == "REPORT_CLEANUP_FAILED"]
        self.assertEqual(1, len(warnings))
        self.assertIn("cleanup denied", warnings[0]["details"])
        self.assertEqual(saved_science, self.science(fixture, bundle))

    def test_actual_renderer_failure_keeps_prior_pair_without_retry(self):
        fixture, bundle = self.frozen()
        output, receipt, prior = self.prior_pair(bundle)
        saved_science = self.science(fixture, bundle)
        broken_renderer = self.path("broken-renderer.mjs")
        broken_renderer.write_text('console.error(JSON.stringify({error:"injected renderer failure"}));\n'
                                   'process.exit(7);\n', encoding="utf-8")
        with mock.patch.object(publish, "RENDERER", broken_renderer), \
             mock.patch.object(publish, "render_payload", wraps=publish.render_payload) as render:
            with self.assertRaises(PublicationError) as caught:
                publish.publish_frozen(bundle, output=output)
        self.assertEqual(1, render.call_count)
        self.assert_retained(caught.exception, output, receipt, prior)
        self.assertEqual(saved_science, self.science(fixture, bundle))

    def test_rendered_content_loss_gives_local_repair_hint_and_keeps_prior_pair(self):
        fixture, bundle = self.frozen()
        output, receipt, prior = self.prior_pair(bundle)
        saved_science = self.science(fixture, bundle)
        original = publish.mechanical_acceptance

        def omit_statement(page, projection, *, build=None):
            pattern = (r'(<(?P<tag>span|div)\b[^>]*data-scientific-ref="items:itm_lem:\d+"'
                       r'[^>]*data-scientific-path="\[&quot;statement&quot;,&quot;text&quot;\]"[^>]*>)'
                       r'(.*?)(</(?P=tag)>)')
            altered, count = re.subn(pattern, lambda match: match[1] + match[4], page.decode("utf-8"),
                                     count=1, flags=re.S)
            self.assertEqual(1, count, "the control must remove one actual scientific display field")
            return original(altered.encode("utf-8"), projection, build=build)

        with mock.patch.object(publish, "mechanical_acceptance", side_effect=omit_statement), \
             mock.patch.object(publish, "render_payload", wraps=publish.render_payload) as render:
            with self.assertRaisesRegex(PublicationError, "mechanical acceptance failed") as caught:
                publish.publish_frozen(bundle, output=output)
        self.assertEqual(1, render.call_count)
        self.assert_retained(caught.exception, output, receipt, prior)
        hint = caught.exception.records[-1]["next_step"].lower()
        self.assertIn("render", hint)
        self.assertIn("same frozen", hint)
        self.assertEqual(saved_science, self.science(fixture, bundle))

    def test_receipt_commit_failure_restores_real_prior_pair_without_retry(self):
        fixture, bundle = self.frozen()
        output, receipt, prior = self.prior_pair(bundle)
        saved_science = self.science(fixture, bundle)
        replace = publish._replace_file

        def fail_receipt(staged, destination):
            if destination == receipt:
                raise PermissionError("receipt commit denied")
            return replace(staged, destination)

        with mock.patch.object(publish, "_replace_file", side_effect=fail_receipt), \
             mock.patch.object(publish, "render_payload", wraps=publish.render_payload) as render:
            with self.assertRaises(PublicationError) as caught:
                publish.publish_frozen(bundle, output=output)
        self.assertEqual(1, render.call_count)
        self.assert_retained(caught.exception, output, receipt, prior)
        self.assertIn("receipt commit denied", str(caught.exception))
        self.assertEqual(saved_science, self.science(fixture, bundle))

    def test_failed_html_restore_does_not_claim_existing_new_bytes_were_retained(self):
        fixture, bundle = self.frozen()
        output, receipt, prior = self.prior_pair(bundle)
        saved_science = self.science(fixture, bundle)
        replace, restore = publish._replace_file, publish._restore_output

        def fail_receipt(staged, destination):
            if destination == receipt:
                raise PermissionError("receipt commit denied")
            return replace(staged, destination)

        def fail_html_restore(path, backup, existed):
            if path == output:
                raise PermissionError("HTML restore denied")
            return restore(path, backup, existed)

        with mock.patch.object(publish, "now_iso", return_value="2099-01-01T00:00:00Z"), \
             mock.patch.object(publish, "_replace_file", side_effect=fail_receipt), \
             mock.patch.object(publish, "_restore_output", side_effect=fail_html_restore):
            with self.assertRaises(PublicationError) as caught:
                publish.publish_frozen(bundle, output=output)
        self.assertTrue(output.exists())
        self.assertNotEqual(prior[0], output.read_bytes())
        self.assertEqual(prior[1], receipt.read_bytes())
        self.assertFalse(caught.exception.records[-1]["prior_output_retained"])
        self.assertTrue(caught.exception.records[-1]["prior_receipt_retained"])
        self.assertIn("receipt commit denied", str(caught.exception))
        self.assertTrue(any("HTML restore denied" in note for note in caught.exception.__notes__))
        self.assertEqual(saved_science, self.science(fixture, bundle))

    def test_public_cli_reports_bad_output_parent_then_reuses_unchanged_bundle(self):
        fixture, bundle = self.frozen()
        saved_science = self.science(fixture, bundle)
        bad_parent = self.path("parent-is-a-file")
        bad_parent.write_bytes(b"keep this file")
        failed, stderr = run_wrapper(PROOFCHECK, "stage3", "build", bundle,
                                     "--out", bad_parent / "report.html", expect=6)
        self.assertEqual("OUTPUT_PATH_FAILED", failed["error"]["code"])
        self.assertNotIn("Traceback", stderr)
        self.assertNotIn("INTERNAL", stderr)
        diagnostic = json.dumps(failed["error"]).lower()
        self.assertIn("director", diagnostic)
        self.assertIn("same frozen", diagnostic)
        self.assertEqual(b"keep this file", bad_parent.read_bytes())
        self.assertEqual(saved_science, self.science(fixture, bundle))
        built, _ = run_wrapper(PROOFCHECK, "stage3", "build", bundle,
                               "--out", self.path("valid-parent", "report.html"))
        self.assert_published_pair(built)
        self.assertEqual(saved_science, self.science(fixture, bundle))

    def test_explicit_partial_keeps_registered_completion_and_promised_scope_distinct(self):
        fixture = self.fixture().audit(independent_required=False).primary()
        database_hash = sha(fixture.path.read_bytes())
        for partial, kind in ((True, "working"), (False, "release")):
            with self.subTest(kind=kind):
                bundle = self.path(kind + "-frozen")
                args = ["stage2", "finalize", fixture.path, "--audit", fixture.audit_id, "--out", bundle]
                if partial:
                    args.append("--partial")
                frozen, _ = run_wrapper(PROOFCHECK, *args)
                self.assertEqual(kind, frozen["kind"])
                self.assertTrue(frozen["process_complete"])
                self.assertEqual([], frozen["finalization_blockers"])
                saved_science = self.science(fixture, bundle)
                built, _ = run_wrapper(PROOFCHECK, "stage3", "build", bundle,
                                       "--out", self.path(kind + ".html"))
                self.assert_published_pair(built)
                page = Path(built["output_path"]).read_text(encoding="utf-8")
                patterns = (r'<section\b[^>]*data-reader-report-state\b[^>]*>.*?</section>',
                            r'<p\b[^>]*data-proof-process-complete="true"[^>]*>.*?</p>')
                for pattern in patterns:
                    section = re.search(pattern, page, re.S)
                    self.assertIsNotNone(section)
                    self.assertIn("Registered examinations complete.", section[0])
                    self.assertNotIn("Required examinations complete.", section[0])
                    self.assertEqual(partial, self.WORKING_LIMIT in section[0])
                    if partial:
                        altered = page[:section.start()] + section[0].replace(self.WORKING_LIMIT, "", 1) + page[section.end():]
                        snapshot, _ = finalization.load_finalization(bundle)
                        accepted = publish.mechanical_acceptance(altered.encode("utf-8"), snapshot["projection"],
                                                                 build={"kind": snapshot["kind"]})
                        self.assertEqual("fail", accepted["status"], "each visible working limitation is required")
                self.assertEqual(saved_science, self.science(fixture, bundle))
        self.assertEqual(database_hash, sha(fixture.path.read_bytes()))


if __name__ == "__main__":
    unittest.main()
