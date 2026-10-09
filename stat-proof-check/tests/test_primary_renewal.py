from __future__ import annotations

import contextlib
import copy
import io
import json
import sys
import unittest
from unittest import mock

import test_compile_annotations as compiler_fixtures
import test_proofcheck as audit_fixtures


proofcheck = compiler_fixtures.proofcheck
read_json = compiler_fixtures.read_json
write_json = compiler_fixtures.write_json


class PrimaryRenewalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = compiler_fixtures.CompileAnnotationsTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.audit = self.fixture.audit
        self.base = self.fixture.base
        self.old_skeleton = self.fixture.ledger
        self.old_ledger = self.fixture.output
        self.skeleton = self.old_skeleton
        self.output = self.old_ledger
        self.packet = self.fixture.packet
        self.annotations_path = self.base / "renewal.annotations.json"
        self.annotations = self.fixture.annotations()
        conclusion = self.annotations["steps"][1]
        conclusion.update(inputs=[], status="gap", issue_ids=["I-001"])
        conclusion["failure"] = {
            "kind": "missing_premise", "issue_id": "I-001",
            "evidence": "The source invokes reflexivity without establishing that its object lies in the required domain.",
        }
        self.annotations["conclusions"][0].update(
            statement_status="not_established", issue_ids=[]
        )
        self.annotations["review"]["source_reference_dispositions"][0].update(
            disposition="unresolved",
            evidence="The failed zero-input audit leaves the source reference unresolved instead of treating it as an established premise.",
        )
        self.write_annotations()
        self.assert_command(0, *self.compile_args())
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        manifest["audit_scope"]["depth"] = "full"
        manifest["audit_scope"]["overall_assessment"] = "defects_found"
        manifest["completion"]["global_consistency_pass"] = {
            "status": "completed",
            "evidence": ["The complete reflexivity fixture has no cross-unit inconsistency."],
            "checks": audit_fixtures.make_global_consistency_checks(),
        }
        write_json(manifest_path, manifest)
        registry_path = self.audit / "audit/03_dependencies/METHOD_INTERFACE_REGISTRY.json"
        registry = read_json(registry_path)
        registry["scope"] = {
            "status": "reviewed", "trigger": "not_required",
            "reason": "The reflexivity fixture has no estimated method interface.",
        }
        write_json(registry_path, registry)
        self.issue_path = self.audit / "audit/06_reports/ISSUE_LOG.json"
        issue = {
            "id": "I-001", "severity": "S2", "confidence": "high",
            "status": "open", "finding_status": "defect", "scope": "unit",
            "load_bearing": True, "affected_result": "lem:compact",
            "affected_results": ["lem:compact"],
            "summary": "The recorded reflexivity move has a missing premise.",
            "origin_ref": {"kind": "ledger_move", "unit_id": "lem:compact",
                           "step_id": "S003", "move_id": "M001"},
            "contract_refs": [{"kind": "conclusion", "unit_id": "lem:compact",
                               "conclusion_id": "C001"}],
            "invalidation_kind": "proof_gap",
            "suggested_changes": [{
                "target_ref": {"kind": "source_span", **proofcheck.locked_span(
                    self.fixture.paper, 5, 5, self.audit)},
                "action": "repair_step", "repair_scope": "local_step",
                "assumption_cost": "none",
                "proposal": "Establish the real-number domain premise before invoking reflexivity.",
                "verification_status": "candidate", "required_rechecks": ["lem:compact"],
            }],
        }
        write_json(self.issue_path, {"schema_version": proofcheck.SCHEMA_VERSION, "issues": [issue]})
        self.history = self.old_skeleton.parent / "history" / "renewal-001"
        self.history.mkdir(parents=True)
        self.old_skeleton.rename(self.history / self.old_skeleton.name)
        self.skeleton = self.old_skeleton.with_name("unit-renewed.skeleton.json")
        self.output = self.skeleton.with_name("unit-renewed.ledger.json")
        self.packet = self.base / "renewal.packet.json"
        self.assert_command(0, "extract", "--file", self.fixture.paper,
                            "--start", "1", "--end", "6",
                            "--statement-file", self.fixture.paper,
                            "--statement-start", "1", "--statement-end", "3",
                            "--unit-id", "lem:compact", "--output", self.skeleton)
        skeleton = read_json(self.skeleton)
        skeleton["obligation"] = copy.deepcopy(read_json(self.old_ledger)["obligation"])
        skeleton["obligation"]["quantifier_scope"] = "For every arbitrary real x."
        write_json(self.skeleton, skeleton)

    def command(self, *arguments):
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.object(sys, "argv", [str(compiler_fixtures.SCRIPT), *map(str, arguments)]), \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            status = proofcheck.main()
        return status, stdout.getvalue(), stderr.getvalue()

    def assert_command(self, expected_status, *arguments):
        status, stdout, stderr = self.command(*arguments)
        self.assertEqual(expected_status, status, stdout + stderr)
        return stdout, stderr

    def packet_args(self, *, mode="primary", renewal=True):
        return ["packet", "--root", self.audit, "--unit-id", "lem:compact",
                "--mode", mode, "--output", self.packet, "--force",
                *(["--for-recompile"] if renewal else [])]

    def compile_args(self):
        return ["compile-annotations", self.skeleton, "--annotations", self.annotations_path,
                "--packet", self.packet, "--output", self.output]

    def write_annotations(self):
        write_json(self.annotations_path, self.annotations)

    def prepare_renewal(self):
        self.assert_command(0, *self.packet_args())
        packet = read_json(self.packet)
        self.annotations["context_binding_sha256"] = packet["context_binding_sha256"]
        self.annotations["obligation_sha256"] = packet["obligation_sha256"]
        self.write_annotations()
        return packet

    def test_own_issue_requires_live_origin_and_explicit_selection_then_renews(self):
        old_bytes = self.old_ledger.read_bytes()
        archived = self.history / self.old_ledger.name
        self.old_ledger.rename(archived)
        _, errors = self.assert_command(2, *self.packet_args())
        self.assertIn("issue target ledger is missing", errors)
        archived.rename(self.old_ledger)

        self.assert_command(0, *self.packet_args(renewal=False))
        ordinary = read_json(self.packet)
        self.assertEqual("canonical_ledger", ordinary["semantic_artifact"]["kind"])
        _, errors = self.assert_command(2, *self.compile_args())
        self.assertIn("does not bind this source-locked skeleton", errors)
        self.assertFalse(self.output.exists())

        renewal = self.prepare_renewal()
        self.assertEqual("source_locked_skeleton", renewal["semantic_artifact"]["kind"])
        self.assertEqual(self.skeleton.relative_to(self.audit).as_posix(),
                         renewal["semantic_artifact"]["audit_relative_file"])
        self.assertEqual(ordinary["issue_triggers"], renewal["issue_triggers"])
        self.assertEqual(ordinary["dependencies"], renewal["dependencies"])
        self.assertNotEqual(read_json(self.old_ledger)["work_context_sha256"],
                            renewal["work_context_sha256"])
        self.assertTrue(renewal["resume"]["ledger_present"])
        self.assert_command(0, *self.compile_args())
        self.assertEqual(old_bytes, self.old_ledger.read_bytes())
        # Preserve the origin until compilation succeeds, then remove it from
        # discovery before another audit command can see duplicate live ledgers.
        self.old_ledger.rename(archived)
        self.assertEqual([self.output], proofcheck.live_local_check_artifacts(self.audit, ".ledger.json"))
        self.assertEqual(old_bytes, archived.read_bytes())
        self.assert_command(0, *self.packet_args(renewal=False))
        current = read_json(self.packet)
        self.assertEqual(renewal["issue_triggers"], current["issue_triggers"])
        self.assertEqual(read_json(self.output)["work_context_sha256"], current["work_context_sha256"])
        stdout, _ = self.assert_command(0, "issues", "--root", self.audit, "--before-challenge")
        self.assertEqual("ready", json.loads(stdout)["readiness"])
        self.assert_command(0, *self.packet_args(mode="challenge", renewal=False))
        _, errors = self.assert_command(1, "finalize", "--root", self.audit)
        self.assertIn("requires an independent challenger pass", errors)
        _, errors = self.assert_command(2, *self.compile_args())
        self.assertIn("cannot be overwritten", errors)

    def test_rechecked_issue_target_can_change_without_staling_its_own_work_context(self):
        renewal = self.prepare_renewal()
        self.annotations["steps"][1]["goal"] = "Recheck the real-number domain premise required to establish x equals x."
        self.write_annotations()
        self.assert_command(0, *self.compile_args())
        self.old_ledger.rename(self.history / self.old_ledger.name)
        self.assert_command(0, *self.packet_args(renewal=False))
        current = read_json(self.packet)
        self.assertNotEqual(renewal["issue_triggers"], current["issue_triggers"])
        self.assertEqual(read_json(self.output)["work_context_sha256"], current["work_context_sha256"])
        self.assert_command(0, "issues", "--root", self.audit, "--before-challenge")

    def test_recompile_flag_rejects_challenge_mode_without_output(self):
        _, errors = self.assert_command(2, *self.packet_args(mode="challenge"))
        self.assertIn("requires --mode primary", errors)
        self.assertFalse(self.packet.exists())

    def test_selection_requires_unique_live_canonical_skeleton(self):
        duplicate = self.skeleton.with_name("duplicate.skeleton.json")
        duplicate.write_bytes(self.skeleton.read_bytes())
        _, errors = self.assert_command(2, *self.packet_args())
        self.assertIn("duplicate source-locked skeletons", errors)
        duplicate.unlink()
        self.skeleton.rename(self.history / self.skeleton.name)
        _, errors = self.assert_command(2, *self.packet_args())
        self.assertIn("exactly one current canonical", errors)

    def test_copied_completed_ledger_is_not_a_fresh_skeleton(self):
        self.skeleton.write_bytes(self.old_ledger.read_bytes())
        _, errors = self.assert_command(2, *self.packet_args())
        self.assertIn("fresh extracted skeleton with empty steps", errors)
        self.assertFalse(self.packet.exists())

    def test_compiler_rejects_skeleton_completed_after_packet_generation(self):
        self.prepare_renewal()
        self.skeleton.write_bytes(self.old_ledger.read_bytes())
        _, errors = self.assert_command(2, *self.compile_args())
        self.assertIn("fresh extracted skeleton with empty steps", errors)
        self.assertFalse(self.output.exists())

    def test_tampered_selection_and_wrong_packet_mode_are_rejected(self):
        original = self.prepare_renewal()
        for field, value in (("kind", "canonical_ledger"),
                             ("audit_relative_file", "audit/04_local_checks/unselected.skeleton.json")):
            with self.subTest(field=field):
                packet = copy.deepcopy(original)
                packet["semantic_artifact"][field] = value
                packet["context_binding"]["semantic_artifact_sha256"] = proofcheck.canonical_sha256(packet["semantic_artifact"])
                packet["context_binding_sha256"] = proofcheck.canonical_sha256(packet["context_binding"])
                write_json(self.packet, packet)
                _, errors = self.assert_command(2, *self.compile_args())
                self.assertIn("does not bind this source-locked skeleton", errors)
        original["mode"] = "challenge"
        write_json(self.packet, original)
        _, errors = self.assert_command(2, *self.compile_args())
        self.assertIn("requires a primary context packet", errors)
        self.assertFalse(self.output.exists())

    def test_compiler_rejects_arbitrary_artifact_path_even_with_rehashed_selection(self):
        packet = self.prepare_renewal()
        arbitrary = self.history / "arbitrary.skeleton.json"
        arbitrary.write_bytes(self.skeleton.read_bytes())
        packet["semantic_artifact"]["audit_relative_file"] = arbitrary.relative_to(self.audit).as_posix()
        packet["context_binding"]["semantic_artifact_sha256"] = proofcheck.canonical_sha256(packet["semantic_artifact"])
        packet["context_binding_sha256"] = proofcheck.canonical_sha256(packet["context_binding"])
        write_json(self.packet, packet)
        self.skeleton = arbitrary
        self.output = arbitrary.with_name("arbitrary.ledger.json")
        _, errors = self.assert_command(2, *self.compile_args())
        self.assertIn("actual current canonical source-locked skeleton", errors)
        self.assertFalse(self.output.exists())

    def test_stale_source_obligation_and_issue_context_reject_saved_packet(self):
        for changed in ("source", "obligation", "issue"):
            with self.subTest(changed=changed):
                self.prepare_renewal()
                target = {"source": self.fixture.paper, "obligation": self.skeleton,
                          "issue": self.issue_path}[changed]
                original = target.read_bytes()
                if changed == "source":
                    target.write_text(target.read_text(encoding="utf-8") + "% drift\n", encoding="utf-8")
                else:
                    value = read_json(target)
                    if changed == "obligation":
                        value["obligation"]["quantifier_scope"] += " The quantifier remains universal."
                    else:
                        value["issues"][0]["summary"] = "The origin move still lacks its required premise."
                    write_json(target, value)
                _, errors = self.assert_command(2, *self.compile_args())
                self.assertRegex(errors, "stale|modified")
                self.assertFalse(self.output.exists())
                target.write_bytes(original)

    def test_same_stem_sibling_output_rule_remains_required(self):
        self.prepare_renewal()
        self.output = self.skeleton.with_name("different.ledger.json")
        _, errors = self.assert_command(2, *self.compile_args())
        self.assertIn("required canonical sibling path", errors)
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
