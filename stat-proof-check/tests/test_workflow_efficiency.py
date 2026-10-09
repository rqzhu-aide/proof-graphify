from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "proofcheck.py"
SPEC = importlib.util.spec_from_file_location("proofcheck_workflow_efficiency", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Cannot load {SCRIPT}")
proofcheck = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(proofcheck)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: dict) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def normalization_checks() -> list[dict[str, str]]:
    statuses = {
        "quantifiers_and_domains": "checked",
        "probability_model": "not_applicable",
        "hypotheses": "not_applicable",
        "definitions": "checked",
        "conclusion": "checked",
        "uniformity": "not_applicable",
        "regime": "not_applicable",
        "constant_dependencies": "not_applicable",
    }
    return [
        {
            "aspect": aspect,
            "status": statuses[aspect],
            "evidence": f"The normalized obligation explicitly resolves {aspect}.",
        }
        for aspect in proofcheck.NORMALIZATION_ASPECTS
    ]


def risk_checks(prefix: str) -> dict[str, dict[str, str]]:
    statuses = {
        "domain": "passed",
        "dimension": "not_applicable",
        "sign": "not_applicable",
        "constant": "not_applicable",
        "rate": "not_applicable",
        "probability": "not_applicable",
        "quantifier": "passed",
        "limit": "not_applicable",
    }
    return {
        aspect: {
            "status": statuses[aspect],
            "evidence": f"{prefix} explicitly checks the {aspect} risk.",
        }
        for aspect in proofcheck.RISK_ASPECTS
    }


class WorkflowEfficiencyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.paper = self.base / "paper source.tex"
        self.paper.write_text(
            "\\begin{lemma}\\label{lem:a}\n"
            "For every real $x$, $x=x$.\n"
            "\\end{lemma}\n"
            "\\begin{proof}\n"
            "The claim follows by reflexivity.\n"
            "\\end{proof}\n",
            encoding="utf-8",
            newline="\n",
        )
        self.audit = self.base / "audit with spaces"
        with contextlib.redirect_stdout(io.StringIO()):
            proofcheck.cmd_scaffold(
                argparse.Namespace(paper=self.paper, output=self.audit)
            )
        responses = [
            {
                "canary_id": "bounded-drift",
                "argument_status": "invalid",
                "statement_status": "refuted",
                "defect_lines": [15],
                "justification": (
                    "The equality recurrence permits an unbounded sequence, "
                    "so the claimed bound and written proof fail."
                ),
            },
            {
                "canary_id": "finite-max",
                "argument_status": "valid",
                "statement_status": "established",
                "defect_lines": [],
                "justification": (
                    "The finite maximum follows from the displayed finite "
                    "union bound and its termwise limit."
                ),
            },
        ]
        response_paths = []
        for index, response in enumerate(responses, 1):
            path = self.base / f"calibration-{index}.response.json"
            write_json(path, response)
            response_paths.append(path)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(
                0,
                proofcheck.cmd_canary_grade(
                    argparse.Namespace(
                        response=response_paths,
                        session_id="cal-workflow-efficiency",
                        root=self.audit,
                        checker_profile_id="checker-test-profile",
                        checker_configuration_id="workflow-efficiency-config",
                        checker_context_id="fresh-workflow-efficiency-context",
                        reviewed_binding=True,
                    )
                ),
            )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def extract_ledger(self) -> Path:
        ledger_dir = self.audit / "audit" / "04_local_checks"
        skeleton = ledger_dir / "lem-a.skeleton.json"
        ledger = ledger_dir / "lem-a.ledger.json"
        with contextlib.redirect_stdout(io.StringIO()):
            proofcheck.cmd_extract(
                argparse.Namespace(
                    file=self.paper,
                    start=1,
                    end=6,
                    statement_file=self.paper,
                    statement_start=1,
                    statement_end=3,
                    separate_statement_reason=None,
                    unit_id="lem:a",
                    output=skeleton,
                    force=False,
                )
            )
        value = read_json(skeleton)
        statement_span = value["obligation"]["statement_spans"][0]
        value["obligation"] = {
                "statement_spans": [statement_span],
                "quantified_variables": [
                    {
                        "symbol": "x",
                        "type": "real number",
                        "domain": "R",
                        "quantifier": "forall",
                    }
                ],
                "quantifier_scope": "For every real x.",
                "probability_model": "not applicable",
                "hypotheses": ["none"],
                "definitions": ["equality on real numbers"],
                "conclusion": "x equals x",
                "conclusions": [
                    {
                        "id": "C001",
                        "claim": "x equals x",
                        "applies_under": ["/quantifier_scope"],
                        "source_spans": [dict(statement_span)],
                        "normalization": {
                            "status": "checked",
                            "evidence": "The locked statement concludes exactly x equals x.",
                        },
                    }
                ],
                "uniformity": "not_applicable",
                "regime": "not_applicable",
                "constant_dependencies": ["none"],
                "context_spans": [],
                "normalization_checks": normalization_checks(),
        }
        write_json(skeleton, value)
        self.review_dependency_registry(critical=False)
        primary_context_path = self.base / "lem-a primary context.json"
        with contextlib.redirect_stdout(io.StringIO()):
            proofcheck.cmd_packet(
                argparse.Namespace(
                    root=self.audit,
                    unit_id="lem:a",
                    mode="primary",
                    output=primary_context_path,
                    force=False,
                )
            )
        primary_context = read_json(primary_context_path)
        annotations = {
            "annotation_schema_version": proofcheck.SEMANTIC_ANNOTATION_SCHEMA_VERSION,
            "unit_id": "lem:a",
            "source_unit_sha256": value["source"]["unit_sha256"],
            "obligation_sha256": proofcheck.canonical_sha256(value["obligation"]),
            "context_binding_sha256": primary_context[
                "context_binding_sha256"
            ],
            "calibration_receipt_sha256": primary_context["context_binding"][
                "calibration_receipt_sha256"
            ],
            "source_groups": [
                {
                    "lines": [1, 3],
                    "kind": "continued_sentence",
                    "partition_evidence": "Lines 1-3 form the complete statement environment.",
                }
            ],
            "dependencies": [],
            "steps": [
                {
                    "key": "statement",
                    "lines": [1, 3],
                    "mode": "noninferential",
                    "kind": "statement",
                    "goal": "Identify the exact lemma obligation.",
                    "claim": "For every real x, x equals x.",
                    "literal": "The locked statement says every real x equals itself.",
                    "atomicity_evidence": "This records the statement without an inference.",
                    "adversarial": ["The real domain and universal quantifier are retained."],
                    "risks": risk_checks("statement"),
                    "inputs": [],
                    "side_conditions": [],
                    "status": "verified",
                    "issue_ids": [],
                },
                {
                    "key": "conclusion",
                    "lines": [5, 5],
                    "mode": "derivation",
                    "kind": "conclusion",
                    "goal": "Establish reflexivity for the arbitrary real x.",
                    "claim": "x equals x",
                    "literal": "The locked proof invokes reflexivity for the claim.",
                    "atomicity_evidence": "The proof line contains one reflexivity move.",
                    "adversarial": ["No real-number case violates equality reflexivity."],
                    "risks": risk_checks("conclusion"),
                    "inputs": [
                        {
                            "kind": "obligation",
                            "reference": "/quantifier_scope",
                            "role": "fact",
                            "evidence": "The statement fixes an arbitrary real x.",
                            "anchor": {"kind": "statement_span", "index": 1},
                        }
                    ],
                    "side_conditions": [],
                    "status": "verified",
                    "issue_ids": [],
                    "rule": "Reflexivity of equality",
                    "justification": "Reflexivity gives x equals x for the fixed real x.",
                },
            ],
            "conclusions": [
                {
                    "conclusion_id": "C001",
                    "support_step": "conclusion",
                    "contract_fidelity": "verified",
                    "statement_status": "established",
                    "issue_ids": [],
                }
            ],
            "review": {
                "explicit_assumptions": [],
                "inherited_assumptions": [],
                "source_reference_dispositions": [],
                "candidate_dependency_dispositions": [],
                "citation_dispositions": [],
                "verification_basis": ["Exact source and atomic semantic annotations."],
                "reviewer_notes": [],
            },
        }
        annotations_path = self.base / "lem-a.annotations.json"
        write_json(annotations_path, annotations)
        with contextlib.redirect_stdout(io.StringIO()):
            proofcheck.cmd_compile_annotations(
                argparse.Namespace(
                    ledger=skeleton,
                    annotations=annotations_path,
                    packet=primary_context_path,
                    output=ledger,
                    force=False,
                )
            )
        return ledger

    def review_dependency_registry(self, *, critical: bool = True) -> None:
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        manifest["audit_scope"]["status"] = "reviewed"
        manifest["audit_scope"]["target_units"] = ["lem:a"]
        manifest["audit_scope"]["in_scope_units"] = ["lem:a"]
        manifest["audit_scope"]["critical_units"] = ["lem:a"] if critical else []
        write_json(manifest_path, manifest)
        inventory_path = self.audit / "audit" / "01_index" / "theorem_inventory.json"
        registry_path = self.audit / "audit" / "03_dependencies" / "DEPENDENCY_REGISTRY.json"
        registry = read_json(registry_path)
        registry["review"] = {
            "status": "reviewed",
            "source_snapshot_sha256": manifest["source_snapshot"]["sha256"],
            "inventory_sha256": proofcheck.sha256_file(inventory_path),
            "in_scope_units": ["lem:a"],
            "evidence": ["The current unit has no direct proof dependency."],
        }
        write_json(registry_path, registry)

    def test_scaffold_and_sync_views_are_deterministic_and_idempotent(self) -> None:
        self.assertEqual(
            "current", proofcheck.workflow_view_freshness(self.audit)["status"]
        )
        for relative in proofcheck.WORKFLOW_VIEW_PATHS:
            text = (self.audit / relative).read_text(encoding="utf-8")
            self.assertIn("**GENERATED VIEW:**", text)

        progress_path = self.audit / "PROGRESS.json"
        progress = read_json(progress_path)
        progress["next_action"] = "Check lem:a from its compact packet."
        write_json(progress_path, progress)
        freshness = proofcheck.workflow_view_freshness(self.audit)
        self.assertEqual("stale", freshness["status"])
        self.assertIn("CHECK_PLAN.md", freshness["stale"])

        first = proofcheck.sync_workflow_views(self.audit)
        self.assertEqual(["CHECK_PLAN.md"], first["changed"])
        second = proofcheck.sync_workflow_views(self.audit)
        self.assertEqual([], second["changed"])
        self.assertEqual(sorted(proofcheck.WORKFLOW_VIEW_PATHS), sorted(second["unchanged"]))

    def test_execution_order_blocks_out_of_scope_dependency_endpoint(self) -> None:
        self.review_dependency_registry()
        registry_path = (
            self.audit / "audit" / "03_dependencies" / "DEPENDENCY_REGISTRY.json"
        )
        registry = read_json(registry_path)
        registry["internal_uses"] = [
            {
                "dependent_unit": "lem:a",
                "use_id": "D001",
                "dependency_id": "ghost",
                "dependency_conclusion_id": "C001",
                "step_ids": ["S001"],
                "needed_form": "The ghost result holds in the needed form.",
                "dependency_conclusion": "The ghost result holds.",
                "dependency_contract_sha256": "0" * 64,
                "compatibility_check": (
                    "The recorded result is asserted to match the needed form."
                ),
                "compatibility_checks": [
                    {
                        "aspect": aspect,
                        "status": "passed",
                        "evidence": f"The {aspect} aspect is asserted compatible.",
                        "issue_ids": [],
                    }
                    for aspect in proofcheck.NORMALIZATION_ASPECTS
                ],
                "status": "passed",
                "issue_ids": [],
            }
        ]
        write_json(registry_path, registry)

        records = proofcheck.load_workflow_records(self.audit)
        ready, errors = proofcheck.workflow_dependency_mapping_readiness(records)
        rendered = proofcheck.render_execution_order(records)

        self.assertFalse(ready)
        self.assertTrue(
            any("dependency_id must name an in-scope unit" in error for error in errors),
            errors,
        )
        self.assertIn("blocked_dependency_mapping", rendered)
        self.assertIn("review dependency mapping", rendered)

    def test_packets_are_portable_minimal_and_challenge_blind(self) -> None:
        self.extract_ledger()
        self.review_dependency_registry()
        challenge_path = self.base / "challenge packet.json"
        with contextlib.redirect_stdout(io.StringIO()):
            proofcheck.cmd_packet(
                argparse.Namespace(
                    root=self.audit,
                    unit_id="lem:a",
                    mode="challenge",
                    output=challenge_path,
                    force=False,
                )
            )
        challenge = read_json(challenge_path)
        serialized = json.dumps(challenge, ensure_ascii=False)
        self.assertEqual("challenge", challenge["mode"])
        self.assertTrue(challenge["semantic_review_ready"])
        self.assertTrue(challenge["primary_record_ready"])
        self.assertRegex(challenge["obligation_sha256"], r"^[0-9a-f]{64}$")
        self.assertRegex(
            challenge["semantic_artifact"]["primary_ledger_sha256"],
            r"^[0-9a-f]{64}$",
        )
        self.assertNotIn("resume", challenge)
        self.assertNotIn(str(self.base), serialized)
        for forbidden_key in (
            "review",
            "steps",
            "independent_check",
            "suggested_changes",
            "challenger_verdict",
            "reconciled_verdict",
        ):
            self.assertNotIn(f'"{forbidden_key}"', serialized)
        self.assertEqual(
            "\\begin{lemma}\\label{lem:a}",
            challenge["source"]["statement"]["lines"][0]["text"],
        )
        self.assertNotIn("line_sha256", serialized)
        def assert_line_records_are_slim(value: object) -> None:
            if isinstance(value, dict):
                if {"line", "text"}.issubset(value):
                    self.assertNotIn("sha256", value)
                for child in value.values():
                    assert_line_records_are_slim(child)
            elif isinstance(value, list):
                for child in value:
                    assert_line_records_are_slim(child)

        assert_line_records_are_slim(challenge)
        for span_name in ("statement", "proof"):
            span = challenge["source"][span_name]
            self.assertRegex(span["span_sha256"], r"^[0-9a-f]{64}$")
            self.assertRegex(
                span["source_member"]["file_sha256"], r"^[0-9a-f]{64}$"
            )
            for line in span["lines"]:
                self.assertEqual({"line", "text"}, set(line))
        self.assertEqual("x equals x", challenge["obligation"]["conclusion"])
        self.assertTrue(challenge["obligation"]["statement_spans"])
        statement_span = challenge["obligation"]["statement_spans"][0]
        self.assertEqual("/source/statement", statement_span["source_span_ref"])
        self.assertNotIn("lines", statement_span)
        conclusion_span = challenge["obligation"]["conclusions"][0][
            "source_spans"
        ][0]
        self.assertEqual("/source/statement", conclusion_span["source_span_ref"])
        self.assertNotIn("lines", conclusion_span)
        self.assertNotIn("normalization_checks", challenge["obligation"])
        self.assertNotIn("normalization", challenge["obligation"]["conclusions"][0])
        self.assertEqual(list(proofcheck.RISK_ASPECTS), challenge["risk_aspects"])
        self.assertEqual([], challenge["issue_triggers"])

        primary_path = self.base / "primary packet.json"
        with contextlib.redirect_stdout(io.StringIO()):
            proofcheck.cmd_packet(
                argparse.Namespace(
                    root=self.audit,
                    unit_id="lem:a",
                    mode="primary",
                    output=primary_path,
                    force=False,
                )
            )
        primary = read_json(primary_path)
        self.assertTrue(primary["resume"]["ledger_present"])
        self.assertEqual(
            "audit/04_local_checks/lem-a.ledger.json",
            primary["resume"]["ledger_audit_relative_file"],
        )

    def test_primary_packet_reuses_only_exactly_bound_partial_work(self) -> None:
        ledger_path = self.extract_ledger()
        baseline = proofcheck.build_context_packet(
            self.audit, "lem:a", "primary"
        )
        ledger = read_json(ledger_path)
        ledger["work_context_sha256"] = baseline["work_context_sha256"]
        partial_step = next(
            step
            for step in reversed(ledger["steps"])
            if step.get("status") != "non_substantive"
        )
        partial_step["status"] = "not_checked"
        for result in ledger["review"]["conclusion_results"]:
            support = result.get("support")
            if isinstance(support, dict) and support.get("step_id") == partial_step["id"]:
                result["statement_status"] = "not_assessed"
        ledger["review"]["unit_status"] = "not_checked"
        write_json(ledger_path, ledger)
        wip_errors, _ = proofcheck.check_ledger_data(ledger_path, False)
        self.assertEqual([], wip_errors)

        exact = proofcheck.build_context_packet(
            self.audit, "lem:a", "primary"
        )
        self.assertFalse(exact["primary_record_ready"])
        self.assertTrue(exact["resume"]["wip_record_ready"])
        self.assertTrue(exact["resume"]["wip"]["included"])
        self.assertEqual(
            ledger["source_units"],
            exact["resume"]["wip"]["semantic_record"]["source_units"],
        )
        self.assertEqual(
            ledger["steps"],
            exact["resume"]["wip"]["semantic_record"]["steps"],
        )
        self.assertEqual(
            ledger["review"],
            exact["resume"]["wip"]["semantic_record"]["review"],
        )

        progress_path = self.audit / "PROGRESS.json"
        progress = read_json(progress_path)
        progress["next_action"] = "Continue the same bound unit."
        write_json(progress_path, progress)
        progress_drift = proofcheck.build_context_packet(
            self.audit, "lem:a", "primary"
        )
        self.assertEqual(
            exact["work_context_sha256"],
            progress_drift["work_context_sha256"],
        )
        self.assertTrue(progress_drift["resume"]["wip_record_ready"])
        self.assertTrue(progress_drift["resume"]["wip"]["included"])
        self.assertNotEqual(
            exact["operational_binding_sha256"],
            progress_drift["operational_binding_sha256"],
        )

        issue_path = self.audit / "audit" / "06_reports" / "ISSUE_LOG.json"
        original_issue_log = read_json(issue_path)
        changed_issue_log = json.loads(json.dumps(original_issue_log))
        changed_issue_log["workflow_note"] = "Issue context changed after WIP."
        write_json(issue_path, changed_issue_log)
        issue_drift = proofcheck.build_context_packet(
            self.audit, "lem:a", "primary"
        )
        self.assertEqual(
            exact["work_context_sha256"],
            issue_drift["work_context_sha256"],
        )
        self.assertTrue(issue_drift["resume"]["wip_record_ready"])
        self.assertTrue(issue_drift["resume"]["wip"]["included"])

        write_json(issue_path, original_issue_log)
        restored = proofcheck.build_context_packet(
            self.audit, "lem:a", "primary"
        )
        self.assertTrue(restored["resume"]["wip"]["included"])
        registry_path = (
            self.audit
            / "audit"
            / "03_dependencies"
            / "DEPENDENCY_REGISTRY.json"
        )
        registry = read_json(registry_path)
        registry["review"]["evidence"] = [
            "The dependency mapping was independently reviewed again."
        ]
        write_json(registry_path, registry)
        dependency_drift = proofcheck.build_context_packet(
            self.audit, "lem:a", "primary"
        )
        self.assertEqual(
            exact["work_context_sha256"],
            dependency_drift["work_context_sha256"],
        )
        self.assertTrue(dependency_drift["resume"]["wip_record_ready"])
        self.assertTrue(dependency_drift["resume"]["wip"]["included"])

    def test_span_reference_requires_exact_resolved_path(self) -> None:
        first = self.base / "first" / "shared.tex"
        second = self.base / "second" / "shared.tex"
        first.parent.mkdir()
        second.parent.mkdir()
        first.write_text("first\n", encoding="utf-8")
        second.write_text("second\n", encoding="utf-8")
        locations = {
            "statement": {
                "file": first.as_posix(),
                "start_line": 1,
                "end_line": 3,
            }
        }
        same = proofcheck.packet_span_reference(
            {"file": first.as_posix(), "start_line": 1, "end_line": 2},
            self.base,
            locations,
            self.base,
        )
        different = proofcheck.packet_span_reference(
            {"file": second.as_posix(), "start_line": 1, "end_line": 2},
            self.base,
            locations,
            self.base,
        )
        self.assertEqual("/source/statement", same)
        self.assertIsNone(different)

    def test_packet_refuses_canonical_audit_output(self) -> None:
        destination = self.audit / "packet.json"
        with self.assertRaisesRegex(ValueError, "outside the canonical audit root"):
            proofcheck.cmd_packet(
                argparse.Namespace(
                    root=self.audit,
                    unit_id="lem:a",
                    mode="primary",
                    output=destination,
                    force=False,
                )
            )
        self.assertFalse(destination.exists())

    def test_packet_fails_closed_on_source_drift(self) -> None:
        self.paper.write_text(
            self.paper.read_text(encoding="utf-8") + "% changed after scaffold\n",
            encoding="utf-8",
            newline="\n",
        )
        destination = self.base / "stale packet.json"
        with self.assertRaisesRegex(ValueError, "stale source state"):
            proofcheck.cmd_packet(
                argparse.Namespace(
                    root=self.audit,
                    unit_id="lem:a",
                    mode="primary",
                    output=destination,
                    force=False,
                )
            )
        self.assertFalse(destination.exists())

    def test_packet_never_overwrites_a_snapshotted_source(self) -> None:
        original = self.paper.read_bytes()
        with self.assertRaisesRegex(ValueError, "snapshotted source"):
            proofcheck.cmd_packet(
                argparse.Namespace(
                    root=self.audit,
                    unit_id="lem:a",
                    mode="primary",
                    output=self.paper,
                    force=True,
                )
            )
        self.assertEqual(original, self.paper.read_bytes())


if __name__ == "__main__":
    unittest.main()
