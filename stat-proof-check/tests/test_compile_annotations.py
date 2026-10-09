from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "proofcheck.py"
SPEC = importlib.util.spec_from_file_location("proofcheck_compiler", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Cannot load {SCRIPT}")
proofcheck = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(proofcheck)


def write_json(path: Path, value: dict) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def install_calibration(root: Path) -> None:
    manifest = read_json(root / "AUDIT_MANIFEST.json")
    calibration_path = root / "audit" / "07_runtime" / "CALIBRATION.json"
    calibration_path.parent.mkdir(parents=True, exist_ok=True)
    responses = [
        {
            "canary_id": "bounded-drift",
            "argument_status": "invalid",
            "statement_status": "refuted",
            "defect_lines": [15],
            "justification": (
                "The equality recurrence yields an unbounded admissible "
                "sequence, so the proof and conclusion fail."
            ),
        },
        {
            "canary_id": "finite-max",
            "argument_status": "valid",
            "statement_status": "established",
            "defect_lines": [],
            "justification": (
                "The fixed finite maximum follows from the displayed union "
                "bound and the finite-sum limit."
            ),
        },
    ]
    results = []
    for response in responses:
        passed, reasons, got = proofcheck.grade_canary_response(
            response, proofcheck.load_canary_key(response["canary_id"])
        )
        results.append(
            {
                "canary_id": response["canary_id"],
                "passed": passed,
                "reasons": reasons,
                "got": got,
                "response_sha256": proofcheck.canonical_sha256(got),
            }
        )
    write_json(
        calibration_path,
        {
            "calibration_schema_version": proofcheck.CALIBRATION_SCHEMA_VERSION,
            "canary_bundle": proofcheck.canary_bundle_identity(),
            "sessions": [
                {
                    "session_id": "cal-compile-001",
                    "graded_utc": "2026-08-09T00:00:00.000001+00:00",
                    "checker_binding": {
                        "checker_profile_id": "checker-test-profile",
                        "checker_configuration_id": "compiler-test-config",
                        "checker_context_id": "fresh-compiler-context",
                        "reviewed": True,
                        "scope": proofcheck.CHECKER_BINDING_SCOPE,
                        "automatic_identity_verification": False,
                        "limitation": proofcheck.CHECKER_BINDING_LIMITATION,
                    },
                    "audit_binding": {
                        "source_snapshot_sha256": manifest["source_snapshot"][
                            "sha256"
                        ],
                        "validator_sha256": manifest["protocol"][
                            "validator_sha256"
                        ],
                        "preexisting_proof_artifacts": [],
                    },
                    "results": results,
                    "passed": True,
                }
            ],
        },
    )


def normalization_checks() -> list[dict[str, str]]:
    rows = {
        "quantifiers_and_domains": (
            "checked",
            "The universal real-number quantifier is explicit in the locked statement.",
        ),
        "probability_model": (
            "not_applicable",
            "The locked equality contains no random object or probability statement.",
        ),
        "hypotheses": (
            "not_applicable",
            "The theorem has no hypotheses beyond the quantified real-number domain.",
        ),
        "definitions": (
            "checked",
            "Equality has its ordinary meaning on the real numbers.",
        ),
        "conclusion": (
            "checked",
            "The normalized conclusion is exactly the displayed equality x equals x.",
        ),
        "uniformity": (
            "not_applicable",
            "The locked claim contains no indexed bound or convergence statement.",
        ),
        "regime": (
            "not_applicable",
            "The locked claim is neither finite-sample nor asymptotic.",
        ),
        "constant_dependencies": (
            "not_applicable",
            "No named or hidden constant occurs in the locked equality.",
        ),
    }
    return [
        {"aspect": aspect, "status": status, "evidence": evidence}
        for aspect, (status, evidence) in rows.items()
    ]


def risks(prefix: str) -> dict[str, dict[str, str]]:
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
    descriptions = {
        "domain": "the current x remains in the real-number domain",
        "dimension": "the scalar equality has no dimension-sensitive operation",
        "sign": "the equality uses no order or sign argument",
        "constant": "the move introduces no explicit or hidden constant",
        "rate": "the move states no stochastic or asymptotic rate",
        "probability": "the move contains no event, measure, or conditioning",
        "quantifier": "the move retains the arbitrary real x fixed by the statement",
        "limit": "the move performs no limiting or exchange operation",
    }
    return {
        aspect: {
            "status": statuses[aspect],
            "evidence": f"{prefix}: {descriptions[aspect]}.",
        }
        for aspect in proofcheck.RISK_ASPECTS
    }


class CompileAnnotationsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name) / "workspace with spaces" / "理论"
        self.base.mkdir(parents=True)
        self.paper = self.base / "paper source.tex"
        self.paper.write_text(
            "\\begin{lemma}\\label{lem:compact}\n"
            "For every real $x$, $x=x$.\n"
            "\\end{lemma}\n"
            "\\begin{proof}\n"
            "For the object in \\ref{lem:compact}, reflexivity gives $x=x$.\n"
            "\\end{proof}\n",
            encoding="utf-8",
            newline="\n",
        )
        self.audit = self.base / "canonical audit"
        with contextlib.redirect_stdout(io.StringIO()):
            proofcheck.cmd_scaffold(
                argparse.Namespace(paper=self.paper, output=self.audit)
            )
        self.ledger = (
            self.audit
            / "audit"
            / "04_local_checks"
            / "unit.skeleton.json"
        )
        self.output = self.ledger.with_name("unit.ledger.json")
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
                    unit_id="lem:compact",
                    output=self.ledger,
                    force=False,
                )
            )
        install_calibration(self.audit)
        ledger = read_json(self.ledger)
        statement_span = ledger["obligation"]["statement_spans"][0]
        ledger["obligation"] = {
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
            "definitions": ["equality on the real numbers"],
            "conclusion": "x equals x",
            "conclusions": [
                {
                    "id": "C001",
                    "claim": "x equals x",
                    "source_spans": [dict(statement_span)],
                    "applies_under": ["/quantifier_scope"],
                    "normalization": {
                        "status": "checked",
                        "evidence": (
                            "The statement gives exactly x equals x for every real x."
                        ),
                    },
                }
            ],
            "uniformity": "not_applicable",
            "regime": "not_applicable",
            "constant_dependencies": ["none"],
            "context_spans": [],
            "normalization_checks": normalization_checks(),
        }
        write_json(self.ledger, ledger)
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        manifest["audit_scope"]["status"] = "reviewed"
        manifest["audit_scope"]["target_units"] = ["lem:compact"]
        manifest["audit_scope"]["in_scope_units"] = ["lem:compact"]
        manifest["audit_scope"]["critical_units"] = []
        write_json(manifest_path, manifest)
        inventory_path = (
            self.audit / "audit" / "01_index" / "theorem_inventory.json"
        )
        registry_path = (
            self.audit
            / "audit"
            / "03_dependencies"
            / "DEPENDENCY_REGISTRY.json"
        )
        registry = read_json(registry_path)
        registry["review"] = {
            "status": "reviewed",
            "source_snapshot_sha256": manifest["source_snapshot"]["sha256"],
            "inventory_sha256": proofcheck.sha256_file(inventory_path),
            "in_scope_units": ["lem:compact"],
            "evidence": [
                "The compact fixture has no direct result dependency."
            ],
        }
        write_json(registry_path, registry)
        self.packet = self.base / "primary packet.json"
        self.regenerate_packet()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def regenerate_packet(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()):
            proofcheck.cmd_packet(
                argparse.Namespace(
                    root=self.audit,
                    unit_id="lem:compact",
                    mode="primary",
                    output=self.packet,
                    force=self.packet.exists(),
                )
            )

    def annotations(self) -> dict:
        ledger = read_json(self.ledger)
        packet = read_json(self.packet)
        occurrence = packet["inventory"]["reference_occurrences"][0]
        annotations = {
            "annotation_schema_version": proofcheck.SEMANTIC_ANNOTATION_SCHEMA_VERSION,
            "unit_id": "lem:compact",
            "source_unit_sha256": ledger["source"]["unit_sha256"],
            "obligation_sha256": proofcheck.canonical_sha256(
                ledger["obligation"]
            ),
            "context_binding_sha256": read_json(self.packet)[
                "context_binding_sha256"
            ],
            "calibration_receipt_sha256": packet["context_binding"][
                "calibration_receipt_sha256"
            ],
            "source_groups": [
                {
                    "lines": [1, 3],
                    "kind": "continued_sentence",
                    "partition_evidence": (
                        "Lines 1-3 are the single locked formal statement environment."
                    ),
                }
            ],
            "dependencies": [],
            "steps": [
                {
                    "key": "statement",
                    "lines": [1, 3],
                    "mode": "noninferential",
                    "kind": "statement",
                    "goal": "Identify the exact theorem obligation.",
                    "claim": "For every real x, x equals x.",
                    "literal": (
                        "The locked statement quantifies over every real x and states x equals x."
                    ),
                    "atomicity_evidence": (
                        "This row records the statement and performs no inference."
                    ),
                    "adversarial": [
                        "The normalized statement retains the same domain and quantifier."
                    ],
                    "risks": risks("statement"),
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
                    "goal": "Establish x equals x for the arbitrary real x.",
                    "claim": "x equals x",
                    "literal": (
                        "Locked line 5 explicitly invokes reflexivity to obtain x equals x."
                    ),
                    "atomicity_evidence": (
                        "The line contains one application of reflexivity."
                    ),
                    "adversarial": [
                        "No real-number boundary case violates reflexivity of equality."
                    ],
                    "risks": risks("conclusion"),
                    "inputs": [
                        {
                            "kind": "obligation",
                            "reference": "/quantifier_scope",
                            "role": "fact",
                            "evidence": (
                                "The locked statement fixes an arbitrary real x."
                            ),
                            "anchor": {"kind": "statement_span", "index": 1},
                            "source_reference_id": occurrence["target"],
                            "source_reference_occurrence_id": occurrence[
                                "occurrence_id"
                            ],
                        }
                    ],
                    "side_conditions": [],
                    "status": "verified",
                    "issue_ids": [],
                    "rule": "Reflexivity of equality",
                    "justification": (
                        "Reflexivity gives x equals x for the arbitrary real x."
                    ),
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
                "verification_basis": [
                    "Exact locked source and authored atomic semantic annotations."
                ],
                "reviewer_notes": [],
            },
        }
        annotations["review"]["source_reference_dispositions"] = [
            {
                "occurrence_id": occurrence["occurrence_id"],
                "target": occurrence["target"],
                "command": occurrence["command"],
                "disposition": "obligation_context",
                "evidence": (
                    "The proof reference identifies this lemma's locked "
                    "statement and quantified domain."
                ),
            }
        ]
        return annotations

    def matching_skeleton(self, output: Path) -> Path:
        self.assertEqual(self.output, output)
        return self.ledger

    def compile(self, annotations: dict, output: Path, *, force: bool = False) -> dict:
        annotation_path = self.base / "semantic.annotations.json"
        write_json(annotation_path, annotations)
        skeleton = self.matching_skeleton(output)
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            status = proofcheck.cmd_compile_annotations(
                argparse.Namespace(
                    ledger=skeleton,
                    annotations=annotation_path,
                    packet=self.packet,
                    output=output,
                    force=force,
                )
            )
        self.assertEqual(0, status)
        return json.loads(stdout.getvalue())

    def test_compiles_valid_schema5_ledger_with_mechanical_coverage(self) -> None:
        output = self.output

        summary = self.compile(self.annotations(), output)

        self.assertEqual("passed", summary["validation"])
        self.assertEqual(
            self.annotations()["obligation_sha256"],
            summary["obligation_sha256"],
        )
        compiled = read_json(output)
        errors, validation = proofcheck.check_ledger_data(output, True)
        self.assertEqual([], errors)
        self.assertEqual("verified", validation["declared_unit_status"])
        self.assertNotIn("annotation_schema_version", compiled)
        self.assertEqual(
            [
                ("U001", [1, 3], "continued_sentence"),
                ("U002", [4, 4], "non_substantive"),
                ("U003", [5, 5], "one_line"),
                ("U004", [6, 6], "non_substantive"),
            ],
            [
                (row["id"], row["lines"], row["kind"])
                for row in compiled["source_units"]
            ],
        )
        self.assertEqual(
            ["S001", "S002", "S003", "S004"],
            [row["id"] for row in compiled["steps"]],
        )
        conclusion = compiled["steps"][2]
        self.assertEqual(
            "For every real x.", conclusion["premise_uses"][0]["claim"]
        )
        self.assertEqual(
            list(proofcheck.RISK_ASPECTS),
            [row["aspect"] for row in conclusion["risk_checks"]],
        )

    def test_not_applicable_risk_shorthand_expands_to_canonical_rows(self) -> None:
        annotations = self.annotations()
        for step in annotations["steps"]:
            step["not_applicable_basis"] = (
                f"{step['key']} uses only real-number equality and has no "
                "dimension, sign, constant, rate, probability, or limit operation."
            )
            for aspect, record in list(step["risks"].items()):
                if record["status"] == "not_applicable":
                    step["risks"][aspect] = "not_applicable"

        self.compile(annotations, self.output)

        compiled = read_json(self.output)
        for step in compiled["steps"]:
            if step["status"] == "non_substantive":
                continue
            checks = step["risk_checks"]
            self.assertEqual(
                list(proofcheck.RISK_ASPECTS),
                [row["aspect"] for row in checks],
            )
            by_aspect = {row["aspect"]: row for row in checks}
            self.assertEqual("passed", by_aspect["domain"]["status"])
            self.assertEqual("passed", by_aspect["quantifier"]["status"])
            for aspect in (
                "dimension",
                "sign",
                "constant",
                "rate",
                "probability",
                "limit",
            ):
                self.assertEqual("not_applicable", by_aspect[aspect]["status"])
                self.assertTrue(
                    by_aspect[aspect]["evidence"].startswith(
                        f"{aspect} is not applicable to this step: "
                    )
                )

    def test_not_applicable_risk_shorthand_has_precise_diagnostics(self) -> None:
        cases = []
        missing_basis = self.annotations()
        missing_basis["steps"][0]["risks"]["dimension"] = "not_applicable"
        cases.append(
            (
                "missing-basis",
                missing_basis,
                "/steps/0/not_applicable_basis",
                "missing_field",
            )
        )
        invalid_literal = self.annotations()
        invalid_literal["steps"][0]["risks"]["dimension"] = "n/a"
        cases.append(
            (
                "invalid-literal",
                invalid_literal,
                "/steps/0/risks/dimension",
                "invalid_enum",
            )
        )
        unused_basis = self.annotations()
        unused_basis["steps"][0]["not_applicable_basis"] = (
            "No shorthand is actually used in this deliberately invalid case."
        )
        cases.append(
            (
                "unused-basis",
                unused_basis,
                "/steps/0/not_applicable_basis",
                "unused_field",
            )
        )

        for name, annotations, pointer, code in cases:
            with self.subTest(case=name):
                annotation_path = self.base / f"{name}.annotations.json"
                write_json(annotation_path, annotations)
                stdout = io.StringIO()
                with contextlib.redirect_stdout(stdout):
                    status = proofcheck.cmd_annotation_check(
                        argparse.Namespace(
                            ledger=self.ledger,
                            annotations=annotation_path,
                            packet=self.packet,
                            json=True,
                        )
                    )
                result = json.loads(stdout.getvalue())
                self.assertEqual(1, status)
                self.assertTrue(
                    any(
                        row["pointer"] == pointer and row["code"] == code
                        for row in result["diagnostics"]
                    ),
                    result["diagnostics"],
                )

    def test_cli_is_registered_and_output_is_deterministic(self) -> None:
        annotations = self.annotations()
        annotation_path = self.base / "semantic.annotations.json"
        write_json(annotation_path, annotations)
        output = self.output
        parser = proofcheck.build_parser()
        rendered: list[bytes] = []
        for _ in range(2):
            skeleton = self.matching_skeleton(output)
            args = parser.parse_args(
                [
                    "compile-annotations",
                    str(skeleton),
                    "--annotations",
                    str(annotation_path),
                    "--packet",
                    str(self.packet),
                    "--output",
                    str(output),
                ]
            )
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(0, args.func(args))
            rendered.append(output.read_bytes())
            output.unlink()

        self.assertEqual(rendered[0], rendered[1])
        text = rendered[0].decode("utf-8")
        self.assertNotIn(str(annotation_path), text)

    def test_annotation_scaffold_is_deterministic_and_prefilled(self) -> None:
        outputs = [
            self.base / "draft one.annotations.json",
            self.base / "draft two.annotations.json",
        ]
        rendered: list[bytes] = []
        for output in outputs:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(
                    0,
                    proofcheck.cmd_annotation_scaffold(
                        argparse.Namespace(
                            ledger=self.ledger,
                            packet=self.packet,
                            output=output,
                        )
                    ),
                )
            rendered.append(output.read_bytes())
        self.assertEqual(rendered[0], rendered[1])
        scaffold = read_json(outputs[0])
        packet = read_json(self.packet)
        ledger = read_json(self.ledger)
        self.assertEqual(
            ledger["source"]["unit_sha256"],
            scaffold["source_unit_sha256"],
        )
        self.assertEqual(
            packet["context_binding_sha256"],
            scaffold["context_binding_sha256"],
        )
        self.assertEqual(
            packet["context_binding"]["calibration_receipt_sha256"],
            scaffold["calibration_receipt_sha256"],
        )
        self.assertEqual([], scaffold["dependencies"])
        self.assertEqual(
            ["C001"],
            [row["conclusion_id"] for row in scaffold["conclusions"]],
        )
        self.assertEqual(
            [packet["inventory"]["reference_occurrences"][0]["occurrence_id"]],
            [
                row["occurrence_id"]
                for row in scaffold["review"][
                    "source_reference_dispositions"
                ]
            ],
        )
        first_step = scaffold["steps"][0]
        self.assertEqual(list(proofcheck.RISK_ASPECTS), list(first_step["risks"]))
        self.assertIsNone(first_step["mode"])
        first_line = first_step["lines"][0]
        source_text = next(
            row["text"]
            for row in ledger["source_lines"]
            if row["line"] == first_line
        )
        self.assertEqual(
            f"Line {first_line} says exactly: {source_text.rstrip()}",
            first_step["literal"],
        )
        self.assertIsNone(first_step["risks"]["domain"]["status"])
        serialized = json.dumps(scaffold, ensure_ascii=False)
        for placeholder in ("TODO", "TBD", "not_checked"):
            self.assertNotIn(placeholder, serialized)

        parser = proofcheck.build_parser()
        args = parser.parse_args(
            [
                "annotation-scaffold",
                str(self.ledger),
                "--packet",
                str(self.packet),
                "--output",
                str(self.base / "parser.annotations.json"),
            ]
        )
        self.assertIs(args.func, proofcheck.cmd_annotation_scaffold)

    def test_annotation_scaffold_refuses_audit_output_and_overwrite(self) -> None:
        audit_output = (
            self.audit
            / "audit"
            / "04_local_checks"
            / "draft.annotations.json"
        )
        with self.assertRaisesRegex(ValueError, "outside the audit root"):
            proofcheck.cmd_annotation_scaffold(
                argparse.Namespace(
                    ledger=self.ledger,
                    packet=self.packet,
                    output=audit_output,
                )
            )
        output = self.base / "safe.annotations.json"
        with contextlib.redirect_stdout(io.StringIO()):
            proofcheck.cmd_annotation_scaffold(
                argparse.Namespace(
                    ledger=self.ledger,
                    packet=self.packet,
                    output=output,
                )
            )
        original = output.read_bytes()
        with self.assertRaisesRegex(FileExistsError, "already exists"):
            proofcheck.cmd_annotation_scaffold(
                argparse.Namespace(
                    ledger=self.ledger,
                    packet=self.packet,
                    output=output,
                )
            )
        self.assertEqual(original, output.read_bytes())

    def test_unanchored_step_evidence_is_rejected(self) -> None:
        annotations = self.annotations()
        conclusion_step = annotations["steps"][1]
        conclusion_step["atomicity_evidence"] = (
            "The line contains exactly one application of the equality rule."
        )
        conclusion_step["adversarial"] = [
            "No boundary case of the domain violates the applied identity."
        ]
        conclusion_step["justification"] = (
            "The reflexive identity closes the current local goal directly."
        )
        for aspect, record in conclusion_step["risks"].items():
            record["evidence"] = (
                f"conclusion: the {aspect} aspect raises no concern for the "
                "applied identity rule."
            )
        annotation_path = self.base / "unanchored.annotations.json"
        write_json(annotation_path, annotations)
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            status = proofcheck.cmd_annotation_check(
                argparse.Namespace(
                    ledger=self.ledger,
                    annotations=annotation_path,
                    packet=self.packet,
                    json=True,
                )
            )
        self.assertEqual(1, status)
        result = json.loads(stdout.getvalue())
        self.assertTrue(
            any(
                "never names a mathematical object" in row["message"]
                for row in result["diagnostics"]
            ),
            result["diagnostics"],
        )

    def test_math_token_extraction_and_anchoring_matching(self) -> None:
        tokens = proofcheck.extract_step_math_tokens(
            "Therefore $P(\\max_{1 \\le j \\le m_n} |X_{n,j}| > \\varepsilon) \\to 0$.",
            whole_math=False,
        )
        self.assertIn("m_n", tokens)
        self.assertIn("X_{n,j}", tokens)
        self.assertIn("P", tokens)
        self.assertNotIn("max", tokens)
        self.assertNotIn("varepsilon", tokens)
        prose_only = proofcheck.extract_step_math_tokens(
            "The conclusion follows by reflexivity and standard arguments.",
            whole_math=False,
        )
        self.assertEqual(set(), prose_only)
        display = proofcheck.extract_step_math_tokens(
            "a_{n+1} \\le C_0 b_n", whole_math=True
        )
        self.assertIn("b_n", display)
        self.assertTrue(
            proofcheck.evidence_names_source_object(
                {"X_{n,j}"},
                ["The union over X_n,j style coordinates is uncontrolled."],
            )
        )
        self.assertTrue(
            proofcheck.evidence_names_source_object(
                {"m_n"}, ["The range grows because m_n tends to infinity."]
            )
        )
        self.assertFalse(
            proofcheck.evidence_names_source_object(
                {"m_n", "P"},
                ["The step follows by standard union arguments."],
            )
        )
        self.assertFalse(
            proofcheck.evidence_names_source_object(
                {"x"}, ["This maximal exchange uses no such object."]
            )
        )

    def test_near_duplicate_evidence_warnings_are_advisory(self) -> None:
        annotations = self.annotations()
        annotations["steps"][0]["atomicity_evidence"] = (
            "This row performs no inference and records the statement exactly."
        )
        annotations["steps"][1]["atomicity_evidence"] = (
            "This row performs no inference and records the statement exactly!"
        )
        annotation_path = self.base / "neardup.annotations.json"
        write_json(annotation_path, annotations)
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            status = proofcheck.cmd_annotation_check(
                argparse.Namespace(
                    ledger=self.ledger,
                    annotations=annotation_path,
                    packet=self.packet,
                    json=True,
                )
            )
        result = json.loads(stdout.getvalue())
        self.assertEqual(0, status)
        self.assertEqual("passed", result["status"])
        self.assertGreaterEqual(result["warning_count"], 1)
        self.assertTrue(
            any(
                warning.startswith("near_duplicate_evidence")
                for warning in result["warnings"]
            )
        )

    def test_reused_not_applicable_basis_gets_an_advisory_warning(self) -> None:
        annotations = self.annotations()
        repeated = (
            "This exact generic basis is deliberately reused across two steps."
        )
        for step in annotations["steps"]:
            step["risks"]["dimension"] = "not_applicable"
            step["not_applicable_basis"] = repeated
        annotation_path = self.base / "reused-basis.annotations.json"
        write_json(annotation_path, annotations)
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            status = proofcheck.cmd_annotation_check(
                argparse.Namespace(
                    ledger=self.ledger,
                    annotations=annotation_path,
                    packet=self.packet,
                    json=True,
                )
            )
        result = json.loads(stdout.getvalue())
        self.assertEqual(0, status)
        self.assertTrue(
            any(
                "identical not_applicable_basis" in warning
                for warning in result["warnings"]
            ),
            result["warnings"],
        )

    def test_rebind_annotations_restores_current_binding_hashes(self) -> None:
        annotation_path = self.base / "rebind.annotations.json"
        with contextlib.redirect_stdout(io.StringIO()):
            proofcheck.cmd_annotation_scaffold(
                argparse.Namespace(
                    ledger=self.ledger,
                    packet=self.packet,
                    output=annotation_path,
                )
            )
        draft = read_json(annotation_path)
        draft["obligation_sha256"] = "0" * 64
        draft["context_binding_sha256"] = "1" * 64
        draft["source_unit_sha256"] = "2" * 64
        write_json(annotation_path, draft)
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.assertEqual(
                0,
                proofcheck.cmd_rebind_annotations(
                    argparse.Namespace(
                        annotations=annotation_path,
                        packet=self.packet,
                        skeleton=self.ledger,
                    )
                ),
            )
        result = json.loads(stdout.getvalue())
        self.assertEqual("rebound", result["status"])
        self.assertTrue(result["judgment_review_required"])
        self.assertEqual(
            ["context_binding_sha256", "obligation_sha256", "source_unit_sha256"],
            result["changed_fields"],
        )
        packet = read_json(self.packet)
        ledger = read_json(self.ledger)
        rebound = read_json(annotation_path)
        self.assertEqual(packet["obligation_sha256"], rebound["obligation_sha256"])
        self.assertEqual(
            packet["context_binding_sha256"], rebound["context_binding_sha256"]
        )
        self.assertEqual(
            ledger["source"]["unit_sha256"], rebound["source_unit_sha256"]
        )

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.assertEqual(
                0,
                proofcheck.cmd_rebind_annotations(
                    argparse.Namespace(
                        annotations=annotation_path,
                        packet=self.packet,
                        skeleton=None,
                    )
                ),
            )
        repeat = json.loads(stdout.getvalue())
        self.assertEqual([], repeat["changed_fields"])
        self.assertFalse(repeat["judgment_review_required"])

        parser = proofcheck.build_parser()
        args = parser.parse_args(
            [
                "rebind-annotations",
                str(annotation_path),
                "--packet",
                str(self.packet),
            ]
        )
        self.assertIs(args.func, proofcheck.cmd_rebind_annotations)
        self.assertIsNone(args.skeleton)

    def test_new_checker_configuration_invalidates_packets_and_annotations(
        self,
    ) -> None:
        annotations = self.annotations()
        annotation_path = self.base / "calibration-bound.annotations.json"
        write_json(annotation_path, annotations)
        old_packet = read_json(self.packet)
        old_receipt = old_packet["context_binding"][
            "calibration_receipt_sha256"
        ]
        old_work_context = old_packet["work_context_sha256"]

        calibration_path = (
            self.audit / "audit" / "07_runtime" / "CALIBRATION.json"
        )
        calibration = read_json(calibration_path)
        latest = json.loads(json.dumps(calibration["sessions"][-1]))
        latest["session_id"] = "cal-compile-002"
        latest["graded_utc"] = "2026-08-09T00:00:00.000002+00:00"
        latest["checker_binding"]["checker_context_id"] = (
            "fresh-compiler-context-002"
        )
        latest["checker_binding"]["checker_configuration_id"] = (
            "proofcheck-test-config-002"
        )
        calibration["sessions"].append(latest)
        write_json(calibration_path, calibration)
        self.assertEqual(
            [], proofcheck.checker_calibration_errors(self.audit)
        )

        with self.assertRaisesRegex(ValueError, "semantic context is stale"):
            proofcheck.cmd_compile_annotations(
                argparse.Namespace(
                    ledger=self.ledger,
                    annotations=annotation_path,
                    packet=self.packet,
                    output=self.output,
                    force=False,
                )
            )

        self.regenerate_packet()
        new_packet = read_json(self.packet)
        self.assertNotEqual(
            old_receipt,
            new_packet["context_binding"]["calibration_receipt_sha256"],
        )
        self.assertNotEqual(old_work_context, new_packet["work_context_sha256"])
        with self.assertRaisesRegex(
            ValueError, "annotations.context_binding_sha256"
        ):
            proofcheck.cmd_compile_annotations(
                argparse.Namespace(
                    ledger=self.ledger,
                    annotations=annotation_path,
                    packet=self.packet,
                    output=self.output,
                    force=False,
                )
            )

        with self.assertRaisesRegex(
            ValueError, "refuses a changed or missing calibration receipt"
        ):
            proofcheck.cmd_rebind_annotations(
                argparse.Namespace(
                    annotations=annotation_path,
                    packet=self.packet,
                    skeleton=self.ledger,
                )
            )
        fresh_path = self.base / "fresh-calibration.annotations.json"
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(
                0,
                proofcheck.cmd_annotation_scaffold(
                    argparse.Namespace(
                        ledger=self.ledger,
                        packet=self.packet,
                        output=fresh_path,
                    )
                ),
            )
        self.assertEqual(
            new_packet["context_binding"]["calibration_receipt_sha256"],
            read_json(fresh_path)["calibration_receipt_sha256"],
        )
        self.compile(self.annotations(), self.output)

    def test_preexisting_ledger_is_provenance_and_does_not_block_recompile(
        self,
    ) -> None:
        unrelated = (
            self.audit
            / "audit"
            / "04_local_checks"
            / "unrelated.ledger.json"
        )
        unrelated.write_text(
            '{"checker_authored":"before-calibration"}',
            encoding="utf-8",
            newline="\n",
        )
        calibration_path = (
            self.audit / "audit" / "07_runtime" / "CALIBRATION.json"
        )
        calibration = read_json(calibration_path)
        latest = json.loads(json.dumps(calibration["sessions"][-1]))
        latest["session_id"] = "cal-compile-recovery"
        latest["graded_utc"] = "2026-08-09T00:00:00.000003+00:00"
        latest["checker_binding"]["checker_context_id"] = (
            "fresh-compiler-recovery-context"
        )
        latest["audit_binding"] = proofcheck.calibration_audit_binding(
            self.audit
        )
        calibration["sessions"].append(latest)
        write_json(calibration_path, calibration)
        self.assertEqual([], proofcheck.checker_calibration_errors(self.audit))

        self.regenerate_packet()
        summary = self.compile(self.annotations(), self.output)
        self.assertEqual("passed", summary["validation"])

    def test_packet_generation_requires_present_latest_passing_calibration(
        self,
    ) -> None:
        calibration_path = (
            self.audit / "audit" / "07_runtime" / "CALIBRATION.json"
        )
        original = calibration_path.read_bytes()
        calibration_path.unlink()
        with self.assertRaisesRegex(ValueError, "current checker calibration"):
            proofcheck.build_context_packet(
                self.audit, "lem:compact", "primary"
            )
        calibration_path.write_bytes(original)

        calibration = read_json(calibration_path)
        latest = json.loads(json.dumps(calibration["sessions"][-1]))
        latest["session_id"] = "cal-compile-failing"
        latest["graded_utc"] = "2026-08-09T00:00:00.000004+00:00"
        latest["checker_binding"]["checker_context_id"] = (
            "fresh-compiler-failing-context"
        )
        response = dict(latest["results"][1]["got"])
        response["argument_status"] = "invalid"
        response["statement_status"] = "not_established"
        key = proofcheck.load_canary_key(response["canary_id"])
        passed, reasons, got = proofcheck.grade_canary_response(response, key)
        latest["results"][1] = {
            "canary_id": response["canary_id"],
            "passed": passed,
            "reasons": reasons,
            "got": got,
            "response_sha256": proofcheck.canonical_sha256(got),
        }
        latest["passed"] = False
        calibration["sessions"].append(latest)
        write_json(calibration_path, calibration)
        with self.assertRaisesRegex(ValueError, "latest balanced.*passes"):
            proofcheck.build_context_packet(
                self.audit, "lem:compact", "primary"
            )

    def test_compiled_ledger_and_existing_challenge_stale_after_calibration(
        self,
    ) -> None:
        self.compile(self.annotations(), self.output)
        compiled = read_json(self.output)
        self.assertEqual(
            read_json(self.packet)["work_context_sha256"],
            compiled["work_context_sha256"],
        )
        old_challenge = proofcheck.build_context_packet(
            self.audit, "lem:compact", "challenge"
        )
        old_receipt = old_challenge["context_binding"][
            "calibration_receipt_sha256"
        ]

        calibration_path = (
            self.audit / "audit" / "07_runtime" / "CALIBRATION.json"
        )
        calibration = read_json(calibration_path)
        latest = json.loads(json.dumps(calibration["sessions"][-1]))
        latest["session_id"] = "cal-compile-after-challenge"
        latest["graded_utc"] = "2026-08-09T00:00:00.000005+00:00"
        latest["checker_binding"]["checker_context_id"] = (
            "fresh-compiler-after-challenge-context"
        )
        latest["checker_binding"]["checker_configuration_id"] = (
            "proofcheck-test-config-after-challenge"
        )
        latest["audit_binding"] = proofcheck.calibration_audit_binding(
            self.audit
        )
        calibration["sessions"].append(latest)
        write_json(calibration_path, calibration)

        current_receipt = proofcheck.current_calibration_receipt(self.audit)
        self.assertNotEqual(old_receipt, current_receipt["sha256"])
        ledger_errors, _, _ = proofcheck.audit_ledgers(self.audit, True)
        self.assertTrue(
            any("work_context_sha256 is stale" in error for error in ledger_errors),
            ledger_errors,
        )
        with self.assertRaisesRegex(
            ValueError, "recompiled under the current calibration-bound"
        ):
            proofcheck.build_context_packet(
                self.audit, "lem:compact", "challenge"
            )

        history = (
            self.audit / "audit" / "04_local_checks" / "history"
        )
        history.mkdir(parents=True)
        archive = history / "unit.ledger.pre-calibration.json"
        self.output.replace(archive)
        self.regenerate_packet()
        recovery_packet = read_json(self.packet)
        self.assertEqual(
            "source_locked_skeleton",
            recovery_packet["semantic_artifact"]["kind"],
        )

        status_output = io.StringIO()
        with contextlib.redirect_stdout(status_output):
            proofcheck.cmd_status(
                argparse.Namespace(
                    root=self.audit,
                    format="json",
                    output=None,
                    force=False,
                )
            )
        archived_status = json.loads(status_output.getvalue())
        self.assertEqual(0, archived_status["ledgers"])
        self.assertFalse(
            any(
                archive.name in value
                for value in archived_status["invalid_ledgers"]
            )
        )

        recovered = self.compile(self.annotations(), self.output)
        self.assertEqual("passed", recovered["validation"])
        self.assertEqual([], proofcheck.checker_calibration_errors(self.audit))
        status_output = io.StringIO()
        with contextlib.redirect_stdout(status_output):
            proofcheck.cmd_status(
                argparse.Namespace(
                    root=self.audit,
                    format="json",
                    output=None,
                    force=False,
                )
            )
        recovered_status = json.loads(status_output.getvalue())
        self.assertEqual(1, recovered_status["ledgers"])
        self.assertEqual(0, recovered_status["ledger_errors"])

    def test_rebind_annotations_rejects_mismatch_and_audit_paths(self) -> None:
        annotation_path = self.base / "mismatch.annotations.json"
        with contextlib.redirect_stdout(io.StringIO()):
            proofcheck.cmd_annotation_scaffold(
                argparse.Namespace(
                    ledger=self.ledger,
                    packet=self.packet,
                    output=annotation_path,
                )
            )
        draft = read_json(annotation_path)
        draft["unit_id"] = "lem:other"
        write_json(annotation_path, draft)
        with self.assertRaisesRegex(ValueError, "unit mismatch"):
            proofcheck.cmd_rebind_annotations(
                argparse.Namespace(
                    annotations=annotation_path,
                    packet=self.packet,
                    skeleton=None,
                )
            )
        inside = self.audit / "inside.annotations.json"
        inside.write_text(
            json.dumps({"unit_id": "lem:compact"}),
            encoding="utf-8",
            newline="\n",
        )
        with self.assertRaisesRegex(ValueError, "outside the canonical audit root"):
            proofcheck.cmd_rebind_annotations(
                argparse.Namespace(
                    annotations=inside,
                    packet=self.packet,
                    skeleton=None,
                )
            )

    def test_annotation_check_reports_multiple_json_pointers(self) -> None:
        annotation_path = self.base / "draft.annotations.json"
        with contextlib.redirect_stdout(io.StringIO()):
            proofcheck.cmd_annotation_scaffold(
                argparse.Namespace(
                    ledger=self.ledger,
                    packet=self.packet,
                    output=annotation_path,
                )
            )
        draft = read_json(annotation_path)
        draft["context_binding_sha256"] = "0" * 64
        del draft["steps"][0]["risks"]["limit"]
        draft["steps"][0]["verdict_note"] = "unused"
        write_json(annotation_path, draft)
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            status = proofcheck.cmd_annotation_check(
                argparse.Namespace(
                    ledger=self.ledger,
                    annotations=annotation_path,
                    packet=self.packet,
                    json=True,
                )
            )
        result = json.loads(stdout.getvalue())
        self.assertEqual(1, status)
        self.assertFalse(result["compile_ready"])
        self.assertGreater(result["error_count"], 8)
        pointers = {row["pointer"] for row in result["diagnostics"]}
        self.assertIn("/context_binding_sha256", pointers)
        self.assertIn("/steps/0/risks/limit", pointers)
        self.assertIn("/steps/0/verdict_note", pointers)
        self.assertFalse(self.output.exists())

    def test_annotation_check_accepts_complete_annotations_without_writing(self) -> None:
        annotation_path = self.base / "complete.annotations.json"
        write_json(annotation_path, self.annotations())
        original_skeleton = self.ledger.read_bytes()
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            status = proofcheck.cmd_annotation_check(
                argparse.Namespace(
                    ledger=self.ledger,
                    annotations=annotation_path,
                    packet=self.packet,
                    json=True,
                )
            )
        result = json.loads(stdout.getvalue())
        self.assertEqual(0, status)
        self.assertTrue(result["compile_ready"])
        self.assertEqual([], result["diagnostics"])
        self.assertEqual(original_skeleton, self.ledger.read_bytes())
        self.assertFalse(self.output.exists())

    def test_annotation_check_aggregates_nonnull_semantic_errors(self) -> None:
        annotation_path = self.base / "invalid semantic.annotations.json"
        annotations = self.annotations()
        annotations["steps"][0]["mode"] = "invented-mode"
        annotations["steps"][0]["kind"] = "invented-kind"
        annotations["steps"][0]["status"] = "invented-status"
        annotations["steps"][0]["risks"]["domain"]["status"] = "invented-risk"
        annotations["conclusions"][0]["contract_fidelity"] = "invented-verdict"
        write_json(annotation_path, annotations)
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            status = proofcheck.cmd_annotation_check(
                argparse.Namespace(
                    ledger=self.ledger,
                    annotations=annotation_path,
                    packet=self.packet,
                    json=True,
                )
            )
        result = json.loads(stdout.getvalue())
        self.assertEqual(1, status)
        pointers = {row["pointer"] for row in result["diagnostics"]}
        self.assertTrue(
            {
                "/steps/0/mode",
                "/steps/0/kind",
                "/steps/0/status",
                "/steps/0/risks/domain/status",
                "/conclusions/0/contract_fidelity",
            }.issubset(pointers)
        )

    def test_annotation_check_aggregates_cross_field_errors(self) -> None:
        annotation_path = self.base / "invalid relationships.annotations.json"
        annotations = self.annotations()
        annotations["source_groups"].append(
            {
                "lines": [2, 3],
                "kind": "continued_sentence",
                "partition_evidence": "This deliberately overlaps the prior group.",
            }
        )
        annotations["steps"][1]["inputs"][0]["compatibility_check"] = (
            "This field is forbidden on an obligation input."
        )
        annotations["conclusions"][0]["support_step"] = "unknown-step"
        annotations["review"]["source_reference_dispositions"][0][
            "dependency_use_id"
        ] = "D001"
        write_json(annotation_path, annotations)
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            status = proofcheck.cmd_annotation_check(
                argparse.Namespace(
                    ledger=self.ledger,
                    annotations=annotation_path,
                    packet=self.packet,
                    json=True,
                )
            )
        result = json.loads(stdout.getvalue())
        self.assertEqual(1, status)
        pointers = {row["pointer"] for row in result["diagnostics"]}
        self.assertTrue(
            {
                "/source_groups/1/lines",
                "/steps/1/inputs/0/compatibility_check",
                "/conclusions/0/support_step",
                "/review/source_reference_dispositions/0/dependency_use_id",
            }.issubset(pointers)
        )

    def test_annotation_inputs_must_remain_outside_audit_root(self) -> None:
        annotation_path = (
            self.audit
            / "audit"
            / "04_local_checks"
            / "inside.annotations.json"
        )
        write_json(annotation_path, self.annotations())
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            status = proofcheck.cmd_annotation_check(
                argparse.Namespace(
                    ledger=self.ledger,
                    annotations=annotation_path,
                    packet=self.packet,
                    json=True,
                )
            )
        result = json.loads(stdout.getvalue())
        self.assertEqual(1, status)
        self.assertIn(
            "invalid_annotation_path", result["counts_by_code"]
        )
        with self.assertRaisesRegex(ValueError, "outside the canonical audit root"):
            proofcheck.cmd_compile_annotations(
                argparse.Namespace(
                    ledger=self.ledger,
                    annotations=annotation_path,
                    packet=self.packet,
                    output=self.output,
                    force=False,
                )
            )
        self.assertFalse(self.output.exists())

    def test_machine_readable_root_pointer_is_empty_string(self) -> None:
        missing = self.base / "missing.annotations.json"
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            status = proofcheck.cmd_annotation_check(
                argparse.Namespace(
                    ledger=self.ledger,
                    annotations=missing,
                    packet=self.packet,
                    json=True,
                )
            )
        result = json.loads(stdout.getvalue())
        self.assertEqual(1, status)
        self.assertEqual("", result["diagnostics"][0]["pointer"])

    def test_identity_diagnostics_keep_all_missing_records_and_unordered_paths(self) -> None:
        diagnostics: list[dict[str, str]] = []
        proofcheck.annotation_identity_diagnostics(
            [],
            [{"id": "A"}, {"id": "B"}],
            "/records",
            "id",
            ("id",),
            diagnostics,
        )
        self.assertEqual(2, len(diagnostics))
        self.assertEqual(2, len({row["message"] for row in diagnostics}))

        diagnostics = []
        proofcheck.annotation_identity_diagnostics(
            [{"candidate_id": "dep:a", "path_ids": ["CP002", "CP001"]}],
            [{"candidate_id": "dep:a", "path_ids": ["CP001", "CP002"]}],
            "/review/candidate_dependency_dispositions",
            "candidate_id",
            ("candidate_id", "path_ids"),
            diagnostics,
            unordered_fields=("path_ids",),
        )
        self.assertEqual([], diagnostics)

    def test_scaffold_prefills_nonempty_packet_mirrors_only(self) -> None:
        packet = read_json(self.packet)
        packet["dependencies"]["direct_external_uses"] = [
            {
                "dependency_id": "ext:fact",
                "use_id": "D001",
                "status": "verified",
                "needed_form": "The exact external fact needed here.",
                "compatibility_check": "The domains and quantifiers match exactly.",
            }
        ]
        packet["inventory"]["candidate_internal_dependency_ids"] = ["lem:prior"]
        packet["inventory"]["candidate_dependency_paths"] = [
            {"candidate_id": "lem:prior", "path_id": "CP002"},
            {"candidate_id": "lem:prior", "path_id": "CP001"},
        ]
        packet["inventory"]["citation_keys"] = ["Author2026"]
        scaffold = proofcheck.annotation_scaffold_data(
            read_json(self.ledger), packet
        )
        self.assertEqual(["D001"], [row["use_id"] for row in scaffold["dependencies"]])
        candidate = scaffold["review"]["candidate_dependency_dispositions"][0]
        self.assertEqual(["CP001", "CP002"], candidate["path_ids"])
        self.assertEqual(
            ["Author2026"],
            [row["key"] for row in scaffold["review"]["citation_dispositions"]],
        )
        self.assertTrue(
            all(
                isinstance(step["literal"], str)
                and step["literal"].startswith(f"Line {step['lines'][0]} says exactly: ")
                for step in scaffold["steps"]
            )
        )
        self.assertTrue(all(step["claim"] is None for step in scaffold["steps"]))

    def test_compile_accepts_operational_drift_but_rejects_packet_tampering(self) -> None:
        progress_path = self.audit / "PROGRESS.json"
        progress = read_json(progress_path)
        progress["next_action"] = "Continue the same semantic unit."
        write_json(progress_path, progress)
        summary = self.compile(self.annotations(), self.output)
        self.assertEqual("passed", summary["validation"])
        self.assertEqual(
            proofcheck.sha256_file(self.packet), summary["packet_sha256"]
        )
        self.assertTrue(summary["operational_binding_drift"])
        self.assertNotEqual(
            summary["submitted_operational_binding_sha256"],
            summary["operational_binding_sha256"],
        )
        self.output.unlink()

        packet = read_json(self.packet)
        packet["source"]["proof"]["lines"][0]["text"] = "tampered source"
        write_json(self.packet, packet)
        annotation_path = self.base / "tampered.annotations.json"
        write_json(annotation_path, self.annotations())
        with self.assertRaisesRegex(ValueError, "semantic context"):
            proofcheck.cmd_compile_annotations(
                argparse.Namespace(
                    ledger=self.ledger,
                    annotations=annotation_path,
                    packet=self.packet,
                    output=self.output,
                    force=False,
                )
            )
        self.assertFalse(self.output.exists())

    def test_operational_binding_tamper_is_not_reported_as_current(self) -> None:
        packet = read_json(self.packet)
        packet["operational_binding"]["manifest_sha256"] = "0" * 64
        packet["operational_binding_sha256"] = proofcheck.canonical_sha256(
            packet["operational_binding"]
        )
        submitted_hash = packet["operational_binding_sha256"]
        write_json(self.packet, packet)
        summary = self.compile(self.annotations(), self.output)
        self.assertTrue(summary["operational_binding_drift"])
        self.assertEqual(
            submitted_hash, summary["submitted_operational_binding_sha256"]
        )
        self.assertNotEqual(
            submitted_hash, summary["operational_binding_sha256"]
        )

    def test_registry_binding_tamper_rejects_old_packet(self) -> None:
        packet = read_json(self.packet)
        packet["dependencies"]["registry_binding"][
            "closure_contract_version"
        ] = 999
        write_json(self.packet, packet)
        annotation_path = self.base / "registry tamper.annotations.json"
        write_json(annotation_path, self.annotations())
        with self.assertRaisesRegex(ValueError, "semantic context"):
            proofcheck.cmd_compile_annotations(
                argparse.Namespace(
                    ledger=self.ledger,
                    annotations=annotation_path,
                    packet=self.packet,
                    output=self.output,
                    force=False,
                )
            )

    def test_direct_dependency_contract_drift_rejects_old_packet(self) -> None:
        annotations = self.dependency_annotations()
        registry_path = (
            self.audit
            / "audit"
            / "03_dependencies"
            / "DEPENDENCY_REGISTRY.json"
        )
        registry = read_json(registry_path)
        registry["external_results"][0]["uses"][0]["needed_form"] = (
            "A materially different external fact is now required."
        )
        write_json(registry_path, registry)
        annotation_path = self.base / "dependency drift.annotations.json"
        write_json(annotation_path, annotations)
        with self.assertRaisesRegex(ValueError, "semantic context"):
            proofcheck.cmd_compile_annotations(
                argparse.Namespace(
                    ledger=self.ledger,
                    annotations=annotation_path,
                    packet=self.packet,
                    output=self.output,
                    force=False,
                )
            )

    def test_invalid_annotation_never_replaces_existing_output(self) -> None:
        annotations = self.annotations()
        annotations["source_unit_sha256"] = "0" * 64
        annotation_path = self.base / "bad.annotations.json"
        write_json(annotation_path, annotations)
        output = self.output
        skeleton = self.matching_skeleton(output)
        original = b"existing output must survive\n"
        output.write_bytes(original)

        with self.assertRaisesRegex(FileExistsError, "cannot be overwritten"):
            proofcheck.cmd_compile_annotations(
                argparse.Namespace(
                    ledger=skeleton,
                    annotations=annotation_path,
                    packet=self.packet,
                    output=output,
                    force=True,
                )
            )

        self.assertEqual(original, output.read_bytes())
        self.assertEqual([], list(self.base.glob(".*.proofcheck.tmp")))

    def test_concurrent_output_creation_is_never_overwritten(self) -> None:
        annotation_path = self.base / "semantic.annotations.json"
        write_json(annotation_path, self.annotations())
        output = self.output
        concurrent = b"concurrent creator owns this output\n"
        real_link = os.link

        def create_then_link(source: str | Path, destination: str | Path) -> None:
            Path(destination).write_bytes(concurrent)
            real_link(source, destination)

        with mock.patch.object(
            proofcheck.os, "link", side_effect=create_then_link
        ):
            with self.assertRaisesRegex(FileExistsError, "appeared during creation"):
                proofcheck.cmd_compile_annotations(
                    argparse.Namespace(
                        ledger=self.ledger,
                        annotations=annotation_path,
                        packet=self.packet,
                        output=output,
                        force=False,
                    )
                )

        self.assertEqual(concurrent, output.read_bytes())
        self.assertEqual([], list(self.base.glob(".*.proofcheck.tmp")))

    def test_no_hard_link_filesystem_uses_verified_exclusive_copy(self) -> None:
        annotation_path = self.base / "semantic annotations.json"
        write_json(annotation_path, self.annotations())
        stdout = io.StringIO()
        with mock.patch.object(
            proofcheck.os, "link", side_effect=OSError("hard links unsupported")
        ):
            with contextlib.redirect_stdout(stdout):
                status = proofcheck.cmd_compile_annotations(
                    argparse.Namespace(
                        ledger=self.ledger,
                        annotations=annotation_path,
                        packet=self.packet,
                        output=self.output,
                        force=False,
                    )
                )
        summary = json.loads(stdout.getvalue())
        self.assertEqual(0, status)
        expected_method = "exclusive_rename" if os.name == "nt" else "exclusive_copy"
        self.assertEqual(expected_method, summary["publication_method"])
        errors, _ = proofcheck.check_ledger_data(self.output, True)
        self.assertEqual([], errors)

    def test_compact_schema_rejects_missing_semantics_and_unknown_fields(self) -> None:
        cases: list[tuple[str, dict, str]] = []
        missing_risk = self.annotations()
        del missing_risk["steps"][1]["risks"]["limit"]
        cases.append(("missing-risk", missing_risk, "missing fields: limit"))
        missing_rule = self.annotations()
        del missing_rule["steps"][1]["rule"]
        cases.append(("missing-rule", missing_rule, "rule must be authored"))
        unknown_field = self.annotations()
        unknown_field["steps"][1]["verdict_note"] = "A misspelled field."
        cases.append(("unknown-field", unknown_field, "unknown fields: verdict_note"))
        derived_field = self.annotations()
        derived_field["conclusions"][0]["use_site_sufficiency"] = "sufficient"
        cases.append(
            (
                "derived-field",
                derived_field,
                "unknown fields: use_site_sufficiency",
            )
        )

        for name, annotations, message in cases:
            with self.subTest(case=name):
                annotation_path = self.base / f"{name}.annotations.json"
                output = self.output
                skeleton = self.matching_skeleton(output)
                write_json(annotation_path, annotations)
                with self.assertRaisesRegex(ValueError, message):
                    proofcheck.cmd_compile_annotations(
                        argparse.Namespace(
                            ledger=skeleton,
                            annotations=annotation_path,
                            packet=self.packet,
                            output=output,
                            force=False,
                        )
                    )
                self.assertFalse(output.exists())

    def test_completed_ledger_cannot_be_recompiled_as_a_fresh_skeleton(self) -> None:
        compiled = self.output
        self.compile(self.annotations(), compiled)
        completed_skeleton = self.base / "completed.skeleton.json"
        completed_skeleton.write_bytes(compiled.read_bytes())

        with self.assertRaisesRegex(ValueError, "fresh extracted skeleton"):
            proofcheck.validate_compile_skeleton(
                read_json(completed_skeleton), completed_skeleton
            )

    def test_compiler_never_overwrites_the_extracted_skeleton(self) -> None:
        annotation_path = self.base / "semantic.annotations.json"
        write_json(annotation_path, self.annotations())
        original = self.ledger.read_bytes()

        with self.assertRaisesRegex(ValueError, "Compiled output must end"):
            proofcheck.cmd_compile_annotations(
                argparse.Namespace(
                    ledger=self.ledger,
                    annotations=annotation_path,
                    packet=self.packet,
                    output=self.ledger,
                    force=True,
                )
            )

        self.assertEqual(original, self.ledger.read_bytes())

    def test_compiler_rejects_stale_obligation_binding(self) -> None:
        annotations = self.annotations()
        ledger = read_json(self.ledger)
        ledger["obligation"]["quantifier_scope"] = "For every complex x."
        write_json(self.ledger, ledger)
        annotation_path = self.base / "semantic.annotations.json"
        write_json(annotation_path, annotations)
        output = self.output

        with self.assertRaisesRegex(ValueError, "obligation_sha256"):
            proofcheck.cmd_compile_annotations(
                argparse.Namespace(
                    ledger=self.ledger,
                    annotations=annotation_path,
                    packet=self.packet,
                    output=output,
                    force=False,
                )
            )

        self.assertFalse(output.exists())

    def test_compiler_rejects_mismatched_output_basename(self) -> None:
        annotation_path = self.base / "semantic.annotations.json"
        write_json(annotation_path, self.annotations())
        output = self.output.parent / "different.ledger.json"

        with self.assertRaisesRegex(ValueError, "output basename"):
            proofcheck.cmd_compile_annotations(
                argparse.Namespace(
                    ledger=self.ledger,
                    annotations=annotation_path,
                    packet=self.packet,
                    output=output,
                    force=False,
                )
            )

        self.assertFalse(output.exists())

    def test_obligation_anchor_errors_name_authored_annotation_pointer(self) -> None:
        annotation_path = self.base / "invalid-anchor.annotations.json"
        original_skeleton = self.ledger.read_bytes()
        cases = [("kind", "statement"), ("kind", "context"),
                 ("index", 0), ("index", -1), ("index", True),
                 ("index", False), ("index", 1.5), ("index", "1")]
        for field, value in cases:
            with self.subTest(field=field, value=value):
                annotations = self.annotations()
                annotations["steps"][1]["inputs"][0]["anchor"][field] = value
                write_json(annotation_path, annotations)
                stdout = io.StringIO()
                with contextlib.redirect_stdout(stdout):
                    status = proofcheck.cmd_annotation_check(argparse.Namespace(
                        ledger=self.ledger, annotations=annotation_path,
                        packet=self.packet, json=True,
                    ))
                result = json.loads(stdout.getvalue())
                self.assertEqual(1, status)
                self.assertFalse(result["compile_ready"])
                matching = [row for row in result["diagnostics"]
                            if row["pointer"] == f"/steps/1/inputs/0/anchor/{field}"]
                self.assertTrue(matching, result["diagnostics"])
                expected = "statement_span" if field == "kind" else "positive one-based integer"
                self.assertTrue(any(expected in row["message"] for row in matching))
                with self.assertRaises(ValueError):
                    proofcheck.cmd_compile_annotations(argparse.Namespace(
                        ledger=self.ledger, annotations=annotation_path,
                        packet=self.packet, output=self.output, force=False,
                    ))
                self.assertFalse(self.output.exists())
                self.assertEqual(original_skeleton, self.ledger.read_bytes())

    def test_wrong_compiled_output_names_exact_canonical_sibling_without_writing(self) -> None:
        annotation_path = self.base / "valid-path.annotations.json"
        write_json(annotation_path, self.annotations())
        before = {path.relative_to(self.base): path.read_bytes()
                  for path in self.base.rglob("*") if path.is_file()}
        for output in (self.output.with_suffix(".txt"),
                       self.output.with_name("different.ledger.json"),
                       self.base / self.output.name):
            with self.subTest(output=output):
                with self.assertRaises(ValueError) as caught:
                    proofcheck.cmd_compile_annotations(argparse.Namespace(
                        ledger=self.ledger, annotations=annotation_path,
                        packet=self.packet, output=output, force=False,
                    ))
                self.assertIn(str(self.output.resolve()), str(caught.exception))
                self.assertFalse(output.exists())
        after = {path.relative_to(self.base): path.read_bytes()
                 for path in self.base.rglob("*") if path.is_file()}
        self.assertEqual(before, after)

    def test_normalization_enum_diagnostics_show_supported_spellings(self) -> None:
        ledger = read_json(self.ledger)
        ledger["obligation"]["uniformity"] = "point-wise"
        ledger["obligation"]["regime"] = "finite-sample"
        write_json(self.ledger, ledger)
        errors, _ = proofcheck.check_ledger_data(self.ledger, True, primary_only=True)
        uniformity = next(error for error in errors if "obligation.uniformity has" in error)
        regime = next(error for error in errors if "obligation.regime has" in error)
        for value in ("pointwise", "uniform", "mixed", "not_applicable", "unclear"):
            self.assertIn(value, uniformity)
        for value in ("finite_sample", "asymptotic", "both", "not_applicable", "unclear"):
            self.assertIn(value, regime)

    def test_compiler_summary_is_ascii_console_safe(self) -> None:
        annotation_path = self.base / "semantic.annotations.json"
        write_json(annotation_path, self.annotations())
        output = self.output
        raw = io.BytesIO()
        stream = io.TextIOWrapper(raw, encoding="ascii", errors="strict")
        try:
            with contextlib.redirect_stdout(stream):
                status = proofcheck.cmd_compile_annotations(
                    argparse.Namespace(
                        ledger=self.ledger,
                        annotations=annotation_path,
                        packet=self.packet,
                        output=output,
                        force=False,
                    )
                )
            stream.flush()
            rendered = raw.getvalue().decode("ascii")
        finally:
            stream.detach()

        self.assertEqual(0, status)
        self.assertEqual("compile-annotations", json.loads(rendered)["command"])
        self.assertTrue(output.is_file())

    def install_external_dependency(self, status: str) -> None:
        source_path = self.base / "external reflexivity.txt"
        source_path.write_text(
            "External Result 1\nEquality is reflexive on the real numbers.\n",
            encoding="utf-8",
            newline="\n",
        )
        exact_statement = "Equality is reflexive on the real numbers."
        source_evidence = [
            {
                "file": proofcheck.relative_or_absolute(
                    source_path, self.audit
                ),
                "sha256": proofcheck.sha256_file(source_path),
                "locator": "External Result 1, line 2",
                "role": "authoritative_theorem_source",
            }
        ]
        contract_payload = {
            "source_identity": "doi:10.0000/reflexivity",
            "version": "version 1",
            "theorem_location": "External Result 1",
            "exact_statement": exact_statement,
            "source_evidence": source_evidence,
        }
        needed_form = "Equality is reflexive on the real numbers."
        compatibility = (
            "The external fact applies to the current real x without a "
            "domain change."
        )
        use = {
            "dependent_unit": "lem:compact",
            "use_id": "D001",
            "dependency_id": "ext:reflexivity",
            "step_ids": ["S003.1"],
            "needed_form": needed_form,
            "dependency_conclusion": exact_statement,
            "dependency_contract_sha256": proofcheck.canonical_sha256(
                contract_payload
            ),
            "compatibility_check": compatibility,
            "compatibility_checks": [
                {
                    "aspect": aspect,
                    "status": "passed",
                    "evidence": (
                        f"The external result is compatible on {aspect}."
                    ),
                    "issue_ids": [],
                }
                for aspect in proofcheck.NORMALIZATION_ASPECTS
            ],
            "status": status,
            "issue_ids": [],
            "citation_keys": [],
            "prerequisite_map": [
                {
                    "prerequisite": "The current object x is real.",
                    "manuscript_evidence": (
                        "The locked statement quantifies x over the real numbers."
                    ),
                    "status": "satisfied",
                    "evidence_spans": [
                        proofcheck.locked_span(
                            self.paper,
                            1,
                            3,
                            self.audit,
                            role="manuscript_prerequisite",
                        )
                    ],
                    "issue_ids": [],
                }
            ],
        }
        registry_path = (
            self.audit
            / "audit"
            / "03_dependencies"
            / "DEPENDENCY_REGISTRY.json"
        )
        registry = read_json(registry_path)
        registry["external_results"] = [
            {
                "id": "ext:reflexivity",
                "status": "verified",
                **contract_payload,
                "issue_ids": [],
                "uses": [use],
            }
        ]
        write_json(registry_path, registry)
        self.regenerate_packet()

    def dependency_annotations(self, status: str = "verified") -> dict:
        self.install_external_dependency(status)
        annotations = self.annotations()
        source_disposition = annotations["review"][
            "source_reference_dispositions"
        ][0]
        annotations["dependencies"] = [
            {
                "id": "ext:reflexivity",
                "use_id": "D001",
                "kind": "external_result",
                "status": status,
                "needed_form": "Equality is reflexive on the real numbers.",
                "compatibility_check": (
                    "The external fact applies to the current real x without a domain change."
                ),
            }
        ]
        annotations["steps"] = [
            annotations["steps"][0],
            {
                "key": "domain",
                "lines": [5, 5],
                "mode": "derivation",
                "kind": "setup",
                "goal": "Record the domain of the arbitrary element.",
                "claim": "x is a real number.",
                "literal": "Locked line 5 identifies x as real before using reflexivity.",
                "atomicity_evidence": (
                    "This annotation isolates only the domain specialization."
                ),
                "adversarial": [
                    "The specialization does not change the universal scope of x."
                ],
                "risks": risks("domain step"),
                "inputs": [
                    {
                        "kind": "obligation",
                        "reference": "/quantifier_scope",
                        "role": "fact",
                        "evidence": "The statement fixes x as an arbitrary real number.",
                        "anchor": {"kind": "statement_span", "index": 1},
                        "source_reference_id": source_disposition["target"],
                        "source_reference_occurrence_id": source_disposition[
                            "occurrence_id"
                        ],
                    }
                ],
                "side_conditions": [],
                "status": "verified",
                "issue_ids": [],
                "rule": "Universal specialization",
                "justification": (
                    "Specializing the universal statement records that the current x is real."
                ),
            },
            {
                "key": "conclusion",
                "lines": [5, 5],
                "mode": "derivation",
                "kind": "conclusion",
                "goal": "Apply reflexivity to the current real x.",
                "claim": "x equals x",
                "literal": "Locked line 5 concludes x equals x by reflexivity.",
                "atomicity_evidence": (
                    "This annotation isolates the single reflexivity move."
                ),
                "adversarial": [
                    "The imported reflexivity fact is used only on its real-number domain."
                ],
                "risks": risks("dependency conclusion"),
                "inputs": [
                    {
                        "kind": "prior_step",
                        "reference": "domain",
                        "role": "fact",
                        "evidence": "The immediately prior atomic step establishes x is real.",
                        "compatibility_check": (
                            "The prior domain claim is used without strengthening."
                        ),
                    },
                    {
                        "kind": "dependency",
                        "reference": "D001",
                        "role": "fact",
                        "evidence": (
                            "The checked external dependency supplies reflexivity on the real numbers."
                        ),
                    },
                ],
                "side_conditions": [],
                "status": "verified",
                "issue_ids": [],
                "rule": "Apply reflexivity on the recorded domain",
                "justification": (
                    "The current x is real and the external dependency gives reflexivity there."
                ),
            },
        ]
        return annotations

    def test_preliminary_dependency_can_scaffold_but_not_compile(self) -> None:
        self.install_external_dependency("unchecked")
        registry_path = (
            self.audit
            / "audit"
            / "03_dependencies"
            / "DEPENDENCY_REGISTRY.json"
        )
        registry = read_json(registry_path)
        registry["external_results"][0]["uses"][0]["step_ids"] = []
        write_json(registry_path, registry)
        self.regenerate_packet()
        scaffold_path = self.base / "preliminary.annotations.json"

        with contextlib.redirect_stdout(io.StringIO()):
            status = proofcheck.cmd_annotation_scaffold(
                argparse.Namespace(
                    ledger=self.ledger,
                    packet=self.packet,
                    output=scaffold_path,
                )
            )

        self.assertEqual(0, status)
        self.assertTrue(scaffold_path.is_file())
        with self.assertRaisesRegex(
            ValueError,
            "requires every direct dependency row to bind exact step_ids",
        ):
            proofcheck.cmd_compile_annotations(
                argparse.Namespace(
                    ledger=self.ledger,
                    annotations=scaffold_path,
                    packet=self.packet,
                    output=self.output,
                    force=False,
                )
            )
        self.assertFalse(self.output.exists())

    def test_compile_rejects_wrong_canonical_dependency_step(self) -> None:
        annotations = self.dependency_annotations()
        annotation_path = self.base / "wrong-step.annotations.json"
        write_json(annotation_path, annotations)
        registry_path = (
            self.audit
            / "audit"
            / "03_dependencies"
            / "DEPENDENCY_REGISTRY.json"
        )
        registry = read_json(registry_path)
        registry["external_results"][0]["uses"][0]["step_ids"] = ["S999"]
        write_json(registry_path, registry)
        self.regenerate_packet()

        with self.assertRaisesRegex(
            ValueError,
            "step_ids disagrees with the invoking ledger",
        ):
            proofcheck.cmd_compile_annotations(
                argparse.Namespace(
                    ledger=self.ledger,
                    annotations=annotation_path,
                    packet=self.packet,
                    output=self.output,
                    force=False,
                )
            )

        self.assertFalse(self.output.exists())

    def test_same_source_unit_steps_get_stable_ids_and_exact_dependency_closure(
        self,
    ) -> None:
        output = self.output

        self.compile(self.dependency_annotations(), output)

        compiled = read_json(output)
        errors, _ = proofcheck.check_ledger_data(output, True)
        self.assertEqual([], errors)
        self.assertEqual(
            ["S001", "S002", "S003", "S003.1", "S004"],
            [row["id"] for row in compiled["steps"]],
        )
        conclusion = next(row for row in compiled["steps"] if row["id"] == "S003.1")
        self.assertEqual(
            ["S003", "D001"],
            [
                row["id"] if row["kind"] == "step" else row["use_id"]
                for row in conclusion["dependencies"]
            ],
        )
        self.assertEqual(
            compiled["review"]["direct_dependencies"][0],
            conclusion["dependencies"][1],
        )
        result = compiled["review"]["conclusion_results"][0]
        self.assertEqual({"step_id": "S003.1", "move_id": "M001"}, result["support"])
        self.assertEqual(["D001"], result["dependency_use_ids"])
        self.assertEqual("verified", result["dependency_closure"])

    def test_preflight_and_compiler_reject_noninferential_premise_roots(self) -> None:
        baseline = self.dependency_annotations()
        for kind in ("setup", "definition"):
            with self.subTest(kind=kind):
                annotations = json.loads(json.dumps(baseline))
                domain = annotations["steps"][1]
                domain["kind"] = kind
                domain["mode"] = "noninferential"
                domain["inputs"] = []
                domain.pop("rule")
                domain.pop("justification")
                diagnostics = proofcheck.annotation_preflight_diagnostics(
                    read_json(self.ledger), self.ledger, annotations,
                    read_json(self.packet), deep_validation=False,
                )
                self.assertTrue(
                    any(
                        row["code"] == "unsupported_premise_root"
                        and row["pointer"] == "/steps/2/inputs/0/reference"
                        and "step domain is noninferential" in row["message"]
                        for row in diagnostics
                    ),
                    diagnostics,
                )
                with self.assertRaisesRegex(ValueError, "step domain is noninferential"):
                    self.compile(annotations, self.output)
                self.assertFalse(self.output.exists())

    def test_conditional_causes_are_derived_without_reauthoring_mirrors(self) -> None:
        annotations = self.dependency_annotations("conditional")
        conclusion = annotations["steps"][2]
        conclusion["status"] = "conditionally_verified"
        conclusion["risks"]["domain"] = {
            "status": "open",
            "evidence": (
                "The application remains conditional on the external result covering the current domain."
            ),
        }
        conclusion["side_conditions"] = [
            {
                "condition": "The external reflexivity statement covers the current presentation of x.",
                "status": "open",
            }
        ]
        annotations["conclusions"][0]["statement_status"] = "conditional"
        output = self.output

        self.compile(annotations, output)

        compiled = read_json(output)
        errors, _ = proofcheck.check_ledger_data(output, True)
        self.assertEqual([], errors)
        final_step = next(row for row in compiled["steps"] if row["id"] == "S003.1")
        self.assertEqual(
            [
                ("side_condition", "SC001"),
                ("dependency", "D001"),
                ("risk_check", "domain"),
            ],
            [(row["kind"], row["reference"]) for row in final_step["conditions"]],
        )
        result = compiled["review"]["conclusion_results"][0]
        self.assertEqual("conditionally_verified", result["dependency_closure"])
        self.assertEqual("conditional", result["argument_status"])
        self.assertEqual("conditionally_verified", compiled["review"]["unit_status"])

    def test_authored_zero_input_failure_is_preserved_and_propagated(self) -> None:
        annotations = self.annotations()
        conclusion = annotations["steps"][1]
        conclusion["inputs"] = []
        conclusion["status"] = "gap"
        conclusion["issue_ids"] = ["I-001"]
        conclusion["failure"] = {
            "kind": "missing_premise",
            "issue_id": "I-001",
            "evidence": (
                "The source invokes reflexivity without establishing that its object lies in the required domain."
            ),
        }
        annotations["conclusions"][0]["statement_status"] = "not_established"
        annotations["conclusions"][0]["issue_ids"] = []
        annotations["review"]["source_reference_dispositions"][0][
            "disposition"
        ] = "unresolved"
        annotations["review"]["source_reference_dispositions"][0][
            "evidence"
        ] = (
            "The failed zero-input audit leaves the source reference "
            "unresolved instead of treating it as an established premise."
        )
        output = self.output

        self.compile(annotations, output)

        compiled = read_json(output)
        errors, _ = proofcheck.check_ledger_data(output, True)
        self.assertEqual([], errors)
        move = compiled["steps"][2]["inference"]["moves"][0]
        self.assertEqual(conclusion["failure"], move["failure"])
        result = compiled["review"]["conclusion_results"][0]
        self.assertEqual(["I-001"], result["issue_ids"])
        self.assertEqual("gap", compiled["review"]["unit_status"])

    def test_source_occurrence_links_are_mirrored_to_generated_premise_ids(
        self,
    ) -> None:
        annotations = self.annotations()
        occurrence = proofcheck.scan_span_evidence(
            self.paper, 1, 6, self.base
        )["reference_occurrences"][0]
        premise = annotations["steps"][1]["inputs"][0]
        premise["source_reference_id"] = occurrence["target"]
        premise["source_reference_occurrence_id"] = occurrence["occurrence_id"]
        annotations["review"]["source_reference_dispositions"] = [
            {
                "occurrence_id": occurrence["occurrence_id"],
                "target": occurrence["target"],
                "command": occurrence["command"],
                "disposition": "obligation_context",
                "evidence": (
                    "The occurrence identifies the locked theorem context supplying the quantified domain."
                ),
            }
        ]
        output = self.output

        self.compile(annotations, output)

        compiled = read_json(output)
        errors, _ = proofcheck.check_ledger_data(output, True)
        self.assertEqual([], errors)
        disposition = compiled["review"]["source_reference_dispositions"][0]
        self.assertEqual(
            [{"step_id": "S003", "premise_id": "P001"}],
            disposition["premise_links"],
        )
