from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import shutil
import unittest
from pathlib import Path


SPEC = importlib.util.spec_from_file_location(
    "semantic_reuse_fixture", Path(__file__).with_name("test_workflow_efficiency.py")
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Cannot load workflow fixture")
workflow = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(workflow)
proofcheck = workflow.proofcheck
read_json = workflow.read_json
write_json = workflow.write_json


class SemanticReuseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = workflow.WorkflowEfficiencyTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.base = self.fixture.base
        self.paper = self.fixture.paper
        self.unrelated = self.base / "unrelated.tex"
        self.unrelated.write_text(
            "\\begin{lemma}\\label{lem:unrelated}\n"
            "For all integers $n$, $n+0=n$.\n"
            "\\end{lemma}\n\\begin{proof}\n"
            "The additive identity gives the claim.\n\\end{proof}\n",
            encoding="utf-8",
        )
        self.shared = self.base / "shared.tex"
        self.shared.write_text(
            "Throughout the paper, all variables are real.\n"
            "\\newcommand{\\domain}{\\mathbb{R}}\n", encoding="utf-8"
        )
        self.paper.write_text(
            self.paper.read_text(encoding="utf-8")
            + "\\input{shared}\n\\input{unrelated}\n", encoding="utf-8"
        )
        prior_root = self.fixture.audit
        self.root = self.base / "semantic reuse audit"
        with contextlib.redirect_stdout(io.StringIO()):
            proofcheck.cmd_scaffold(argparse.Namespace(paper=self.paper, output=self.root))
        (self.root / "audit/07_runtime").mkdir(exist_ok=True)
        shutil.copyfile(
            prior_root / "audit/07_runtime/CALIBRATION.json",
            self.root / "audit/07_runtime/CALIBRATION.json",
        )
        self.fixture.audit = self.root
        self.ledger_path = self.fixture.extract_ledger()

    def packet(self) -> dict:
        return proofcheck.build_context_packet(self.root, "lem:a", "primary")

    def reconcile_source_fixture(self) -> None:
        """Explicitly model source rescan and reviewed registry, never a release seal."""
        manifest_path = self.root / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        files = [proofcheck.resolve_stored_path(row["file"], self.root)
                 for row in manifest["source_snapshot"]["files"]]
        rows = [{"file": proofcheck.relative_or_absolute(path, self.root),
                 "sha256": proofcheck.sha256_file(path)} for path in files]
        manifest["source_snapshot"] = {
            "files": rows, "sha256": proofcheck.canonical_sha256(rows)
        }
        write_json(manifest_path, manifest)
        inventory = proofcheck.scan_formal_units(self.paper, source_files=files)
        write_json(self.root / "audit/01_index/theorem_inventory.json", inventory)
        self.fixture.review_dependency_registry(critical=False)

    def change_unrelated(self) -> None:
        self.unrelated.write_text(
            self.unrelated.read_text(encoding="utf-8").replace(
                "The additive identity gives the claim.",
                "Since adding zero leaves every integer unchanged, the claim follows.",
            ), encoding="utf-8"
        )

    def test_unrelated_included_proof_preserves_work_after_explicit_reconciliation(self) -> None:
        before = self.packet()
        self.change_unrelated()
        with self.assertRaisesRegex(ValueError, "stale source state"):
            self.packet()
        self.reconcile_source_fixture()
        after = self.packet()
        self.assertNotEqual(before["source_snapshot_sha256"], after["source_snapshot_sha256"])
        self.assertEqual(before["work_context_sha256"], after["work_context_sha256"])
        self.assertEqual(
            proofcheck.context_packet_semantic_projection(before),
            proofcheck.context_packet_semantic_projection(after),
        )

    def test_shared_assumption_invalidates_work(self) -> None:
        before = self.packet()
        self.shared.write_text(self.shared.read_text(encoding="utf-8").replace(
            "all variables are real", "all variables are positive real numbers"
        ), encoding="utf-8")
        self.reconcile_source_fixture()
        self.assertNotEqual(before["work_context_sha256"], self.packet()["work_context_sha256"])

    def test_shared_macro_invalidates_work(self) -> None:
        before = self.packet()
        self.shared.write_text(self.shared.read_text(encoding="utf-8").replace(
            "\\mathbb{R}", "\\mathbb{C}"
        ), encoding="utf-8")
        self.reconcile_source_fixture()
        self.assertNotEqual(before["work_context_sha256"], self.packet()["work_context_sha256"])

    def test_formal_shared_assumption_and_definition_invalidate_work(self) -> None:
        for environment in ("assumption", "definition"):
            with self.subTest(environment=environment):
                self.shared.write_text(
                    f"\\begin{{{environment}}}\nAll variables lie in R.\n\\end{{{environment}}}\n",
                    encoding="utf-8")
                self.reconcile_source_fixture()
                before = self.packet()
                self.shared.write_text(self.shared.read_text(encoding="utf-8").replace(
                    "lie in R", "lie in the positive part of R"
                ), encoding="utf-8")
                self.reconcile_source_fixture()
                self.assertNotEqual(before["work_context_sha256"], self.packet()["work_context_sha256"])

    def test_macro_inside_an_unrelated_proof_still_invalidates_work(self) -> None:
        self.unrelated.write_text(self.unrelated.read_text(encoding="utf-8").replace(
            "The additive identity gives the claim.", "\\gdef\\domain{\\mathbb{R}}"
        ), encoding="utf-8")
        self.reconcile_source_fixture()
        before = self.packet()
        self.unrelated.write_text(self.unrelated.read_text(encoding="utf-8").replace(
            "\\mathbb{R}", "\\mathbb{C}"
        ), encoding="utf-8")
        self.reconcile_source_fixture()
        self.assertNotEqual(before["work_context_sha256"], self.packet()["work_context_sha256"])

    def test_configuration_file_contents_are_in_shared_closure(self) -> None:
        config = self.base / "local.sty"
        config.write_text("\\ProvidesPackage{local}\n\\def\\domain{R}\n", encoding="utf-8")
        members = [(self.paper, {}), (config, {})]
        before = proofcheck.packet_shared_source_context_sha256(self.root, self.paper, members)
        config.write_text("\\ProvidesPackage{local}\n\\def\\domain{C}\n", encoding="utf-8")
        self.assertNotEqual(before, proofcheck.packet_shared_source_context_sha256(self.root, self.paper, members))

    def test_effectful_and_unknown_invocations_invalidate_old_work(self) -> None:
        for first, second in ((r'\selectgood', r'\selectbad'),
                              (r'\indirectgood', r'\indirectbad'),
                              (r'\unknownfirst', r'\unknownsecond')):
            with self.subTest(command=first):
                self.shared.write_text(
                    '\\newcommand{\\selectgood}{\\gdef\\Claim{x=x}}\n'
                    '\\newcommand{\\selectbad}{\\gdef\\Claim{x=x+1}}\n'
                    '\\newcommand{\\indirectgood}{\\selectgood}\n'
                    '\\newcommand{\\indirectbad}{\\selectbad}\n', encoding='utf-8')
                self.unrelated.write_text(
                    '\\begin{lemma}\\label{lem:unrelated}\nFor integers $n$, $n+0=n$.\n'
                    '\\end{lemma}\n\\begin{proof}\n' + first + '\nThe identity proves the claim.\n\\end{proof}\n', encoding='utf-8')
                self.reconcile_source_fixture()
                before = self.packet()
                self.unrelated.write_text(self.unrelated.read_text(encoding='utf-8').replace(first, second), encoding='utf-8')
                self.reconcile_source_fixture()
                self.assertNotEqual(before['work_context_sha256'], self.packet()['work_context_sha256'])

    def test_unknown_command_multiline_argument_is_not_excluded(self) -> None:
        self.unrelated.write_text(
            '\\begin{lemma}\\label{lem:unrelated}\nFor integers $n$, $n+0=n$.\n'
            '\\end{lemma}\n\\begin{proof}\n\\setclaim{\nx=x\n}\n\\end{proof}\n', encoding='utf-8')
        self.reconcile_source_fixture()
        before = self.packet()
        self.unrelated.write_text(self.unrelated.read_text(encoding='utf-8').replace('x=x', 'x=x+1'), encoding='utf-8')
        self.reconcile_source_fixture()
        self.assertNotEqual(before['work_context_sha256'], self.packet()['work_context_sha256'])

    def test_active_characters_cannot_hide_changes_in_plain_unrelated_text(self) -> None:
        self.shared.write_text(
            '\\catcode`\\!=13\n\\catcode`\\?=13\n'
            '\\gdef!{\\gdef\\Claim{x=x}}\n\\gdef?{\\gdef\\Claim{x=x+1}}\n', encoding='utf-8')
        self.unrelated.write_text(
            '\\begin{lemma}\\label{lem:unrelated}\nFor integers $n$, $n+0=n$.\n'
            '\\end{lemma}\n\\begin{proof}\n!\n\\end{proof}\n', encoding='utf-8')
        self.reconcile_source_fixture()
        before = self.packet()
        self.unrelated.write_text(self.unrelated.read_text(encoding='utf-8').replace('\n!\n', '\n?\n'), encoding='utf-8')
        self.reconcile_source_fixture()
        self.assertNotEqual(before['work_context_sha256'], self.packet()['work_context_sha256'])

    def test_redefined_label_and_unresolved_style_effects_disable_plain_exclusion(self) -> None:
        for declaration in (
            '\\renewcommand{\\label}[1]{\\csname#1\\endcsname}\n',
            '\\AddToHook{env/proof/begin}{\\setclaimfrombody}\n',
            '\\usepackage{possibly-active-characters}\n',
        ):
            with self.subTest(declaration=declaration):
                self.shared.write_text(declaration, encoding='utf-8')
                self.reconcile_source_fixture()
                before = self.packet()
                self.change_unrelated()
                self.reconcile_source_fixture()
                self.assertNotEqual(before['work_context_sha256'], self.packet()['work_context_sha256'])
                self.unrelated.write_text(self.unrelated.read_text(encoding='utf-8').replace(
                    'Since adding zero leaves every integer unchanged, the claim follows.',
                    'The additive identity gives the claim.'), encoding='utf-8')

    def test_unreadable_shared_configuration_still_binds_every_byte(self) -> None:
        config = self.base / "unreadable.sty"
        config.write_bytes(b"\\ProvidesPackage{local}\n\xff\n")
        members = [(self.paper, {}), (config, {})]
        before = proofcheck.packet_shared_source_context_sha256(self.root, self.paper, members)
        config.write_bytes(b"\\ProvidesPackage{local}\n\xfe\n")
        self.assertNotEqual(before, proofcheck.packet_shared_source_context_sha256(self.root, self.paper, members))

    def test_old_primary_packet_compiles_after_unrelated_source_reconciliation(self) -> None:
        old_packet = self.base / "lem-a primary context.json"
        annotations = self.base / "lem-a.annotations.json"
        skeleton = self.ledger_path.with_name("lem-a.skeleton.json")
        original = read_json(self.ledger_path)
        self.ledger_path.rename(self.base / "previous-ledger.json")
        self.change_unrelated()
        self.reconcile_source_fixture()
        with contextlib.redirect_stdout(io.StringIO()):
            proofcheck.cmd_compile_annotations(argparse.Namespace(
                ledger=skeleton, annotations=annotations, packet=old_packet,
                output=self.ledger_path, force=False,
            ))
        compiled = read_json(self.ledger_path)
        self.assertEqual(original["steps"], compiled["steps"])
        self.assertEqual(original["work_context_sha256"], compiled["work_context_sha256"])

    def test_old_primary_packet_rejects_shared_semantic_change(self) -> None:
        old_packet = self.base / "lem-a primary context.json"
        skeleton = self.ledger_path.with_name("lem-a.skeleton.json")
        self.ledger_path.rename(self.base / "previous-ledger.json")
        self.shared.write_text("All variables are now required to be positive.\n", encoding="utf-8")
        self.reconcile_source_fixture()
        with self.assertRaisesRegex(ValueError, "semantic context is stale"):
            proofcheck.validate_current_primary_packet(read_json(skeleton), skeleton, old_packet)

    def test_earlier_effectful_call_rejects_old_annotations_for_later_claim(self) -> None:
        prior_root = self.root
        self.paper.write_text(
            '\\begin{lemma}\\label{lem:a}\nFor every real $x$, $\\Claim$.\n'
            '\\end{lemma}\n\\begin{proof}\nThe claim follows by reflexivity.\n\\end{proof}\n', encoding='utf-8')
        self.shared.write_text(
            '\\newcommand{\\Claim}{x=x}\n'
            '\\newcommand{\\selectgood}{\\gdef\\Claim{x=x}}\n'
            '\\newcommand{\\selectbad}{\\gdef\\Claim{x=x+1}}\n', encoding='utf-8')
        self.unrelated.write_text(
            '\\begin{lemma}\\label{lem:unrelated}\nFor integers $n$, $n+0=n$.\n'
            '\\end{lemma}\n\\begin{proof}\n\\selectgood The identity proves the claim.\n\\end{proof}\n', encoding='utf-8')
        wrapper = self.base / 'earlier-effect.tex'
        wrapper.write_text('\\input{shared}\n\\input{unrelated}\n\\input{' + self.paper.name + '}\n', encoding='utf-8')
        self.root = self.base / 'earlier effect audit'
        (self.base / 'lem-a primary context.json').rename(self.base / 'setup-primary-context.json')
        with contextlib.redirect_stdout(io.StringIO()):
            proofcheck.cmd_scaffold(argparse.Namespace(paper=wrapper, output=self.root))
            (self.root / 'audit/07_runtime').mkdir(exist_ok=True)
            shutil.copyfile(prior_root / 'audit/07_runtime/CALIBRATION.json', self.root / 'audit/07_runtime/CALIBRATION.json')
            self.fixture.audit = self.root
            self.ledger_path = self.fixture.extract_ledger()
        self.paper = wrapper
        before = self.packet()
        self.unrelated.write_text(self.unrelated.read_text(encoding='utf-8').replace('\\selectgood', '\\selectbad'), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'stale source state'):
            self.packet()
        self.reconcile_source_fixture()
        self.assertNotEqual(before['work_context_sha256'], self.packet()['work_context_sha256'])
        self.ledger_path.rename(self.base / 'prior-effect-ledger.json')
        with self.assertRaisesRegex(ValueError, 'semantic context is stale'):
            proofcheck.cmd_compile_annotations(argparse.Namespace(
                ledger=self.ledger_path.with_name('lem-a.skeleton.json'),
                annotations=self.base / 'lem-a.annotations.json',
                packet=self.base / 'lem-a primary context.json', output=self.ledger_path, force=False))
        self.assertFalse(self.ledger_path.exists())

    def test_changed_prerequisite_conclusion_invalidates_dependent_work(self) -> None:
        spec = importlib.util.spec_from_file_location("reuse_dependency_fixture", Path(__file__).with_name("test_proofcheck.py"))
        core = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(core)
        fixture = core.FinalizationTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        with contextlib.redirect_stdout(io.StringIO()):
            ledger = fixture.make_complete_audit()
            prior_path, _ = fixture.install_internal_dependency(ledger)
        before = proofcheck.build_context_packet(fixture.audit, "lem:main", "primary")
        prior = read_json(prior_path)
        prior["obligation"]["conclusions"][0]["claim"] = "Equality is reflexive on the positive real numbers"
        write_json(prior_path, prior)
        registry_path = fixture.audit / "audit/03_dependencies/DEPENDENCY_REGISTRY.json"
        registry = read_json(registry_path)
        registry["internal_uses"][0]["dependency_conclusion"] = prior["obligation"]["conclusions"][0]["claim"]
        registry["internal_uses"][0]["dependency_contract_sha256"] = proofcheck.canonical_sha256(
            proofcheck.conclusion_contract_payload(prior["obligation"], "C001")
        )
        write_json(registry_path, registry)
        with self.assertRaisesRegex(ValueError, "dependency ledger is not locally final"):
            proofcheck.build_context_packet(fixture.audit, "lem:main", "primary")

    def test_an_unrelated_region_in_the_same_file_preserves_work(self) -> None:
        self.paper.write_text(self.paper.read_text(encoding="utf-8") +
            "\\begin{lemma}\\label{lem:second}\nFor real $y$, $y+0=y$.\n"
            "\\end{lemma}\n\\begin{proof}\nThe identity proves the claim.\n\\end{proof}\n",
            encoding="utf-8")
        self.reconcile_source_fixture()
        before = self.packet()
        self.paper.write_text(self.paper.read_text(encoding="utf-8").replace(
            "The identity proves the claim.", "Adding zero proves the claim."
        ), encoding="utf-8")
        self.reconcile_source_fixture()
        after = self.packet()
        self.assertNotEqual(before["source"]["proof"]["source_member"]["file_sha256"],
                            after["source"]["proof"]["source_member"]["file_sha256"])
        self.assertEqual(before["work_context_sha256"], after["work_context_sha256"])
        self.assertEqual(proofcheck.context_packet_semantic_projection(before),
                         proofcheck.context_packet_semantic_projection(after))

    def test_partial_judgments_resume_after_unrelated_edit(self) -> None:
        ledger = read_json(self.ledger_path)
        step = next(step for step in reversed(ledger["steps"]) if step.get("status") != "non_substantive")
        step["status"] = "not_checked"
        ledger["review"]["conclusion_results"][0]["statement_status"] = "not_assessed"
        ledger["review"]["unit_status"] = "not_checked"
        write_json(self.ledger_path, ledger)
        before = self.packet()
        self.assertTrue(before["resume"]["wip"]["included"])
        self.change_unrelated()
        self.reconcile_source_fixture()
        after = self.packet()
        self.assertTrue(after["resume"]["wip"]["included"])
        self.assertEqual(before["resume"]["wip"]["semantic_record"], after["resume"]["wip"]["semantic_record"])

    def test_initial_challenge_survives_unrelated_snapshot_but_needs_current_binding(self) -> None:
        packet = proofcheck.build_context_packet(self.root, "lem:a", "challenge")
        packet_path, response_path = self.base / "challenge.json", self.base / "response.json"
        write_json(packet_path, packet)
        write_json(response_path, {
            "response_schema_version": 2, "unit_id": "lem:a",
            "independence_level": "fresh_context_same_model", "challenger_verdict": "verified",
            "conclusions": [{"conclusion_id": "C001", "verdict": "verified",
                "argument_status": "valid", "statement_status": "established",
                "decisive_reason": "Reflexivity on proof line 5 establishes x=x for the arbitrary real variable.",
                "source_refs": [{"packet_pointer": "/source/proof", "start_line": 5, "end_line": 5}]}],
            "issue_assessments": [],
        })
        with contextlib.redirect_stdout(io.StringIO()):
            proofcheck.cmd_record_challenge(argparse.Namespace(
                root=self.root, unit_id="lem:a", packet=packet_path, response=response_path))
        _, before_ref, errors = proofcheck.load_initial_challenge(self.root, "lem:a", packet)
        self.assertEqual([], errors)
        self.change_unrelated()
        self.reconcile_source_fixture()
        current = proofcheck.build_context_packet(self.root, "lem:a", "challenge")
        _, after_ref, errors = proofcheck.load_initial_challenge(self.root, "lem:a", current)
        self.assertEqual([], errors)
        self.assertEqual(before_ref, after_ref)
        self.assertNotEqual(packet["context_binding_sha256"], current["context_binding_sha256"])


if __name__ == "__main__":
    unittest.main()
