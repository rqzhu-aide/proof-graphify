"""Cross-reference recovery and external evidence keep existing source locks."""
from __future__ import annotations

import contextlib
import copy
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import test_proofcheck as core

pc = core.proofcheck


def tree_bytes(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes()
            for path in root.rglob("*") if path.is_file()}


class ExternalMixedEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.fixture = core.FinalizationTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.root = self.fixture.audit
        with contextlib.redirect_stdout(io.StringIO()):
            ledger = self.fixture.make_complete_audit()
            self.text, _ = self.fixture.install_external_dependency(ledger)
        errors, summaries, _ = pc.audit_ledgers(self.root, True)
        self.assertEqual([], errors)
        self.summaries = {row["unit_id"]: row for row in summaries}
        self.manifest = core.read_json(self.root / "AUDIT_MANIFEST.json")
        self.manifest["protocol"]["challenge_contract_version"] = 3
        core.write_json(self.root / "AUDIT_MANIFEST.json", self.manifest)
        self.registry = core.read_json(self.root / "audit/03_dependencies/DEPENDENCY_REGISTRY.json")
        self.pdf = self.fixture.base / "external-theorem.pdf"
        self.pdf.write_bytes(b"%PDF-1.4\nTheorem 1 on page 1\n%%EOF\n")
        self.pdf_evidence = {"file": str(self.pdf), "sha256": pc.sha256_file(self.pdf),
                             "locator": "Theorem 1, page 1", "role": "authoritative_theorem_source"}

    def closure_errors(self, evidence, spans):
        registry = copy.deepcopy(self.registry)
        result = registry["external_results"][0]
        result["source_evidence"] = evidence
        for binding in result["citation_bindings"]:
            binding["external_identity_sha256"] = pc.external_result_identity_sha256(result)
        use = result["uses"][0]
        use["dependency_contract_sha256"] = pc.canonical_sha256(pc.external_result_contract(result))
        use["prerequisite_map"][0]["source_evidence_spans"] = spans
        before = tree_bytes(self.root)
        errors = []
        pc.validate_dependency_closure(
            registry, self.root, self.summaries,
            source_snapshot_sha256=self.manifest["source_snapshot"]["sha256"],
            inventory_sha256=pc.sha256_file(self.root / "audit/01_index/theorem_inventory.json"),
            in_scope=self.manifest["audit_scope"]["in_scope_units"], errors=errors,
        )
        self.assertEqual(before, tree_bytes(self.root), "Validation must not renew evidence or judgments")
        return errors

    def test_text_and_mixed_sources_both_require_actual_text_hypothesis(self):
        text_evidence = self.registry["external_results"][0]["source_evidence"]
        for evidence in (text_evidence, [*text_evidence, self.pdf_evidence]):
            with self.subTest(evidence_count=len(evidence)):
                errors = self.closure_errors(evidence, [])
                self.assertEqual(1, len(errors), errors)
                self.assertIn("source_evidence_spans must anchor the actual external hypothesis", errors[0])
                self.assertIn("add its locked text span", errors[0])

    def test_current_mixed_text_anchor_and_pdf_only_locator_are_accepted(self):
        text_evidence = self.registry["external_results"][0]["source_evidence"]
        self.assertEqual([], self.closure_errors(
            [*text_evidence, self.pdf_evidence], [pc.locked_span(self.text, 2, 2, self.root)]))
        self.assertEqual([], self.closure_errors([self.pdf_evidence], []))
        # A syntactically readable PDF is still not a textual hypothesis anchor.
        errors = self.closure_errors([*text_evidence, self.pdf_evidence],
                                    [pc.locked_span(self.pdf, 2, 2, self.root)])
        self.assertTrue(any("registered text theorem evidence" in error for error in errors), errors)

    def test_missing_or_changed_mixed_source_still_fails(self):
        evidence = [*self.registry["external_results"][0]["source_evidence"], self.pdf_evidence]
        spans = [pc.locked_span(self.text, 2, 2, self.root)]
        original = self.text.read_bytes()
        self.text.write_bytes(original + b"A changed condition.\n")
        self.assertTrue(any("source drift" in error for error in self.closure_errors(evidence, spans)))
        self.text.unlink()
        self.assertTrue(any(".file does not exist" in error for error in self.closure_errors(evidence, spans)))


class CrossReferenceRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.inputs = self.base / "source inputs"
        self.inputs.mkdir()
        self.paper = self.inputs / "paper.tex"
        self.paper.write_text(
            "\\input{definitions}\n\\begin{lemma}\\label{lem:a}\n$x=x$.\n"
            "\\end{lemma}\n\\begin{proof}\nSee \\ref{eq:supp}.\n\\end{proof}\n",
            encoding="utf-8")
        (self.inputs / "definitions.tex").write_text("\\newtheorem{lemma}{Lemma}\n", encoding="utf-8")
        self.supplement = self.inputs / "supplement.tex"
        self.supplement.write_text("\\begin{equation}\\label{eq:supp}x=x\\end{equation}\n", encoding="utf-8")
        self.root = self.base / "audit"

    def run_command(self, argv):
        args = pc.build_parser().parse_args(argv)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = args.func(args)
        return status, json.loads(output.getvalue())

    def scaffold(self, portable=True):
        argv = ["scaffold", "--paper", str(self.paper), "--input-kind", "latex",
                "--output", str(self.root), "--report-format", "markdown",
                "--additional-source", str(self.supplement), "Supplement establishes equation eq:supp",
                "The lemma explicitly cites eq:supp from this supplement"]
        if portable:
            argv.append("--portable-sources")
        self.assertEqual(0, self.run_command(argv)[0])
        return self.root / "audit/01_index/cross_reference_audit.json", self.root / "audit/01_index/cross_reference_audit.md"

    def refresh(self):
        return self.run_command(["crossref", "--root", str(self.root)])

    def test_portable_pair_restored_after_move_without_touching_reviewed_records(self):
        json_path, md_path = self.scaffold()
        expected = core.read_json(json_path)
        expected_markdown = md_path.read_bytes()
        self.assertEqual("paper.tex", expected["root_file"])
        self.assertIn("eq:supp", expected["labels"])
        before = tree_bytes(self.root)
        json_path.write_text('{}\n', encoding="utf-8")
        md_path.write_text("stale\n", encoding="utf-8")
        moved = self.base / "relocated audit"
        self.root.rename(moved)
        self.root = moved
        shutil.rmtree(self.inputs)
        status, result = self.refresh()
        self.assertEqual(0, status)
        self.assertEqual("refreshed", result["status"])
        self.assertEqual(before, tree_bytes(self.root))
        self.assertEqual(expected, core.read_json(self.root / "audit/01_index/cross_reference_audit.json"))
        self.assertEqual(expected_markdown, (self.root / "audit/01_index/cross_reference_audit.md").read_bytes())
        errors, _ = pc.check_audit_finalization(self.root)
        self.assertFalse(any("cross_reference_audit" in error for error in errors), errors)

    def test_nonportable_recovery_and_standalone_scanner_remain_supported(self):
        json_path, md_path = self.scaffold(portable=False)
        before = tree_bytes(self.root)
        json_path.unlink()
        md_path.unlink()
        self.assertEqual(0, self.refresh()[0])
        self.assertEqual(before, tree_bytes(self.root))
        _, standalone = self.run_command(["crossref", "--file", str(self.paper)])
        self.assertEqual(str(self.paper.resolve()), standalone["root_file"])
        self.assertNotIn("eq:supp", standalone["labels"])

    def test_drift_rejected_without_changing_pair_or_source_locks(self):
        self.scaffold()
        manifest = core.read_json(self.root / "AUDIT_MANIFEST.json")
        paper = pc.resolve_stored_path(manifest["paper_file"], self.root)
        paper.write_bytes(paper.read_bytes() + b"% source revision\n")
        before = tree_bytes(self.root)
        with self.assertRaisesRegex(ValueError, "Source drift in included file"):
            self.refresh()
        self.assertEqual(before, tree_bytes(self.root))

    def test_newly_resolvable_include_is_not_added_to_locked_closure(self):
        self.paper.write_text(self.paper.read_text(encoding="utf-8") + "\\input{late}\n", encoding="utf-8")
        self.scaffold()
        manifest = core.read_json(self.root / "AUDIT_MANIFEST.json")
        paper = pc.resolve_stored_path(manifest["paper_file"], self.root)
        (paper.parent / "late.tex").write_text("\\label{new:claim}\n", encoding="utf-8")
        before = tree_bytes(self.root)
        with self.assertRaisesRegex(ValueError, "Source closure has new or unrecorded files"):
            self.refresh()
        self.assertEqual(before, tree_bytes(self.root))

    def test_portable_transcription_preserves_canonical_warning_and_manual_inventory(self):
        transcription = self.inputs / "transcription.txt"
        transcription.write_text("Page 1: Lemma 1. For every x, x=x.\n", encoding="utf-8")
        publisher = self.inputs / "publisher.pdf"
        publisher.write_bytes(b"%PDF-1.4\npage 1\n%%EOF\n")
        self.run_command([
            "scaffold", "--paper", str(transcription), "--input-kind", "pdf_transcription",
            "--publisher-pdf", str(publisher), "--output", str(self.root),
            "--portable-sources", "--report-format", "markdown",
        ])
        before = tree_bytes(self.root)
        json_path = self.root / "audit/01_index/cross_reference_audit.json"
        data = core.read_json(json_path)
        self.assertIn(pc.PDF_TRANSCRIPTION_WARNING, data["warnings"])
        self.assertEqual("transcription.txt", data["root_file"])
        json_path.write_text('{"invalid":true}\n', encoding="utf-8")
        self.refresh()
        self.assertEqual(before, tree_bytes(self.root))

    def test_failed_second_publication_restores_both_prior_views(self):
        json_path, md_path = self.scaffold()
        json_path.write_text('{}\n', encoding="utf-8")
        md_path.write_text("old Markdown\n", encoding="utf-8")
        before = tree_bytes(self.root)
        replace = pc.os.replace
        publications = 0

        def fail_second(source, target):
            nonlocal publications
            if Path(target) in (json_path, md_path):
                publications += 1
                if publications == 2:
                    raise OSError("injected second publication failure")
            return replace(source, target)

        with mock.patch.object(pc.os, "replace", side_effect=fail_second):
            with self.assertRaisesRegex(OSError, "injected second publication"):
                self.refresh()
        self.assertEqual(before, tree_bytes(self.root))

    def test_concurrent_source_change_prevents_publication(self):
        self.scaffold()
        manifest = core.read_json(self.root / "AUDIT_MANIFEST.json")
        paper = pc.resolve_stored_path(manifest["paper_file"], self.root)
        before = tree_bytes(self.root)
        transaction = pc.transactional_write_texts

        def change_before_commit(*args, **kwargs):
            paper.write_bytes(paper.read_bytes() + b"% concurrent source revision\n")
            return transaction(*args, **kwargs)

        with mock.patch.object(pc, "transactional_write_texts", side_effect=change_before_commit):
            with self.assertRaisesRegex(ValueError, "Transactional baseline changed before commit"):
                self.refresh()
        after = tree_bytes(self.root)
        changed = [path for path in before if before[path] != after[path]]
        self.assertEqual([paper.relative_to(self.root).as_posix()], changed)
        self.assertEqual(set(before), set(after))

    def test_stale_diagnostic_names_recovery_and_does_not_renew_finalization(self):
        json_path, _ = self.scaffold()
        json_path.write_text('{}\n', encoding="utf-8")
        errors, _ = pc.check_audit_finalization(self.root)
        self.assertTrue(any('cross_reference_audit.json is stale' in error and
                            f'crossref --root "{self.root}"' in error for error in errors), errors)
        seal = self.root / "FINALIZATION.json"
        seal.write_text('{"preserved_previous_release":"fixture"}\n', encoding="utf-8")
        before = seal.read_bytes()
        self.refresh()
        self.assertEqual(before, seal.read_bytes())

    def test_root_selector_rejects_conflicting_output_before_writes(self):
        self.scaffold()
        before = tree_bytes(self.root)
        for flags in (["--output", str(self.base / "custom.json")], ["--format", "markdown"], ["--force"]):
            with self.subTest(flags=flags):
                with self.assertRaisesRegex(ValueError, "refreshes both canonical files"):
                    self.run_command(["crossref", "--root", str(self.root), *flags])
                self.assertEqual(before, tree_bytes(self.root))


if __name__ == "__main__":
    unittest.main()
