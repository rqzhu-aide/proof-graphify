from __future__ import annotations

import argparse
import base64
import contextlib
import importlib.util
import io
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "proofcheck.py"
SPEC = importlib.util.spec_from_file_location("proofcheck", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Cannot load {SCRIPT}")
proofcheck = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(proofcheck)


def write_json(path: Path, data: dict) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def make_normalization_checks() -> list[dict[str, str]]:
    statuses = {
        "quantifiers_and_domains": (
            "checked",
            "The universal quantifier and real-number domain are explicit.",
        ),
        "probability_model": (
            "not_applicable",
            "The claim contains no random quantity or probability statement.",
        ),
        "hypotheses": (
            "not_applicable",
            "The theorem has no hypotheses beyond its quantified domain.",
        ),
        "definitions": (
            "checked",
            "Equality has its standard meaning on the stated domain.",
        ),
        "conclusion": (
            "checked",
            "The normalized conclusion is exactly x equals x.",
        ),
        "uniformity": (
            "not_applicable",
            "The claim has no indexed convergence or bound.",
        ),
        "regime": (
            "not_applicable",
            "The claim is neither finite-sample nor asymptotic.",
        ),
        "constant_dependencies": (
            "not_applicable",
            "No hidden or named constants occur.",
        ),
    }
    return [
        {"aspect": aspect, "status": status, "evidence": evidence}
        for aspect, (status, evidence) in statuses.items()
    ]


def make_risk_checks() -> list[dict[str, str]]:
    statuses = {
        "domain": (
            "passed",
            "The only object is the real number x from the locked statement.",
        ),
        "dimension": (
            "not_applicable",
            "No vector, matrix, or dimension-sensitive operation occurs.",
        ),
        "sign": (
            "not_applicable",
            "No inequality, monotonicity, or sign argument occurs.",
        ),
        "constant": (
            "not_applicable",
            "No explicit or hidden constant occurs.",
        ),
        "rate": (
            "not_applicable",
            "No stochastic or asymptotic rate occurs.",
        ),
        "probability": (
            "not_applicable",
            "No event, measure, conditioning, or independence claim occurs.",
        ),
        "quantifier": (
            "passed",
            "The move applies to the arbitrary x fixed by the theorem statement.",
        ),
        "limit": (
            "not_applicable",
            "No limiting or exchange operation occurs.",
        ),
    }
    return [
        {"aspect": aspect, "status": status, "evidence": evidence}
        for aspect, (status, evidence) in statuses.items()
    ]


GLOBAL_CONSISTENCY_ASPECTS = (
    "source_resolution",
    "assumption_and_definition_propagation",
    "notation_domain_and_dimension",
    "constants_and_rates",
    "probability_events_and_conditioning",
    "quantifiers_uniformity_and_regime",
    "use_site_sufficiency",
    "issue_propagation",
)


def make_global_consistency_checks() -> list[dict]:
    return [
        {
            "aspect": aspect,
            "status": "passed",
            "evidence": f"The clean focused audit passed the {aspect} check.",
            "affected_units": [],
            "issue_ids": [],
        }
        for aspect in GLOBAL_CONSISTENCY_ASPECTS
    ]


def make_compatibility_checks() -> list[dict]:
    return [
        {
            "aspect": aspect,
            "status": "passed",
            "evidence": f"The dependency is compatible on the {aspect} aspect.",
            "issue_ids": [],
        }
        for aspect in proofcheck.NORMALIZATION_ASPECTS
    ]



def make_repair_search(severity: str) -> dict:
    if severity == "S0":
        return {
            "strategies": [
                {
                    "name": "union_bound",
                    "attempt": (
                        "Bound the failure event by the sum of the per-index "
                        "tail probabilities under the stated hypotheses."
                    ),
                    "outcome": "failed",
                    "evidence": (
                        "The available per-index bound is not summable over "
                        "the growing index range, so the union bound does not "
                        "close the step."
                    ),
                },
                {
                    "name": "weakened_conclusion_variant",
                    "attempt": (
                        "Derive the stated conclusion for a fixed finite index "
                        "range instead of the growing range."
                    ),
                    "outcome": "failed",
                    "evidence": (
                        "The fixed-range variant is provable but does not "
                        "support the stated main claim at its use site."
                    ),
                },
            ],
            "conclusion": "no_local_repair_found",
        }
    return {
        "strategies": [
            {
                "name": "direct_repair",
                "attempt": (
                    "Close the recorded failure directly from the stated "
                    "hypotheses without new assumptions."
                ),
                "outcome": "failed",
                "evidence": (
                    "The stated hypotheses do not supply the missing control "
                    "identified at the failed move."
                ),
            },
            {
                "name": "strengthened_hypothesis_variant",
                "attempt": (
                    "Add an explicit uniform bound strong enough to close the "
                    "failed move, and re-derive the conclusion from it."
                ),
                "outcome": "survives_local_inspection",
                "evidence": (
                    "With the strengthened hypothesis the failed move closes "
                    "locally; the full recheck closure remains required."
                ),
            },
        ],
        "conclusion": "candidate_repair_exists",
    }


class FinalizationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.paper = self.base / "paper.tex"
        self.definitions = self.base / "definitions.tex"
        self.definitions.write_text(
            "\\newtheorem{lemma}{Lemma}\n", encoding="utf-8", newline="\n"
        )
        self.paper.write_text(
            "\\input{definitions}\n"
            "\\begin{lemma}\\label{lem:main}\n"
            "$x=x$ for every real $x$.\\label{eq:reflexive}\n"
            "\\end{lemma}\n"
            "\\begin{proof}\n"
            "The conclusion follows by reflexivity; see \\ref{eq:reflexive} and \\cite{smith}.\n"
            "\\end{proof}\n",
            encoding="utf-8",
            newline="\n",
        )
        self.audit = self.base / "audit-root"
        with contextlib.redirect_stdout(io.StringIO()):
            proofcheck.cmd_scaffold(
                argparse.Namespace(paper=self.paper, output=self.audit, report_format="markdown")
            )
        # These fixtures exercise the historical Markdown/challenge contract.
        # New HTML and initial-response contracts have separate integration tests.
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        manifest["protocol"].pop("challenge_contract_version", None)
        write_json(manifest_path, manifest)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def make_complete_audit(self) -> Path:
        ledger_path = (
            self.audit / "audit" / "04_local_checks" / "lem-main.ledger.json"
        )
        with contextlib.redirect_stdout(io.StringIO()):
            proofcheck.cmd_extract(
                argparse.Namespace(
                    file=self.paper,
                    start=2,
                    end=7,
                    statement_file=self.paper,
                    statement_start=2,
                    statement_end=4,
                    separate_statement_reason=None,
                    unit_id="lem:main",
                    output=ledger_path,
                    force=False,
                )
        )
        ledger = read_json(ledger_path)
        inventory = read_json(
            self.audit / "audit" / "01_index" / "theorem_inventory.json"
        )
        source_occurrences = inventory["units"][0]["reference_occurrences"]
        source_occurrence = source_occurrences[0] if source_occurrences else None
        conclusion_span = proofcheck.locked_span(
            self.paper, 2, 4, ledger_path.parent
        )
        ledger["obligation"] = {
            "statement_spans": [conclusion_span],
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
                    "source_spans": [dict(conclusion_span)],
                    "applies_under": ["/quantifier_scope"],
                    "normalization": {
                        "status": "checked",
                        "evidence": (
                            "The source states the reflexive equality under the "
                            "universal real-number quantifier."
                        ),
                    },
                }
            ],
            "uniformity": "not_applicable",
            "regime": "not_applicable",
            "constant_dependencies": ["none"],
            "context_spans": [],
            "normalization_checks": make_normalization_checks(),
        }
        ledger["review"] = {
            "unit_status": "verified",
            "conclusion_step_id": "S003",
            "conclusion_results": [
                {
                    "conclusion_id": "C001",
                    "support": {"step_id": "S003", "move_id": "M001"},
                    "contract_fidelity": "verified",
                    "argument_status": "valid",
                    "statement_status": "established",
                    "dependency_closure": "verified",
                    "use_site_sufficiency": "not_applicable",
                    "dependency_use_ids": [],
                    "issue_ids": [],
                }
            ],
            "contract_fidelity": "verified",
            "argument_status": "valid",
            "statement_status": "established",
            "dependency_closure": "verified",
            "use_site_sufficiency": "not_applicable",
            "explicit_assumptions": [],
            "inherited_assumptions": [],
            "direct_dependencies": [],
            "source_reference_dispositions": (
                [
                    {
                        "occurrence_id": source_occurrence["occurrence_id"],
                        "id": source_occurrence["target"],
                        "target": source_occurrence["target"],
                        "command": source_occurrence["command"],
                        "disposition": "non_load_bearing",
                        "evidence": "The proof is reconstructed from reflexivity; this self-reference supplies no premise."
                    }
                ]
                if source_occurrence is not None
                else []
            ),
            "citation_dispositions": [
                {
                    "key": "smith",
                    "disposition": "bibliographic_only",
                    "evidence": "The citation supplies attribution and no proof premise."
                }
            ],
            "use_sites": [],
            "verification_basis": [
                "Exact source ledger and direct reconstruction"
            ],
            "reviewer_notes": [],
        }
        ledger["independent_check"] = {
            "required": True,
            "status": "agreed",
            "independence_level": "fresh_context_same_model",
            "challenger_verdict": "verified",
            "reconciled_verdict": "verified",
            "artifact": "audit/05_adversarial/lem-main-challenge.md",
            "covered_issue_ids": [],
            "source_snapshot_sha256": "0" * 64,
            "challenged_ledger_sha256": "0" * 64,
            "challenge_context_sha256": "0" * 64,
            "challenge_artifact_sha256": "0" * 64,
            "issue_assessments": [],
            "generated_utc": "2026-08-09T00:00:00+00:00",
            "disagreements": [],
            "resolution": "",
        }
        ledger["steps"] = [
            {
                "id": "S001",
                "source_unit_id": "U001",
                "kind": "statement",
                "goal": "Identify the exact theorem obligation.",
                "restatement": "For every real x, x equals x.",
                "premise_uses": [],
                "dependencies": [],
                "inference": {
                    "moves": [],
                    "conclusion_move": None,
                },
                "checks": {
                    "literal": "The quantifier, domain, and equality are explicit.",
                    "atomicity": {
                        "status": "non_inferential",
                        "evidence": (
                            "This row source-locks the theorem statement and derives "
                            "no new claim."
                        ),
                    },
                    "adversarial": [
                        "The normalized contract has the same quantifier and domain."
                    ],
                },
                "side_conditions": [],
                "risk_checks": make_risk_checks(),
                "status": "verified",
                "issue_ids": [],
            },
            {
                "id": "S002",
                "source_unit_id": "U002",
                "kind": "other",
                "status": "non_substantive",
                "issue_ids": [],
            },
            {
                "id": "S003",
                "source_unit_id": "U003",
                "support_role": "derivation",
                "kind": "conclusion",
                "goal": "Establish x = x for an arbitrary real x.",
                "restatement": "x equals x",
                "premise_uses": [
                    {
                        "id": "P001",
                        "role": "fact",
                        "claim": "For every real x.",
                        "origin": {
                            "kind": "obligation",
                            "reference": "/quantifier_scope",
                            "anchor": {
                                "kind": "statement_span",
                                "index": 1,
                            },
                        },
                        "evidence": (
                            "The locked theorem statement supplies this exact "
                            "quantifier scope."
                        ),
                    }
                ],
                "dependencies": [],
                "inference": {
                    "moves": [
                        {
                            "id": "M001",
                            "claim": "x equals x",
                            "rule": "Reflexivity of equality",
                            "premise_ids": ["P001"],
                            "prior_move_ids": [],
                            "justification": (
                                "Reflexivity gives x = x for the arbitrary real x."
                            ),
                        }
                    ],
                    "conclusion_move": "M001",
                },
                "checks": {
                    "literal": "The line claims that reflexivity closes the goal.",
                    "atomicity": {
                        "status": "single_move",
                        "evidence": "The line contains one application of reflexivity.",
                    },
                    "adversarial": [
                        "No boundary value or domain element violates reflexivity."
                    ],
                },
                "side_conditions": [],
                "risk_checks": make_risk_checks(),
                "status": "verified",
                "issue_ids": [],
            },
            {
                "id": "S004",
                "source_unit_id": "U004",
                "kind": "other",
                "status": "non_substantive",
                "issue_ids": [],
            },
        ]
        ledger["schema_version"] = 5
        ledger["evidence_contract_version"] = proofcheck.EVIDENCE_CONTRACT_VERSION
        ledger["source_units"] = [
            {
                "id": "U001",
                "lines": [2, 4],
                "kind": "continued_sentence",
                "source_sha256": proofcheck.source_span_sha256(
                    self.paper, 2, 4
                ),
                "partition_evidence": (
                    "Lines 2-4 are the single formal statement environment."
                ),
            },
            {
                "id": "U002",
                "lines": [5, 5],
                "kind": "non_substantive",
                "source_sha256": proofcheck.source_span_sha256(
                    self.paper, 5, 5
                ),
                "partition_evidence": "Line 5 only opens the proof environment.",
            },
            {
                "id": "U003",
                "lines": [6, 6],
                "kind": "one_line",
                "source_sha256": proofcheck.source_span_sha256(
                    self.paper, 6, 6
                ),
                "partition_evidence": (
                    "Line 6 is one source sentence containing one inference."
                ),
            },
            {
                "id": "U004",
                "lines": [7, 7],
                "kind": "non_substantive",
                "source_sha256": proofcheck.source_span_sha256(
                    self.paper, 7, 7
                ),
                "partition_evidence": "Line 7 only closes the proof environment.",
            },
        ]
        write_json(ledger_path, ledger)

        challenge = self.audit / "audit" / "05_adversarial" / "lem-main-challenge.md"
        challenge.write_text(
            "# Blinded challenge\n\n"
            "The blinded reconstruction was checked line by line; "
            "its verdict is verified.\n",
            encoding="utf-8",
            newline="\n",
        )
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        manifest["audit_scope"] = {
            "status": "reviewed",
            "depth": "focused",
            "overall_assessment": "no_defect_found",
            "in_scope_units": ["lem:main"],
            "target_units": ["lem:main"],
            "critical_units": ["lem:main"],
            "in_scope_interfaces": [],
            "excluded_units": [],
            "inventory_overrides": [],
            "source_or_parser_limits": [],
        }
        manifest["completion"] = {
            "inventory_reviewed": True,
            "parser_warnings_reviewed": True,
            "dependency_registry_reviewed": True,
            "method_interface_registry_reviewed": True,
            "global_consistency_pass": {
                "status": "completed",
                "evidence": ["Focused global consistency pass completed."],
                "checks": make_global_consistency_checks(),
            },
            "adversarial_pass": {
                "status": "completed",
                "evidence": ["Boundary and weakened-assumption checks completed."],
            },
            "final_report_ready": True,
        }
        write_json(manifest_path, manifest)

        inventory_path = (
            self.audit / "audit" / "01_index" / "theorem_inventory.json"
        )
        dependency_registry_path = (
            self.audit
            / "audit"
            / "03_dependencies"
            / "DEPENDENCY_REGISTRY.json"
        )
        dependency_registry = read_json(dependency_registry_path)
        dependency_registry["closure_contract_version"] = (
            proofcheck.CLOSURE_CONTRACT_VERSION
        )
        dependency_registry["review"] = {
            "status": "reviewed",
            "source_snapshot_sha256": manifest["source_snapshot"]["sha256"],
            "inventory_sha256": proofcheck.sha256_file(inventory_path),
            "in_scope_units": ["lem:main"],
            "evidence": [
                "The dependency registry was reconciled against the locked "
                "source, reviewed inventory, and focused audit scope."
            ],
        }
        dependency_registry["internal_uses"] = []
        write_json(dependency_registry_path, dependency_registry)

        interface_registry_path = (
            self.audit
            / "audit"
            / "03_dependencies"
            / "METHOD_INTERFACE_REGISTRY.json"
        )
        interface_registry = read_json(interface_registry_path)
        interface_registry["scope"] = {
            "status": "reviewed",
            "trigger": "not_required",
            "reason": "The focused reflexivity proof has no estimated method interface.",
        }
        write_json(interface_registry_path, interface_registry)

        self.install_calibration()
        primary_packet = proofcheck.build_context_packet(
            self.audit, "lem:main", "primary"
        )
        ledger = read_json(ledger_path)
        ledger["work_context_sha256"] = primary_packet[
            "work_context_sha256"
        ]
        write_json(ledger_path, ledger)
        self.seal_schema5_challenge(ledger_path, read_json(ledger_path))
        final_report = self.audit / "audit" / "06_reports" / "FINAL_REPORT.md"
        final_report.write_text(
            "# Final Proof-Check Report\n\n"
            "## Summary\n\n"
            "- Overall judgment:\n"
            "- Main reason:\n"
            "- Impact on paper conclusions/results:\n"
            "- Repair options and difficulty:\n\n"
            "## Results and impact\n\n"
            "Pending generation.\n\n"
            "## Findings and repairs\n\n"
            "No issues.\n\n"
            "## Scope and assurance\n\n"
            "- Overall assessment code: no_defect_found\n"
            "- Target results: lem:main\n"
            "- Checked scope: lem:main\n"
            "- Source revision: scaffolded source snapshot.\n"
            f"- Skill version: {proofcheck.SKILL_VERSION}\n"
            f"- Artifact schema version: {proofcheck.SCHEMA_VERSION}\n"
            f"- Evidence contract version: {proofcheck.EVIDENCE_CONTRACT_VERSION}\n"
            "- Method-interface schema version: 1\n"
            f"- Closure contract version: {proofcheck.CLOSURE_CONTRACT_VERSION}\n"
            f"- Source snapshot ID: {manifest['source_snapshot']['sha256']}\n"
            "- Finalization record: audit/06_reports/FINALIZATION.json\n"
            "- Highest-consequence issue: none\n"
            "- Final confidence: high within the declared non-formal scope.\n"
            "- Files and results checked: paper.tex and lem:main.\n"
            "- Results not checked: none\n"
            "- External results checked: none\n"
            "- External results not checked: none\n"
            "- Tooling, extraction, or rendering limitations: none\n"
            "- Independent check levels: fresh_context_same_model\n"
            "- Declared external deliverables: none\n\n"
            "This is a non-formal audit. This is not a kernel-checked proof certificate.\n\n"
            "### Independent verification\n\n"
            "| Result | Check status | Independence | Challenger verdict | Final verdict | Reconciliation |\n"
            "|---|---|---|---|---|---|\n"
            "| lem:main | agreed | fresh_context_same_model | verified | verified | agreed |\n\n"
            "### Declared external deliverables\n\n"
            "None.\n",
            encoding="utf-8",
            newline="\n",
        )

        progress_path = self.audit / "PROGRESS.json"
        progress = read_json(progress_path)
        progress["status"] = "complete"
        progress["current_pass"] = 8
        progress["source_snapshot_sha256"] = manifest["source_snapshot"]["sha256"]
        progress["active_unit"] = None
        progress["completed_units"] = ["lem:main"]
        progress["conditional_units"] = []
        progress["blocked_units"] = {}
        progress["not_started_units"] = []
        progress["open_high_priority_issues"] = []
        progress["source_or_parser_limits"] = []
        progress["next_action"] = (
            "Audit complete; rerun finalization after any source or artifact change."
        )
        write_json(progress_path, progress)
        output = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(stderr):
            report_status = proofcheck.cmd_issues(
                argparse.Namespace(
                    root=self.audit,
                    write_summary=True,
                    write_report_views=True,
                    final=True,
                )
            )
        self.assertEqual(0, report_status, stderr.getvalue())
        return ledger_path

    def install_calibration(self, root: Path | None = None) -> None:
        audit_root = self.audit if root is None else root
        calibration_path = (
            audit_root / "audit" / "07_runtime" / "CALIBRATION.json"
        )
        calibration_path.parent.mkdir(parents=True, exist_ok=True)
        manifest = read_json(audit_root / "AUDIT_MANIFEST.json")
        responses = [
            {
                "canary_id": "bounded-drift",
                "argument_status": "invalid",
                "statement_status": "refuted",
                "defect_lines": [15],
                "justification": (
                    "The recurrence permits an equality sequence whose product "
                    "grows without bound, so the proof and conclusion fail."
                ),
            },
            {
                "canary_id": "finite-max",
                "argument_status": "valid",
                "statement_status": "established",
                "defect_lines": [],
                "justification": (
                    "The maximum is over a fixed finite set, so the displayed "
                    "union bound and finite-sum limit establish the conclusion."
                ),
            },
        ]
        results = []
        for response in responses:
            key = proofcheck.load_canary_key(response["canary_id"])
            passed, reasons, got = proofcheck.grade_canary_response(response, key)
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
                        "session_id": "cal-001",
                        "graded_utc": "2026-08-09T00:00:00+00:00",
                        "checker_binding": {
                            "checker_profile_id": "checker-test-profile",
                            "checker_configuration_id": "proofcheck-test-config",
                            "checker_context_id": "fresh-context-cal-001",
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

    def add_snapshot_source(self, path: Path, ledger_path: Path) -> None:
        """Register an additional authoritative source (as --additional-source
        would) and re-stamp every fixture binding of the snapshot hash."""
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        row = {
            "file": proofcheck.relative_or_absolute(path, self.audit),
            "sha256": proofcheck.sha256_file(path),
        }
        files = manifest["source_snapshot"]["files"]
        files[:] = [
            record
            for record in files
            if record.get("file") != row["file"]
        ]
        files.append(row)
        old_sha = manifest["source_snapshot"]["sha256"]
        new_sha = proofcheck.canonical_sha256(files)
        manifest["source_snapshot"]["sha256"] = new_sha
        additional = manifest["source_discovery"]["additional_files"]
        additional[:] = [
            record
            for record in additional
            if record.get("file") != row["file"]
        ]
        if True:
            additional.append(
                {
                    **row,
                    "reason": "Load-bearing bibliography identity source.",
                    "evidence": (
                        "The bound citation entries live in this file, so it "
                        "belongs to the authoritative source closure."
                    ),
                }
            )
        write_json(manifest_path, manifest)
        paper = proofcheck.resolve_stored_path(
            manifest["paper_file"], self.audit
        )
        closure = proofcheck.discover_source_closure(
            paper,
            additional_files=[
                proofcheck.resolve_stored_path(record["file"], self.audit)
                for record in additional
            ],
            fls_file=None,
            project_root=paper.parent,
        )
        fresh_cross_references = proofcheck.scan_cross_references(
            paper,
            source_files=closure["files"],
            source_warnings=closure["warnings"],
        )
        index_dir = self.audit / "audit" / "01_index"
        write_json(
            index_dir / "cross_reference_audit.json", fresh_cross_references
        )
        (index_dir / "cross_reference_audit.md").write_text(
            proofcheck.crossref_markdown(fresh_cross_references),
            encoding="utf-8",
            newline="\n",
        )
        for artifact in [
            self.audit / "PROGRESS.json",
            ledger_path,
            self.audit / "audit" / "06_reports" / "FINAL_REPORT.md",
            index_dir / "theorem_inventory.json",
            index_dir / "theorem_inventory.md",
            self.audit
            / "audit"
            / "03_dependencies"
            / "DEPENDENCY_REGISTRY.json",
        ]:
            if artifact.is_file():
                content = artifact.read_text(encoding="utf-8")
                artifact.write_text(
                    content.replace(old_sha, new_sha),
                    encoding="utf-8",
                    newline="\n",
                )
        self.install_calibration()
        ledger = read_json(ledger_path)
        old_challenge = dict(ledger.get("independent_check", {}))
        if old_challenge.get("required") is True:
            self.seal_schema5_challenge(
                ledger_path,
                ledger,
                covered_issue_ids=old_challenge.get("covered_issue_ids"),
            )
            new_challenge = read_json(ledger_path)["independent_check"]
            report_path = (
                self.audit / "audit" / "06_reports" / "FINAL_REPORT.md"
            )
            if report_path.is_file():
                report = report_path.read_text(encoding="utf-8")
                for field in (
                    "source_snapshot_sha256",
                    "challenged_ledger_sha256",
                    "challenge_context_sha256",
                    "challenge_artifact_sha256",
                    "generated_utc",
                ):
                    report = report.replace(
                        str(old_challenge.get(field)),
                        str(new_challenge.get(field)),
                    )
                report_path.write_text(report, encoding="utf-8", newline="\n")

    def refresh_dependency_review(self) -> dict:
        manifest = read_json(self.audit / "AUDIT_MANIFEST.json")
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
        registry["closure_contract_version"] = (
            proofcheck.CLOSURE_CONTRACT_VERSION
        )
        registry["review"] = {
            "status": "reviewed",
            "source_snapshot_sha256": manifest["source_snapshot"]["sha256"],
            "inventory_sha256": proofcheck.sha256_file(inventory_path),
            "in_scope_units": list(manifest["audit_scope"]["in_scope_units"]),
            "evidence": [
                "The dependency registry was reconciled against the locked "
                "source, reviewed inventory, and declared audit scope."
            ],
        }
        registry.setdefault("internal_uses", [])
        write_json(registry_path, registry)
        return registry

    def refresh_report_views(self) -> None:
        output = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(stderr):
            status = proofcheck.cmd_issues(
                argparse.Namespace(
                    root=self.audit,
                    write_summary=True,
                    write_report_views=True,
                    final=True,
                )
            )
        self.assertEqual(0, status, stderr.getvalue())

    def attach_result_dependency(self, ledger_path: Path, dependency: dict) -> None:
        ledger = read_json(ledger_path)
        step = ledger["steps"][2]
        step["dependencies"] = [dict(dependency)]
        step["premise_uses"].append(
            {
                "id": "P002",
                "role": "fact",
                "claim": dependency["needed_form"],
                "origin": {
                    "kind": dependency["kind"],
                    "reference": dependency["use_id"],
                },
                "evidence": (
                    "The dependency supplies exactly the recorded needed form."
                ),
            }
        )
        step["inference"]["moves"][0]["premise_ids"].append("P002")
        ledger["review"]["direct_dependencies"] = [dict(dependency)]
        ledger["review"]["conclusion_results"][0]["dependency_use_ids"] = [
            dependency["use_id"]
        ]
        write_json(ledger_path, ledger)

    def install_internal_dependency(self, ledger_path: Path) -> tuple[Path, dict]:
        prior_path = ledger_path.with_name("lem-prior.ledger.json")
        prior_source = self.base / "prior.tex"
        prior_source.write_text(
            "\\begin{reviewedresult}\\label{lem:prior}\n"
            "Equality is reflexive on the real numbers.\n"
            "\\end{reviewedresult}\n"
            "\\begin{proof}\n"
            "This follows directly from reflexivity of equality.\n"
            "\\end{proof}\n",
            encoding="utf-8",
            newline="\n",
        )
        self.add_snapshot_source(prior_source, ledger_path)
        prior = read_json(ledger_path)
        prior["unit_id"] = "lem:prior"
        prior["independent_check"]["artifact"] = (
            "audit/05_adversarial/lem-prior-challenge.md"
        )
        prior_lines = prior_source.read_text(encoding="utf-8").splitlines()
        prior_statement = " ".join(prior_lines[:3])
        prior_span = proofcheck.locked_span(
            prior_source, 1, 3, prior_path.parent
        )
        prior["source"] = {
            "file": proofcheck.relative_or_absolute(
                prior_source, prior_path.parent
            ),
            "start_line": 1,
            "end_line": 6,
            "unit_sha256": proofcheck.source_span_sha256(
                prior_source, 1, 6
            ),
            "coverage_mode": "statement_and_proof",
            "separate_statement_reason": "",
        }
        prior["source_lines"] = [
            {
                "line": line_number,
                "text": text,
                "sha256": proofcheck.sha256_text(text),
            }
            for line_number, text in enumerate(prior_lines, 1)
        ]
        prior["obligation"]["statement_spans"] = [prior_span]
        prior["obligation"]["conclusion"] = (
            "Equality is reflexive on the real numbers"
        )
        prior["obligation"]["conclusions"][0]["claim"] = (
            "Equality is reflexive on the real numbers"
        )
        prior["obligation"]["conclusions"][0]["source_spans"] = [
            dict(prior_span)
        ]
        prior_step = json.loads(json.dumps(prior["steps"][2]))
        prior_step["id"] = "S001"
        prior_step["source_unit_id"] = "U001"
        prior_step["goal"] = "Establish reflexivity of real-number equality."
        prior_step["restatement"] = (
            "Equality is reflexive on the real numbers"
        )
        prior_step["inference"]["moves"][0]["claim"] = prior_step[
            "restatement"
        ]
        prior["steps"] = [prior_step]
        prior["source_units"] = [
            {
                "id": "U001",
                "lines": [1, 6],
                "kind": "continued_sentence",
                "source_sha256": proofcheck.source_span_sha256(
                    prior_source, 1, 6
                ),
                "partition_evidence": (
                    "Lines 1-6 contain the complete statement and proof of lem:prior."
                ),
            }
        ]
        prior["review"]["conclusion_step_id"] = "S001"
        prior["review"]["conclusion_results"][0]["support"]["step_id"] = "S001"
        prior["review"]["source_reference_dispositions"] = []
        prior["review"]["citation_dispositions"] = []
        write_json(prior_path, prior)

        inventory_path = (
            self.audit / "audit" / "01_index" / "theorem_inventory.json"
        )
        inventory = read_json(inventory_path)
        prior_unit = json.loads(json.dumps(inventory["units"][0]))
        prior_unit["id"] = "lem:prior"
        prior_unit["label"] = "lem:prior"
        prior_unit["environment"] = "lemma"
        prior_unit["proof_required"] = True
        prior_unit["statement"] = {
            "file": proofcheck.relative_or_absolute(
                prior_source, self.paper.parent
            ),
            "start_line": 1,
            "end_line": 3,
        }
        prior_unit["statement_excerpt"] = prior_statement
        prior_unit["proof"] = {
            "file": proofcheck.relative_or_absolute(
                prior_source, self.paper.parent
            ),
            "start_line": 4,
            "end_line": 6,
        }
        prior_unit["proof_redirects"] = []
        prior_unit["proof_association"] = {
            "status": "associated",
            "method": "reviewed_manual",
            "target": "lem:prior",
            "evidence_occurrence_ids": [],
        }
        prior_unit["reference_occurrences"] = []
        prior_unit["dependencies"] = []
        prior_unit["candidate_internal_dependencies"] = []
        prior_unit["citations"] = []
        inventory["units"].append(prior_unit)
        write_json(inventory_path, inventory)

        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        manifest["audit_scope"]["in_scope_units"] = ["lem:main", "lem:prior"]
        manifest["audit_scope"]["inventory_overrides"] = [
            {
                "unit_id": "lem:prior",
                "kind": "manual_unit",
                "reason": (
                    "The synthetic prior lemma is added to exercise internal "
                    "dependency closure."
                ),
                "evidence": (
                    "Its exact statement, proof, association, and references are "
                    "recorded in the reviewed inventory row."
                ),
                "reviewed_unit_sha256": proofcheck.canonical_sha256(prior_unit),
            }
        ]
        paper = proofcheck.resolve_stored_path(manifest["paper_file"], self.audit)
        closure = proofcheck.discover_source_closure(
            paper,
            additional_files=[
                proofcheck.resolve_stored_path(row["file"], self.audit)
                for row in manifest["source_discovery"]["additional_files"]
            ],
            project_root=paper.parent,
        )
        fresh_inventory = proofcheck.scan_formal_units(
            paper,
            source_files=closure["files"],
            source_warnings=closure["warnings"],
        )
        fresh_cross_references = proofcheck.scan_cross_references(
            paper,
            source_files=closure["files"],
            source_warnings=closure["warnings"],
        )
        parser_warnings = sorted(
            set(closure["warnings"])
            | set(fresh_inventory["warnings"])
            | set(fresh_cross_references["warnings"])
        )
        manifest["parser_warnings"] = parser_warnings
        manifest["parser_warning_reviews"] = [
            {
                "warning": warning,
                "disposition": "confirmed_non_load_bearing",
                "affected_units": ["lem:prior"],
                "evidence": (
                    "The warning belongs to the intentionally parser-omitted "
                    "manual unit whose exact statement and complete proof are "
                    "bound by the manual_unit override."
                ),
            }
            for warning in parser_warnings
        ]
        write_json(manifest_path, manifest)

        progress_path = self.audit / "PROGRESS.json"
        progress = read_json(progress_path)
        progress["completed_units"] = ["lem:main", "lem:prior"]
        write_json(progress_path, progress)

        report_path = self.audit / "audit" / "06_reports" / "FINAL_REPORT.md"
        report = report_path.read_text(encoding="utf-8")
        report = report.replace(
            "- Checked scope: lem:main",
            "- Checked scope: lem:main, lem:prior",
        )
        report = report.replace(
            "- Files and results checked: paper.tex and lem:main.",
            "- Files and results checked: paper.tex, lem:main, and lem:prior.",
        )
        report_path.write_text(report, encoding="utf-8", newline="\n")

        dependency = {
            "id": "lem:prior",
            "use_id": "D001",
            "kind": "internal_result",
            "conclusion_id": "C001",
            "status": "verified",
            "needed_form": prior["obligation"]["conclusion"],
            "compatibility_check": (
                "The required result has the same quantifiers, domain, and conclusion."
            ),
        }
        self.attach_result_dependency(ledger_path, dependency)
        use = {
            "dependent_unit": "lem:main",
            "use_id": dependency["use_id"],
            "dependency_id": "lem:prior",
            "dependency_conclusion_id": dependency["conclusion_id"],
            "step_ids": ["S003"],
            "needed_form": dependency["needed_form"],
            "dependency_conclusion": prior["obligation"]["conclusion"],
            "dependency_contract_sha256": proofcheck.canonical_sha256(
                proofcheck.conclusion_contract_payload(
                    prior["obligation"], dependency["conclusion_id"]
                )
            ),
            "compatibility_check": dependency["compatibility_check"],
            "compatibility_checks": make_compatibility_checks(),
            "status": "verified",
            "issue_ids": [],
        }
        registry = self.refresh_dependency_review()
        registry["internal_uses"] = [use]
        registry_path = (
            self.audit
            / "audit"
            / "03_dependencies"
            / "DEPENDENCY_REGISTRY.json"
        )
        write_json(registry_path, registry)
        self.seal_live_challenges()
        self.refresh_report_views()
        return prior_path, use

    def install_external_dependency(
        self,
        ledger_path: Path,
        *,
        reconcile_report_views: bool = True,
    ) -> tuple[Path, dict]:
        source_path = self.base / "external-reflexivity.txt"
        source_path.write_text(
            "External Result 1\nEquality is reflexive on the real numbers.\n",
            encoding="utf-8",
            newline="\n",
        )
        exact_statement = "Equality is reflexive on the real numbers."
        source_evidence = [
            {
                "file": proofcheck.relative_or_absolute(source_path, self.audit),
                "sha256": proofcheck.sha256_file(source_path),
                "locator": "External Result 1, line 2",
                "role": "authoritative_theorem_source",
            }
        ]
        dependency = {
            "id": "ext:reflexivity",
            "use_id": "D001",
            "kind": "external_result",
            "status": "verified",
            "needed_form": "Equality is reflexive on the real numbers",
            "compatibility_check": (
                "The external conclusion has the same domain and exact needed form."
            ),
        }
        self.attach_result_dependency(ledger_path, dependency)
        ledger = read_json(ledger_path)
        ledger["review"]["citation_dispositions"][0] = {
            "key": "smith",
            "disposition": "external_result",
            "dependency_id": dependency["id"],
            "dependency_use_id": dependency["use_id"],
            "evidence": (
                "The citation supplies the exact external reflexivity result used in S003."
            ),
        }
        write_json(ledger_path, ledger)

        core_contract = {
            "source_identity": "doi:10.0000/reflexivity",
            "version": "version 1",
            "theorem_location": "External Result 1",
            "exact_statement": exact_statement,
            "source_evidence": source_evidence,
        }
        bibliography_path = self.base / "external-reflexivity.bib"
        bibliography_path.write_text(
            "@article{smith,\n"
            "  author = {Smith, A.},\n"
            "  title = {Reflexivity of equality},\n"
            "  year = {2026}\n"
            "}\n",
            encoding="utf-8",
            newline="\n",
        )
        self.add_snapshot_source(bibliography_path, ledger_path)
        citation_bindings = [
            {
                "key": "smith",
                "source_kind": "bibtex_entry",
                "external_result_id": dependency["id"],
                "external_identity_sha256": (
                    proofcheck.external_result_identity_sha256(
                        {"id": dependency["id"], **core_contract}
                    )
                ),
                "file": proofcheck.relative_or_absolute(
                    bibliography_path, self.audit
                ),
                "start_line": 1,
                "end_line": 5,
                "sha256": proofcheck.source_span_sha256(
                    bibliography_path, 1, 5
                ),
                "role": "bibliography_identity",
                "locator": "BibTeX entry smith",
            }
        ]
        contract_payload = {
            **core_contract,
            "citation_bindings": citation_bindings,
        }
        use = {
            "dependent_unit": "lem:main",
            "use_id": dependency["use_id"],
            "dependency_id": dependency["id"],
            "step_ids": ["S003"],
            "needed_form": dependency["needed_form"],
            "dependency_conclusion": exact_statement,
            "dependency_contract_sha256": proofcheck.canonical_sha256(
                contract_payload
            ),
            "compatibility_check": dependency["compatibility_check"],
            "compatibility_checks": make_compatibility_checks(),
            "status": "verified",
            "issue_ids": [],
            "citation_keys": ["smith"],
            "prerequisite_map": [
                {
                    "prerequisite": "The manuscript variable x is real.",
                    "manuscript_evidence": (
                        "The locked theorem statement quantifies x over the real numbers."
                    ),
                    "status": "satisfied",
                    "evidence_spans": [
                        proofcheck.locked_span(
                            self.paper,
                            2,
                            4,
                            self.audit,
                            role="manuscript_prerequisite",
                        )
                    ],
                    "issue_ids": [],
                }
            ],
        }
        external = {
            "id": dependency["id"],
            "status": "verified",
            **contract_payload,
            "citation_binding_review": {
                "status": "reviewed",
                "required_keys": ["smith"],
                "evidence": (
                    "The locked BibTeX entry key equals the manuscript citation key "
                    "and is bound to this external result identity."
                ),
            },
            "issue_ids": [],
            "uses": [use],
        }
        registry = self.refresh_dependency_review()
        registry["external_results"] = [external]
        registry_path = (
            self.audit
            / "audit"
            / "03_dependencies"
            / "DEPENDENCY_REGISTRY.json"
        )
        write_json(registry_path, registry)

        report_path = self.audit / "audit" / "06_reports" / "FINAL_REPORT.md"
        report = report_path.read_text(encoding="utf-8").replace(
            "- External results checked: none",
            "- External results checked: ext:reflexivity",
        )
        report_path.write_text(report, encoding="utf-8", newline="\n")
        self.seal_schema5_challenge(ledger_path, read_json(ledger_path))
        if reconcile_report_views:
            self.refresh_report_views()
        return source_path, use

    def make_external_restatement_audit(
        self, *, with_statement_citation: bool = False
    ) -> Path:
        citation = "\\cite{smith}" if with_statement_citation else ""
        self.paper = self.base / "imported-result.tex"
        self.paper.write_text(
            "\\input{definitions}\n"
            "\\begin{lemma}\\label{lem:main}\n"
            f"$x=x$ for every real $x$.{citation}\n"
            "\\end{lemma}\n"
            "% This imported result has no local proof.\n"
            "Reflexivity establishes the claim.\n"
            "\n",
            encoding="utf-8",
            newline="\n",
        )
        self.audit = self.base / "imported-result-audit"
        with contextlib.redirect_stdout(io.StringIO()):
            proofcheck.cmd_scaffold(
                argparse.Namespace(paper=self.paper, output=self.audit, report_format="markdown")
            )
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        manifest["protocol"].pop("challenge_contract_version", None)
        write_json(manifest_path, manifest)
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        old_challenge = dict(ledger["independent_check"])

        source = ledger["source"]
        source["end_line"] = 4
        source["unit_sha256"] = proofcheck.source_span_sha256(
            self.paper, 2, 4
        )
        source["coverage_mode"] = "external_restatement"
        source["external_dependency_use_id"] = "D001"
        source.pop("separate_statement_reason", None)
        ledger["source_lines"] = ledger["source_lines"][:3]
        ledger["source_units"] = [
            {
                "id": "U001",
                "lines": [2, 4],
                "kind": "continued_sentence",
                "source_sha256": proofcheck.source_span_sha256(
                    self.paper, 2, 4
                ),
                "partition_evidence": (
                    "Lines 2-4 are one formal imported-result statement."
                ),
            }
        ]

        dependency = {
            "id": "ext:reflexivity",
            "use_id": "D001",
            "kind": "external_result",
            "status": "verified",
            "needed_form": "For every real x, x equals x.",
            "compatibility_check": (
                "The external theorem has the same quantifier, domain, and "
                "reflexive equality as the manuscript statement."
            ),
        }
        statement_step = ledger["steps"][0]
        conclusion_step = ledger["steps"][2]
        conclusion_step["id"] = "S002"
        conclusion_step["source_unit_id"] = "U001"
        conclusion_step["goal"] = (
            "Verify the imported manuscript result against the external theorem."
        )
        conclusion_step["restatement"] = "x equals x"
        conclusion_step["premise_uses"] = [
            {
                "id": "P001",
                "role": "fact",
                "claim": dependency["needed_form"],
                "origin": {
                    "kind": "external_result",
                    "reference": dependency["use_id"],
                },
                "evidence": (
                    "The independently locked external source states this "
                    "universal reflexivity result."
                ),
            },
            {
                "id": "P002",
                "role": "assumption",
                "claim": "For every real x.",
                "origin": {
                    "kind": "obligation",
                    "reference": "/quantifier_scope",
                    "anchor": {
                        "kind": "statement_span",
                        "index": 1,
                    },
                },
                "evidence": (
                    "The formal statement supplies the real-number quantifier."
                ),
            },
        ]
        conclusion_step["dependencies"] = [dict(dependency)]
        conclusion_step["inference"] = {
            "moves": [
                {
                    "id": "M001",
                    "claim": "x equals x",
                    "rule": "Verified external restatement",
                    "premise_ids": ["P001", "P002"],
                    "prior_move_ids": [],
                    "justification": (
                        "The verified external universal result establishes the "
                        "same claim for the arbitrary real x."
                    ),
                }
            ],
            "conclusion_move": "M001",
        }
        conclusion_step["checks"]["literal"] = (
            "The manuscript statement and external result assert the same "
            "quantified equality."
        )
        conclusion_step["checks"]["atomicity"] = {
            "status": "single_move",
            "evidence": (
                "This step performs one exact external-result application."
            ),
        }
        conclusion_step["checks"]["adversarial"] = [
            "The domain, quantifier, and equality were compared explicitly."
        ]
        ledger["steps"] = [statement_step, conclusion_step]
        ledger["review"]["conclusion_step_id"] = "S002"
        ledger["review"]["conclusion_results"][0]["support"] = {
            "step_id": "S002",
            "move_id": "M001",
        }
        ledger["review"]["conclusion_results"][0][
            "dependency_use_ids"
        ] = ["D001"]
        ledger["review"]["direct_dependencies"] = [dict(dependency)]
        ledger["review"]["source_reference_dispositions"] = []
        ledger["review"]["citation_dispositions"] = (
            [
                {
                    "key": "smith",
                    "disposition": "external_result",
                    "dependency_id": dependency["id"],
                    "dependency_use_id": dependency["use_id"],
                    "evidence": (
                        "The statement citation identifies the exact external "
                        "result designated by the override."
                    ),
                }
            ]
            if with_statement_citation
            else []
        )
        ledger["review"]["verification_basis"] = [
            "Exact statement ledger and independently verified external theorem"
        ]
        write_json(ledger_path, ledger)

        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        manifest["audit_scope"]["inventory_overrides"] = [
            {
                "unit_id": "lem:main",
                "kind": "external_restatement",
                "external_dependency_use_id": "D001",
                "statement_sha256": proofcheck.source_span_sha256(
                    self.paper, 2, 4
                ),
                "reason": (
                    "The manuscript deliberately states an imported theorem "
                    "without supplying a local proof."
                ),
                "evidence": (
                    "The exact statement is source-locked and checked against "
                    "one independently verified external theorem contract."
                ),
            }
        ]
        for review in manifest["parser_warning_reviews"]:
            if review["warning"].startswith(
                "Proof-required result has no associated proof: lem:main at "
            ):
                review.update(
                    {
                        "disposition": "external_restatement",
                        "affected_units": ["lem:main"],
                        "evidence": (
                            "The explicit override and external dependency "
                            "supply the reviewed verification path."
                        ),
                    }
                )
            else:
                review.update(
                    {
                        "disposition": "confirmed_non_load_bearing",
                        "affected_units": [],
                        "evidence": (
                            "This parser warning does not affect the imported "
                            "result verification path."
                        ),
                    }
                )
        write_json(manifest_path, manifest)

        external_source = self.base / "external-imported-result.txt"
        external_source.write_text(
            "External Result 1\nFor every real x, x equals x.\n",
            encoding="utf-8",
            newline="\n",
        )
        source_evidence = [
            {
                "file": proofcheck.relative_or_absolute(
                    external_source, self.audit
                ),
                "sha256": proofcheck.sha256_file(external_source),
                "locator": "External Result 1, line 2",
                "role": "authoritative_theorem_source",
            }
        ]
        exact_statement = "For every real x, x equals x."
        core_contract = {
            "source_identity": "doi:10.0000/imported-reflexivity",
            "version": "version 1",
            "theorem_location": "External Result 1",
            "exact_statement": exact_statement,
            "source_evidence": source_evidence,
        }
        citation_bindings = []
        if with_statement_citation:
            bibliography_path = self.base / "external-imported-result.bbl"
            bibliography_path.write_text(
                "\\begin{thebibliography}{1}\n"
                "\\bibitem{smith} A. Smith. Reflexivity of equality. 2026.\n"
                "\\end{thebibliography}\n",
                encoding="utf-8",
                newline="\n",
            )
            self.add_snapshot_source(bibliography_path, ledger_path)
            citation_bindings = [
                {
                    "key": "smith",
                    "source_kind": "bibitem",
                    "external_result_id": "ext:reflexivity",
                    "external_identity_sha256": (
                        proofcheck.external_result_identity_sha256(
                            {"id": "ext:reflexivity", **core_contract}
                        )
                    ),
                    "file": proofcheck.relative_or_absolute(
                        bibliography_path, self.audit
                    ),
                    "start_line": 2,
                    "end_line": 2,
                    "sha256": proofcheck.source_span_sha256(
                        bibliography_path, 2, 2
                    ),
                    "role": "bibliography_identity",
                    "locator": "thebibliography item smith",
                }
            ]
        contract_payload = dict(core_contract)
        if citation_bindings:
            contract_payload["citation_bindings"] = citation_bindings
        use = {
            "dependent_unit": "lem:main",
            "use_id": "D001",
            "dependency_id": "ext:reflexivity",
            "step_ids": ["S002"],
            "needed_form": dependency["needed_form"],
            "dependency_conclusion": exact_statement,
            "dependency_contract_sha256": proofcheck.canonical_sha256(
                contract_payload
            ),
            "compatibility_check": dependency["compatibility_check"],
            "compatibility_checks": make_compatibility_checks(),
            "status": "verified",
            "issue_ids": [],
            "citation_keys": ["smith"] if with_statement_citation else [],
            "prerequisite_map": [
                {
                    "prerequisite": "The manuscript variable x is real.",
                    "manuscript_evidence": (
                        "The formal statement quantifies x over the reals."
                    ),
                    "status": "satisfied",
                    "evidence_spans": [
                        proofcheck.locked_span(
                            self.paper,
                            2,
                            4,
                            self.audit,
                            role="manuscript_prerequisite",
                        )
                    ],
                    "issue_ids": [],
                }
            ],
        }
        registry = self.refresh_dependency_review()
        registry["external_results"] = [
            {
                "id": "ext:reflexivity",
                "status": "verified",
                **contract_payload,
                **(
                    {
                        "citation_binding_review": {
                            "status": "reviewed",
                            "required_keys": ["smith"],
                            "evidence": (
                                "The locked bibitem key equals the statement citation "
                                "key and is bound to this external result identity."
                            ),
                        }
                    }
                    if with_statement_citation
                    else {}
                ),
                "issue_ids": [],
                "uses": [use],
            }
        ]
        registry_path = (
            self.audit
            / "audit"
            / "03_dependencies"
            / "DEPENDENCY_REGISTRY.json"
        )
        write_json(registry_path, registry)

        self.seal_schema5_challenge(ledger_path, read_json(ledger_path))
        new_challenge = read_json(ledger_path)["independent_check"]
        report_path = self.audit / "audit" / "06_reports" / "FINAL_REPORT.md"
        report = report_path.read_text(encoding="utf-8")
        report = report.replace(
            "paper.tex and lem:main",
            f"{self.paper.name} and lem:main",
        )
        report = report.replace(
            "- External results checked: none",
            "- External results checked: ext:reflexivity",
        )
        report = report.replace(
            "| lem:main | C001 | verified | valid | established | verified | "
            "not_applicable | S003/M001 | none | none |",
            "| lem:main | C001 | verified | valid | established | verified | "
            "not_applicable | S002/M001 | D001 | none |",
        )
        empty_closure = (
            "| Dependent | Use ID | Dependency | Dependency conclusion | Kind | "
            "Source status | Applicability status | Effective status | Issue IDs |\n"
            "|---|---|---|---|---|---|---|---|---|\n"
            "None."
        )
        external_closure = (
            "| Dependent | Use ID | Dependency | Dependency conclusion | Kind | "
            "Source status | Applicability status | Effective status | Issue IDs |\n"
            "|---|---|---|---|---|---|---|---|---|\n"
            "| lem:main | D001 | ext:reflexivity | none | external_result | "
            "verified | passed | verified | none |"
        )
        report = report.replace(empty_closure, external_closure)
        for field in (
            "challenged_ledger_sha256",
            "challenge_context_sha256",
            "challenge_artifact_sha256",
            "generated_utc",
        ):
            report = report.replace(
                str(old_challenge[field]),
                str(new_challenge[field]),
            )
        report_path.write_text(report, encoding="utf-8", newline="\n")
        self.refresh_report_views()
        return ledger_path

    def migrate_issue_fixture_to_schema5(
        self,
        issue: dict,
        *,
        ledger_path: Path | None = None,
        step_index: int | None = None,
    ) -> tuple[dict, int | None]:
        if (
            "origin_ref" in issue
            and "contract_refs" in issue
            and "invalidation_kind" in issue
            and "suggested_changes" in issue
        ):
            return issue, step_index

        affected_result = issue.get("affected_result")
        if ledger_path is not None:
            ledger = read_json(ledger_path)
            if step_index is None:
                conclusion_step_id = ledger.get("review", {}).get(
                    "conclusion_step_id"
                )
                step_index = next(
                    (
                        index
                        for index, step in enumerate(ledger.get("steps", []))
                        if step.get("id") == conclusion_step_id
                    ),
                    0,
                )
            step = ledger["steps"][step_index]
            moves = step.get("inference", {}).get("moves", [])
            move_id = (
                moves[-1].get("id")
                if isinstance(moves, list)
                and moves
                and isinstance(moves[-1], dict)
                else None
            )
            issue["origin_ref"] = (
                {
                    "kind": "ledger_move",
                    "unit_id": ledger["unit_id"],
                    "step_id": step["id"],
                    "move_id": move_id,
                }
                if move_id is not None
                else {
                    "kind": "obligation_pointer",
                    "unit_id": ledger["unit_id"],
                    "pointer": "/conclusions/0",
                }
            )
        elif isinstance(issue.get("interface_id"), str):
            issue["origin_ref"] = {
                "kind": "interface_record",
                "interface_id": issue["interface_id"],
                "evidence_spans": [
                    proofcheck.locked_span(
                        self.paper,
                        2,
                        4,
                        self.audit,
                        role="authoritative_definition",
                    )
                ],
            }
        else:
            issue["origin_ref"] = {
                "kind": "obligation_pointer",
                "unit_id": affected_result,
                "pointer": "/conclusions/0",
            }

        issue["contract_refs"] = []
        if issue["origin_ref"]["kind"] == "obligation_pointer":
            issue["contract_refs"].append(
                {
                    "kind": "obligation_pointer",
                    "unit_id": affected_result,
                    "pointer": issue["origin_ref"]["pointer"],
                }
            )
        issue["contract_refs"].append(
            {
                "kind": "conclusion",
                "unit_id": affected_result,
                "conclusion_id": "C001",
            }
        )
        finding_status = issue.get("finding_status")
        issue["invalidation_kind"] = (
            "scope_inconclusive"
            if finding_status == "inconclusive"
            else (
                "proof_invalid"
                if issue.get("load_bearing") is True
                else "presentation_only"
            )
        )
        proposal = issue.get("possible_repair")
        if not isinstance(proposal, str):
            proposal = "Resolve the finding and rerun every required check."
        affected_results = issue.get("affected_results")
        required_rechecks = (
            sorted(
                result
                for result in affected_results
                if isinstance(result, str)
            )
            if isinstance(affected_results, list)
            else []
        )
        issue["suggested_changes"] = [
            {
                "target_ref": {
                    "kind": "source_span",
                    "file": proofcheck.relative_or_absolute(
                        self.paper, self.audit
                    ),
                    "start_line": 2,
                    "end_line": 4,
                    "sha256": proofcheck.source_span_sha256(
                        self.paper, 2, 4
                    ),
                },
                "action": "repair_step",
                "repair_scope": (
                    "unit_statement"
                    if issue.get("severity") == "S0"
                    else "local_step"
                ),
                "assumption_cost": (
                    "adds_regularity_or_moment"
                    if issue.get("severity") == "S0"
                    else "none"
                ),
                "proposal": proposal,
                "verification_status": "candidate",
                "required_rechecks": required_rechecks,
            }
        ]
        for field in (
            "location",
            "evidence",
            "downstream_consequences",
            "possible_repair",
        ):
            issue.pop(field, None)
        return issue, step_index

    def install_canonical_issue(
        self,
        issue: dict,
        *,
        ledger_path: Path | None = None,
        step_index: int | None = None,
        migrate: bool = True,
        reconcile_report_views: bool = True,
    ) -> None:
        if migrate:
            issue, step_index = self.migrate_issue_fixture_to_schema5(
                issue,
                ledger_path=ledger_path,
                step_index=step_index,
            )
        if ledger_path is not None:
            ledger = read_json(ledger_path)
            if step_index is None:
                step_index = 0
            linked_step = ledger["steps"][step_index]
            linked_step["issue_ids"] = sorted(
                set([*linked_step["issue_ids"], issue["id"]])
            )
            for result in ledger.get("review", {}).get(
                "conclusion_results", []
            ):
                support = result.get("support")
                if (
                    isinstance(support, dict)
                    and support.get("step_id") == linked_step.get("id")
                ):
                    result["issue_ids"] = sorted(
                        set([*result.get("issue_ids", []), issue["id"]])
                    )
            write_json(ledger_path, ledger)
        issue_path = self.audit / "audit" / "06_reports" / "ISSUE_LOG.json"
        write_json(
            issue_path,
            {"schema_version": proofcheck.SCHEMA_VERSION, "issues": [issue]},
        )
        self.seal_live_challenges()
        summary_path = self.audit / "audit" / "06_reports" / "ISSUE_SUMMARY.md"
        summary_path.write_text(
            proofcheck.render_issue_summary([issue]),
            encoding="utf-8",
            newline="\n",
        )

        report_path = self.audit / "audit" / "06_reports" / "FINAL_REPORT.md"
        report = report_path.read_text(encoding="utf-8")
        if issue.get("status") in {"open", "deferred"}:
            report = report.replace(
                "- Highest-consequence issue: none",
                f"- Highest-consequence issue: {issue['id']}",
            )
        report_path.write_text(report, encoding="utf-8", newline="\n")
        if not reconcile_report_views:
            return
        output = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(stderr):
            status = proofcheck.cmd_issues(
                argparse.Namespace(
                    root=self.audit,
                    write_summary=True,
                    write_report_views=True,
                    final=True,
                )
            )
        self.assertEqual(0, status, stderr.getvalue())

    def make_global_issue(
        self,
        *,
        finding_status: str = "inconclusive",
        load_bearing: bool = False,
        affected_result: str = "lem:main",
        affected_results: list[str] | None = None,
        issue_id: str = "I-001",
        severity: str = "S2",
        summary: str = "A proof-audit finding requires explicit resolution.",
    ) -> dict:
        issue = {
            "id": issue_id,
            "severity": severity,
            "confidence": "high",
            "status": "open",
            "finding_status": finding_status,
            "scope": "global",
            "load_bearing": load_bearing,
            "affected_result": affected_result,
            "affected_results": (
                [affected_result]
                if affected_results is None
                else list(affected_results)
            ),
            "summary": summary,
        }
        if severity in {"S0", "S1"}:
            issue["repair_search"] = make_repair_search(severity)
        issue, _ = self.migrate_issue_fixture_to_schema5(issue)
        return issue

    def set_expected_assessment(self, assessment: str) -> None:
        judgments = {
            "no_defect_found": (
                "No load-bearing defect found under the stated non-formal protocol."
            ),
            "inconclusive": "Inconclusive under the stated non-formal protocol.",
            "defects_found": (
                "Defects found under the stated non-formal protocol."
            ),
        }
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        previous = manifest["audit_scope"]["overall_assessment"]
        manifest["audit_scope"]["overall_assessment"] = assessment
        write_json(manifest_path, manifest)

        report_path = self.audit / "audit" / "06_reports" / "FINAL_REPORT.md"
        report = report_path.read_text(encoding="utf-8")
        report = report.replace(
            f"- Overall assessment code: {previous}",
            f"- Overall assessment code: {assessment}",
        )
        for judgment in judgments.values():
            report = report.replace(
                f"- Overall judgment: {judgment}",
                f"- Overall judgment: {judgments[assessment]}",
            )
        report_path.write_text(report, encoding="utf-8", newline="\n")

    def sync_incorrect_main_report(
        self,
        ledger_path: Path,
        *,
        dependency_issue: bool = False,
    ) -> None:
        del ledger_path, dependency_issue
        self.refresh_report_views()

    def make_ledger_move_defect_audit(self) -> tuple[Path, dict, str]:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        step = ledger["steps"][2]
        failure_evidence = (
            "The cited reflexivity rule does not establish the altered "
            "conclusion under the recorded premise."
        )
        step["status"] = "incorrect"
        step["issue_ids"] = ["I-001"]
        step["inference"]["moves"][0]["failure"] = {
            "kind": "invalid_rule",
            "issue_id": "I-001",
            "evidence": failure_evidence,
        }
        conclusion = ledger["review"]["conclusion_results"][0]
        conclusion["argument_status"] = "invalid"
        conclusion["statement_status"] = "not_established"
        conclusion["issue_ids"] = ["I-001"]
        ledger["review"]["unit_status"] = "incorrect"
        ledger["review"]["argument_status"] = "invalid"
        ledger["review"]["statement_status"] = "not_established"
        ledger["independent_check"]["covered_issue_ids"] = ["I-001"]
        ledger["independent_check"]["challenger_verdict"] = "incorrect"
        ledger["independent_check"]["reconciled_verdict"] = "incorrect"
        write_json(ledger_path, ledger)
        self.seal_schema5_challenge(ledger_path, read_json(ledger_path))

        issue = self.make_global_issue(
            finding_status="defect",
            load_bearing=True,
            severity="S2",
            summary=(
                "The recorded inference rule does not establish the claimed "
                "conclusion."
            ),
        )
        issue.update(
            {
                "origin_ref": {
                    "kind": "ledger_move",
                    "unit_id": "lem:main",
                    "step_id": "S003",
                    "move_id": "M001",
                },
                "contract_refs": [
                    {
                        "kind": "conclusion",
                        "unit_id": "lem:main",
                        "conclusion_id": "C001",
                    }
                ],
                "invalidation_kind": "proof_invalid",
            }
        )
        self.set_expected_assessment("defects_found")
        self.install_canonical_issue(
            issue,
            ledger_path=ledger_path,
            step_index=2,
            migrate=False,
        )
        self.sync_incorrect_main_report(ledger_path)
        return ledger_path, issue, failure_evidence

    def make_dependency_mismatch_audit(self) -> tuple[Path, dict]:
        ledger_path = self.make_complete_audit()
        self.install_internal_dependency(ledger_path)
        ledger = read_json(ledger_path)
        step = ledger["steps"][2]
        for dependency in (
            step["dependencies"][0],
            ledger["review"]["direct_dependencies"][0],
        ):
            dependency["status"] = "incorrect"
            dependency["issue_ids"] = ["I-001"]
        step["status"] = "incorrect"
        step["issue_ids"] = ["I-001"]
        step["inference"]["moves"][0]["failure"] = {
            "kind": "invalid_rule",
            "issue_id": "I-001",
            "evidence": (
                "The dependency compatibility check is incorrect, so this "
                "move cannot use D001 as recorded."
            ),
        }
        conclusion = ledger["review"]["conclusion_results"][0]
        conclusion["argument_status"] = "invalid"
        conclusion["statement_status"] = "not_established"
        conclusion["dependency_closure"] = "incorrect"
        conclusion["issue_ids"] = ["I-001"]
        ledger["review"]["unit_status"] = "incorrect"
        ledger["review"]["argument_status"] = "invalid"
        ledger["review"]["statement_status"] = "not_established"
        ledger["review"]["dependency_closure"] = "incorrect"
        ledger["independent_check"]["covered_issue_ids"] = ["I-001"]
        ledger["independent_check"]["challenger_verdict"] = "incorrect"
        ledger["independent_check"]["reconciled_verdict"] = "incorrect"
        write_json(ledger_path, ledger)

        registry_path = (
            self.audit
            / "audit"
            / "03_dependencies"
            / "DEPENDENCY_REGISTRY.json"
        )
        registry = read_json(registry_path)
        use = registry["internal_uses"][0]
        use["compatibility_checks"][0].update(
            {
                "status": "incorrect",
                "evidence": (
                    "The dependency conclusion has the wrong quantified domain "
                    "at this use site."
                ),
                "issue_ids": ["I-001"],
            }
        )
        use["status"] = "incorrect"
        use["issue_ids"] = ["I-001"]
        write_json(registry_path, registry)
        self.seal_schema5_challenge(ledger_path, read_json(ledger_path))

        issue = self.make_global_issue(
            finding_status="defect",
            load_bearing=True,
            severity="S2",
            summary=(
                "The D001 dependency use fails its quantified-domain "
                "compatibility check."
            ),
        )
        issue.update(
            {
                "origin_ref": {
                    "kind": "dependency_use",
                    "unit_id": "lem:main",
                    "use_id": "D001",
                },
                "contract_refs": [
                    {
                        "kind": "dependency_use",
                        "unit_id": "lem:main",
                        "use_id": "D001",
                    },
                    {
                        "kind": "conclusion",
                        "unit_id": "lem:main",
                        "conclusion_id": "C001",
                    },
                ],
                "invalidation_kind": "dependency_mismatch",
            }
        )
        issue["suggested_changes"][0]["action"] = "repair_dependency"
        self.set_expected_assessment("defects_found")
        self.install_canonical_issue(
            issue,
            ledger_path=ledger_path,
            step_index=2,
            migrate=False,
        )
        self.sync_incorrect_main_report(
            ledger_path,
            dependency_issue=True,
        )
        return ledger_path, issue

    def make_interface_record(
        self,
        *,
        specification: str = "clear",
        target_verdict: str = "match",
        implementation_inspection: str = "inspected",
        code_to_documented: str = "consistent",
        code_to_target: str = "consistent",
        execution_provenance: str = "not_checked",
        load_bearing: bool = False,
        implementation_required: bool = False,
        execution_required: bool = False,
    ) -> dict:
        code = self.base / "estimator.py"
        code.write_text(
            "def fit_ratio(states, beta_actions, pi_actions):\n"
            "    return states, beta_actions, pi_actions\n",
            encoding="utf-8",
            newline="\n",
        )
        manuscript_span = proofcheck.locked_span(
            self.paper, 2, 4, self.audit, role="authoritative_definition"
        )
        inspected = implementation_inspection == "inspected"
        implementation_spans = (
            [
                proofcheck.locked_span(
                    code,
                    1,
                    2,
                    self.audit,
                    role="implementation_snapshot",
                )
            ]
            if inspected
            else []
        )
        run_record = self.base / "run-record.txt"
        run_record.write_text(
            "reported_revision=other-snapshot\n",
            encoding="utf-8",
            newline="\n",
        )
        provenance_spans = (
            [
                proofcheck.locked_span(
                    run_record,
                    1,
                    1,
                    self.audit,
                    role="execution_provenance",
                )
            ]
            if execution_provenance in {"matched", "not_matched"}
            else []
        )
        alternatives = []
        if specification in {"ambiguous", "incomplete"}:
            alternatives = [
                {
                    "interpretation": "The two laws share the same state reference law.",
                    "consequence": "The state marginal cancels.",
                    "evidence": ["paper.tex:2-4"],
                },
                {
                    "interpretation": "The two laws use policy-specific state marginals.",
                    "consequence": "An additional state-density ratio remains.",
                    "evidence": ["paper.tex:2-4"],
                },
            ]
        unresolved = (
            specification in {"ambiguous", "incomplete", "not_checked"}
            or target_verdict
            in {"conditional_match", "not_assessable", "not_checked"}
            or (
                implementation_required
                and (
                    implementation_inspection
                    in {"available_not_checked", "unavailable", "out_of_scope"}
                    or code_to_documented != "consistent"
                    or code_to_target != "consistent"
                )
            )
            or (execution_required and execution_provenance != "matched")
        )
        return {
            "id": "MI-001",
            "kind": "density_ratio",
            "load_bearing": load_bearing,
            "implementation_required_for_claim": implementation_required,
            "execution_provenance_required_for_claim": execution_required,
            "affected_results": ["lem:main"],
            "population_target": {
                "formula": "pi(a|s) / beta(a|s)",
                "measure_and_support": "The conditional action laws on their common support.",
                "equality_notion": "Equality almost everywhere under the behavior law.",
            },
            "identification_identity": "d(P_ref pi) / d(P_ref beta) = pi / beta.",
            "fitting_sample_laws": [
                {
                    "role": "numerator",
                    "law": "P_ref(ds) pi(da|s)",
                    "reference_law": "P_ref",
                    "evidence_spans": [dict(manuscript_span)],
                },
                {
                    "role": "denominator",
                    "law": "P_ref(ds) beta(da|s)",
                    "reference_law": "P_ref",
                    "evidence_spans": [dict(manuscript_span)],
                },
            ],
            "marginal_relationships": [
                "The state reference law is equal; the conditional action law changes."
            ],
            "evaluation_sites": ["Logged successor state-action inputs."],
            "downstream_uses": ["The weight in lem:main."],
            "interface_specification_status": specification,
            "derivation_status": "valid",
            "target_relation": {
                "verdict": target_verdict,
                "assumptions": [],
                "reason": "The relation follows from, or is limited by, the locked specification.",
                "evidence_spans": [dict(manuscript_span)],
            },
            "implementation_relation": {
                "inspection_status": implementation_inspection,
                "inspection_mode": "static" if inspected else "not_applicable",
                "revision": "test-snapshot" if inspected else "",
                "evidence_spans": implementation_spans,
                "reason": (
                    "The locked implementation snapshot was inspected."
                    if inspected
                    else "Implementation evidence was unavailable or outside inspection scope."
                ),
                "comparisons": [
                    {
                        "to": "documented_estimator",
                        "verdict": code_to_documented,
                        "reason": "The code was compared with the documented estimator.",
                        "evidence_spans": (
                            implementation_spans
                            if code_to_documented in {"consistent", "inconsistent"}
                            else []
                        ),
                    },
                    {
                        "to": "required_target",
                        "verdict": code_to_target,
                        "reason": "The code was compared with the required target.",
                        "evidence_spans": (
                            implementation_spans
                            if code_to_target in {"consistent", "inconsistent"}
                            else []
                        ),
                    },
                ],
                "execution_provenance": {
                    "status": execution_provenance,
                    "reason": (
                        "The locked run record identifies a different revision."
                        if execution_provenance == "not_matched"
                        else "No run-to-snapshot linkage was supplied."
                    ),
                    "evidence_spans": provenance_spans,
                },
            },
            "alternative_interpretations": alternatives,
            "resolution_evidence_needed": (
                ["Authoritative fitting laws or implementation evidence are needed."]
                if unresolved
                else []
            ),
            "issue_ids": [],
        }

    def install_interface_record(self, record: dict) -> None:
        registry_path = (
            self.audit
            / "audit"
            / "03_dependencies"
            / "METHOD_INTERFACE_REGISTRY.json"
        )
        registry = read_json(registry_path)
        registry["scope"] = {
            "status": "reviewed",
            "trigger": "required",
            "reason": "A load-bearing density-ratio interface was reviewed.",
        }
        registry["interfaces"] = [record]
        write_json(registry_path, registry)
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        manifest["audit_scope"]["in_scope_interfaces"] = [record["id"]]
        write_json(manifest_path, manifest)

    def install_interface_issue(self, record: dict, issue: dict) -> None:
        record["issue_ids"] = [issue["id"]]
        self.install_interface_record(record)
        self.install_canonical_issue(issue)

    def test_complete_minimal_audit_passes(self) -> None:
        self.make_complete_audit()
        errors, result = proofcheck.check_audit_finalization(self.audit)
        self.assertEqual([], errors)
        self.assertEqual(0, result["errors"])

    def test_empty_audit_fails_finalization(self) -> None:
        errors, _ = proofcheck.check_audit_finalization(self.audit)
        self.assertTrue(
            any("at least one proof-unit ledger" in error for error in errors),
            errors,
        )

    def test_unknown_verified_dependency_fails(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        dependency = {
            "id": "lem:missing",
            "use_id": "D001",
            "kind": "internal_result",
            "conclusion_id": "C001",
            "status": "verified",
            "needed_form": "A missing conclusion.",
            "compatibility_check": "The record claims compatibility.",
        }
        ledger["steps"][0]["dependencies"] = [dependency]
        ledger["review"]["direct_dependencies"] = [dependency]
        write_json(ledger_path, ledger)
        errors, _ = proofcheck.check_audit_finalization(self.audit)
        self.assertTrue(
            any("unknown internal dependency lem:missing" in error for error in errors),
            errors,
        )

    def test_step_dependency_cycle_fails(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        ledger["steps"][0]["dependencies"] = [
            {
                "id": "S001",
                "kind": "step",
                "status": "verified",
            }
        ]
        write_json(ledger_path, ledger)
        errors, _ = proofcheck.check_ledger_data(ledger_path, True)
        self.assertTrue(any("Step dependency cycle" in error for error in errors), errors)

    def test_step_cannot_depend_on_a_later_step(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        ledger["steps"][0]["dependencies"] = [
            {
                "id": "S003",
                "kind": "step",
                "status": "verified",
            }
        ]
        write_json(ledger_path, ledger)
        errors, _ = proofcheck.check_ledger_data(ledger_path, True)
        self.assertTrue(
            any("not established before use" in error for error in errors), errors
        )

    def test_conditional_status_cannot_hide_failed_dependency(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        dependency = {
            "id": "ext:failed",
            "use_id": "D001",
            "kind": "external_result",
            "status": "gap",
            "needed_form": "A required external conclusion.",
            "compatibility_check": "The external prerequisite is absent.",
        }
        ledger["steps"][0]["dependencies"] = [dependency]
        ledger["steps"][0]["status"] = "conditionally_verified"
        ledger["steps"][0]["conditions"] = ["Assume the missing premise."]
        ledger["review"]["unit_status"] = "conditionally_verified"
        ledger["review"]["argument_status"] = "conditional"
        ledger["review"]["statement_status"] = "conditional"
        ledger["review"]["dependency_closure"] = "conditionally_verified"
        ledger["review"]["direct_dependencies"] = [dependency]
        write_json(ledger_path, ledger)
        errors, _ = proofcheck.check_ledger_data(ledger_path, True)
        self.assertTrue(
            any("cannot hide failed dependencies" in error for error in errors),
            errors,
        )

    def mark_s003_conditional(self, ledger: dict) -> dict:
        step = ledger["steps"][2]
        step["status"] = "conditionally_verified"
        ledger["review"]["unit_status"] = "conditionally_verified"
        ledger["review"]["argument_status"] = "conditional"
        ledger["review"]["statement_status"] = "conditional"
        result = ledger["review"]["conclusion_results"][0]
        result["argument_status"] = "conditional"
        result["statement_status"] = "conditional"
        ledger["independent_check"]["challenger_verdict"] = (
            "conditionally_verified"
        )
        ledger["independent_check"]["reconciled_verdict"] = (
            "conditionally_verified"
        )
        return step

    def test_legacy_ledger_is_inspection_only(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = self.downgrade_ledger_fixture_to_schema4(
            read_json(ledger_path)
        )
        write_json(ledger_path, ledger)
        errors, _ = proofcheck.check_ledger_data(ledger_path, True)
        self.assertTrue(
            any(
                "schema 4 is inspection-only" in error
                or "evidence contract 3 is inspection-only" in error
                for error in errors
            ),
            errors,
        )

    def test_legacy_ledger_remains_readable_in_nonfinal_mode(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = self.downgrade_ledger_fixture_to_schema4(
            read_json(ledger_path)
        )
        del ledger["obligation"]["normalization_checks"]
        del ledger["obligation"]["quantified_variables"][0]["quantifier"]
        ledger["review"]["conclusion_results"] = []
        for step in (ledger["steps"][0], ledger["steps"][2]):
            step.pop("premise_uses", None)
            step.pop("inference", None)
            step.pop("risk_checks", None)
            step["required_facts"] = ["Legacy free-text fact."]
            step["assumptions"] = ["Legacy free-text assumption."]
            step["checks"]["inferential"] = "Legacy free-text inference."
            step["checks"]["atomicity"] = "Legacy free-text atomicity."
        write_json(ledger_path, ledger)
        errors, _ = proofcheck.check_ledger_data(ledger_path, False)
        self.assertEqual([], errors)

    def test_evidence_contract_rejects_legacy_step_fields(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        ledger["steps"][2]["required_facts"] = ["Reflexivity"]
        write_json(ledger_path, ledger)
        errors, _ = proofcheck.check_ledger_data(ledger_path, True)
        self.assertTrue(
            any("legacy free-text fields are not allowed" in error for error in errors),
            errors,
        )

    def test_obligation_premise_origin_must_resolve(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        ledger["steps"][2]["premise_uses"][0]["origin"]["reference"] = (
            "/quantified_variables/99"
        )
        write_json(ledger_path, ledger)
        errors, _ = proofcheck.check_ledger_data(ledger_path, True)
        self.assertTrue(
            any("unresolved obligation premise" in error for error in errors),
            errors,
        )

    def test_theorem_statement_cannot_be_used_as_its_own_premise(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        ledger["steps"][2]["premise_uses"][0]["origin"]["reference"] = (
            "/statement_spans/0"
        )
        write_json(ledger_path, ledger)
        errors, _ = proofcheck.check_ledger_data(ledger_path, True)
        self.assertTrue(
            any("unresolved obligation premise /statement_spans/0" in error for error in errors),
            errors,
        )

    def test_obligation_premise_needs_a_locked_anchor(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        ledger["steps"][2]["premise_uses"][0]["origin"]["anchor"]["index"] = 2
        write_json(ledger_path, ledger)
        errors, _ = proofcheck.check_ledger_data(ledger_path, True)
        self.assertTrue(
            any("origin.anchor is out of range" in error for error in errors),
            errors,
        )

    def test_inference_must_consume_every_premise(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        ledger["steps"][2]["inference"]["moves"][0]["premise_ids"] = []
        write_json(ledger_path, ledger)
        errors, _ = proofcheck.check_ledger_data(ledger_path, True)
        self.assertTrue(
            any("premise uses not consumed" in error for error in errors),
            errors,
        )

    def test_inference_cannot_use_an_unknown_premise(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        ledger["steps"][2]["inference"]["moves"][0]["premise_ids"] = ["P999"]
        write_json(ledger_path, ledger)
        errors, _ = proofcheck.check_ledger_data(ledger_path, True)
        self.assertTrue(
            any("uses unknown premise P999" in error for error in errors),
            errors,
        )

    def test_final_inference_claim_must_match_restatement(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        ledger["steps"][2]["inference"]["moves"][0]["claim"] = "x equals x."
        write_json(ledger_path, ledger)
        errors, _ = proofcheck.check_ledger_data(ledger_path, True)
        self.assertTrue(
            any("final inference claim must exactly match restatement" in error for error in errors),
            errors,
        )

    def test_source_indivisible_chain_records_each_atomic_move(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = self.downgrade_ledger_fixture_to_schema4(
            read_json(ledger_path)
        )
        step = ledger["steps"][2]
        step["checks"]["atomicity"] = {
            "status": "source_indivisible_chain",
            "source_unit_kind": "one_line",
            "partition_evidence": (
                "The single source line contains two successive logical moves."
            ),
            "evidence": "One physical source line contains two linked transitions.",
        }
        step["inference"] = {
            "moves": [
                {
                    "id": "M001",
                    "claim": "Reflexivity applies to x.",
                    "rule": "Reflexivity of equality",
                    "premise_ids": ["P001"],
                    "prior_move_ids": [],
                    "justification": "The rule applies to the arbitrary real x.",
                },
                {
                    "id": "M002",
                    "claim": step["restatement"],
                    "rule": "Goal closure",
                    "premise_ids": [],
                    "prior_move_ids": ["M001"],
                    "justification": "The reflexive equality is exactly the goal.",
                },
            ],
            "conclusion_move": "M002",
        }
        ledger["review"]["conclusion_results"][0]["support"]["move_id"] = "M002"
        write_json(ledger_path, ledger)
        errors, summary = proofcheck.check_ledger_data(ledger_path, False)
        self.assertEqual([], errors)
        self.assertEqual("legacy_inspection_only", summary["validation_scope"][
            "local_record_integrity"
        ])

    def test_legacy_multiline_chain_remains_inspection_only(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = self.downgrade_ledger_fixture_to_schema4(
            read_json(ledger_path)
        )
        step = ledger["steps"][2]
        del ledger["steps"][1]
        step["lines"] = [5, 6]
        step["checks"]["atomicity"] = {
            "status": "source_indivisible_chain",
            "evidence": "This negative control improperly groups two source lines.",
        }
        step["inference"] = {
            "moves": [
                {
                    "id": "M001",
                    "claim": "Reflexivity applies to x.",
                    "rule": "Reflexivity of equality",
                    "premise_ids": ["P001"],
                    "prior_move_ids": [],
                    "justification": "The rule applies to the arbitrary real x.",
                },
                {
                    "id": "M002",
                    "claim": step["restatement"],
                    "rule": "Goal closure",
                    "premise_ids": [],
                    "prior_move_ids": ["M001"],
                    "justification": "The reflexive equality is exactly the goal.",
                },
            ],
            "conclusion_move": "M002",
        }
        ledger["review"]["conclusion_results"][0]["support"]["move_id"] = "M002"
        write_json(ledger_path, ledger)
        errors, summary = proofcheck.check_ledger_data(ledger_path, False)
        self.assertEqual([], errors)
        self.assertEqual(
            "legacy_inspection_only",
            summary["validation_scope"]["local_record_integrity"],
        )

    def test_single_move_atomicity_rejects_a_chain(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        step = ledger["steps"][2]
        step["inference"]["moves"].append(
            {
                "id": "M002",
                "claim": step["restatement"],
                "rule": "Repeated closure",
                "premise_ids": [],
                "prior_move_ids": ["M001"],
                "justification": "A second move was inserted for the negative control.",
            }
        )
        step["inference"]["conclusion_move"] = "M002"
        write_json(ledger_path, ledger)
        errors, _ = proofcheck.check_ledger_data(ledger_path, True)
        self.assertTrue(
            any(
                "schema-5 inferential step must contain exactly one move"
                in error
                for error in errors
            ),
            errors,
        )

    def test_draft_validation_respects_recorded_noninferential_atomicity(self) -> None:
        ledger_path = self.make_complete_audit()

        errors, summary = proofcheck.check_ledger_data(ledger_path, False)

        self.assertEqual([], errors)
        self.assertEqual("draft", summary["validation_mode"])

    def test_draft_validation_keeps_the_schema5_one_move_contract(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        ledger["steps"][2]["inference"]["moves"] = []
        ledger["steps"][2]["inference"]["conclusion_move"] = None
        write_json(ledger_path, ledger)

        errors, summary = proofcheck.check_ledger_data(ledger_path, False)

        self.assertEqual("draft", summary["validation_mode"])
        self.assertTrue(
            any(
                "schema-5 inferential step must contain exactly one move"
                in error
                for error in errors
            ),
            errors,
        )

    def test_draft_validation_rejects_populated_invalid_atomicity(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        ledger["steps"][2]["checks"]["atomicity"]["status"] = (
            "invented_status"
        )
        write_json(ledger_path, ledger)

        errors, summary = proofcheck.check_ledger_data(ledger_path, False)

        self.assertEqual("draft", summary["validation_mode"])
        self.assertIn(
            "S003.checks.atomicity.status is invalid",
            errors,
        )

    def test_risk_matrix_requires_exact_aspect_coverage(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        ledger["steps"][2]["risk_checks"] = [
            row
            for row in ledger["steps"][2]["risk_checks"]
            if row["aspect"] != "rate"
        ]
        write_json(ledger_path, ledger)
        errors, _ = proofcheck.check_ledger_data(ledger_path, True)
        self.assertTrue(
            any("risk_checks must contain each required aspect exactly once" in error for error in errors),
            errors,
        )

    def test_verified_step_rejects_an_open_risk(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        domain = next(
            row for row in ledger["steps"][2]["risk_checks"]
            if row["aspect"] == "domain"
        )
        domain["status"] = "open"
        domain["evidence"] = "The domain compatibility has not been established."
        write_json(ledger_path, ledger)
        errors, _ = proofcheck.check_ledger_data(ledger_path, True)
        self.assertTrue(
            any("verified step has unresolved risk checks: domain" in error for error in errors),
            errors,
        )

    def test_side_conditions_field_cannot_be_omitted(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        del ledger["steps"][2]["side_conditions"]
        write_json(ledger_path, ledger)
        errors, _ = proofcheck.check_ledger_data(ledger_path, True)
        self.assertTrue(
            any("S003.side_conditions must be a list" in error for error in errors),
            errors,
        )

    def test_discharged_side_condition_needs_resolvable_evidence(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        ledger["steps"][2]["side_conditions"] = [
            {
                "id": "SC001",
                "generated_by": "M001",
                "condition": "x belongs to the domain of equality.",
                "status": "discharged",
                "discharge": {
                    "sources": [
                        {
                            "kind": "premise",
                            "reference": "P999",
                            "contribution": (
                                "This intentionally unresolved premise would "
                                "supply the domain fact."
                            ),
                        }
                    ],
                    "rule": "Domain membership discharges the side condition.",
                    "evidence": "",
                },
            }
        ]
        write_json(ledger_path, ledger)
        errors, _ = proofcheck.check_ledger_data(ledger_path, True)
        self.assertTrue(
            any("SC001 has unknown discharge premise P999" in error for error in errors),
            errors,
        )
        self.assertTrue(
            any("SC001 discharge evidence must be nonempty" in error for error in errors),
            errors,
        )

    def test_resolved_side_condition_passes(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        ledger["steps"][2]["side_conditions"] = [
            {
                "id": "SC001",
                "generated_by": "M001",
                "condition": "x belongs to the domain of equality.",
                "status": "discharged",
                "discharge": {
                    "sources": [
                        {
                            "kind": "premise",
                            "reference": "P001",
                            "contribution": "P001 supplies the real-number domain.",
                        }
                    ],
                    "rule": "A real number lies in the domain of real equality.",
                    "evidence": "P001 records x as a real number.",
                },
            }
        ]
        write_json(ledger_path, ledger)
        self.seal_schema5_challenge(ledger_path, read_json(ledger_path))
        errors, _ = proofcheck.check_ledger_data(ledger_path, True)
        self.assertEqual([], errors)

        cases = (
            ("condition", "S003.side_conditions[1].condition"),
            ("discharge_evidence", "SC001 discharge evidence"),
        )
        for case, expected in cases:
            with self.subTest(case=case):
                invalid_ledger = json.loads(json.dumps(ledger))
                side_condition = invalid_ledger["steps"][2]["side_conditions"][0]
                if case == "condition":
                    side_condition["condition"] = "N/A"
                else:
                    side_condition["discharge"]["evidence"] = "N/A"
                write_json(ledger_path, invalid_ledger)
                errors, _ = proofcheck.check_ledger_data(ledger_path, True)
                self.assertTrue(
                    any(
                        expected in error
                        and (
                            "substantive" in error or "reserved placeholder" in error
                        )
                        for error in errors
                    ),
                    errors,
                )

    def test_side_condition_discharge_cannot_be_circular(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        ledger["steps"][2]["side_conditions"] = [
            {
                "id": "SC001",
                "generated_by": "M001",
                "condition": "The move's own domain condition holds.",
                "status": "discharged",
                "discharge": {
                    "sources": [
                        {
                            "kind": "inference_move",
                            "reference": "M001",
                            "contribution": (
                                "This intentionally circular source repeats the "
                                "generating move."
                            ),
                        }
                    ],
                    "rule": "The generating move cannot discharge itself.",
                    "evidence": "This intentionally circular record is invalid.",
                },
            }
        ]
        write_json(ledger_path, ledger)
        errors, _ = proofcheck.check_ledger_data(ledger_path, True)
        self.assertTrue(
            any("is not established before generating move M001" in error for error in errors),
            errors,
        )

    def test_conditional_step_requires_exact_cause_mapping(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        step = self.mark_s003_conditional(ledger)
        step["side_conditions"] = [
            {
                "id": "SC001",
                "generated_by": "M001",
                "condition": "Assume x lies in the required support.",
                "status": "open",
            }
        ]
        step["conditions"] = []
        write_json(ledger_path, ledger)
        errors, _ = proofcheck.check_ledger_data(ledger_path, True)
        self.assertTrue(
            any("conditions must match every unresolved conditional cause" in error for error in errors),
            errors,
        )

    def test_conditional_step_with_exact_cause_mapping_passes(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        step = self.mark_s003_conditional(ledger)
        step["side_conditions"] = [
            {
                "id": "SC001",
                "generated_by": "M001",
                "condition": "Assume x lies in the required support.",
                "status": "open",
            }
        ]
        step["conditions"] = [
            {
                "kind": "side_condition",
                "reference": "SC001",
                "condition": "Validity is conditional on the stated support condition.",
            }
        ]
        write_json(ledger_path, ledger)
        self.seal_schema5_challenge(ledger_path, read_json(ledger_path))
        errors, _ = proofcheck.check_ledger_data(ledger_path, True)
        self.assertEqual([], errors)

    def test_checkpoint_derives_partitions_and_preserves_resume_fields(self) -> None:
        complete_path = self.make_complete_audit()
        complete = read_json(complete_path)
        ledger_dir = complete_path.parent

        conditional = json.loads(json.dumps(complete))
        conditional["unit_id"] = "lem:conditional"
        conditional_step = self.mark_s003_conditional(conditional)
        conditional_step["side_conditions"] = [
            {
                "id": "SC001",
                "generated_by": "M001",
                "condition": "Assume x lies in the required support.",
                "status": "open",
            }
        ]
        conditional_step["conditions"] = [
            {
                "kind": "side_condition",
                "reference": "SC001",
                "condition": "Validity is conditional on the stated support condition.",
            }
        ]
        conditional_path = ledger_dir / "lem-conditional.ledger.json"
        write_json(conditional_path, conditional)
        self.seal_schema5_challenge(
            conditional_path, read_json(conditional_path)
        )

        for unit_id, filename in (
            ("lem:active", "lem-active.ledger.json"),
            ("lem:not-started", "lem-not-started.ledger.json"),
        ):
            with contextlib.redirect_stdout(io.StringIO()):
                proofcheck.cmd_extract(
                    argparse.Namespace(
                        file=self.paper,
                        start=2,
                        end=7,
                        statement_file=self.paper,
                        statement_start=2,
                        statement_end=4,
                        separate_statement_reason=None,
                        unit_id=unit_id,
                        output=ledger_dir / filename,
                        force=False,
                    )
                )
        active_path = ledger_dir / "lem-active.ledger.json"
        active = read_json(active_path)
        active["obligation"] = json.loads(json.dumps(complete["obligation"]))
        active["steps"] = [
            {
                "id": "S001",
                "lines": [2, 2],
                "kind": "other",
                "status": "non_substantive",
                "issue_ids": [],
            }
        ]
        write_json(active_path, active)
        not_started_path = ledger_dir / "lem-not-started.ledger.json"
        not_started = read_json(not_started_path)
        not_started["obligation"] = json.loads(
            json.dumps(complete["obligation"])
        )
        write_json(not_started_path, not_started)

        unit_ids = [
            "lem:main",
            "lem:conditional",
            "lem:active",
            "lem:not-started",
        ]
        inventory_path = (
            self.audit / "audit" / "01_index" / "theorem_inventory.json"
        )
        inventory = read_json(inventory_path)
        discovered = inventory["units"][0]
        for unit_id in unit_ids[1:]:
            added = json.loads(json.dumps(discovered))
            added["id"] = unit_id
            added["label"] = unit_id
            added["proof_association"]["target"] = unit_id
            inventory["units"].append(added)
        write_json(inventory_path, inventory)

        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        manifest["audit_scope"]["in_scope_units"] = unit_ids
        write_json(manifest_path, manifest)

        next_action = "Continue the atomic ledger for lem:active from source line 3."
        checkpoint_output = io.StringIO()
        with contextlib.redirect_stdout(checkpoint_output):
            status = proofcheck.cmd_checkpoint(
                argparse.Namespace(
                    root=self.audit,
                    active_unit="lem:active",
                    clear_active_unit=False,
                    next_action=next_action,
                )
            )

        progress = read_json(self.audit / "PROGRESS.json")
        self.assertEqual(0, status)
        self.assertEqual("lem:active", progress["active_unit"])
        self.assertEqual(next_action, progress["next_action"])
        self.assertEqual(4, progress["current_pass"])
        self.assertCountEqual(
            ["lem:main", "lem:conditional"], progress["completed_units"]
        )
        self.assertCountEqual(
            ["lem:conditional"], progress["conditional_units"]
        )
        self.assertCountEqual(["lem:active"], progress["in_progress_units"])
        self.assertCountEqual(
            ["lem:not-started"], progress["not_started_units"]
        )

    def test_checkpoint_status_and_issue_views_are_registered_in_cli(
        self,
    ) -> None:
        parser = proofcheck.build_parser()
        checkpoint = parser.parse_args(
            [
                "checkpoint",
                "--root",
                str(self.audit),
                "--active-unit",
                "lem:main",
                "--next-action",
                "Continue lem:main.",
            ]
        )
        status = parser.parse_args(
            ["status", "--root", str(self.audit), "--verbose"]
        )
        issues = parser.parse_args(
            [
                "issues",
                "--root",
                str(self.audit),
                "--write-summary",
                "--write-report-views",
                "--final",
            ]
        )
        revalidate = parser.parse_args(
            ["revalidate-protocol", "--root", str(self.audit)]
        )

        self.assertIs(proofcheck.cmd_checkpoint, checkpoint.func)
        self.assertEqual("lem:main", checkpoint.active_unit)
        self.assertFalse(checkpoint.clear_active_unit)
        self.assertTrue(status.verbose)
        self.assertIs(proofcheck.cmd_issues, issues.func)
        self.assertTrue(issues.write_summary)
        self.assertTrue(issues.write_report_views)
        self.assertTrue(issues.final)
        self.assertIs(proofcheck.cmd_revalidate_protocol, revalidate.func)

    def test_early_checkpoints_derive_passes_one_two_and_three(self) -> None:
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        observed_passes = []
        for expected_pass, transition in (
            (1, "scaffolded"),
            (2, "scope_reviewed"),
            (3, "map_reviewed"),
        ):
            if transition == "scope_reviewed":
                manifest = read_json(manifest_path)
                manifest["audit_scope"].update(
                    {
                        "status": "reviewed",
                        "depth": "focused",
                        "in_scope_units": ["lem:main"],
                        "target_units": ["lem:main"],
                        "critical_units": ["lem:main"],
                    }
                )
                write_json(manifest_path, manifest)
            elif transition == "map_reviewed":
                manifest = read_json(manifest_path)
                manifest["completion"]["inventory_reviewed"] = True
                manifest["completion"]["parser_warnings_reviewed"] = True
                write_json(manifest_path, manifest)
            with contextlib.redirect_stdout(io.StringIO()):
                proofcheck.cmd_checkpoint(
                    argparse.Namespace(
                        root=self.audit,
                        active_unit="lem:main",
                        clear_active_unit=False,
                        next_action=(
                            f"Continue the canonical work required for pass {expected_pass}."
                        ),
                    )
                )
            observed_passes.append(
                read_json(self.audit / "PROGRESS.json")["current_pass"]
            )

        self.assertEqual([1, 2, 3], observed_passes)

    def test_partially_normalized_ledger_cannot_advance_past_pass_three(
        self,
    ) -> None:
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        manifest["audit_scope"].update(
            {
                "status": "reviewed",
                "depth": "focused",
                "in_scope_units": ["lem:main"],
                "target_units": ["lem:main"],
                "critical_units": ["lem:main"],
            }
        )
        manifest["completion"]["inventory_reviewed"] = True
        manifest["completion"]["parser_warnings_reviewed"] = True
        write_json(manifest_path, manifest)

        ledger_path = (
            self.audit / "audit" / "04_local_checks" / "lem-main.ledger.json"
        )
        with contextlib.redirect_stdout(io.StringIO()):
            proofcheck.cmd_extract(
                argparse.Namespace(
                    file=self.paper,
                    start=2,
                    end=7,
                    statement_file=self.paper,
                    statement_start=2,
                    statement_end=4,
                    separate_statement_reason=None,
                    unit_id="lem:main",
                    output=ledger_path,
                    force=False,
                )
            )
        ledger = read_json(ledger_path)
        ledger["obligation"]["quantifier_scope"] = "For every real x."
        ledger["obligation"]["conclusion"] = "x equals x"
        ledger["steps"] = [
            {
                "id": "S001",
                "lines": [2, 2],
                "kind": "other",
                "status": "non_substantive",
                "issue_ids": [],
            }
        ]
        write_json(ledger_path, ledger)

        with contextlib.redirect_stdout(io.StringIO()):
            proofcheck.cmd_checkpoint(
                argparse.Namespace(
                    root=self.audit,
                    active_unit="lem:main",
                    clear_active_unit=False,
                    next_action="Finish normalizing every field of the locked obligation.",
                )
            )

        progress = read_json(self.audit / "PROGRESS.json")
        self.assertEqual(3, progress["current_pass"])
        self.assertCountEqual(["lem:main"], progress["in_progress_units"])

    def test_duplicate_step_dependency_fails(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        dependency = {
            "id": "S001",
            "kind": "step",
            "status": "verified",
            "needed_form": "The source-locked theorem obligation.",
            "compatibility_check": "S001 records exactly the obligation used here.",
        }
        step = ledger["steps"][2]
        step["dependencies"] = [dependency, dict(dependency)]
        step["premise_uses"].append(
            {
                "id": "P002",
                "role": "fact",
                "claim": "The theorem obligation is x equals x.",
                "origin": {"kind": "prior_step", "reference": "S001"},
                "evidence": "S001 is the prior source-locked statement row.",
            }
        )
        step["inference"]["moves"][0]["premise_ids"].append("P002")
        write_json(ledger_path, ledger)
        errors, _ = proofcheck.check_ledger_data(ledger_path, True)
        self.assertTrue(
            any("duplicate dependency use S001" in error for error in errors),
            errors,
        )

    def test_dependency_must_be_used_by_a_premise(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        ledger["steps"][2]["dependencies"] = [
            {
                "id": "S001",
                "kind": "step",
                "status": "verified",
                "needed_form": "The source-locked theorem obligation.",
                "compatibility_check": "The dependency is available but unused.",
            }
        ]
        write_json(ledger_path, ledger)
        errors, _ = proofcheck.check_ledger_data(ledger_path, True)
        self.assertTrue(
            any("dependencies not used by premise_uses: S001" in error for error in errors),
            errors,
        )

    def test_review_cannot_list_an_unused_direct_dependency(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        ledger["review"]["direct_dependencies"] = [
            {
                "id": "lem:unused",
                "use_id": "D001",
                "kind": "internal_result",
                "conclusion_id": "C001",
                "status": "verified",
                "needed_form": "An unused result.",
                "compatibility_check": "No proof step actually invokes it.",
            }
        ]
        write_json(ledger_path, ledger)
        errors, _ = proofcheck.check_ledger_data(ledger_path, True)
        self.assertTrue(
            any("direct_dependencies contains unused results" in error for error in errors),
            errors,
        )

    def test_normalization_matrix_requires_exact_aspect_coverage(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        ledger["obligation"]["normalization_checks"] = [
            row
            for row in ledger["obligation"]["normalization_checks"]
            if row["aspect"] != "regime"
        ]
        write_json(ledger_path, ledger)
        errors, _ = proofcheck.check_ledger_data(ledger_path, True)
        self.assertTrue(
            any("normalization_checks must contain each required aspect exactly once" in error for error in errors),
            errors,
        )

    def test_verified_contract_rejects_unclear_normalization(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        ledger["obligation"]["uniformity"] = "unclear"
        uniformity = next(
            row for row in ledger["obligation"]["normalization_checks"]
            if row["aspect"] == "uniformity"
        )
        uniformity["status"] = "unclear"
        uniformity["evidence"] = "The statement does not determine uniformity."
        write_json(ledger_path, ledger)
        errors, _ = proofcheck.check_ledger_data(ledger_path, True)
        self.assertTrue(
            any("verified contract fidelity has unresolved normalization checks" in error for error in errors),
            errors,
        )

    def test_not_applicable_normalization_requires_explicit_absence(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        ledger["obligation"]["probability_model"] = (
            "Independent observations follow a common distribution P."
        )
        write_json(ledger_path, ledger)
        errors, _ = proofcheck.check_ledger_data(ledger_path, True)
        self.assertTrue(
            any(
                "normalization_checks[probability_model] is not_applicable "
                "but obligation.probability_model is substantive" in error
                for error in errors
            ),
            errors,
        )


    def test_explicit_absence_requires_not_applicable_normalization(self) -> None:
        ledger_path = self.make_complete_audit()
        base_ledger = read_json(ledger_path)
        cases = (
            ("probability_model", "N/A."),
            ("hypotheses", ["N/A"]),
            ("definitions", ["none"]),
            ("uniformity", "not_applicable"),
            ("regime", "not applicable"),
            ("constant_dependencies", ["not-applicable"]),
        )
        for aspect, marker in cases:
            with self.subTest(aspect=aspect):
                ledger = json.loads(json.dumps(base_ledger))
                ledger["obligation"][aspect] = marker
                normalization = next(
                    item
                    for item in ledger["obligation"]["normalization_checks"]
                    if item["aspect"] == aspect
                )
                normalization["status"] = "checked"
                normalization["evidence"] = (
                    "This intentionally inconsistent record is rejected."
                )
                write_json(ledger_path, ledger)
                errors, _ = proofcheck.check_ledger_data(ledger_path, True)
                expected = (
                    f"obligation.normalization_checks[{aspect}] is 'checked' "
                    f"but obligation.{aspect} records only absence"
                )
                self.assertTrue(
                    any(expected in error for error in errors),
                    errors,
                )

    def test_checked_normalization_rejects_embedded_absence_marker(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        ledger["obligation"]["definitions"].append("N/A")
        write_json(ledger_path, ledger)
        errors, _ = proofcheck.check_ledger_data(ledger_path, True)
        self.assertTrue(
            any(
                "obligation.definitions[2] cannot use an absence marker "
                "unless the field is not_applicable" in error
                for error in errors
            ),
            errors,
        )

    def test_conditional_contract_rejects_unclear_normalization(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        self.mark_s003_conditional(ledger)
        ledger["review"]["contract_fidelity"] = "conditionally_verified"
        ledger["obligation"]["uniformity"] = "unclear"
        uniformity = next(
            row for row in ledger["obligation"]["normalization_checks"]
            if row["aspect"] == "uniformity"
        )
        uniformity["status"] = "unclear"
        uniformity["evidence"] = "The source does not determine uniformity."
        write_json(ledger_path, ledger)
        errors, _ = proofcheck.check_ledger_data(ledger_path, True)
        self.assertTrue(
            any(
                "conditionally_verified contract fidelity has unresolved "
                "normalization checks" in error
                for error in errors
            ),
            errors,
        )

    def test_failed_zero_input_move_requires_structured_failure(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        step = ledger["steps"][2]
        step["premise_uses"] = []
        step["inference"]["moves"][0]["premise_ids"] = []
        step["status"] = "gap"
        step["issue_ids"] = ["I-001"]
        ledger["review"]["unit_status"] = "gap"
        ledger["review"]["argument_status"] = "gap"
        ledger["review"]["statement_status"] = "not_established"
        ledger["independent_check"]["challenger_verdict"] = "gap"
        ledger["independent_check"]["reconciled_verdict"] = "gap"
        write_json(ledger_path, ledger)
        errors, _ = proofcheck.check_ledger_data(ledger_path, True)
        self.assertTrue(
            any("zero-input failed move requires" in error for error in errors),
            errors,
        )

    def test_failed_zero_input_move_with_issue_link_passes(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        step = ledger["steps"][2]
        step["premise_uses"] = []
        move = step["inference"]["moves"][0]
        move["premise_ids"] = []
        move["rule"] = "Unsupported source assertion"
        move["justification"] = (
            "The source supplies no premise from which the conclusion follows."
        )
        move["failure"] = {
            "kind": "unsupported_assertion",
            "issue_id": "I-001",
            "evidence": (
                "The conclusion is asserted without a load-bearing premise."
            ),
        }
        step["status"] = "gap"
        step["issue_ids"] = ["I-001"]
        ledger["review"]["unit_status"] = "gap"
        ledger["review"]["argument_status"] = "gap"
        ledger["review"]["statement_status"] = "not_established"
        result = ledger["review"]["conclusion_results"][0]
        result["argument_status"] = "gap"
        result["statement_status"] = "not_established"
        result["issue_ids"] = ["I-001"]
        ledger["independent_check"]["challenger_verdict"] = "gap"
        ledger["independent_check"]["reconciled_verdict"] = "gap"
        write_json(ledger_path, ledger)
        self.seal_schema5_challenge(ledger_path, read_json(ledger_path))
        errors, _ = proofcheck.check_ledger_data(ledger_path, True)
        self.assertEqual([], errors)

        move["failure"]["evidence"] = "N/A"
        write_json(ledger_path, ledger)
        errors, _ = proofcheck.check_ledger_data(ledger_path, True)
        self.assertTrue(
            any(
                "failure.evidence must be nonempty and substantive" in error
                for error in errors
            ),
            errors,
        )

    def test_direct_dependency_must_exactly_mirror_step_record(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        dependency = {
            "id": "lem:prior",
            "use_id": "D001",
            "kind": "internal_result",
            "conclusion_id": "C001",
            "status": "verified",
            "needed_form": "The imported result gives x equals x.",
            "compatibility_check": "The result has the same domain and conclusion.",
        }
        step = ledger["steps"][2]
        step["dependencies"] = [dependency]
        step["premise_uses"].append(
            {
                "id": "P002",
                "role": "fact",
                "claim": dependency["needed_form"],
                "origin": {
                    "kind": "internal_result",
                    "reference": "D001",
                },
                "evidence": "The dependency supplies exactly the recorded form.",
            }
        )
        step["inference"]["moves"][0]["premise_ids"].append("P002")
        direct_dependency = dict(dependency)
        direct_dependency["needed_form"] = "A different imported conclusion."
        ledger["review"]["direct_dependencies"] = [direct_dependency]
        ledger["review"]["conclusion_results"][0]["dependency_use_ids"] = [
            "D001"
        ]
        write_json(ledger_path, ledger)
        errors, _ = proofcheck.check_ledger_data(ledger_path, True)
        self.assertTrue(
            any(
                "needed_form differs from review.direct_dependencies" in error
                for error in errors
            ),
            errors,
        )

    def test_source_reference_anchor_must_contain_exact_label(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        ledger["obligation"]["context_spans"].append(
            proofcheck.locked_span(
                self.definitions,
                1,
                1,
                ledger_path.parent,
                role="unrelated definition",
            )
        )
        premise = ledger["steps"][2]["premise_uses"][0]
        premise["origin"]["anchor"] = {
            "kind": "context_span",
            "index": 1,
        }
        premise["source_reference_id"] = "eq:reflexive"
        disposition = ledger["review"]["source_reference_dispositions"][0]
        premise["source_reference_occurrence_id"] = disposition["occurrence_id"]
        disposition["disposition"] = "obligation_context"
        disposition["premise_links"] = [
            {
                "step_id": "S003",
                "premise_id": "P001",
            }
        ]
        disposition["evidence"] = (
            "This link intentionally points to an unrelated locked span."
        )
        write_json(ledger_path, ledger)
        errors, _ = proofcheck.check_ledger_data(ledger_path, True)
        self.assertTrue(
            any("is not contained in its locked anchor" in error for error in errors),
            errors,
        )

    def test_missing_premise_cannot_support_refuted_status(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        step = ledger["steps"][2]
        step["premise_uses"] = []
        move = step["inference"]["moves"][0]
        move["premise_ids"] = []
        move["failure"] = {
            "kind": "missing_premise",
            "issue_id": "I-001",
            "evidence": "A required load-bearing premise is absent.",
        }
        step["status"] = "incorrect"
        step["issue_ids"] = ["I-001"]
        ledger["review"]["unit_status"] = "incorrect"
        ledger["review"]["argument_status"] = "invalid"
        ledger["review"]["statement_status"] = "refuted"
        result = ledger["review"]["conclusion_results"][0]
        result["argument_status"] = "invalid"
        result["statement_status"] = "refuted"
        result["issue_ids"] = ["I-001"]
        ledger["independent_check"]["challenger_verdict"] = "incorrect"
        ledger["independent_check"]["reconciled_verdict"] = "incorrect"
        write_json(ledger_path, ledger)
        errors, _ = proofcheck.check_ledger_data(ledger_path, True)
        self.assertTrue(
            any("missing_premise requires step status gap" in error for error in errors),
            errors,
        )
        self.assertTrue(
            any("counterexample or contradiction" in error for error in errors),
            errors,
        )

    def install_failure_computation(
        self, name: str = "witness-check.py"
    ) -> dict:
        script_path = self.audit / "audit" / "05_adversarial" / name
        script_path.parent.mkdir(parents=True, exist_ok=True)
        script_path.write_text(
            "value = 1\n"
            "assert value == value\n"
            "print('witness violates the claim')\n",
            encoding="utf-8",
            newline="\n",
        )
        return {
            "status": "instantiated",
            "script_file": f"../05_adversarial/{name}",
            "script_sha256": proofcheck.sha256_file(script_path),
            "command": f"python3 {name}",
            "output_excerpt": "witness violates the claim",
        }

    def refuted_ledger_with_failure(self, failure_extra: dict) -> Path:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        step = ledger["steps"][2]
        step["premise_uses"] = []
        step["restatement"] = "The recorded witness violates the conclusion."
        move = step["inference"]["moves"][0]
        move["claim"] = step["restatement"]
        move["premise_ids"] = []
        move["rule"] = "Counterexample"
        move["justification"] = "The recorded witness directly violates the claim."
        move["failure"] = {
            "kind": "counterexample",
            "issue_id": "I-001",
            "evidence": "Record the exact witness and evaluate both sides.",
            "target": ledger["obligation"]["conclusion"],
            **failure_extra,
        }
        step["status"] = "incorrect"
        step["issue_ids"] = ["I-001"]
        ledger["review"]["unit_status"] = "incorrect"
        ledger["review"]["argument_status"] = "invalid"
        ledger["review"]["statement_status"] = "refuted"
        result = ledger["review"]["conclusion_results"][0]
        result["argument_status"] = "invalid"
        result["statement_status"] = "refuted"
        result["issue_ids"] = ["I-001"]
        ledger["independent_check"]["challenger_verdict"] = "incorrect"
        ledger["independent_check"]["reconciled_verdict"] = "incorrect"
        write_json(ledger_path, ledger)
        self.seal_schema5_challenge(ledger_path, read_json(ledger_path))
        return ledger_path

    def test_counterexample_failure_can_support_refuted_status(self) -> None:
        ledger_path = self.refuted_ledger_with_failure(
            {"computation": self.install_failure_computation()}
        )
        errors, _ = proofcheck.check_ledger_data(ledger_path, True)
        self.assertEqual([], errors)

    def test_not_instantiable_computation_needs_substantive_reason(self) -> None:
        ledger_path = self.refuted_ledger_with_failure(
            {
                "computation": {
                    "status": "not_instantiable",
                    "reason": (
                        "The witness is a non-measurable construction with no "
                        "finite numerical instantiation."
                    ),
                }
            }
        )
        errors, _ = proofcheck.check_ledger_data(ledger_path, True)
        self.assertEqual([], errors)
        ledger = read_json(ledger_path)
        failure = ledger["steps"][2]["inference"]["moves"][0]["failure"]
        failure["computation"] = {"status": "not_instantiable", "reason": "TBD"}
        write_json(ledger_path, ledger)
        errors, _ = proofcheck.check_ledger_data(ledger_path, True)
        self.assertTrue(
            any("reason must be nonempty and substantive" in error for error in errors),
            errors,
        )

    def test_refutation_failure_requires_computation_record(self) -> None:
        ledger_path = self.refuted_ledger_with_failure({})
        errors, _ = proofcheck.check_ledger_data(ledger_path, True)
        self.assertTrue(
            any(
                "failure.computation is required for a counterexample failure"
                in error
                for error in errors
            ),
            errors,
        )

    def test_instantiated_computation_locks_a_real_adversarial_script(self) -> None:
        computation = self.install_failure_computation()
        ledger_path = self.refuted_ledger_with_failure(
            {"computation": computation}
        )
        cases = {
            "stale_hash": {**computation, "script_sha256": "0" * 64},
            "missing_file": {
                **computation,
                "script_file": "../05_adversarial/absent.py",
            },
            "outside_adversarial": {
                **computation,
                "script_file": "../../PROGRESS.json",
            },
        }
        expected = {
            "stale_hash": "does not match the current script file",
            "missing_file": "script_file not found",
            "outside_adversarial": "must resolve inside audit/05_adversarial",
        }
        for case, bad_computation in cases.items():
            with self.subTest(case=case):
                ledger = read_json(ledger_path)
                failure = ledger["steps"][2]["inference"]["moves"][0]["failure"]
                failure["computation"] = bad_computation
                write_json(ledger_path, ledger)
                self.seal_schema5_challenge(ledger_path, read_json(ledger_path))
                errors, _ = proofcheck.check_ledger_data(ledger_path, True)
                self.assertTrue(
                    any(expected[case] in error for error in errors),
                    errors,
                )

    def test_malformed_failure_kind_is_rejected_without_crashing(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        step = ledger["steps"][2]
        step["premise_uses"] = []
        move = step["inference"]["moves"][0]
        move["premise_ids"] = []
        move["failure"] = {
            "kind": [],
            "issue_id": "I-001",
            "evidence": "This malformed record must be rejected safely.",
        }
        step["status"] = "incorrect"
        step["issue_ids"] = ["I-001"]
        ledger["review"]["unit_status"] = "incorrect"
        ledger["review"]["argument_status"] = "invalid"
        ledger["review"]["statement_status"] = "refuted"
        ledger["independent_check"]["challenger_verdict"] = "incorrect"
        ledger["independent_check"]["reconciled_verdict"] = "incorrect"
        write_json(ledger_path, ledger)
        errors, _ = proofcheck.check_ledger_data(ledger_path, True)
        self.assertTrue(
            any("failure.kind is invalid" in error for error in errors),
            errors,
        )

    def test_mandatory_obligation_fields_reject_absence_markers(self) -> None:
        ledger_path = self.make_complete_audit()
        base_ledger = read_json(ledger_path)
        cases = (
            ("quantifier_scope", "obligation.quantifier_scope"),
            ("conclusion", "obligation.conclusion"),
            ("quantified_variable_domain", "quantified_variables[1].domain"),
        )
        for case, expected_field in cases:
            with self.subTest(case=case):
                ledger = json.loads(json.dumps(base_ledger))
                if case == "quantified_variable_domain":
                    ledger["obligation"]["quantified_variables"][0]["domain"] = (
                        "not applicable"
                    )
                else:
                    ledger["obligation"][case] = "not applicable"
                write_json(ledger_path, ledger)
                errors, _ = proofcheck.check_ledger_data(ledger_path, True)
                self.assertTrue(
                    any(
                        f"{expected_field} cannot use an absence marker" in error
                        for error in errors
                    ),
                    errors,
                )

    def test_normalized_obligation_rejects_unresolved_placeholders(self) -> None:
        ledger_path = self.make_complete_audit()
        base_ledger = read_json(ledger_path)
        cases = (
            (("quantifier_scope",), "TODO: fill this in", "obligation.quantifier_scope"),
            (("probability_model",), "**unknown**", "obligation.probability_model"),
            (("conclusion",), "`TBD`", "obligation.conclusion"),
            (("hypotheses", 0), r"\texttt{TODO}", "obligation.hypotheses[1]"),
            (("definitions", 0), r"\texttt{TODO}", "obligation.definitions[1]"),
            (
                ("constant_dependencies", 0),
                "TBD?",
                "obligation.constant_dependencies[1]",
            ),
            (
                ("quantified_variables", 0, "symbol"),
                r"\texttt{TODO}",
                "obligation.quantified_variables[1].symbol",
            ),
            (
                ("quantified_variables", 0, "type"),
                "TODO: fill this in",
                "obligation.quantified_variables[1].type",
            ),
            (
                ("quantified_variables", 0, "domain"),
                r"\texttt{TODO}",
                "obligation.quantified_variables[1].domain",
            ),
            (
                ("quantifier_scope",),
                "unknown: fill this in",
                "obligation.quantifier_scope",
            ),
            (
                ("conclusion",),
                "unresolved: verify later",
                "obligation.conclusion",
            ),
            (
                ("definitions", 0),
                "pending: author response",
                "obligation.definitions[1]",
            ),
            (
                ("quantified_variables", 0, "symbol"),
                "not checked: run audit",
                "obligation.quantified_variables[1].symbol",
            ),
            (
                ("quantifier_scope",),
                "unknown\uFF1Afill this in",
                "obligation.quantifier_scope",
            ),
            (
                ("quantified_variables", 0, "symbol"),
                "not  checked: run audit",
                "obligation.quantified_variables[1].symbol",
            ),
            (
                ("quantifier_scope",),
                "unknown\u2236fill this in",
                "obligation.quantifier_scope",
            ),
            (
                ("conclusion",),
                "unknown\uFE13fill this in",
                "obligation.conclusion",
            ),
            (
                ("definitions", 0),
                "unknown\u02D0fill this in",
                "obligation.definitions[1]",
            ),
            (
                ("quantified_variables", 0, "symbol"),
                "not\u200Bchecked: run audit",
                "obligation.quantified_variables[1].symbol",
            ),
            (
                ("quantified_variables", 0, "type"),
                "not\u2060checked: run audit",
                "obligation.quantified_variables[1].type",
            ),
            (
                ("quantifier_scope",),
                "unknown\uFE0F: fill this in",
                "obligation.quantifier_scope",
            ),
            (
                ("conclusion",),
                "unk\u034Fnown: fill this in",
                "obligation.conclusion",
            ),
        )
        for path, marker, expected_field in cases:
            with self.subTest(path=path, marker=marker):
                ledger = json.loads(json.dumps(base_ledger))
                target = ledger["obligation"]
                for part in path[:-1]:
                    target = target[part]
                target[path[-1]] = marker
                write_json(ledger_path, ledger)
                errors, _ = proofcheck.check_ledger_data(ledger_path, True)
                self.assertTrue(
                    any(
                        f"{expected_field} cannot use an unresolved placeholder"
                        in error
                        for error in errors
                    ),
                    errors,
                )

    def test_statistical_unknown_phrases_are_not_placeholders(self) -> None:
        ledger_path = self.make_complete_audit()
        base_ledger = read_json(ledger_path)
        phrases = (
            "Unknown (but fixed) parameter theta lies in Theta.",
            "Unknown-variance Gaussian errors have finite fourth moment.",
        )
        for phrase in phrases:
            with self.subTest(phrase=phrase):
                ledger = json.loads(json.dumps(base_ledger))
                ledger["obligation"]["hypotheses"] = [phrase]
                normalization = next(
                    item
                    for item in ledger["obligation"]["normalization_checks"]
                    if item["aspect"] == "hypotheses"
                )
                normalization["status"] = "checked"
                normalization["evidence"] = (
                    "The statistical hypothesis is stated explicitly."
                )
                write_json(ledger_path, ledger)
                self.seal_schema5_challenge(
                    ledger_path, read_json(ledger_path)
                )
                errors, _ = proofcheck.check_ledger_data(ledger_path, True)
                self.assertEqual([], errors)

    def test_commented_label_cannot_satisfy_source_anchor(self) -> None:
        ledger_path = self.make_complete_audit()
        self.definitions.write_text(
            "% \\label{eq:reflexive}\n",
            encoding="utf-8",
            newline="\n",
        )
        ledger = read_json(ledger_path)
        ledger["obligation"]["context_spans"].append(
            proofcheck.locked_span(
                self.definitions,
                1,
                1,
                ledger_path.parent,
                role="commented label",
            )
        )
        premise = ledger["steps"][2]["premise_uses"][0]
        premise["origin"]["anchor"] = {
            "kind": "context_span",
            "index": 1,
        }
        premise["source_reference_id"] = "eq:reflexive"
        disposition = ledger["review"]["source_reference_dispositions"][0]
        premise["source_reference_occurrence_id"] = disposition["occurrence_id"]
        disposition["disposition"] = "obligation_context"
        disposition["premise_links"] = [
            {
                "step_id": "S003",
                "premise_id": "P001",
            }
        ]
        disposition["evidence"] = "The only apparent label is commented out."
        write_json(ledger_path, ledger)
        errors, _ = proofcheck.check_ledger_data(ledger_path, True)
        self.assertTrue(
            any("is not contained in its locked anchor" in error for error in errors),
            errors,
        )

    def test_direct_dependency_compatibility_check_must_match(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        dependency = {
            "id": "lem:prior",
            "use_id": "D001",
            "kind": "internal_result",
            "conclusion_id": "C001",
            "status": "verified",
            "needed_form": "The imported result gives x equals x.",
            "compatibility_check": "The result has the same domain and conclusion.",
        }
        step = ledger["steps"][2]
        step["dependencies"] = [dependency]
        step["premise_uses"].append(
            {
                "id": "P002",
                "role": "fact",
                "claim": dependency["needed_form"],
                "origin": {
                    "kind": "internal_result",
                    "reference": "D001",
                },
                "evidence": "The dependency supplies exactly the recorded form.",
            }
        )
        step["inference"]["moves"][0]["premise_ids"].append("P002")
        direct_dependency = dict(dependency)
        direct_dependency["compatibility_check"] = (
            "A different compatibility assessment."
        )
        ledger["review"]["direct_dependencies"] = [direct_dependency]
        ledger["review"]["conclusion_results"][0]["dependency_use_ids"] = [
            "D001"
        ]
        write_json(ledger_path, ledger)
        errors, _ = proofcheck.check_ledger_data(ledger_path, True)
        self.assertTrue(
            any(
                "compatibility_check differs from review.direct_dependencies"
                in error
                for error in errors
            ),
            errors,
        )

    def test_local_enum_fields_reject_unhashable_values(self) -> None:
        ledger_path = self.make_complete_audit()
        base_ledger = read_json(ledger_path)
        paths = (
            ("source.coverage_mode", ("source", "coverage_mode")),
            (
                "obligation.quantifier",
                ("obligation", "quantified_variables", 0, "quantifier"),
            ),
            (
                "obligation.normalization.status",
                ("obligation", "normalization_checks", 0, "status"),
            ),
            ("obligation.uniformity", ("obligation", "uniformity")),
            ("obligation.regime", ("obligation", "regime")),
            ("independent.status", ("independent_check", "status")),
            (
                "independent.level",
                ("independent_check", "independence_level"),
            ),
            (
                "independent.challenger",
                ("independent_check", "challenger_verdict"),
            ),
            (
                "independent.reconciled",
                ("independent_check", "reconciled_verdict"),
            ),
            ("premise.role", ("steps", 2, "premise_uses", 0, "role")),
            (
                "premise.origin.kind",
                ("steps", 2, "premise_uses", 0, "origin", "kind"),
            ),
            (
                "premise.anchor.kind",
                (
                    "steps",
                    2,
                    "premise_uses",
                    0,
                    "origin",
                    "anchor",
                    "kind",
                ),
            ),
            ("step.kind", ("steps", 2, "kind")),
            ("step.status", ("steps", 2, "status")),
            (
                "step.atomicity",
                ("steps", 2, "checks", "atomicity", "status"),
            ),
            ("review.unit", ("review", "unit_status")),
            ("review.contract", ("review", "contract_fidelity")),
            ("review.dependency", ("review", "dependency_closure")),
            ("review.argument", ("review", "argument_status")),
            ("review.statement", ("review", "statement_status")),
            ("review.use", ("review", "use_site_sufficiency")),
            (
                "review.source_disposition",
                ("review", "source_reference_dispositions", 0, "disposition"),
            ),
            (
                "review.citation_disposition",
                ("review", "citation_dispositions", 0, "disposition"),
            ),
            ("risk.status", ("steps", 2, "risk_checks", 0, "status")),
        )
        for name, path in paths:
            with self.subTest(field=name):
                ledger = json.loads(json.dumps(base_ledger))
                cursor = ledger
                for token in path[:-1]:
                    cursor = cursor[token]
                cursor[path[-1]] = []
                write_json(ledger_path, ledger)
                errors, _ = proofcheck.check_ledger_data(ledger_path, True)
                self.assertTrue(errors)

    def test_nested_enum_fields_reject_unhashable_values(self) -> None:
        ledger_path = self.make_complete_audit()
        base_ledger = read_json(ledger_path)
        dependency = {
            "id": "lem:prior",
            "use_id": "D001",
            "kind": "internal_result",
            "conclusion_id": "C001",
            "status": "verified",
            "needed_form": "The imported result gives x equals x.",
            "compatibility_check": "The domains and conclusion agree.",
        }
        cases = (
            "step_dependency_kind",
            "step_dependency_status",
            "direct_dependency_kind",
            "direct_dependency_status",
            "side_condition_status",
            "discharge_kind",
            "condition_kind",
        )
        for case in cases:
            with self.subTest(case=case):
                ledger = json.loads(json.dumps(base_ledger))
                step = ledger["steps"][2]
                if case.startswith("step_dependency"):
                    record = dict(dependency)
                    record[case.rsplit("_", 1)[1]] = []
                    step["dependencies"] = [record]
                elif case.startswith("direct_dependency"):
                    record = dict(dependency)
                    record[case.rsplit("_", 1)[1]] = []
                    ledger["review"]["direct_dependencies"] = [record]
                elif case == "side_condition_status":
                    step["side_conditions"] = [
                        {
                            "id": "SC001",
                            "generated_by": "M001",
                            "condition": "A test condition.",
                            "status": [],
                        }
                    ]
                elif case == "discharge_kind":
                    step["side_conditions"] = [
                        {
                            "id": "SC001",
                            "generated_by": "M001",
                            "condition": "A test condition.",
                            "status": "discharged",
                            "discharge": {
                                "sources": [
                                    {
                                        "kind": [],
                                        "reference": "P001",
                                        "contribution": (
                                            "The malformed source would supply "
                                            "the domain premise."
                                        ),
                                    }
                                ],
                                "rule": "The domain premise discharges the condition.",
                                "evidence": "A malformed discharge kind.",
                            },
                        }
                    ]
                else:
                    step["conditions"] = [
                        {
                            "kind": [],
                            "reference": "domain",
                            "condition": "A malformed cause kind.",
                        }
                    ]
                write_json(ledger_path, ledger)
                errors, _ = proofcheck.check_ledger_data(ledger_path, True)
                self.assertTrue(errors)

    def test_malformed_move_links_return_errors_without_crashing(self) -> None:
        ledger_path = self.make_complete_audit()
        base_ledger = read_json(ledger_path)
        for case in ("conclusion_move", "generated_by", "discharge_reference"):
            with self.subTest(case=case):
                ledger = json.loads(json.dumps(base_ledger))
                step = ledger["steps"][2]
                if case == "conclusion_move":
                    step["inference"]["conclusion_move"] = []
                else:
                    step["side_conditions"] = [
                        {
                            "id": "SC001",
                            "generated_by": [] if case == "generated_by" else "M001",
                            "condition": "A malformed link.",
                            "status": "discharged",
                            "discharge": {
                                "sources": [
                                    {
                                        "kind": "inference_move",
                                        "reference": (
                                            []
                                            if case == "discharge_reference"
                                            else "M001"
                                        ),
                                        "contribution": (
                                            "The source is intentionally malformed "
                                            "for this negative control."
                                        ),
                                    }
                                ],
                                "rule": "Only an earlier move may discharge the condition.",
                                "evidence": "This malformed link must be rejected.",
                            },
                        }
                    ]
                write_json(ledger_path, ledger)
                errors, _ = proofcheck.check_ledger_data(ledger_path, True)
                self.assertTrue(errors)

    def test_malformed_obligation_span_lists_do_not_crash(self) -> None:
        ledger_path = self.make_complete_audit()
        base_ledger = read_json(ledger_path)
        for field in ("statement_spans", "context_spans"):
            for bad_value in (None, 1, True):
                with self.subTest(field=field, value=bad_value):
                    ledger = json.loads(json.dumps(base_ledger))
                    ledger["obligation"][field] = bad_value
                    write_json(ledger_path, ledger)
                    errors, _ = proofcheck.check_ledger_data(ledger_path, True)
                    self.assertTrue(errors)

    def test_n_a_marker_is_rejected_in_mandatory_obligation_fields(self) -> None:
        ledger_path = self.make_complete_audit()
        base_ledger = read_json(ledger_path)
        cases = (
            ("quantifier_scope", "obligation.quantifier_scope"),
            ("conclusion", "obligation.conclusion"),
            ("quantified_variable_domain", "quantified_variables[1].domain"),
        )
        for case, expected_field in cases:
            with self.subTest(case=case):
                ledger = json.loads(json.dumps(base_ledger))
                if case == "quantified_variable_domain":
                    ledger["obligation"]["quantified_variables"][0]["domain"] = "N/A"
                else:
                    ledger["obligation"][case] = "N/A"
                write_json(ledger_path, ledger)
                errors, _ = proofcheck.check_ledger_data(ledger_path, True)
                self.assertTrue(
                    any(
                        f"{expected_field} cannot use an absence marker" in error
                        for error in errors
                    ),
                    errors,
                )

    def test_reserved_bare_markers_are_not_substantive(self) -> None:
        markers = (
            "none",
            "N/A",
            "N/A.",
            "*N/A*",
            "**N/A**",
            "---N/A---",
            "not applicable",
            "not-applicable",
            "not_applicable",
            "unclear",
            "unknown",
            "***unknown***",
            "unresolved",
            "TBD",
            "TBD?",
            "TODO: fill this in",
            "TODO",
            "`TODO`",
            "_TODO_",
            "\\text{TODO}",
            "**\\text{TODO}**",
            "pending",
            "(pending)",
            "not checked",
            "not_checked",
        )
        for marker in markers:
            with self.subTest(marker=marker):
                self.assertFalse(proofcheck.is_substantive_string(marker))

    def test_marker_normalization_removes_visual_blank_characters(self) -> None:
        codepoints = (
            0x115F,
            0x1160,
            0x17B4,
            0x17B5,
            0x2800,
            0x3164,
            0xFFA0,
        )
        for codepoint in codepoints:
            with self.subTest(codepoint=hex(codepoint)):
                marker = f"unk{chr(codepoint)}nown: fill this in"
                self.assertEqual(
                    "unknown: fill this in",
                    proofcheck.normalized_marker(marker),
                )
                self.assertTrue(
                    proofcheck.is_forbidden_contract_placeholder(marker)
                )

    def test_structured_obligation_pointer_cannot_supply_arbitrary_claim(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        premise = ledger["steps"][2]["premise_uses"][0]
        premise["claim"] = "The Moon is made of green cheese."
        premise["origin"]["reference"] = "/quantified_variables/0"
        premise["evidence"] = "This arbitrary claim is intentionally invalid."
        write_json(ledger_path, ledger)
        errors, _ = proofcheck.check_ledger_data(ledger_path, True)
        self.assertTrue(
            any(
                "obligation premise must resolve to one concrete item" in error
                for error in errors
            ),
            errors,
        )

    def test_inactive_conditional_label_cannot_satisfy_source_anchor(self) -> None:
        ledger_path = self.make_complete_audit()
        self.definitions.write_text(
            "\\iffalse\n"
            "\\label{eq:reflexive}\n"
            "\\fi\n",
            encoding="utf-8",
            newline="\n",
        )
        ledger = read_json(ledger_path)
        ledger["obligation"]["context_spans"].append(
            proofcheck.locked_span(
                self.definitions,
                1,
                3,
                ledger_path.parent,
                role="inactive label",
            )
        )
        premise = ledger["steps"][2]["premise_uses"][0]
        premise["origin"]["anchor"] = {
            "kind": "context_span",
            "index": 1,
        }
        premise["source_reference_id"] = "eq:reflexive"
        disposition = ledger["review"]["source_reference_dispositions"][0]
        premise["source_reference_occurrence_id"] = disposition["occurrence_id"]
        disposition["disposition"] = "obligation_context"
        disposition["premise_links"] = [
            {
                "step_id": "S003",
                "premise_id": "P001",
            }
        ]
        disposition["evidence"] = "The only matching label is inactive."
        write_json(ledger_path, ledger)
        errors, _ = proofcheck.check_ledger_data(ledger_path, True)
        self.assertTrue(
            any("is not contained in its locked anchor" in error for error in errors),
            errors,
        )

    def test_unknown_and_unless_conditional_labels_are_not_treated_as_active(self) -> None:
        ledger_path = self.make_complete_audit()
        base_ledger = read_json(ledger_path)
        for conditional in ("\\ifcustom", "\\unless\\iftrue"):
            with self.subTest(conditional=conditional):
                self.definitions.write_text(
                    f"{conditional}\n"
                    "\\label{eq:reflexive}\n"
                    "\\fi\n",
                    encoding="utf-8",
                    newline="\n",
                )
                ledger = json.loads(json.dumps(base_ledger))
                ledger["obligation"]["context_spans"].append(
                    proofcheck.locked_span(
                        self.definitions,
                        1,
                        3,
                        ledger_path.parent,
                        role="unresolved conditional label",
                    )
                )
                premise = ledger["steps"][2]["premise_uses"][0]
                premise["origin"]["anchor"] = {
                    "kind": "context_span",
                    "index": 1,
                }
                premise["source_reference_id"] = "eq:reflexive"
                disposition = ledger["review"]["source_reference_dispositions"][0]
                premise["source_reference_occurrence_id"] = disposition[
                    "occurrence_id"
                ]
                disposition["disposition"] = "obligation_context"
                disposition["premise_links"] = [
                    {
                        "step_id": "S003",
                        "premise_id": "P001",
                    }
                ]
                disposition["evidence"] = "The matching label is not statically active."
                write_json(ledger_path, ledger)
                self.seal_schema5_challenge(
                    ledger_path, read_json(ledger_path)
                )
                errors, _ = proofcheck.check_ledger_data(ledger_path, True)
                self.assertTrue(
                    any(
                        "is not contained in its locked anchor" in error
                        for error in errors
                    ),
                    errors,
                )

    def test_nonexecuting_label_tokens_cannot_satisfy_source_anchor(self) -> None:
        ledger_path = self.make_complete_audit()
        base_ledger = read_json(ledger_path)
        cases = (
            (
                "newcommand",
                "\\newcommand{\\ghost}{\\label{eq:reflexive}}\n",
            ),
            (
                "conditional newcommand",
                "\\newcommand{\\ghost}{\\iftrue\\label{eq:reflexive}\\fi}\n",
            ),
            (
                "multiline newcommand",
                "\\newcommand{\\ghost}{%\n"
                "  \\label{eq:reflexive}\n"
                "}\n",
            ),
            (
                "primitive definition",
                "\\def\\ghost{\\label{eq:reflexive}}\n",
            ),
            (
                "document command",
                "\\NewDocumentCommand{\\ghost}{m}{\\label{eq:reflexive}}\n",
            ),
            (
                "latex3 command definition",
                "\\cs_new:Npn \\ghost:n #1 {\\label{eq:reflexive}}\n",
            ),
            (
                "latex3 protected command definition",
                "\\cs_new_protected:Npn \\ghost:n #1 "
                "{\\label{eq:reflexive}}\n",
            ),
            (
                "new document environment",
                "\\NewDocumentEnvironment{ghost}{}"
                "{\\label{eq:reflexive}}{}\n",
            ),
            (
                "renewed document environment",
                "\\RenewDocumentEnvironment{ghost}{}"
                "{\\label{eq:reflexive}}{}\n",
            ),
            (
                "paired delimiter definition",
                "\\DeclarePairedDelimiter{\\ghost}"
                "{\\label{eq:reflexive}}{\\rvert}\n",
            ),
            (
                "theorem definition",
                "\\newtheorem{ghost}{Title \\label{eq:reflexive}}\n",
            ),
            (
                "inline verb",
                "\\verb|\\label{eq:reflexive}|\n",
            ),
            (
                "verbatim environment",
                "\\begin{verbatim}\n"
                "\\label{eq:reflexive}\n"
                "\\end{verbatim}\n",
            ),
        )
        for case, source_text in cases:
            with self.subTest(case=case):
                self.definitions.write_text(
                    source_text,
                    encoding="utf-8",
                    newline="\n",
                )
                ledger = json.loads(json.dumps(base_ledger))
                end_line = len(source_text.splitlines())
                ledger["obligation"]["context_spans"].append(
                    proofcheck.locked_span(
                        self.definitions,
                        1,
                        end_line,
                        ledger_path.parent,
                        role="nonexecuting label token",
                    )
                )
                premise = ledger["steps"][2]["premise_uses"][0]
                premise["origin"]["anchor"] = {
                    "kind": "context_span",
                    "index": 1,
                }
                premise["source_reference_id"] = "eq:reflexive"
                disposition = ledger["review"]["source_reference_dispositions"][0]
                premise["source_reference_occurrence_id"] = disposition[
                    "occurrence_id"
                ]
                disposition["disposition"] = "obligation_context"
                disposition["premise_links"] = [
                    {
                        "step_id": "S003",
                        "premise_id": "P001",
                    }
                ]
                disposition["evidence"] = (
                    "The matching token occurs only in nonexecuting TeX."
                )
                write_json(ledger_path, ledger)
                errors, _ = proofcheck.check_ledger_data(ledger_path, True)
                self.assertTrue(
                    any(
                        "is not contained in its locked anchor" in error
                        for error in errors
                    ),
                    errors,
                )

    def test_label_after_command_definition_remains_active(self) -> None:
        ledger_path = self.make_complete_audit()
        self.definitions.write_text(
            "\\newcommand{\\ghost}{\\label{eq:inactive}}\n"
            "\\label{eq:reflexive}\n",
            encoding="utf-8",
            newline="\n",
        )
        ledger = read_json(ledger_path)
        ledger["obligation"]["context_spans"].append(
            proofcheck.locked_span(
                self.definitions,
                1,
                2,
                ledger_path.parent,
                role="active label after a definition",
            )
        )
        premise = ledger["steps"][2]["premise_uses"][0]
        premise["origin"]["anchor"] = {
            "kind": "context_span",
            "index": 1,
        }
        premise["source_reference_id"] = "eq:reflexive"
        disposition = ledger["review"]["source_reference_dispositions"][0]
        premise["source_reference_occurrence_id"] = disposition["occurrence_id"]
        disposition["disposition"] = "obligation_context"
        disposition["premise_links"] = [
            {
                "step_id": "S003",
                "premise_id": "P001",
            }
        ]
        disposition["evidence"] = "The label after the definition is active."
        write_json(ledger_path, ledger)
        self.seal_schema5_challenge(ledger_path, read_json(ledger_path))
        errors, _ = proofcheck.check_ledger_data(ledger_path, True)
        self.assertEqual([], errors)

    def test_label_after_extended_definition_families_remains_active(self) -> None:
        definitions = (
            (
                "latex3 command",
                "\\cs_new:Npn \\ghost:n #1 {\\label{eq:inactive}}\n",
            ),
            (
                "latex3 protected command",
                "\\cs_new_protected:Npn \\ghost:n #1 "
                "{\\label{eq:inactive}}\n",
            ),
            (
                "new document environment",
                "\\NewDocumentEnvironment{ghost}{}"
                "{\\label{eq:inactive}}{}\n",
            ),
            (
                "renewed document environment",
                "\\RenewDocumentEnvironment{ghost}{}"
                "{\\label{eq:inactive}}{}\n",
            ),
            (
                "paired delimiter",
                "\\DeclarePairedDelimiter{\\ghost}"
                "{\\label{eq:inactive}}{\\rvert}\n",
            ),
            (
                "theorem definition",
                "\\newtheorem{ghost}{Title \\label{eq:inactive}}\n",
            ),
        )
        for case, definition in definitions:
            with self.subTest(case=case):
                source_text = definition + "\\label{eq:reflexive}\n"
                self.definitions.write_text(
                    source_text, encoding="utf-8", newline="\n"
                )
                span = proofcheck.locked_span(
                    self.definitions,
                    1,
                    len(source_text.splitlines()),
                    self.base,
                )
                self.assertTrue(
                    proofcheck.locked_span_contains_label(
                        span, self.base, "eq:reflexive"
                    )
                )

    def test_refutation_requires_exact_target_and_verified_contract(self) -> None:
        ledger_path = self.make_complete_audit()
        base_ledger = read_json(ledger_path)
        step = base_ledger["steps"][2]
        step["premise_uses"] = []
        step["restatement"] = "The recorded witness violates the conclusion."
        move = step["inference"]["moves"][0]
        move["claim"] = step["restatement"]
        move["premise_ids"] = []
        move["rule"] = "Counterexample"
        move["justification"] = "The recorded witness directly violates the claim."
        move["failure"] = {
            "kind": "counterexample",
            "issue_id": "I-001",
            "target": base_ledger["obligation"]["conclusion"],
            "evidence": "Record the exact witness and evaluate both sides.",
        }
        step["status"] = "incorrect"
        step["issue_ids"] = ["I-001"]
        base_ledger["review"]["unit_status"] = "incorrect"
        base_ledger["review"]["argument_status"] = "invalid"
        base_ledger["review"]["statement_status"] = "refuted"
        result = base_ledger["review"]["conclusion_results"][0]
        result["argument_status"] = "invalid"
        result["statement_status"] = "refuted"
        result["issue_ids"] = ["I-001"]
        base_ledger["independent_check"]["challenger_verdict"] = "incorrect"
        base_ledger["independent_check"]["reconciled_verdict"] = "incorrect"

        cases = ("missing_target", "wrong_target", "unclear_contract")
        for case in cases:
            with self.subTest(case=case):
                ledger = json.loads(json.dumps(base_ledger))
                failure = ledger["steps"][2]["inference"]["moves"][0]["failure"]
                if case == "missing_target":
                    del failure["target"]
                elif case == "wrong_target":
                    failure["target"] = "An unrelated theorem."
                else:
                    ledger["review"]["contract_fidelity"] = "unclear"
                    ledger["review"]["conclusion_results"][0][
                        "contract_fidelity"
                    ] = "unclear"
                write_json(ledger_path, ledger)
                errors, _ = proofcheck.check_ledger_data(ledger_path, True)
                if case == "unclear_contract":
                    expected = "requires verified contract fidelity"
                else:
                    expected = "refutation target must exactly match"
                self.assertTrue(
                    any(expected in error for error in errors),
                    errors,
                )

    def record_domain_introduction(self, ledger: dict, prior: dict) -> None:
        prior["kind"] = "setup"
        prior["restatement"] = "x is fixed as a real number."
        prior["support_role"] = "derivation"
        prior["premise_uses"] = [
            {
                "id": "P001",
                "role": "fact",
                "claim": ledger["obligation"]["quantifier_scope"],
                "origin": {
                    "kind": "obligation",
                    "reference": "/quantifier_scope",
                    "anchor": {"kind": "statement_span", "index": 1},
                },
                "evidence": "The normalized universal quantifier authorizes this arbitrary real x.",
            }
        ]
        prior["checks"]["atomicity"] = {
            "status": "single_move",
            "evidence": "This introduction specializes the real domain while keeping x arbitrary.",
        }
        prior["inference"] = {
            "moves": [
                {
                    "id": "M001",
                    "claim": prior["restatement"],
                    "rule": "Introduction of an arbitrary element of the quantified domain",
                    "premise_ids": ["P001"],
                    "prior_move_ids": [],
                    "justification": "The universal real-number domain permits fixing arbitrary x without imposing positivity or another restriction.",
                }
            ],
            "conclusion_move": "M001",
        }

    def test_prior_step_dependency_is_bound_to_prior_restatement(self) -> None:
        ledger_path = self.make_complete_audit()
        valid_ledger = read_json(ledger_path)
        prior = valid_ledger["steps"][0]
        self.record_domain_introduction(valid_ledger, prior)
        dependency = {
            "id": "S001",
            "kind": "step",
            "status": "verified",
            "needed_form": prior["restatement"],
            "compatibility_check": "The same x is used in the conclusion step.",
        }
        step = valid_ledger["steps"][2]
        step["dependencies"] = [dependency]
        step["premise_uses"].append(
            {
                "id": "P002",
                "role": "fact",
                "claim": dependency["needed_form"],
                "origin": {
                    "kind": "prior_step",
                    "reference": "S001",
                },
                "evidence": "S001 supplies this exact setup claim.",
            }
        )
        step["inference"]["moves"][0]["premise_ids"].append("P002")
        write_json(ledger_path, valid_ledger)
        self.seal_schema5_challenge(ledger_path, read_json(ledger_path))
        errors, _ = proofcheck.check_ledger_data(ledger_path, True)
        self.assertEqual([], errors)

        invalid_ledger = json.loads(json.dumps(valid_ledger))
        invalid_dependency = invalid_ledger["steps"][2]["dependencies"][0]
        invalid_dependency["needed_form"] = "The Moon is made of green cheese."
        invalid_premise = invalid_ledger["steps"][2]["premise_uses"][1]
        invalid_premise["claim"] = invalid_dependency["needed_form"]
        write_json(ledger_path, invalid_ledger)
        errors, _ = proofcheck.check_ledger_data(ledger_path, True)
        self.assertTrue(
            any(
                "needed_form must exactly match the prior step restatement" in error
                for error in errors
            ),
            errors,
        )

    def add_consumed_definition_introduction(self, ledger: dict) -> dict:
        conclusion = next(
            step
            for step in ledger["steps"]
            if step["id"] == ledger["review"]["conclusion_step_id"]
        )
        introduction = json.loads(json.dumps(conclusion))
        introduction.update(
            {
                "id": "S099",
                "kind": "definition",
                "support_role": "derivation",
                "goal": "Expose the reflexive property of equality on the real domain.",
                "restatement": "Equality is reflexive on the real numbers.",
                "dependencies": [],
                "premise_uses": [
                    {
                        "id": "P001",
                        "role": "definition",
                        "claim": ledger["obligation"]["definitions"][0],
                        "origin": {
                            "kind": "obligation",
                            "reference": "/definitions/0",
                            "anchor": {"kind": "statement_span", "index": 1},
                        },
                        "evidence": "The normalized definition fixes equality on the real domain.",
                    }
                ],
            }
        )
        introduction["inference"] = {
            "moves": [
                {
                    "id": "M001",
                    "claim": introduction["restatement"],
                    "rule": "Expose the reflexive property of real equality",
                    "premise_ids": ["P001"],
                    "prior_move_ids": [],
                    "justification": "The equality relation used for real x is reflexive on its domain.",
                }
            ],
            "conclusion_move": "M001",
        }
        introduction["checks"]["literal"] = (
            "The locked proof invokes reflexivity for the current real x."
        )
        introduction["checks"]["atomicity"] = {
            "status": "single_move",
            "evidence": "The introduction isolates the reflexive property used for x.",
        }
        introduction["checks"]["adversarial"] = [
            "The equality relation remains defined for every real x, including zero."
        ]
        conclusion["premise_uses"].append(
            {
                "id": "P099",
                "role": "fact",
                "claim": introduction["restatement"],
                "origin": {"kind": "prior_step", "reference": "S099"},
                "evidence": "S099 establishes the reflexive property used for the current x.",
            }
        )
        conclusion["dependencies"].append(
            {
                "id": "S099",
                "kind": "step",
                "status": "verified",
                "needed_form": introduction["restatement"],
                "compatibility_check": "The same real equality relation is applied to x.",
            }
        )
        conclusion["inference"]["moves"][0]["premise_ids"].append("P099")
        ledger["steps"].insert(ledger["steps"].index(conclusion), introduction)
        return introduction

    def test_noninferential_setup_cannot_launder_forbidden_definition(self) -> None:
        ledger_path = self.make_complete_audit()
        baseline_errors, _ = proofcheck.check_audit_finalization(self.audit)
        self.assertEqual([], baseline_errors)
        ledger = read_json(ledger_path)
        introduction = self.add_consumed_definition_introduction(ledger)
        write_json(ledger_path, ledger)
        errors, _ = proofcheck.check_ledger_data(ledger_path, True, primary_only=True)
        self.assertTrue(
            any("outside C001.applies_under: /definitions/0" in error for error in errors),
            errors,
        )

        for kind in ("setup", "definition"):
            with self.subTest(kind=kind):
                introduction["kind"] = kind
                introduction.pop("support_role", None)
                introduction["premise_uses"] = []
                introduction["dependencies"] = []
                introduction["inference"] = {"moves": [], "conclusion_move": None}
                introduction["checks"]["atomicity"]["status"] = "non_inferential"
                write_json(ledger_path, ledger)
                self.seal_live_challenges()
                local_errors, _ = proofcheck.check_ledger_data(
                    ledger_path, True, primary_only=True
                )
                final_errors, _ = proofcheck.check_audit_finalization(self.audit)
                for level, observed in (("local", local_errors), ("final", final_errors)):
                    with self.subTest(level=level):
                        self.assertTrue(
                            any("unsupported step S099 as a factual premise" in error for error in observed),
                            observed,
                        )
                        self.assertTrue(
                            any("support closure stops at S099" in error for error in observed),
                            observed,
                        )

    def test_consumed_definition_introduction_keeps_authorized_assumptions(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        self.add_consumed_definition_introduction(ledger)
        ledger["obligation"]["conclusions"][0]["applies_under"].append("/definitions/0")
        write_json(ledger_path, ledger)
        self.seal_live_challenges()
        self.refresh_report_views()
        errors, _ = proofcheck.check_audit_finalization(self.audit)
        self.assertEqual([], errors)

    def test_unused_noninferential_declaration_is_still_allowed(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        declaration = self.add_consumed_definition_introduction(ledger)
        declaration.pop("support_role", None)
        declaration["premise_uses"] = []
        declaration["dependencies"] = []
        declaration["inference"] = {"moves": [], "conclusion_move": None}
        declaration["checks"]["atomicity"]["status"] = "non_inferential"
        conclusion = next(
            step for step in ledger["steps"]
            if step["id"] == ledger["review"]["conclusion_step_id"]
        )
        conclusion["premise_uses"] = [
            row for row in conclusion["premise_uses"] if row["id"] != "P099"
        ]
        conclusion["dependencies"] = [
            row for row in conclusion["dependencies"] if row["id"] != "S099"
        ]
        conclusion["inference"]["moves"][0]["premise_ids"].remove("P099")
        write_json(ledger_path, ledger)
        self.seal_live_challenges()
        self.refresh_report_views()
        errors, _ = proofcheck.check_audit_finalization(self.audit)
        self.assertEqual([], errors)

    def test_reserved_placeholders_cannot_form_a_prior_step_chain(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        prior = ledger["steps"][0]
        prior["kind"] = "setup"
        prior["restatement"] = "N/A"
        dependency = {
            "id": "S001",
            "kind": "step",
            "status": "verified",
            "needed_form": "N/A",
            "compatibility_check": "N/A",
        }
        step = ledger["steps"][2]
        step["dependencies"] = [dependency]
        step["premise_uses"].append(
            {
                "id": "P002",
                "role": "fact",
                "claim": "N/A",
                "origin": {
                    "kind": "prior_step",
                    "reference": "S001",
                },
                "evidence": "N/A",
            }
        )
        step["inference"]["moves"][0]["premise_ids"].append("P002")
        write_json(ledger_path, ledger)
        errors, _ = proofcheck.check_ledger_data(ledger_path, True)
        expected_fragments = (
            "S001: substantive step needs a restatement",
            ".needed_form must state the exact form used",
            ".compatibility_check must map the result to this use",
            ".claim must be a nonempty string",
            ".evidence must be a nonempty string",
        )
        for fragment in expected_fragments:
            with self.subTest(fragment=fragment):
                self.assertTrue(
                    any(
                        fragment in error and "reserved placeholder" in error
                        for error in errors
                    ),
                    errors,
                )

    def test_reserved_placeholders_are_rejected_across_evidence_fields(self) -> None:
        ledger_path = self.make_complete_audit()
        base_ledger = read_json(ledger_path)
        cases = (
            (
                "normalization evidence",
                lambda value: value["obligation"]["normalization_checks"][0].__setitem__(
                    "evidence", "N/A"
                ),
                "obligation.normalization_checks[1].evidence",
            ),
            (
                "risk evidence",
                lambda value: value["steps"][2]["risk_checks"][0].__setitem__("evidence", "N/A"),
                "S003.risk_checks[1].evidence",
            ),
            (
                "premise evidence",
                lambda value: value["steps"][2]["premise_uses"][0].__setitem__("evidence", "N/A"),
                "S003.premise_uses[1].evidence",
            ),
            (
                "source-reference evidence",
                lambda value: value["review"]["source_reference_dispositions"][0].__setitem__(
                    "evidence", "N/A"
                ),
                "review.source_reference_dispositions[1].evidence",
            ),
            (
                "citation evidence",
                lambda value: value["review"]["citation_dispositions"][0].__setitem__(
                    "evidence", "N/A"
                ),
                "review.citation_dispositions[1].evidence",
            ),
            (
                "move rule",
                lambda value: value["steps"][2]["inference"]["moves"][0].__setitem__("rule", "N/A"),
                "S003.inference.moves[1].rule",
            ),
            (
                "literal check",
                lambda value: value["steps"][2]["checks"].__setitem__("literal", "N/A"),
                "S003.checks.literal",
            ),
            (
                "adversarial check",
                lambda value: value["steps"][2]["checks"].__setitem__("adversarial", ["N/A"]),
                "S003.checks.adversarial",
            ),
            (
                "atomicity evidence",
                lambda value: value["steps"][2]["checks"]["atomicity"].__setitem__(
                    "evidence", "N/A"
                ),
                "S003.checks.atomicity.evidence",
            ),
            (
                "verification basis",
                lambda value: value["review"].__setitem__("verification_basis", ["N/A"]),
                "review.verification_basis",
            ),
            (
                "reviewer note",
                lambda value: value["review"].__setitem__("reviewer_notes", ["N/A"]),
                "review.reviewer_notes",
            ),
        )
        for case, mutate, field in cases:
            with self.subTest(case=case):
                ledger = json.loads(json.dumps(base_ledger))
                mutate(ledger)
                write_json(ledger_path, ledger)
                errors, _ = proofcheck.check_ledger_data(ledger_path, True)
                self.assertTrue(
                    any(
                        field in error
                        and ("substantive" in error or "reserved placeholder" in error)
                        for error in errors
                    ),
                    errors,
                )

    def test_duplicate_quantified_variable_symbol_fails(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        ledger["obligation"]["quantified_variables"].append(
            {
                "symbol": "x",
                "type": "real number",
                "domain": "R",
                "quantifier": "forall",
            }
        )
        write_json(ledger_path, ledger)
        errors, _ = proofcheck.check_ledger_data(ledger_path, True)
        self.assertTrue(
            any("duplicate quantified variable symbol x" in error for error in errors),
            errors,
        )

    def test_final_ledger_requires_designated_conclusion_step(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        del ledger["review"]["conclusion_step_id"]
        write_json(ledger_path, ledger)
        errors, _ = proofcheck.check_ledger_data(ledger_path, True)
        self.assertTrue(
            any("conclusion_step_id must equal its support step" in error for error in errors),
            errors,
        )

    def test_designated_conclusion_step_must_exist(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        ledger["review"]["conclusion_step_id"] = "S999"
        write_json(ledger_path, ledger)
        errors, _ = proofcheck.check_ledger_data(ledger_path, True)
        self.assertTrue(
            any("conclusion_step_id must equal its support step" in error for error in errors),
            errors,
        )

    def test_designated_conclusion_must_match_obligation(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        ledger["obligation"]["conclusion"] = "y equals y"
        write_json(ledger_path, ledger)
        errors, _ = proofcheck.check_ledger_data(ledger_path, True)
        self.assertTrue(
            any(
                "obligation.conclusion must exactly match" in error
                for error in errors
            ),
            errors,
        )

    def test_designated_conclusion_step_must_be_inferential(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        ledger["review"]["conclusion_step_id"] = "S001"
        write_json(ledger_path, ledger)
        errors, _ = proofcheck.check_ledger_data(ledger_path, True)
        self.assertTrue(
            any("conclusion_step_id must equal its support step" in error for error in errors),
            errors,
        )

    def test_conclusion_step_status_matches_statement_status(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        self.mark_s003_conditional(ledger)
        ledger["review"]["statement_status"] = "established"
        write_json(ledger_path, ledger)
        errors, _ = proofcheck.check_ledger_data(ledger_path, True)
        self.assertTrue(
            any(
                "review.statement_status must be the weakest conclusion judgment"
                in error
                for error in errors
            ),
            errors,
        )

    def test_inference_move_cannot_have_zero_inputs(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        step = ledger["steps"][2]
        step["premise_uses"] = []
        step["inference"]["moves"][0]["premise_ids"] = []
        write_json(ledger_path, ledger)
        errors, _ = proofcheck.check_ledger_data(ledger_path, True)
        self.assertTrue(
            any(
                "must use at least one premise or earlier move" in error
                for error in errors
            ),
            errors,
        )

    def test_orphan_inference_move_is_rejected(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        step = ledger["steps"][2]
        second_premise = json.loads(json.dumps(step["premise_uses"][0]))
        second_premise["id"] = "P002"
        step["premise_uses"].append(second_premise)
        step["checks"]["atomicity"] = {
            "status": "source_indivisible_chain",
            "source_unit_kind": "one_line",
            "partition_evidence": (
                "The one line has two independent candidate moves for this test."
            ),
            "evidence": "The negative control records two moves on one source line.",
        }
        step["inference"] = {
            "moves": [
                {
                    "id": "M001",
                    "claim": "A detached domain observation.",
                    "rule": "Domain inspection",
                    "premise_ids": ["P001"],
                    "prior_move_ids": [],
                    "justification": "P001 gives the stated domain observation.",
                },
                {
                    "id": "M002",
                    "claim": step["restatement"],
                    "rule": "Reflexivity of equality",
                    "premise_ids": ["P002"],
                    "prior_move_ids": [],
                    "justification": "P002 supplies the arbitrary real variable.",
                },
            ],
            "conclusion_move": "M002",
        }
        ledger["review"]["conclusion_results"][0]["support"]["move_id"] = "M002"
        write_json(ledger_path, ledger)
        errors, _ = proofcheck.check_ledger_data(ledger_path, True)
        self.assertTrue(
            any(
                "inference moves are not load-bearing for the conclusion: M001"
                in error
                for error in errors
            ),
            errors,
        )

    def test_dependency_premise_claim_must_match_needed_form(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        dependency = {
            "id": "lem:prior",
            "use_id": "D001",
            "kind": "internal_result",
            "conclusion_id": "C001",
            "status": "verified",
            "needed_form": "The imported result gives x equals x.",
            "compatibility_check": "The result has the same domain and conclusion.",
        }
        step = ledger["steps"][2]
        step["dependencies"] = [dependency]
        step["premise_uses"].append(
            {
                "id": "P002",
                "role": "fact",
                "claim": "A stronger claim not supplied by the result.",
                "origin": {
                    "kind": "internal_result",
                    "reference": "D001",
                },
                "evidence": "This is an intentional mismatch.",
            }
        )
        step["inference"]["moves"][0]["premise_ids"].append("P002")
        ledger["review"]["direct_dependencies"] = [dependency]
        ledger["review"]["conclusion_results"][0]["dependency_use_ids"] = [
            "D001"
        ]
        write_json(ledger_path, ledger)
        errors, _ = proofcheck.check_ledger_data(ledger_path, True)
        self.assertTrue(
            any(
                "claim must exactly match dependency D001 needed_form" in error
                for error in errors
            ),
            errors,
        )

    def test_prior_step_premise_claim_must_match_needed_form(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        ledger["steps"][0]["kind"] = "setup"
        dependency = {
            "id": "S001",
            "kind": "step",
            "status": "verified",
            "needed_form": "x is fixed as a real number.",
            "compatibility_check": "The setup introduces the same x used below.",
        }
        step = ledger["steps"][2]
        step["dependencies"] = [dependency]
        step["premise_uses"].append(
            {
                "id": "P002",
                "role": "fact",
                "claim": "x is a positive real number.",
                "origin": {"kind": "prior_step", "reference": "S001"},
                "evidence": "This intentionally strengthens the needed form.",
            }
        )
        step["inference"]["moves"][0]["premise_ids"].append("P002")
        write_json(ledger_path, ledger)
        errors, _ = proofcheck.check_ledger_data(ledger_path, True)
        self.assertTrue(
            any(
                "claim must exactly match dependency S001 needed_form" in error
                for error in errors
            ),
            errors,
        )

    def test_theorem_statement_step_cannot_be_a_prior_premise(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        dependency = {
            "id": "S001",
            "kind": "step",
            "status": "verified",
            "needed_form": "For every real x, x equals x.",
            "compatibility_check": "This intentionally cites the target statement.",
        }
        step = ledger["steps"][2]
        step["dependencies"] = [dependency]
        step["premise_uses"].append(
            {
                "id": "P002",
                "role": "fact",
                "claim": dependency["needed_form"],
                "origin": {"kind": "prior_step", "reference": "S001"},
                "evidence": "This is the circular target statement.",
            }
        )
        step["inference"]["moves"][0]["premise_ids"].append("P002")
        write_json(ledger_path, ledger)
        errors, _ = proofcheck.check_ledger_data(ledger_path, True)
        self.assertTrue(
            any("cannot use the theorem statement step S001" in error for error in errors),
            errors,
        )

    def test_non_substantive_step_cannot_be_a_prior_premise(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        dependency = {
            "id": "S002",
            "kind": "step",
            "status": "not_applicable",
            "needed_form": "The proof environment is open.",
            "compatibility_check": "This intentionally cites a delimiter row.",
        }
        step = ledger["steps"][2]
        step["dependencies"] = [dependency]
        step["premise_uses"].append(
            {
                "id": "P002",
                "role": "fact",
                "claim": dependency["needed_form"],
                "origin": {"kind": "prior_step", "reference": "S002"},
                "evidence": "This is an intentional non-substantive premise.",
            }
        )
        step["inference"]["moves"][0]["premise_ids"].append("P002")
        write_json(ledger_path, ledger)
        errors, _ = proofcheck.check_ledger_data(ledger_path, True)
        self.assertTrue(
            any("cannot use non_substantive step S002" in error for error in errors),
            errors,
        )

    def test_duplicate_premise_id_is_rejected(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        duplicate = json.loads(json.dumps(ledger["steps"][2]["premise_uses"][0]))
        ledger["steps"][2]["premise_uses"].append(duplicate)
        write_json(ledger_path, ledger)
        errors, _ = proofcheck.check_ledger_data(ledger_path, True)
        self.assertTrue(
            any("duplicate premise id P001" in error for error in errors),
            errors,
        )

    def test_string_obligation_premise_claim_must_match_origin(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        premise = ledger["steps"][2]["premise_uses"][0]
        premise["origin"]["reference"] = "/quantifier_scope"
        premise["claim"] = "A different quantifier scope."
        write_json(ledger_path, ledger)
        errors, _ = proofcheck.check_ledger_data(ledger_path, True)
        self.assertTrue(
            any(
                "claim must exactly match its string-valued obligation premise"
                in error
                for error in errors
            ),
            errors,
        )

    def test_risk_check_evidence_cannot_be_blank(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        ledger["steps"][2]["risk_checks"][0]["evidence"] = " "
        write_json(ledger_path, ledger)
        errors, _ = proofcheck.check_ledger_data(ledger_path, True)
        self.assertTrue(
            any(
                "S003.risk_checks[1].evidence must be a nonempty string"
                in error
                for error in errors
            ),
            errors,
        )

    def test_conditional_step_cannot_hide_failed_risk(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        step = self.mark_s003_conditional(ledger)
        domain = next(
            row for row in step["risk_checks"] if row["aspect"] == "domain"
        )
        domain["status"] = "failed"
        domain["evidence"] = "The required domain relation is false."
        step["conditions"] = []
        write_json(ledger_path, ledger)
        errors, _ = proofcheck.check_ledger_data(ledger_path, True)
        self.assertTrue(
            any(
                "cannot hide failed or unclear risk checks: domain" in error
                for error in errors
            ),
            errors,
        )

    def test_conditional_open_risk_with_exact_mapping_passes(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        step = self.mark_s003_conditional(ledger)
        domain = next(
            row for row in step["risk_checks"] if row["aspect"] == "domain"
        )
        domain["status"] = "open"
        domain["evidence"] = "Domain compatibility remains an explicit condition."
        step["conditions"] = [
            {
                "kind": "risk_check",
                "reference": "domain",
                "condition": "Validity is conditional on domain compatibility.",
            }
        ]
        write_json(ledger_path, ledger)
        self.seal_schema5_challenge(ledger_path, read_json(ledger_path))
        errors, _ = proofcheck.check_ledger_data(ledger_path, True)
        self.assertEqual([], errors)

    def test_conclusion_normalization_cannot_be_not_applicable(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        conclusion = next(
            row
            for row in ledger["obligation"]["normalization_checks"]
            if row["aspect"] == "conclusion"
        )
        conclusion["status"] = "not_applicable"
        conclusion["evidence"] = "This disposition is intentionally invalid."
        write_json(ledger_path, ledger)
        errors, _ = proofcheck.check_ledger_data(ledger_path, True)
        self.assertTrue(
            any(
                "normalization_checks[conclusion] cannot be not_applicable" in error
                for error in errors
            ),
            errors,
        )

    def test_unclear_model_requires_unclear_normalization(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        ledger["obligation"]["probability_model"] = "unclear"
        write_json(ledger_path, ledger)
        errors, _ = proofcheck.check_ledger_data(ledger_path, True)
        self.assertTrue(
            any(
                "probability_model is unclear but its normalization check is not"
                in error
                for error in errors
            ),
            errors,
        )
        self.assertFalse(
            any(
                "cannot use an unresolved placeholder" in error
                for error in errors
            ),
            errors,
        )

    def test_braces_are_substantive_source_lines(self) -> None:
        self.assertFalse(proofcheck.is_non_substantive("{"))
        self.assertFalse(proofcheck.is_non_substantive("}"))

    def test_nonfinal_validation_is_inspection_only(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = self.downgrade_ledger_fixture_to_schema4(
            read_json(ledger_path)
        )
        write_json(ledger_path, ledger)
        errors, summary = proofcheck.check_ledger_data(ledger_path, False)
        self.assertEqual([], errors)
        self.assertEqual("draft", summary["validation_mode"])
        self.assertEqual(
            "legacy_inspection_only",
            summary["validation_scope"]["local_record_integrity"],
        )

    def test_legacy_challenge_without_schema5_freshness_is_inspection_only(
        self,
    ) -> None:
        ledger_path = self.make_complete_audit()
        ledger = self.downgrade_ledger_fixture_to_schema4(
            read_json(ledger_path)
        )
        for field in (
            "covered_issue_ids",
            "source_snapshot_sha256",
            "challenged_ledger_sha256",
            "challenge_context_sha256",
            "challenge_artifact_sha256",
            "issue_assessments",
            "generated_utc",
        ):
            ledger["independent_check"].pop(field, None)
        write_json(ledger_path, ledger)

        draft_errors, summary = proofcheck.check_ledger_data(
            ledger_path, False
        )
        final_errors, _ = proofcheck.check_ledger_data(ledger_path, True)

        self.assertEqual([], draft_errors)
        self.assertEqual(
            "legacy_inspection_only",
            summary["validation_scope"]["local_record_integrity"],
        )
        self.assertTrue(
            any("upgrade_required" in error for error in final_errors),
            final_errors,
        )
        for field in (
            "covered_issue_ids",
            "source_snapshot_sha256",
            "challenged_ledger_sha256",
            "challenge_context_sha256",
            "challenge_artifact_sha256",
            "issue_assessments",
            "generated_utc",
        ):
            self.assertFalse(
                any(field in error for error in final_errors),
                (field, final_errors),
            )

    def test_schema4_issue_log_is_inspection_only_and_blocks_final_mode(
        self,
    ) -> None:
        self.make_complete_audit()
        issue_path = self.audit / "audit" / "06_reports" / "ISSUE_LOG.json"
        issue_log = read_json(issue_path)
        issue_log["schema_version"] = 4
        write_json(issue_path, issue_log)

        final_errors, _ = proofcheck.check_audit_finalization(self.audit)
        output = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(
            stderr
        ):
            status = proofcheck.cmd_issues(
                argparse.Namespace(
                    root=self.audit,
                    write_summary=False,
                    write_report_views=False,
                    final=True,
                )
            )

        self.assertEqual(1, status)
        self.assertTrue(
            any(
                "ISSUE_LOG" in error
                and "upgrade_required" in error
                and "schema" in error.lower()
                for error in final_errors
            ),
            final_errors,
        )
        self.assertIn("upgrade_required", stderr.getvalue())

    def test_legacy_finalize_does_not_overwrite_authored_workflow_views(
        self,
    ) -> None:
        self.make_complete_audit()
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        manifest["schema_version"] = proofcheck.LEGACY_SCHEMA_VERSION
        manifest["protocol"]["artifact_schema_version"] = (
            proofcheck.LEGACY_SCHEMA_VERSION
        )
        write_json(manifest_path, manifest)
        plan_path = self.audit / "CHECK_PLAN.md"
        authored = (
            "# Legacy authored plan\n\n"
            "This central claim and risk analysis must be preserved.\n"
        )
        plan_path.write_text(authored, encoding="utf-8", newline="\n")

        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(
            io.StringIO()
        ):
            status = proofcheck.cmd_finalize(argparse.Namespace(root=self.audit))

        self.assertEqual(1, status)
        self.assertEqual(authored, plan_path.read_text(encoding="utf-8"))

    def test_obligation_context_reference_requires_a_premise_link(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        disposition = ledger["review"]["source_reference_dispositions"][0]
        disposition["disposition"] = "obligation_context"
        write_json(ledger_path, ledger)
        errors, _ = proofcheck.check_ledger_data(ledger_path, True)
        self.assertTrue(
            any(
                "obligation_context requires nonempty premise_links" in error
                for error in errors
            ),
            errors,
        )

    def test_obligation_context_reference_with_exact_premise_link_passes(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        premise = ledger["steps"][2]["premise_uses"][0]
        premise["source_reference_id"] = "eq:reflexive"
        disposition = ledger["review"]["source_reference_dispositions"][0]
        premise["source_reference_occurrence_id"] = disposition["occurrence_id"]
        disposition["disposition"] = "obligation_context"
        disposition["premise_links"] = [
            {
                "step_id": "S003",
                "premise_id": "P001",
            }
        ]
        disposition["evidence"] = (
            "The referenced statement supplies the exact domain premise P001."
        )
        write_json(ledger_path, ledger)
        self.seal_schema5_challenge(ledger_path, read_json(ledger_path))
        errors, _ = proofcheck.check_ledger_data(ledger_path, True)
        self.assertEqual([], errors)

    def test_source_reference_premise_requires_reverse_disposition_link(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        ledger["steps"][2]["premise_uses"][0]["source_reference_id"] = (
            "eq:reflexive"
        )
        ledger["steps"][2]["premise_uses"][0][
            "source_reference_occurrence_id"
        ] = ledger["review"]["source_reference_dispositions"][0]["occurrence_id"]
        write_json(ledger_path, ledger)
        errors, _ = proofcheck.check_ledger_data(ledger_path, True)
        self.assertTrue(
            any(
                "Premises with source reference anchors lack an exact "
                "occurrence link" in error
                for error in errors
            ),
            errors,
        )

    def test_completed_gap_can_preserve_target_mismatch(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        ledger["obligation"]["conclusion"] = "A stronger conclusion."
        ledger["obligation"]["conclusions"][0]["claim"] = "A stronger conclusion."
        step = ledger["steps"][2]
        step["status"] = "gap"
        step["issue_ids"] = ["I-001"]
        ledger["review"]["unit_status"] = "gap"
        ledger["review"]["argument_status"] = "gap"
        ledger["review"]["statement_status"] = "not_established"
        result = ledger["review"]["conclusion_results"][0]
        result["argument_status"] = "gap"
        result["statement_status"] = "not_established"
        result["issue_ids"] = ["I-001"]
        ledger["independent_check"]["challenger_verdict"] = "gap"
        ledger["independent_check"]["reconciled_verdict"] = "gap"
        write_json(ledger_path, ledger)
        self.seal_schema5_challenge(ledger_path, read_json(ledger_path))
        errors, _ = proofcheck.check_ledger_data(ledger_path, True)
        self.assertEqual([], errors)

    def test_locked_source_records_must_be_an_ordered_bijection(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        ledger["source_lines"][1]["line"] = ledger["source_lines"][0]["line"]
        write_json(ledger_path, ledger)
        errors, _ = proofcheck.check_ledger_data(ledger_path, True)
        self.assertTrue(
            any("source_lines[2].line must be" in error for error in errors),
            errors,
        )

    def test_contract_must_anchor_the_inventoried_statement(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        ledger["obligation"]["statement_spans"] = [
            proofcheck.locked_span(self.paper, 3, 3, ledger_path.parent)
        ]
        write_json(ledger_path, ledger)
        errors, _ = proofcheck.check_audit_finalization(self.audit)
        self.assertTrue(
            any("does not exactly match the inventory" in error for error in errors),
            errors,
        )

    def test_source_reference_needs_a_reviewed_disposition(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        ledger["review"]["source_reference_dispositions"] = []
        write_json(ledger_path, ledger)
        errors, _ = proofcheck.check_audit_finalization(self.audit)
        self.assertTrue(
            any(
                "source occurrences lack reviewed dispositions" in error
                for error in errors
            ),
            errors,
        )

    def test_reviewed_inventory_cannot_drop_a_discovered_unit(self) -> None:
        self.make_complete_audit()
        inventory_path = (
            self.audit / "audit" / "01_index" / "theorem_inventory.json"
        )
        inventory = read_json(inventory_path)
        inventory["units"] = []
        write_json(inventory_path, inventory)
        errors, _ = proofcheck.check_audit_finalization(self.audit)
        self.assertTrue(
            any("omits parser-discovered units" in error for error in errors), errors
        )

    def test_agreed_challenger_must_match_primary_verdict(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        ledger["independent_check"]["challenger_verdict"] = "incorrect"
        write_json(ledger_path, ledger)
        errors, _ = proofcheck.check_ledger_data(ledger_path, True)
        self.assertTrue(
            any("challenger_verdict differs" in error for error in errors), errors
        )

    def test_agreed_challenge_requires_matching_recorded_verdicts(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        ledger["independent_check"]["challenger_verdict"] = "verified"
        ledger["independent_check"]["reconciled_verdict"] = "incorrect"
        ledger["independent_check"]["disagreements"] = []
        self.seal_schema5_challenge(ledger_path, ledger)

        errors, _ = proofcheck.check_ledger_data(ledger_path, True)

        self.assertTrue(
            any(
                "agreed" in error
                and "challenger" in error
                and "reconciled" in error
                for error in errors
            ),
            errors,
        )

    def test_resolved_challenge_requires_a_recorded_disagreement(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        ledger["independent_check"].update(
            {
                "status": "resolved",
                "challenger_verdict": "incorrect",
                "reconciled_verdict": "verified",
                "disagreements": [],
                "resolution": (
                    "The primary audit rechecked the disputed transition and "
                    "documented why the verified verdict is retained."
                ),
            }
        )
        self.seal_schema5_challenge(ledger_path, ledger)

        errors, _ = proofcheck.check_ledger_data(ledger_path, True)

        self.assertTrue(
            any(
                "resolved" in error
                and "disagreement" in error
                for error in errors
            ),
            errors,
        )

    def test_required_challenger_cannot_be_not_checked(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        ledger["independent_check"]["challenger_verdict"] = "not_checked"
        write_json(ledger_path, ledger)
        errors, _ = proofcheck.check_ledger_data(ledger_path, True)
        self.assertTrue(
            any("needs a checked challenger verdict" in error for error in errors),
            errors,
        )

    def test_parser_warning_record_cannot_be_rewritten(self) -> None:
        self.make_complete_audit()
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        manifest["parser_warnings"] = ["invented warning"]
        manifest["audit_scope"]["source_or_parser_limits"] = [
            "An invented warning was reviewed."
        ]
        write_json(manifest_path, manifest)
        errors, _ = proofcheck.check_audit_finalization(self.audit)
        self.assertTrue(
            any("does not match the current parser warning set" in error for error in errors),
            errors,
        )

    def test_extract_supports_statement_and_proof_in_different_files(self) -> None:
        statement_file = self.base / "statement.tex"
        proof_file = self.base / "proof.tex"
        statement_file.write_text(
            "\\begin{lemma}\nA statement.\n\\end{lemma}\n",
            encoding="utf-8",
            newline="\n",
        )
        proof_file.write_text(
            "\\begin{proof}\nA proof.\n\\end{proof}\n",
            encoding="utf-8",
            newline="\n",
        )
        ledger_path = self.base / "split.ledger.json"
        with contextlib.redirect_stdout(io.StringIO()):
            proofcheck.cmd_extract(
                argparse.Namespace(
                    file=proof_file,
                    start=1,
                    end=3,
                    statement_file=statement_file,
                    statement_start=1,
                    statement_end=3,
                    separate_statement_reason="Statement and proof are in different files.",
                    unit_id="lem:split",
                    output=ledger_path,
                    force=False,
                )
            )
        ledger = read_json(ledger_path)
        span = ledger["obligation"]["statement_spans"][0]
        self.assertEqual(
            statement_file.resolve(),
            proofcheck.resolve_stored_path(span["file"], ledger_path.parent),
        )

    def test_extract_reports_skeleton_state_and_next_action(self) -> None:
        ledger_path = self.base / "skeleton.ledger.json"
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = proofcheck.cmd_extract(
                argparse.Namespace(
                    file=self.paper,
                    start=2,
                    end=7,
                    statement_file=self.paper,
                    statement_start=2,
                    statement_end=4,
                    separate_statement_reason=None,
                    unit_id="lem:skeleton",
                    output=ledger_path,
                    force=False,
                )
            )
        payload = json.loads(output.getvalue())

        self.assertEqual(0, status)
        self.assertEqual("source_locked_skeleton", payload["artifact_state"])
        self.assertIn("next_action", payload)
        self.assertTrue(payload["next_action"].strip())
        self.assertIn("obligation", payload["next_action"].lower())
        self.assertIn("step", payload["next_action"].lower())

    def make_legacy_migration_fixture(self) -> tuple[Path, Path, dict]:
        current_path = self.make_complete_audit()
        current = read_json(current_path)
        legacy_path = current_path.with_name("lem-main-v4.ledger.json")
        legacy = self.downgrade_ledger_fixture_to_schema4(
            json.loads(json.dumps(current))
        )
        write_json(legacy_path, legacy)
        return legacy_path, current_path.with_name(
            "lem-main-migrated.ledger.json"
        ), current

    def test_migrate_ledger_never_overwrites_the_legacy_record(self) -> None:
        legacy_path, migrated_path, _ = self.make_legacy_migration_fixture()
        legacy_bytes = legacy_path.read_bytes()

        with contextlib.redirect_stdout(io.StringIO()):
            status = proofcheck.cmd_migrate_ledger(
                argparse.Namespace(
                    ledger=legacy_path,
                    output=migrated_path,
                    force=False,
                )
            )

        self.assertEqual(0, status)
        self.assertEqual(legacy_bytes, legacy_path.read_bytes())
        with self.assertRaises(ValueError):
            proofcheck.cmd_migrate_ledger(
                argparse.Namespace(
                    ledger=legacy_path,
                    output=legacy_path,
                    force=False,
                )
            )
        with self.assertRaises(FileExistsError):
            proofcheck.cmd_migrate_ledger(
                argparse.Namespace(
                    ledger=legacy_path,
                    output=migrated_path,
                    force=False,
                )
            )

    def test_migrate_ledger_creates_a_schema5_recheck_skeleton(self) -> None:
        legacy_path, migrated_path, _ = self.make_legacy_migration_fixture()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = proofcheck.cmd_migrate_ledger(
                argparse.Namespace(
                    ledger=legacy_path,
                    output=migrated_path,
                    force=False,
                )
            )

        payload = json.loads(output.getvalue())
        migrated = read_json(migrated_path)
        legacy = read_json(legacy_path)
        self.assertEqual(0, status)
        self.assertEqual("requires_manual_recheck", payload["artifact_state"])
        self.assertTrue(payload["next_action"].strip())
        self.assertEqual(5, migrated["schema_version"])
        self.assertEqual(
            proofcheck.EVIDENCE_CONTRACT_VERSION,
            migrated["evidence_contract_version"],
        )
        self.assertEqual([], migrated["steps"])
        self.assertEqual("not_checked", migrated["review"]["unit_status"])
        self.assertFalse(migrated["independent_check"]["required"])
        self.assertEqual(
            len(migrated["source_lines"]), len(migrated["source_units"])
        )
        self.assertEqual(
            proofcheck.sha256_file(legacy_path),
            migrated["migration"]["legacy_ledger_sha256"],
        )
        self.assertEqual(
            len(legacy["steps"]), migrated["migration"]["legacy_step_count"]
        )
        self.assertEqual(
            "requires_manual_recheck", migrated["migration"]["status"]
        )

    def test_migrated_ledger_needs_an_explicit_full_recheck(self) -> None:
        legacy_path, migrated_path, current = (
            self.make_legacy_migration_fixture()
        )
        with contextlib.redirect_stdout(io.StringIO()):
            proofcheck.cmd_migrate_ledger(
                argparse.Namespace(
                    ledger=legacy_path,
                    output=migrated_path,
                    force=False,
                )
            )
        migrated = read_json(migrated_path)
        for field in (
            "source_units",
            "obligation",
            "review",
            "independent_check",
            "steps",
        ):
            migrated[field] = json.loads(json.dumps(current[field]))
        write_json(migrated_path, migrated)
        self.seal_schema5_challenge(
            migrated_path, read_json(migrated_path)
        )

        errors, _ = proofcheck.check_ledger_data(migrated_path, True)

        self.assertTrue(
            any(
                "requires a full manual atomic recheck" in error
                for error in errors
            ),
            errors,
        )

        migrated = read_json(migrated_path)
        migrated["migration"].update(
            {
                "status": "rechecked",
                "recheck_evidence": (
                    "Every atomic step was rechecked against the locked source."
                ),
                "rechecked_utc": "2026-08-09T00:00:00+00:00",
            }
        )
        write_json(migrated_path, migrated)
        self.seal_schema5_challenge(
            migrated_path, read_json(migrated_path)
        )

        errors, _ = proofcheck.check_ledger_data(migrated_path, True)

        self.assertEqual([], errors)

    def test_skeleton_coverage_diagnostics_are_grouped_and_bounded(self) -> None:
        source = self.base / "long-proof.tex"
        source.write_text(
            "\n".join(f"Proof source line {line}." for line in range(1, 161))
            + "\n",
            encoding="utf-8",
            newline="\n",
        )
        ledger_path = self.base / "long-proof.ledger.json"
        with contextlib.redirect_stdout(io.StringIO()):
            proofcheck.cmd_extract(
                argparse.Namespace(
                    file=source,
                    start=1,
                    end=160,
                    statement_file=None,
                    statement_start=None,
                    statement_end=None,
                    separate_statement_reason="Statement location is not yet recorded.",
                    unit_id="lem:long-skeleton",
                    output=ledger_path,
                    force=False,
                )
            )

        ledger = read_json(ledger_path)
        ledger["source_units"] = []
        write_json(ledger_path, ledger)
        errors, _ = proofcheck.check_ledger_data(ledger_path, False)
        uncovered = [
            error for error in errors if "Uncovered source line" in error
        ]

        self.assertEqual(1, len(uncovered), errors)
        self.assertIn("1-160", uncovered[0])
        self.assertLess(len(errors), 50, errors)

    def test_locked_source_mismatch_reports_expected_actual_and_first_difference(
        self,
    ) -> None:
        source = self.base / "exact-source.tex"
        source.write_text(
            "Alpha.\nBeta.\nGamma.\n",
            encoding="utf-8",
            newline="\n",
        )
        ledger_path = self.base / "exact-source.ledger.json"
        with contextlib.redirect_stdout(io.StringIO()):
            proofcheck.cmd_extract(
                argparse.Namespace(
                    file=source,
                    start=1,
                    end=3,
                    statement_file=None,
                    statement_start=None,
                    statement_end=None,
                    separate_statement_reason="Statement location is not yet recorded.",
                    unit_id="lem:exact-source",
                    output=ledger_path,
                    force=False,
                )
            )
        source.write_text(
            "Alpha.\nChanged beta.\nGamma.\n",
            encoding="utf-8",
            newline="\n",
        )

        errors, _ = proofcheck.check_ledger_data(ledger_path, False)
        mismatches = [
            error for error in errors if "Locked source mismatch" in error
        ]

        self.assertEqual(1, len(mismatches), errors)
        message = mismatches[0]
        self.assertIn("source_lines", message)
        self.assertIn("expected=", message)
        self.assertIn("actual=", message)
        self.assertIn("first difference", message.replace("_", " ").lower())
        self.assertIn("Beta.", message)
        self.assertIn("Changed beta.", message)

    def test_late_exact_mismatch_reports_bounded_context_around_difference(
        self,
    ) -> None:
        prefix = "shared-prefix-" + "a" * 220
        expected_tail = "EXPECTED_DIFFERING_SUBSTRING"
        actual_tail = "ACTUAL_DIFFERING_SUBSTRING"
        suffix = "-shared-suffix-" + "z" * 220
        source = self.base / "late-exact-source.tex"
        source.write_text(
            prefix + expected_tail + suffix + "\n",
            encoding="utf-8",
            newline="\n",
        )
        ledger_path = self.base / "late-exact-source.ledger.json"
        with contextlib.redirect_stdout(io.StringIO()):
            proofcheck.cmd_extract(
                argparse.Namespace(
                    file=source,
                    start=1,
                    end=1,
                    statement_file=None,
                    statement_start=None,
                    statement_end=None,
                    separate_statement_reason="Statement location is not yet recorded.",
                    unit_id="lem:late-exact-source",
                    output=ledger_path,
                    force=False,
                )
            )
        source.write_text(
            prefix + actual_tail + suffix + "\n",
            encoding="utf-8",
            newline="\n",
        )

        errors, _ = proofcheck.check_ledger_data(ledger_path, False)
        message = next(
            error for error in errors if "Locked source mismatch" in error
        )

        self.assertIn(expected_tail, message)
        self.assertIn(actual_tail, message)
        self.assertIn("first difference at character", message)
        self.assertLess(len(message), 500)
        self.assertNotIn("a" * 180, message)

    def test_unbraced_input_is_included_in_source_closure(self) -> None:
        root = self.base / "unbraced.tex"
        child = self.base / "child.tex"
        child.write_text("Child content.\n", encoding="utf-8", newline="\n")
        root.write_text("\\input child\n", encoding="utf-8", newline="\n")
        files, warnings = proofcheck.collect_tex_files(root)
        self.assertIn(child.resolve(), files)
        self.assertEqual([], warnings)

    def test_dynamic_subfile_emits_parser_warning(self) -> None:
        root = self.base / "dynamic.tex"
        root.write_text("\\subfile{\\whichfile}\n", encoding="utf-8", newline="\n")
        _, warnings = proofcheck.collect_tex_files(root)
        self.assertTrue(any("Dynamic include" in item for item in warnings), warnings)

    def test_verified_external_result_needs_explicit_prerequisite_map(self) -> None:
        ledger_path = self.make_complete_audit()
        self.install_external_dependency(ledger_path)
        registry_path = (
            self.audit
            / "audit"
            / "03_dependencies"
            / "DEPENDENCY_REGISTRY.json"
        )
        registry = read_json(registry_path)
        registry["external_results"][0]["uses"][0]["prerequisite_map"] = []
        write_json(registry_path, registry)

        errors, _ = proofcheck.check_audit_finalization(self.audit)

        self.assertTrue(
            any("prerequisite_map must not be empty" in error for error in errors),
            errors,
        )

    def test_final_report_assessment_must_match_manifest(self) -> None:
        self.make_complete_audit()
        report_path = self.audit / "audit" / "06_reports" / "FINAL_REPORT.md"
        report = report_path.read_text(encoding="utf-8")
        report = report.replace(
            "Overall assessment code: no_defect_found",
            "Overall assessment code: defects_found",
        )
        report_path.write_text(report, encoding="utf-8", newline="\n")
        errors, _ = proofcheck.check_audit_finalization(self.audit)
        self.assertTrue(
            any("Final report assessment disagrees" in error for error in errors),
            errors,
        )

    def test_same_file_separate_statement_requires_a_reason(self) -> None:
        ledger_path = self.make_complete_audit()
        original = read_json(ledger_path)
        with contextlib.redirect_stdout(io.StringIO()):
            proofcheck.cmd_extract(
                argparse.Namespace(
                    file=self.paper,
                    start=5,
                    end=7,
                    statement_file=self.paper,
                    statement_start=2,
                    statement_end=4,
                    unit_id="lem:main",
                    output=ledger_path,
                    force=True,
                )
            )
        proof_only = read_json(ledger_path)
        proof_only["obligation"] = original["obligation"]
        proof_only["review"] = original["review"]
        proof_only["independent_check"] = original["independent_check"]
        proof_only["steps"] = original["steps"][1:]
        for index, step in enumerate(proof_only["steps"], 1):
            step["source_unit_id"] = f"U{index:03d}"
        write_json(ledger_path, proof_only)
        errors, _ = proofcheck.check_audit_finalization(self.audit)
        self.assertTrue(
            any("separate_statement_reason" in error for error in errors),
            errors,
        )
        proof_only["source"]["separate_statement_reason"] = (
            "The theorem statement and its distant proof are intentionally audited as "
            "separate locked spans."
        )
        write_json(ledger_path, proof_only)
        self.seal_schema5_challenge(ledger_path, read_json(ledger_path))
        self.refresh_report_views()
        errors, _ = proofcheck.check_audit_finalization(self.audit)
        self.assertEqual([], errors)

    def test_citation_needs_a_reviewed_disposition(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        ledger["review"]["citation_dispositions"] = []
        write_json(ledger_path, ledger)
        errors, _ = proofcheck.check_audit_finalization(self.audit)
        self.assertTrue(
            any("citations lack reviewed dispositions" in error for error in errors),
            errors,
        )

    def test_proof_required_result_cannot_be_verified_without_a_proof(self) -> None:
        proofless_paper = self.base / "proofless.tex"
        proofless_paper.write_text(
            "\\input{definitions}\n"
            "\\begin{lemma}\\label{lem:main}\n"
            "$x=x$ for every real $x$.\\label{eq:reflexive}\n"
            "\\end{lemma}\n"
            "% no proof is supplied\n"
            "Reflexivity establishes the claim.\n"
            "\n",
            encoding="utf-8",
            newline="\n",
        )
        proofless_audit = self.base / "proofless-audit"
        original_paper, original_audit = self.paper, self.audit
        try:
            self.paper, self.audit = proofless_paper, proofless_audit
            with contextlib.redirect_stdout(io.StringIO()):
                proofcheck.cmd_scaffold(
                    argparse.Namespace(paper=self.paper, output=self.audit)
                )
            self.make_complete_audit()
            errors, _ = proofcheck.check_audit_finalization(self.audit)
        finally:
            self.paper, self.audit = original_paper, original_audit
        self.assertTrue(
            any("proof-required result has no inventoried proof range" in error for error in errors),
            errors,
        )

    def test_custom_theorem_environment_requires_a_proof(self) -> None:
        custom = self.base / "custom.tex"
        custom.write_text(
            "\\newtheorem{thm}{Theorem}\n"
            "\\begin{thm}\\label{thm:custom}\nA claim.\n\\end{thm}\n",
            encoding="utf-8",
            newline="\n",
        )
        inventory = proofcheck.scan_formal_units(custom)
        unit = next(item for item in inventory["units"] if item["id"] == "thm:custom")
        self.assertTrue(unit["proof_required"])
        self.assertTrue(
            any("no associated proof" in warning for warning in inventory["warnings"]),
            inventory["warnings"],
        )

    def test_common_and_unsupported_citation_commands_are_not_silent(self) -> None:
        source = self.base / "citations.tex"
        source.write_text(
            "\\newtheorem{lemma}{Lemma}\n"
            "\\begin{lemma}\\label{lem:cite}\nA claim.\n\\end{lemma}\n"
            "\\begin{proof}\n"
            "Use \\footcite{known} and \\mycite{unknown}.\n"
            "\\end{proof}\n",
            encoding="utf-8",
            newline="\n",
        )
        inventory = proofcheck.scan_formal_units(source)
        unit = next(item for item in inventory["units"] if item["id"] == "lem:cite")
        self.assertIn("known", unit["citations"])
        self.assertTrue(
            any("Unsupported citation command" in warning for warning in inventory["warnings"]),
            inventory["warnings"],
        )

    def test_s0_issue_cannot_be_declared_non_load_bearing(self) -> None:
        issues = [
            {
                "id": "I-001",
                "severity": "S0",
                "confidence": "high",
                "status": "open",
                "finding_status": "defect",
                "scope": "unit",
                "load_bearing": False,
                "location": "paper.tex:6",
                "affected_result": "lem:main",
                "affected_results": ["lem:main"],
                "summary": "A fatal proof defect.",
                "evidence": ["paper.tex:6"],
                "downstream_consequences": ["The central claim is not established."],
                "possible_repair": "none proposed",
            }
        ]
        errors, _ = proofcheck.validate_issues(issues, {"I-001"}, True)
        self.assertTrue(
            any("S0 and S1 issues must be load-bearing" in error for error in errors),
            errors,
        )

    def test_severe_issue_requires_repair_search_record(self) -> None:
        issue = self.make_schema5_issue(severity="S1", status="open")
        del issue["repair_search"]
        errors, _ = proofcheck.validate_issues([issue], {"I-001"}, True)
        self.assertTrue(
            any(
                "severity S1 requires a repair_search record" in error
                for error in errors
            ),
            errors,
        )
        moderate = self.make_schema5_issue(severity="S2", status="open")
        moderate["finding_status"] = "inconclusive"
        moderate.pop("repair_search", None)
        errors, _ = proofcheck.validate_issues([moderate], {"I-001"}, True)
        self.assertFalse(
            any("repair_search" in error for error in errors),
            errors,
        )

    def test_repair_search_conclusion_must_match_severity_and_outcomes(self) -> None:
        base = make_repair_search("S1")
        cases = {
            "s0_with_candidate": (
                "S0",
                make_repair_search("S1"),
                "severity S0 requires conclusion no_local_repair_found",
            ),
            "s1_with_no_local_repair": (
                "S1",
                make_repair_search("S0"),
                "severity S1 requires conclusion candidate_repair_exists",
            ),
            "candidate_without_survivor": (
                "S1",
                {
                    "strategies": [
                        {
                            **base["strategies"][0],
                            "outcome": "failed",
                        }
                    ],
                    "conclusion": "candidate_repair_exists",
                },
                "requires at least one strategy with outcome "
                "survives_local_inspection",
            ),
            "no_local_repair_with_survivor": (
                "S0",
                {
                    "strategies": [
                        {
                            **base["strategies"][1],
                            "outcome": "survives_local_inspection",
                        }
                    ],
                    "conclusion": "no_local_repair_found",
                },
                "requires every attempted strategy to record outcome failed",
            ),
            "placeholder_attempt": (
                "S1",
                {
                    "strategies": [
                        {
                            "name": "union_bound",
                            "attempt": "TBD",
                            "outcome": "survives_local_inspection",
                            "evidence": "The bound closes the failed move locally.",
                        }
                    ],
                    "conclusion": "candidate_repair_exists",
                },
                "attempt must be nonempty and substantive",
            ),
            "unknown_field": (
                "S1",
                {**make_repair_search("S1"), "difficulty": "easy"},
                "has unknown fields: difficulty",
            ),
        }
        for case, (severity, record, expected) in cases.items():
            with self.subTest(case=case):
                errors = proofcheck.validate_repair_search(
                    record, severity, "I-001.repair_search"
                )
                self.assertTrue(
                    any(expected in error for error in errors),
                    (case, errors),
                )
        self.assertEqual(
            [],
            proofcheck.validate_repair_search(
                make_repair_search("S0"), "S0", "I-001.repair_search"
            ),
        )
        self.assertEqual(
            [],
            proofcheck.validate_repair_search(
                make_repair_search("S1"), "S1", "I-001.repair_search"
            ),
        )

    def test_required_challenge_units_equal_in_scope(self) -> None:
        manifest = {
            "source_snapshot": {"sha256": "a" * 64},
            "audit_scope": {
                "critical_units": ["thm:main"],
                "in_scope_units": [
                    "thm:main",
                    "lem:a",
                    "lem:b",
                    "lem:c",
                ],
            },
        }
        expected = ["lem:a", "lem:b", "lem:c", "thm:main"]
        required, triggers = proofcheck.required_challenge_requirements(
            manifest, []
        )
        self.assertEqual(expected, required)
        self.assertEqual({}, triggers)

        changed = json.loads(json.dumps(manifest))
        changed["source_snapshot"]["sha256"] = "b" * 64
        changed["audit_scope"]["critical_units"] = []
        self.assertEqual(
            (expected, {}),
            proofcheck.required_challenge_requirements(changed, []),
        )

    def test_severe_issues_change_triggers_not_challenge_coverage(self) -> None:
        manifest = {
            "audit_scope": {
                "critical_units": [],
                "in_scope_units": ["thm:main", "lem:a"],
            }
        }
        issues = [
            {
                "id": "I-001",
                "status": "open",
                "load_bearing": True,
                "severity": "S1",
                "affected_results": ["thm:main"],
            }
        ]
        required, triggers = proofcheck.required_challenge_requirements(
            manifest, issues
        )
        self.assertEqual(["lem:a", "thm:main"], required)
        self.assertEqual({"thm:main": {"I-001"}}, triggers)

    def test_manifest_rejects_obsolete_sampling_field_but_not_priority_choice(
        self,
    ) -> None:
        self.make_complete_audit()
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        manifest["audit_scope"]["verified_challenge_sample_rate"] = 0.2
        write_json(manifest_path, manifest)
        errors, _ = proofcheck.check_audit_finalization(self.audit)
        self.assertTrue(
            any("verified_challenge_sample_rate is obsolete" in error for error in errors),
            errors,
        )

        del manifest["audit_scope"]["verified_challenge_sample_rate"]
        manifest["audit_scope"]["critical_units"] = []
        write_json(manifest_path, manifest)
        errors, _ = proofcheck.check_audit_finalization(self.audit)
        self.assertFalse(
            any("target unit must also be critical" in error.lower() for error in errors),
            errors,
        )

    def test_noncritical_in_scope_unit_still_requires_independent_check(
        self,
    ) -> None:
        ledger_path = self.make_complete_audit()
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        manifest["audit_scope"]["critical_units"] = []
        write_json(manifest_path, manifest)
        ledger = read_json(ledger_path)
        ledger["independent_check"] = {
            "required": False,
            "status": "not_required",
            "independence_level": "none",
            "challenger_verdict": "not_checked",
            "reconciled_verdict": "not_checked",
            "artifact": "",
            "covered_issue_ids": [],
            "source_snapshot_sha256": "",
            "challenged_ledger_sha256": "",
            "challenge_context_sha256": "",
            "challenge_artifact_sha256": "",
            "issue_assessments": [],
            "generated_utc": "",
            "disagreements": [],
            "resolution": "",
        }
        write_json(ledger_path, ledger)

        errors, _ = proofcheck.check_audit_finalization(self.audit)
        self.assertTrue(
            any(
                "In-scope unit lem:main requires an independent" in error
                for error in errors
            ),
            errors,
        )
        packet = proofcheck.build_context_packet(
            self.audit, "lem:main", "challenge"
        )
        self.assertEqual([], packet["issue_triggers"])
    def test_failed_checker_calibration_blocks_finalization(self) -> None:
        self.make_complete_audit()
        calibration_path = (
            self.audit / "audit" / "07_runtime" / "CALIBRATION.json"
        )
        calibration = read_json(calibration_path)
        passing_session = json.loads(json.dumps(calibration["sessions"][0]))
        failing_response = {
            "canary_id": "finite-max",
            "argument_status": "invalid",
            "statement_status": "not_established",
            "defect_lines": [15],
            "justification": (
                "This deliberately incorrect calibration response claims a "
                "defect in the valid finite-union-bound proof."
            ),
        }
        passed, reasons, got = proofcheck.grade_canary_response(
            failing_response, proofcheck.load_canary_key("finite-max")
        )
        calibration["sessions"][0]["results"][1] = {
            "canary_id": "finite-max",
            "passed": passed,
            "reasons": reasons,
            "got": got,
            "response_sha256": proofcheck.canonical_sha256(got),
        }
        calibration["sessions"][0]["passed"] = False
        write_json(calibration_path, calibration)
        errors, _ = proofcheck.check_audit_finalization(self.audit)
        self.assertTrue(
            any("checker calibration failed" in error for error in errors),
            errors,
        )
        passing_session["session_id"] = "cal-002"
        passing_session["graded_utc"] = "2026-08-09T01:00:00+00:00"
        passing_session["checker_binding"]["checker_context_id"] = (
            "fresh-context-cal-002"
        )
        calibration["sessions"].append(passing_session)
        write_json(calibration_path, calibration)
        errors, _ = proofcheck.check_audit_finalization(self.audit)
        self.assertFalse(
            any("checker calibration" in error for error in errors),
            errors,
        )

    def test_repair_cost_fields_are_required_and_coherent(self) -> None:
        base = self.make_schema5_issue(severity="S1", status="open")

        def errors_for(mutate) -> list[str]:
            issue = json.loads(json.dumps(base))
            mutate(issue["suggested_changes"][0], issue)
            errors, _ = proofcheck.validate_issues([issue], {"I-001"}, True)
            return errors

        def unchanged(change, issue):
            return None

        self.assertFalse(
            any(
                "repair_scope" in e or "assumption_cost" in e or "claim_cost" in e
                for e in errors_for(unchanged)
            ),
            errors_for(unchanged),
        )

        def drop_scope(change, issue):
            del change["repair_scope"]

        self.assertTrue(
            any("repair_scope must be" in e for e in errors_for(drop_scope))
        )

        def bad_cost(change, issue):
            change["assumption_cost"] = "easy"

        self.assertTrue(
            any("assumption_cost must be" in e for e in errors_for(bad_cost))
        )

        def free_strengthening(change, issue):
            change["action"] = "strengthen_assumption"
            change["assumption_cost"] = "none"

        self.assertTrue(
            any(
                "cannot be none for strengthen_assumption" in e
                for e in errors_for(free_strengthening)
            )
        )

        def weaken_without_cost(change, issue):
            change["action"] = "weaken_claim"

        self.assertTrue(
            any(
                "claim_cost is required for weaken_claim" in e
                for e in errors_for(weaken_without_cost)
            )
        )

        def costless_weakening(change, issue):
            change["action"] = "weaken_claim"
            change["claim_cost"] = "none"

        self.assertTrue(
            any(
                "cannot be none for weaken_claim" in e
                for e in errors_for(costless_weakening)
            )
        )

        def stray_claim_cost(change, issue):
            change["claim_cost"] = "restricts_scope"

        self.assertTrue(
            any(
                "allowed only for a weaken_claim action" in e
                for e in errors_for(stray_claim_cost)
            )
        )

        def costly_presentation(change, issue):
            change["action"] = "presentation_edit"
            change["repair_scope"] = "global"
            change["assumption_cost"] = "structural"

        presentation_errors = errors_for(costly_presentation)
        self.assertTrue(
            any("cannot carry an assumption cost" in e for e in presentation_errors)
        )
        self.assertTrue(
            any(
                "must have repair_scope local_step" in e
                for e in presentation_errors
            )
        )

    def test_no_local_repair_forbids_a_free_local_suggested_change(self) -> None:
        issue = self.make_schema5_issue(severity="S0", status="open")
        self.assertEqual(
            "no_local_repair_found", issue["repair_search"]["conclusion"]
        )
        clean_errors, _ = proofcheck.validate_issues([issue], {"I-001"}, True)
        self.assertFalse(
            any("repair_search concluded does not exist" in e for e in clean_errors),
            clean_errors,
        )
        issue["suggested_changes"][0]["repair_scope"] = "local_step"
        issue["suggested_changes"][0]["assumption_cost"] = "none"
        errors, _ = proofcheck.validate_issues([issue], {"I-001"}, True)
        self.assertTrue(
            any(
                "asserts exactly the local repair" in e
                and "repair_search concluded does not exist" in e
                for e in errors
            ),
            errors,
        )

    def test_included_source_drift_fails(self) -> None:
        self.make_complete_audit()
        self.definitions.write_text(
            "\\newtheorem{lemma}{Lemma}\n% changed context\n",
            encoding="utf-8",
            newline="\n",
        )
        errors, _ = proofcheck.check_audit_finalization(self.audit)
        self.assertTrue(
            any("Source drift in included file" in error for error in errors),
            errors,
        )

    def test_resolved_issue_without_recheck_fails(self) -> None:
        ledger_path = self.make_complete_audit()
        manifest = read_json(self.audit / "AUDIT_MANIFEST.json")
        issue = {
            "id": "I-001",
            "severity": "S3",
            "confidence": "high",
            "status": "resolved",
            "finding_status": "resolved",
            "scope": "unit",
            "load_bearing": False,
            "location": "paper.tex:6",
            "affected_result": "lem:main",
            "affected_results": ["lem:main"],
            "summary": "A resolved exposition issue.",
            "evidence": ["paper.tex:6"],
            "downstream_consequences": ["none identified"],
            "possible_repair": "Text was clarified.",
            "resolution": "Text was clarified.",
            "source_snapshot_sha256": manifest["source_snapshot"]["sha256"],
            "rechecked_units": ["lem:main"],
        }
        self.install_canonical_issue(
            issue,
            ledger_path=ledger_path,
            reconcile_report_views=False,
        )
        errors, _ = proofcheck.check_audit_finalization(self.audit)
        self.assertTrue(
            any("source_revision" in error for error in errors), errors
        )
        self.assertTrue(
            any("recheck_evidence" in error for error in errors), errors
        )

    def test_open_load_bearing_issue_blocks_no_defect_claim(self) -> None:
        ledger_path = self.make_complete_audit()
        issue = {
            "id": "I-001",
            "severity": "S2",
            "confidence": "high",
            "status": "open",
            "finding_status": "defect",
            "scope": "unit",
            "load_bearing": True,
            "location": "paper.tex:6",
            "affected_result": "lem:main",
            "affected_results": ["lem:main"],
            "summary": "A load-bearing premise is missing.",
            "evidence": ["paper.tex:6"],
            "downstream_consequences": ["lem:main is not established"],
            "possible_repair": "none proposed",
        }
        self.install_canonical_issue(
            issue,
            ledger_path=ledger_path,
            reconcile_report_views=False,
        )
        errors, result = proofcheck.check_audit_finalization(self.audit)
        self.assertEqual("defects_found", result["derived_assessment"])
        self.assertTrue(
            any(
                "load-bearing defect finding" in error
                or "expected defects_found" in error
                for error in errors
            ),
            errors,
        )

    def test_density_ratio_interface_requires_complete_trace(self) -> None:
        record = self.make_interface_record()
        registry = {
            "schema_version": proofcheck.METHOD_INTERFACE_SCHEMA_VERSION,
            "scope": {
                "status": "reviewed",
                "trigger": "required",
                "reason": "Density-ratio target is load-bearing.",
            },
            "interfaces": [record],
        }
        mutations = {
            "population target": lambda item: item.pop("population_target"),
            "identification identity": lambda item: item.pop("identification_identity"),
            "numerator law": lambda item: item["fitting_sample_laws"].pop(0),
            "marginal relationships": lambda item: item.pop("marginal_relationships"),
            "evaluation site": lambda item: item.pop("evaluation_sites"),
            "downstream use": lambda item: item.pop("downstream_uses"),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                changed = json.loads(json.dumps(registry))
                mutate(changed["interfaces"][0])
                errors: list[str] = []
                proofcheck.validate_method_interface_registry(changed, self.audit, errors)
                self.assertTrue(errors, label)

    def test_ambiguous_interface_cannot_be_declared_a_target_mismatch(self) -> None:
        record = self.make_interface_record(
            specification="ambiguous", target_verdict="mismatch"
        )
        record["issue_ids"] = ["I-001"]
        registry = {
            "schema_version": proofcheck.METHOD_INTERFACE_SCHEMA_VERSION,
            "scope": {
                "status": "reviewed",
                "trigger": "required",
                "reason": "The fitting laws permit distinct interpretations.",
            },
            "interfaces": [record],
        }
        errors: list[str] = []
        proofcheck.validate_method_interface_registry(registry, self.audit, errors)
        self.assertTrue(
            any("cannot establish target_relation" in error for error in errors), errors
        )

    def test_unavailable_implementation_cannot_support_mismatch_finding(self) -> None:
        record = self.make_interface_record(
            implementation_inspection="unavailable",
            code_to_documented="not_checked",
            code_to_target="not_checked",
        )
        record["issue_ids"] = ["I-001"]
        issue = {
            "id": "I-001",
            "severity": "S2",
            "confidence": "medium",
            "status": "open",
            "finding_status": "defect",
            "scope": "global",
            "load_bearing": False,
            "interface_id": "MI-001",
            "finding_class": "implementation_mismatch",
            "affected_layer": "implementation",
            "evidence_class": "not_established",
            "estimator_target_status": "match",
            "implementation_inspection_status": "unavailable",
            "code_to_documented_estimator": "not_checked",
            "code_to_required_target": "not_checked",
            "execution_provenance_status": "not_checked",
            "location": "paper.tex:2-4",
            "affected_result": "lem:main",
            "affected_results": ["lem:main"],
            "summary": "The implementation is unavailable.",
            "evidence": ["No code snapshot was supplied."],
            "resolution_evidence_needed": ["Supply and inspect the implementation."],
            "downstream_consequences": ["Implementation correspondence is unknown."],
            "possible_repair": "Inspect an exact implementation revision.",
        }
        errors, _ = proofcheck.validate_issues(
            [issue],
            set(),
            True,
            evidence_base=self.audit,
            interfaces={"MI-001": record},
        )
        self.assertTrue(
            any("requires code-to-documentation inconsistency" in error for error in errors),
            errors,
        )

    def test_ambiguity_with_consistent_code_preserves_calibrated_finding(self) -> None:
        self.make_complete_audit()
        record = self.make_interface_record(
            specification="ambiguous",
            target_verdict="not_assessable",
            code_to_documented="not_assessable",
        )
        issue = {
            "id": "I-001",
            "severity": "S3",
            "confidence": "high",
            "status": "open",
            "finding_status": "inconclusive",
            "scope": "global",
            "load_bearing": False,
            "interface_id": "MI-001",
            "finding_class": "exposition_ambiguity",
            "affected_layer": "specification",
            "evidence_class": "observed",
            "estimator_target_status": "not_assessable",
            "implementation_inspection_status": "inspected",
            "code_to_documented_estimator": "not_assessable",
            "code_to_required_target": "consistent",
            "execution_provenance_status": "not_checked",
            "location": "paper.tex:2-4",
            "affected_result": "lem:main",
            "affected_results": ["lem:main"],
            "summary": "Generic notation leaves two population readings open.",
            "evidence": ["paper.tex:2-4", "estimator.py:1-2"],
            "resolution_evidence_needed": [
                "State the numerator and denominator laws in the manuscript."
            ],
            "downstream_consequences": ["The prose is not self-contained."],
            "possible_repair": "Add the two fitting laws explicitly.",
        }
        self.install_interface_issue(record, issue)
        errors, result = proofcheck.check_audit_finalization(self.audit)
        self.assertEqual([], errors)
        self.assertEqual("no_defect_found", result["derived_assessment"])
        report_path = self.audit / "audit" / "06_reports" / "FINAL_REPORT.md"
        report = report_path.read_text(encoding="utf-8")
        self.assertIn(
            "- Overall judgment: No load-bearing defect found under the "
            "stated non-formal protocol.",
            report,
        )
        self.assertNotIn(
            "- Overall judgment: No defect found under the stated non-formal "
            "protocol.",
            report,
        )
        findings = proofcheck.report_section(
            report, "## Findings and repairs"
        ) or ""
        self.assertIn("implementation inspection is inspected", findings)
        report_path.write_text(
            report.replace(
                "implementation inspection is inspected",
                "implementation inspection is executed",
                1,
            ),
            encoding="utf-8",
            newline="\n",
        )

        errors, _ = proofcheck.check_audit_finalization(self.audit)

        self.assertTrue(
            any(
                "Findings and repairs disagrees" in error
                for error in errors
            ),
            errors,
        )

    def test_interface_issue_origin_requires_member_evidence_span(self) -> None:
        self.make_complete_audit()
        record = self.make_interface_record(
            specification="ambiguous",
            target_verdict="not_assessable",
            code_to_documented="not_assessable",
        )
        issue = self.make_global_issue(
            finding_status="inconclusive",
            load_bearing=False,
            severity="S3",
            summary="The method interface has two unresolved population readings.",
        )
        issue.update(
            {
                "interface_id": "MI-001",
                "finding_class": "exposition_ambiguity",
                "affected_layer": "specification",
                "evidence_class": "observed",
                "estimator_target_status": "not_assessable",
                "implementation_inspection_status": "inspected",
                "code_to_documented_estimator": "not_assessable",
                "code_to_required_target": "consistent",
                "execution_provenance_status": "not_checked",
                "resolution_evidence_needed": [
                    "State the numerator and denominator laws explicitly."
                ],
                "origin_ref": {
                    "kind": "interface_record",
                    "interface_id": "MI-001",
                    "evidence_spans": [
                        dict(record["fitting_sample_laws"][0][
                            "evidence_spans"
                        ][0])
                    ],
                },
                "invalidation_kind": "scope_inconclusive",
            }
        )
        self.install_interface_issue(record, issue)

        errors, _ = proofcheck.check_audit_finalization(self.audit)
        self.assertEqual([], errors)
        detail_section = proofcheck.report_section(
            (
                self.audit
                / "audit"
                / "06_reports"
                / "FINAL_REPORT.md"
            ).read_text(encoding="utf-8"),
            "## Findings and repairs",
        )
        failure_row = proofcheck.markdown_tables(
            detail_section or ""
        )[0][2]
        self.assertNotEqual("none", failure_row[1])
        self.assertNotEqual("none", failure_row[2])

        issue_without_evidence = json.loads(json.dumps(issue))
        issue_without_evidence["origin_ref"].pop("evidence_spans")
        self.install_canonical_issue(
            issue_without_evidence,
            migrate=False,
            reconcile_report_views=False,
        )
        errors, _ = proofcheck.check_audit_finalization(self.audit)
        self.assertTrue(
            any(
                "I-001.origin_ref.evidence_spans" in error
                and "nonempty" in error.lower()
                for error in errors
            ),
            errors,
        )

    def test_issue_origin_contract_and_invalidation_must_be_coherent(
        self,
    ) -> None:
        ledger_path = self.make_complete_audit()
        self.install_internal_dependency(ledger_path)
        record = self.make_interface_record(
            specification="ambiguous",
            target_verdict="not_assessable",
            code_to_documented="not_assessable",
        )
        record["issue_ids"] = ["I-001"]
        self.install_interface_record(record)
        issue = self.make_global_issue(
            finding_status="inconclusive",
            load_bearing=False,
            severity="S3",
            summary="The method interface remains ambiguous.",
        )
        issue.update(
            {
                "interface_id": "MI-001",
                "finding_class": "exposition_ambiguity",
                "affected_layer": "specification",
                "evidence_class": "observed",
                "estimator_target_status": "not_assessable",
                "implementation_inspection_status": "inspected",
                "code_to_documented_estimator": "not_assessable",
                "code_to_required_target": "consistent",
                "execution_provenance_status": "not_checked",
                "resolution_evidence_needed": [
                    "State the two fitting laws explicitly."
                ],
                "origin_ref": {
                    "kind": "interface_record",
                    "interface_id": "MI-001",
                    "evidence_spans": [
                        dict(record["fitting_sample_laws"][0][
                            "evidence_spans"
                        ][0])
                    ],
                },
                "invalidation_kind": "scope_inconclusive",
            }
        )
        _, summaries, _ = proofcheck.audit_ledgers(self.audit, True)
        manifest = read_json(self.audit / "AUDIT_MANIFEST.json")

        def issue_errors(candidate: dict) -> list[str]:
            errors, _ = proofcheck.validate_issues(
                [candidate],
                set(),
                True,
                evidence_base=self.audit,
                interfaces={"MI-001": record},
                source_snapshot_id=manifest["source_snapshot"]["sha256"],
                in_scope=["lem:main", "lem:prior"],
                ledger_summaries=summaries,
            )
            return errors

        self.assertEqual([], issue_errors(issue))

        unrelated_contract = json.loads(json.dumps(issue))
        unrelated_contract["contract_refs"] = [
            {
                "kind": "conclusion",
                "unit_id": "lem:prior",
                "conclusion_id": "C001",
            }
        ]
        errors = issue_errors(unrelated_contract)
        self.assertTrue(
            any(
                "contract_refs" in error
                and "affected_result" in error
                for error in errors
            ),
            errors,
        )

        wrong_finding = json.loads(json.dumps(issue))
        wrong_finding["finding_status"] = "defect"
        errors = issue_errors(wrong_finding)
        self.assertTrue(
            any(
                "scope_inconclusive" in error
                and "finding_status" in error
                for error in errors
            ),
            errors,
        )

        wrong_dependency_origin = json.loads(json.dumps(issue))
        wrong_dependency_origin["finding_status"] = "defect"
        wrong_dependency_origin["invalidation_kind"] = "dependency_mismatch"
        errors = issue_errors(wrong_dependency_origin)
        self.assertTrue(
            any(
                "dependency_mismatch" in error
                and "origin_ref" in error
                for error in errors
            ),
            errors,
        )

        wrong_refutation_origin = json.loads(json.dumps(issue))
        wrong_refutation_origin["finding_status"] = "defect"
        wrong_refutation_origin["invalidation_kind"] = "statement_refuted"
        errors = issue_errors(wrong_refutation_origin)
        self.assertTrue(
            any(
                "statement_refuted" in error
                and "origin_ref" in error
                for error in errors
            ),
            errors,
        )

    def test_ledger_move_issue_rejects_unlinked_clean_conclusion_contract_ref(
        self,
    ) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        second_conclusion = json.loads(
            json.dumps(ledger["obligation"]["conclusions"][0])
        )
        second_conclusion["id"] = "C002"
        second_conclusion["claim"] = "Every real x is identical to itself"
        ledger["obligation"]["conclusions"].append(second_conclusion)

        failed_step = ledger["steps"][2]
        clean_step = json.loads(json.dumps(failed_step))
        clean_step["id"] = "S004"
        clean_step["goal"] = "Establish the independent verbal conclusion."
        clean_step["restatement"] = second_conclusion["claim"]
        clean_move = clean_step["inference"]["moves"][0]
        clean_move["claim"] = second_conclusion["claim"]
        clean_move["rule"] = "Reflexivity in verbal form"
        clean_move["justification"] = (
            "Reflexivity establishes identity with itself for the arbitrary "
            "real x."
        )
        clean_step["issue_ids"] = []
        ledger["steps"][3]["id"] = "S005"
        ledger["steps"].insert(3, clean_step)

        second_result = json.loads(
            json.dumps(ledger["review"]["conclusion_results"][0])
        )
        second_result["conclusion_id"] = "C002"
        second_result["support"] = {"step_id": "S004", "move_id": "M001"}
        ledger["review"]["conclusion_results"].append(second_result)
        ledger["review"]["conclusion_step_id"] = ""

        failed_step["status"] = "gap"
        failed_step["issue_ids"] = ["I-001"]
        failed_step["inference"]["moves"][0]["failure"] = {
            "kind": "unsupported_assertion",
            "issue_id": "I-001",
            "evidence": "The recorded premise does not establish this conclusion.",
        }
        first_result = ledger["review"]["conclusion_results"][0]
        first_result["argument_status"] = "gap"
        first_result["statement_status"] = "not_established"
        first_result["issue_ids"] = ["I-001"]
        ledger["review"]["unit_status"] = "gap"
        ledger["review"]["argument_status"] = "gap"
        ledger["review"]["statement_status"] = "not_established"
        ledger["independent_check"]["covered_issue_ids"] = ["I-001"]
        ledger["independent_check"]["challenger_verdict"] = "gap"
        ledger["independent_check"]["reconciled_verdict"] = "gap"
        write_json(ledger_path, ledger)
        self.seal_schema5_challenge(ledger_path, read_json(ledger_path))

        ledger_errors, summary = proofcheck.check_ledger_data(
            ledger_path, True
        )
        self.assertEqual([], ledger_errors)
        issue = self.make_global_issue(
            finding_status="defect",
            load_bearing=True,
            severity="S1",
            summary="The first conclusion has an unsupported proof move.",
        )
        issue.update(
            {
                "origin_ref": {
                    "kind": "ledger_move",
                    "unit_id": "lem:main",
                    "step_id": "S003",
                    "move_id": "M001",
                },
                "contract_refs": [
                    {
                        "kind": "conclusion",
                        "unit_id": "lem:main",
                        "conclusion_id": "C001",
                    },
                    {
                        "kind": "conclusion",
                        "unit_id": "lem:main",
                        "conclusion_id": "C002",
                    },
                ],
                "invalidation_kind": "proof_gap",
            }
        )
        manifest = read_json(self.audit / "AUDIT_MANIFEST.json")

        errors, _ = proofcheck.validate_issues(
            [issue],
            set(),
            True,
            evidence_base=self.audit,
            source_snapshot_id=manifest["source_snapshot"]["sha256"],
            in_scope=["lem:main"],
            ledger_summaries=[summary],
            dependency_edges=[],
        )

        self.assertTrue(
            any(
                "I-001.contract_refs[2]" in error
                and "C002" in error
                and "not linked back" in error
                for error in errors
            ),
            errors,
        )

    def test_dependency_mismatch_origin_must_itself_establish_the_defect(
        self,
    ) -> None:
        ledger_path = self.make_complete_audit()
        self.install_internal_dependency(ledger_path)
        ledger = read_json(ledger_path)
        step = ledger["steps"][2]
        first_dependency = step["dependencies"][0]
        first_dependency["status"] = "unchecked"
        first_dependency["issue_ids"] = ["I-001"]
        second_dependency = json.loads(json.dumps(first_dependency))
        second_dependency.update(
            {
                "use_id": "D002",
                "status": "incorrect",
                "needed_form": "Equality is symmetric on the real numbers",
            }
        )
        step["dependencies"].append(second_dependency)
        second_premise = json.loads(json.dumps(step["premise_uses"][1]))
        second_premise.update(
            {
                "id": "P003",
                "claim": second_dependency["needed_form"],
                "evidence": (
                    "D002 supplies exactly its separately recorded needed form."
                ),
            }
        )
        second_premise["origin"]["reference"] = "D002"
        step["premise_uses"].append(second_premise)
        step["inference"]["moves"][0]["premise_ids"].append("P003")
        step["inference"]["moves"][0]["failure"] = {
            "kind": "invalid_rule",
            "issue_id": "I-001",
            "evidence": (
                "The incorrect D002 compatibility record prevents this "
                "inference move."
            ),
        }
        step["status"] = "incorrect"
        step["issue_ids"] = ["I-001"]

        first_review_dependency = ledger["review"]["direct_dependencies"][0]
        first_review_dependency["status"] = "unchecked"
        first_review_dependency["issue_ids"] = ["I-001"]
        second_review_dependency = json.loads(
            json.dumps(first_review_dependency)
        )
        second_review_dependency.update(
            {
                "use_id": "D002",
                "status": "incorrect",
                "needed_form": second_dependency["needed_form"],
            }
        )
        ledger["review"]["direct_dependencies"].append(
            second_review_dependency
        )
        conclusion = ledger["review"]["conclusion_results"][0]
        conclusion["argument_status"] = "invalid"
        conclusion["statement_status"] = "not_established"
        conclusion["dependency_closure"] = "incorrect"
        conclusion["dependency_use_ids"] = ["D001", "D002"]
        conclusion["issue_ids"] = ["I-001"]
        ledger["review"]["unit_status"] = "incorrect"
        ledger["review"]["argument_status"] = "invalid"
        ledger["review"]["statement_status"] = "not_established"
        ledger["review"]["dependency_closure"] = "incorrect"
        ledger["independent_check"]["covered_issue_ids"] = ["I-001"]
        ledger["independent_check"]["challenger_verdict"] = "incorrect"
        ledger["independent_check"]["reconciled_verdict"] = "incorrect"
        write_json(ledger_path, ledger)
        self.seal_schema5_challenge(ledger_path, read_json(ledger_path))

        registry_path = (
            self.audit
            / "audit"
            / "03_dependencies"
            / "DEPENDENCY_REGISTRY.json"
        )
        registry = read_json(registry_path)
        first_use = registry["internal_uses"][0]
        first_use["compatibility_checks"][0].update(
            {
                "status": "unchecked",
                "evidence": (
                    "The D001 quantified-domain comparison was not checked."
                ),
                "issue_ids": ["I-001"],
            }
        )
        first_use["status"] = "unchecked"
        first_use["issue_ids"] = ["I-001"]
        second_use = json.loads(json.dumps(first_use))
        second_use["use_id"] = "D002"
        second_use["needed_form"] = second_dependency["needed_form"]
        second_use["compatibility_checks"][0].update(
            {
                "status": "incorrect",
                "evidence": (
                    "The D002 quantified-domain comparison is incorrect."
                ),
                "issue_ids": ["I-001"],
            }
        )
        second_use["status"] = "incorrect"
        registry["internal_uses"].append(second_use)
        write_json(registry_path, registry)
        self.seal_live_challenges()

        ledger_errors, summaries, _ = proofcheck.audit_ledgers(
            self.audit, True
        )
        self.assertEqual([], ledger_errors)
        summaries_by_id = {
            summary["unit_id"]: summary for summary in summaries
        }
        manifest = read_json(self.audit / "AUDIT_MANIFEST.json")
        inventory_path = (
            self.audit / "audit" / "01_index" / "theorem_inventory.json"
        )
        closure_errors: list[str] = []
        closure = proofcheck.validate_dependency_closure(
            registry,
            self.audit,
            summaries_by_id,
            source_snapshot_sha256=manifest["source_snapshot"]["sha256"],
            inventory_sha256=proofcheck.sha256_file(inventory_path),
            in_scope=manifest["audit_scope"]["in_scope_units"],
            errors=closure_errors,
        )
        self.assertEqual([], closure_errors)
        issue = self.make_global_issue(
            finding_status="defect",
            load_bearing=True,
            severity="S2",
            summary=(
                "The dependency closure contains one unchecked use and one "
                "incorrect use."
            ),
        )
        issue.update(
            {
                "origin_ref": {
                    "kind": "dependency_use",
                    "unit_id": "lem:main",
                    "use_id": "D001",
                },
                "contract_refs": [
                    {
                        "kind": "dependency_use",
                        "unit_id": "lem:main",
                        "use_id": "D001",
                    },
                    {
                        "kind": "dependency_use",
                        "unit_id": "lem:main",
                        "use_id": "D002",
                    },
                    {
                        "kind": "conclusion",
                        "unit_id": "lem:main",
                        "conclusion_id": "C001",
                    },
                ],
                "invalidation_kind": "dependency_mismatch",
            }
        )
        issue["suggested_changes"][0]["action"] = "repair_dependency"

        errors, _ = proofcheck.validate_issues(
            [issue],
            set(),
            True,
            evidence_base=self.audit,
            source_snapshot_id=manifest["source_snapshot"]["sha256"],
            in_scope=manifest["audit_scope"]["in_scope_units"],
            ledger_summaries=summaries,
            dependency_edges=closure["edges"],
        )

        self.assertTrue(
            any(
                "I-001.origin_ref" in error
                and "dependency use" in error
                and "unchecked" in error
                and "cannot establish dependency_mismatch" in error
                for error in errors
            ),
            errors,
        )

    def test_established_target_mismatch_forces_defects_found(self) -> None:
        self.make_complete_audit()
        record = self.make_interface_record(
            target_verdict="mismatch",
            code_to_documented="consistent",
            code_to_target="inconsistent",
        )
        issue = {
            "id": "I-001",
            "severity": "S2",
            "confidence": "high",
            "status": "open",
            "finding_status": "defect",
            "scope": "global",
            "load_bearing": False,
            "interface_id": "MI-001",
            "finding_class": "estimator_target_mismatch",
            "affected_layer": "estimator_target",
            "evidence_class": "observed",
            "estimator_target_status": "mismatch",
            "implementation_inspection_status": "inspected",
            "code_to_documented_estimator": "consistent",
            "code_to_required_target": "inconsistent",
            "execution_provenance_status": "not_checked",
            "location": "paper.tex:2-4",
            "affected_result": "lem:main",
            "affected_results": ["lem:main"],
            "summary": "The fixed fitting laws target a different population ratio.",
            "evidence": ["paper.tex:2-4"],
            "resolution_evidence_needed": ["Change the estimator or the claimed target."],
            "downstream_consequences": ["The documented feasible method is mismatched."],
            "possible_repair": "Use equal state reference laws.",
        }
        self.install_interface_issue(record, issue)
        errors, result = proofcheck.check_audit_finalization(self.audit)
        self.assertEqual("defects_found", result["derived_assessment"])
        self.assertTrue(
            any("expected defects_found" in error for error in errors), errors
        )

    def test_locked_code_evidence_detects_drift(self) -> None:
        record = self.make_interface_record()
        registry = {
            "schema_version": proofcheck.METHOD_INTERFACE_SCHEMA_VERSION,
            "scope": {
                "status": "reviewed",
                "trigger": "required",
                "reason": "The implementation relation was inspected.",
            },
            "interfaces": [record],
        }
        errors: list[str] = []
        proofcheck.validate_method_interface_registry(registry, self.audit, errors)
        self.assertEqual([], errors)
        (self.base / "estimator.py").write_text(
            "def fit_ratio(states, beta_actions, pi_actions):\n"
            "    return states, pi_actions, beta_actions\n",
            encoding="utf-8",
            newline="\n",
        )
        errors = []
        proofcheck.validate_method_interface_registry(registry, self.audit, errors)
        self.assertTrue(any("source drift" in error for error in errors), errors)

    def test_unlinked_code_does_not_block_an_oracle_theorem_scope(self) -> None:
        self.make_complete_audit()
        record = self.make_interface_record(
            load_bearing=True,
            implementation_required=False,
            execution_required=False,
            execution_provenance="not_checked",
        )
        self.install_interface_record(record)
        errors, result = proofcheck.check_audit_finalization(self.audit)
        self.assertEqual([], errors)
        self.assertEqual("no_defect_found", result["derived_assessment"])

    def test_required_execution_provenance_forces_inconclusive(self) -> None:
        self.make_complete_audit()
        record = self.make_interface_record(
            load_bearing=True,
            execution_required=True,
            execution_provenance="not_checked",
        )
        issue = {
            "id": "I-001",
            "severity": "S2",
            "confidence": "high",
            "status": "open",
            "finding_status": "inconclusive",
            "scope": "global",
            "load_bearing": True,
            "interface_id": "MI-001",
            "finding_class": "reproducibility_gap",
            "affected_layer": "execution_provenance",
            "evidence_class": "not_established",
            "estimator_target_status": "match",
            "implementation_inspection_status": "inspected",
            "code_to_documented_estimator": "consistent",
            "code_to_required_target": "consistent",
            "execution_provenance_status": "not_checked",
            "location": "reported experiments",
            "affected_result": "lem:main",
            "affected_results": ["lem:main"],
            "summary": "The inspected revision is not linked to reported runs.",
            "evidence": ["No run-to-revision record was supplied."],
            "resolution_evidence_needed": [
                "Supply revision, semantic configuration, inputs, and output linkage."
            ],
            "downstream_consequences": [
                "The declared end-to-end empirical claim remains unverified."
            ],
            "possible_repair": "Provide source-locked execution provenance.",
        }
        self.install_interface_issue(record, issue)
        errors, result = proofcheck.check_audit_finalization(self.audit)
        self.assertEqual("inconclusive", result["derived_assessment"])
        self.assertTrue(any("expected inconclusive" in error for error in errors), errors)

    def test_nonrequired_provenance_nonmatch_does_not_block_oracle_scope(self) -> None:
        self.make_complete_audit()
        record = self.make_interface_record(
            load_bearing=True,
            execution_required=False,
            execution_provenance="not_matched",
        )
        issue = {
            "id": "I-001",
            "severity": "S3",
            "confidence": "high",
            "status": "open",
            "finding_status": "defect",
            "scope": "global",
            "load_bearing": False,
            "interface_id": "MI-001",
            "finding_class": "reproducibility_gap",
            "affected_layer": "execution_provenance",
            "evidence_class": "observed",
            "estimator_target_status": "match",
            "implementation_inspection_status": "inspected",
            "code_to_documented_estimator": "consistent",
            "code_to_required_target": "consistent",
            "execution_provenance_status": "not_matched",
            "location": "reported experiments",
            "affected_result": "lem:main",
            "affected_results": ["lem:main"],
            "summary": "The archived revision differs from the recorded run revision.",
            "evidence": ["run-record.txt:1"],
            "resolution_evidence_needed": ["Locate the executed revision."],
            "downstream_consequences": [
                "The archive cannot reproduce the run, but the oracle proof is unaffected."
            ],
            "possible_repair": "Archive the executed revision and configuration.",
        }
        self.install_interface_issue(record, issue)
        errors, result = proofcheck.check_audit_finalization(self.audit)
        self.assertEqual([], errors)
        self.assertEqual("no_defect_found", result["derived_assessment"])
        report = (
            self.audit / "audit" / "06_reports" / "FINAL_REPORT.md"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "- Overall judgment: No load-bearing defect found under the "
            "stated non-formal protocol.",
            report,
        )
        self.assertIn(
            "I-001: The archived revision differs from the recorded run revision.",
            report,
        )

    def test_load_bearing_interface_issue_requires_load_bearing_interface(self) -> None:
        record = self.make_interface_record(
            specification="ambiguous",
            target_verdict="not_assessable",
            code_to_documented="not_assessable",
            load_bearing=False,
        )
        record["issue_ids"] = ["I-001"]
        issue = {
            "id": "I-001",
            "severity": "S1",
            "confidence": "medium",
            "status": "open",
            "finding_status": "inconclusive",
            "scope": "global",
            "load_bearing": True,
            "interface_id": "MI-001",
            "finding_class": "exposition_ambiguity",
            "affected_layer": "specification",
            "evidence_class": "observed",
            "estimator_target_status": "not_assessable",
            "implementation_inspection_status": "inspected",
            "code_to_documented_estimator": "not_assessable",
            "code_to_required_target": "consistent",
            "execution_provenance_status": "not_checked",
            "location": "paper.tex:2-4",
            "affected_result": "lem:main",
            "affected_results": ["lem:main"],
            "summary": "A central estimator description is ambiguous.",
            "evidence": ["paper.tex:2-4"],
            "resolution_evidence_needed": ["Clarify both fitting laws."],
            "downstream_consequences": ["The central feasible method is not assessable."],
            "possible_repair": "State both laws explicitly.",
        }
        errors, _ = proofcheck.validate_issues(
            [issue],
            set(),
            True,
            evidence_base=self.audit,
            interfaces={"MI-001": record},
        )
        self.assertTrue(
            any("requires a load-bearing interface" in error for error in errors),
            errors,
        )

    def test_open_interface_contract_detects_semantic_span_drift(self) -> None:
        self.make_complete_audit()
        record = self.make_interface_record(
            specification="ambiguous",
            target_verdict="not_assessable",
            code_to_documented="not_assessable",
        )
        record["issue_ids"] = ["I-001"]
        manifest = read_json(self.audit / "AUDIT_MANIFEST.json")
        issue = {
            "id": "I-001",
            "severity": "S3",
            "confidence": "high",
            "status": "open",
            "finding_status": "inconclusive",
            "scope": "global",
            "load_bearing": False,
            "interface_id": "MI-001",
            "finding_class": "exposition_ambiguity",
            "affected_layer": "specification",
            "evidence_class": "observed",
            "estimator_target_status": "not_assessable",
            "implementation_inspection_status": "inspected",
            "code_to_documented_estimator": "not_assessable",
            "code_to_required_target": "consistent",
            "execution_provenance_status": "not_checked",
            "location": "paper.tex:2-4",
            "affected_result": "lem:main",
            "affected_results": ["lem:main"],
            "summary": "The interface wording remains ambiguous.",
            "evidence": ["paper.tex:2-4"],
            "resolution_evidence_needed": ["State both fitting laws."],
            "downstream_consequences": ["none identified"],
            "possible_repair": "State both fitting laws explicitly.",
            "rechecked_units": [],
            "rechecked_dependency_uses": [],
            "reconciled_deliverables": [],
            "semantic_contract": {
                "protected_meaning": "Both laws use the same state reference measure.",
                "supporting_spans": [
                    proofcheck.locked_span(
                        self.paper,
                        2,
                        4,
                        self.audit,
                        role="authoritative_definition",
                    )
                ],
                "dependent_claims": ["lem:main"],
                "reopen_if": ["The common reference law becomes unspecified."],
                "regression_check": "Reconstruct both fitting laws after edits.",
                "source_snapshot_sha256": manifest["source_snapshot"]["sha256"],
            },
        }
        issue, _ = self.migrate_issue_fixture_to_schema5(issue)
        _, summaries, _ = proofcheck.audit_ledgers(self.audit, True)
        errors, _ = proofcheck.validate_issues(
            [issue],
            set(),
            True,
            evidence_base=self.audit,
            interfaces={"MI-001": record},
            source_snapshot_id=manifest["source_snapshot"]["sha256"],
            ledger_summaries=summaries,
        )
        self.assertEqual([], errors)
        self.paper.write_text(
            self.paper.read_text(encoding="utf-8").replace("$x=x$", "$x\\le x$"),
            encoding="utf-8",
            newline="\n",
        )
        errors, _ = proofcheck.validate_issues(
            [issue],
            set(),
            True,
            evidence_base=self.audit,
            interfaces={"MI-001": record},
            source_snapshot_id=manifest["source_snapshot"]["sha256"],
            ledger_summaries=summaries,
        )
        self.assertTrue(any("source drift" in error for error in errors), errors)

    def test_finalize_writes_protocol_seal(self) -> None:
        self.make_complete_audit()
        with contextlib.redirect_stdout(io.StringIO()):
            status = proofcheck.cmd_finalize(argparse.Namespace(root=self.audit))
        self.assertEqual(0, status)
        record = read_json(
            self.audit / "audit" / "06_reports" / "FINALIZATION.json"
        )
        self.assertEqual("passed", record["status"])
        self.assertEqual(
            proofcheck.SKILL_VERSION, record["protocol"]["skill_version"]
        )
        self.assertTrue(record["audit_state_sha256"])

    def test_portable_finalization_stays_fresh_after_relocation_with_warning(
        self,
    ) -> None:
        self.definitions.write_text(
            self.definitions.read_text(encoding="utf-8")
            + "\\input{missing-portable-source}\n",
            encoding="utf-8",
            newline="\n",
        )
        original_paper = self.paper
        original_definitions = self.definitions
        self.audit = self.base / "portable-final-audit"
        with contextlib.redirect_stdout(io.StringIO()):
            status = proofcheck.cmd_scaffold(
                argparse.Namespace(
                    paper=self.paper,
                    output=self.audit,
                    report_format="markdown",
                    input_kind="latex",
                    publisher_pdf=None,
                    portable_sources=True,
                    visual_review_status="not_started",
                    visual_review_notes=None,
                    additional_source=None,
                    fls=None,
                    project_root=self.base,
                )
            )
        self.assertEqual(0, status)

        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        manifest["protocol"].pop("challenge_contract_version", None)
        write_json(manifest_path, manifest)
        inventory = read_json(
            self.audit / "audit" / "01_index" / "theorem_inventory.json"
        )
        cross_references = read_json(
            self.audit / "audit" / "01_index" / "cross_reference_audit.json"
        )
        self.assertEqual("paper.tex", inventory["root_file"])
        self.assertEqual("paper.tex", cross_references["root_file"])
        self.assertTrue(manifest["parser_warnings"])
        self.assertTrue(
            any(
                "Included file not found: definitions.tex:2: "
                "missing-portable-source" in warning
                for warning in manifest["parser_warnings"]
            ),
            manifest["parser_warnings"],
        )
        persisted_text = json.dumps(
            [manifest, inventory, cross_references], ensure_ascii=False
        )
        self.assertNotIn(".proofcheck.stage", persisted_text)

        self.paper = proofcheck.resolve_stored_path(
            manifest["paper_file"], self.audit
        )
        self.definitions = self.paper.parent / "definitions.tex"
        self.make_complete_audit()
        manifest = read_json(manifest_path)
        for review in manifest["parser_warning_reviews"]:
            review.update(
                {
                    "disposition": "confirmed_non_load_bearing",
                    "affected_units": [],
                    "evidence": (
                        "The missing optional input contains no audited proof content."
                    ),
                }
            )
        write_json(manifest_path, manifest)

        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(
            io.StringIO()
        ):
            finalize_status = proofcheck.cmd_finalize(
                argparse.Namespace(root=self.audit)
            )
        self.assertEqual(0, finalize_status)

        original_paper.unlink()
        original_definitions.unlink()
        moved = self.base / "relocated portable final audit"
        self.audit.rename(moved)
        self.audit = moved
        moved_ledger = next(self.audit.rglob("lem-main.ledger.json"))
        moved_challenge = read_json(moved_ledger)["independent_check"]
        moved_artifact = self.audit / moved_challenge["artifact"]
        self.assertEqual(
            [],
            proofcheck.challenge_artifact_binding_errors(
                moved_artifact, "lem:main", moved_challenge
            ),
        )
        freshness = proofcheck.check_finalization_freshness(self.audit)

        self.assertEqual("current", freshness["freshness"])
        self.assertTrue(freshness["usable_finalization"])
        self.assertEqual([], freshness["current_gate_errors"])
        self.assertEqual([], freshness["stale_reasons"])

    def test_source_closure_follows_local_classes_and_packages(self) -> None:
        root = self.base / "local-dependencies.tex"
        local_class = self.base / "localjournal.cls"
        local_package = self.base / "localmath.sty"
        class_helper = self.base / "classhelper.sty"
        package_helper = self.base / "package-helper.tex"
        root.write_text(
            "\\documentclass{localjournal}\n"
            "\\usepackage{localmath}\n"
            "Document body.\n",
            encoding="utf-8",
            newline="\n",
        )
        local_class.write_text(
            "\\LoadClass{article}\n\\RequirePackage{classhelper}\n",
            encoding="utf-8",
            newline="\n",
        )
        local_package.write_text(
            "\\input{package-helper}\n",
            encoding="utf-8",
            newline="\n",
        )
        class_helper.write_text(
            "\\ProvidesPackage{classhelper}\n",
            encoding="utf-8",
            newline="\n",
        )
        package_helper.write_text(
            "\\newcommand{\\helper}{helper}\n",
            encoding="utf-8",
            newline="\n",
        )

        closure = proofcheck.discover_source_closure(root)

        self.assertEqual(
            {
                root.resolve(),
                local_class.resolve(),
                local_package.resolve(),
                class_helper.resolve(),
                package_helper.resolve(),
            },
            set(closure["files"]),
        )
        self.assertEqual([], closure["warnings"])

    def test_scaffold_locks_additional_sources_and_their_dependencies(self) -> None:
        additional = self.base / "supplement.tex"
        helper = self.base / "supplement-helper.tex"
        additional.write_text(
            "\\input{supplement-helper}\nSupplement.\n",
            encoding="utf-8",
            newline="\n",
        )
        helper.write_text("Helper.\n", encoding="utf-8", newline="\n")
        audit = self.base / "additional-source-audit"
        with contextlib.redirect_stdout(io.StringIO()):
            proofcheck.cmd_scaffold(
                argparse.Namespace(
                    paper=self.paper,
                    output=audit,
                    additional_source=[
                        (
                            str(additional),
                            "The supplement contains proof context.",
                            "The author identified this file as part of the audit scope.",
                        )
                    ],
                    fls=None,
                )
            )

        manifest = read_json(audit / "AUDIT_MANIFEST.json")
        locked_files = {
            proofcheck.resolve_stored_path(row["file"], audit)
            for row in manifest["source_snapshot"]["files"]
        }
        self.assertIn(additional.resolve(), locked_files)
        self.assertIn(helper.resolve(), locked_files)
        self.assertEqual(
            "The supplement contains proof context.",
            manifest["source_discovery"]["additional_files"][0]["reason"],
        )

        helper.write_text("Changed helper.\n", encoding="utf-8", newline="\n")
        errors, _ = proofcheck.check_audit_finalization(audit)
        self.assertTrue(
            any("Source drift in included file" in error for error in errors),
            errors,
        )

    def test_fls_adds_project_sources_and_is_itself_source_locked(self) -> None:
        recorder_source = self.base / "generated-definitions.sty"
        recorder_source.write_text(
            "\\ProvidesPackage{generated-definitions}\n",
            encoding="utf-8",
            newline="\n",
        )
        outside_input = self.base.parent / "external-system-package.sty"
        fls = self.base / "paper.fls"
        fls.write_text(
            f"PWD {self.base}\n"
            f"INPUT {recorder_source}\n"
            f"INPUT {outside_input}\n",
            encoding="utf-8",
            newline="\n",
        )
        audit = self.base / "fls-audit"
        with contextlib.redirect_stdout(io.StringIO()):
            proofcheck.cmd_scaffold(
                argparse.Namespace(
                    paper=self.paper,
                    output=audit,
                    additional_source=None,
                    fls=fls,
                )
            )

        manifest = read_json(audit / "AUDIT_MANIFEST.json")
        locked_files = {
            proofcheck.resolve_stored_path(row["file"], audit)
            for row in manifest["source_snapshot"]["files"]
        }
        fls_record = manifest["source_discovery"]["fls"]
        self.assertIn(recorder_source.resolve(), locked_files)
        self.assertEqual(
            [str(outside_input.resolve())],
            fls_record["outside_project_inputs"],
        )

        fls.write_text(
            fls.read_text(encoding="utf-8") + "OUTPUT paper.pdf\n",
            encoding="utf-8",
            newline="\n",
        )
        errors, _ = proofcheck.check_audit_finalization(audit)
        self.assertTrue(any("Recorder file drift" in error for error in errors), errors)

    def rebuild_with_parser_warning(self) -> Path:
        self.paper.write_text(
            self.paper.read_text(encoding="utf-8") + "\\subfile{\\whichfile}\n",
            encoding="utf-8",
            newline="\n",
        )
        self.audit = self.base / "warning-audit"
        with contextlib.redirect_stdout(io.StringIO()):
            proofcheck.cmd_scaffold(
                argparse.Namespace(paper=self.paper, output=self.audit, report_format="markdown")
            )
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        manifest["protocol"].pop("challenge_contract_version", None)
        write_json(manifest_path, manifest)
        self.make_complete_audit()
        return self.audit / "AUDIT_MANIFEST.json"

    def test_parser_warning_reviews_are_an_exact_bijection(self) -> None:
        manifest_path = self.rebuild_with_parser_warning()
        manifest = read_json(manifest_path)
        self.assertTrue(manifest["parser_warnings"])
        manifest["parser_warning_reviews"] = []
        write_json(manifest_path, manifest)

        errors, _ = proofcheck.check_audit_finalization(self.audit)

        self.assertTrue(
            any("must be a one-to-one review" in error for error in errors),
            errors,
        )

    def test_parser_warning_disposition_controls_no_defect_claim(self) -> None:
        manifest_path = self.rebuild_with_parser_warning()
        manifest = read_json(manifest_path)
        review = manifest["parser_warning_reviews"][0]
        review.update(
            {
                "disposition": "confirmed_non_load_bearing",
                "affected_units": [],
                "evidence": "The dynamic include occurs after the only proof unit.",
            }
        )
        write_json(manifest_path, manifest)
        errors, _ = proofcheck.check_audit_finalization(self.audit)
        self.assertEqual([], errors)

        manifest = read_json(manifest_path)
        manifest["parser_warning_reviews"][0]["disposition"] = "unresolved"
        write_json(manifest_path, manifest)
        errors, _ = proofcheck.check_audit_finalization(self.audit)
        self.assertTrue(
            any(
                "unresolved parser warning blocks no_defect_found" in error
                for error in errors
            ),
            errors,
        )

    def test_parser_scope_limitation_requires_a_recorded_limit(self) -> None:
        manifest_path = self.rebuild_with_parser_warning()
        manifest = read_json(manifest_path)
        manifest["parser_warning_reviews"][0].update(
            {
                "disposition": "scope_limitation",
                "affected_units": [],
                "evidence": "The dynamically selected file could not be resolved.",
            }
        )
        write_json(manifest_path, manifest)

        errors, _ = proofcheck.check_audit_finalization(self.audit)

        self.assertTrue(
            any("scope_limitation requires" in error for error in errors),
            errors,
        )

    def test_parser_limitation_outside_scope_is_assessment_neutral(self) -> None:
        manifest_path = self.rebuild_with_parser_warning()
        inventory_path = (
            self.audit / "audit" / "01_index" / "theorem_inventory.json"
        )
        inventory = read_json(inventory_path)
        excluded = json.loads(json.dumps(inventory["units"][0]))
        excluded["id"] = "lem:excluded"
        excluded["label"] = "lem:excluded"
        inventory["units"].append(excluded)
        write_json(inventory_path, inventory)

        limitation = "Dynamic source selection outside the audited proof scope."
        manifest = read_json(manifest_path)
        manifest["audit_scope"]["excluded_units"] = [
            {
                "id": "lem:excluded",
                "reason": "The companion proof unit is outside the focused audit.",
            }
        ]
        manifest["audit_scope"]["inventory_overrides"] = [
            {
                "unit_id": "lem:excluded",
                "kind": "manual_unit",
                "reason": "Rendered-source review identified a companion proof unit.",
                "evidence": "Its statement and proof are visible in rendered source.",
            }
        ]
        manifest["audit_scope"]["source_or_parser_limits"] = [limitation]
        manifest["parser_warning_reviews"][0].update(
            {
                "disposition": "scope_limitation",
                "affected_units": ["lem:excluded"],
                "evidence": "The unresolved include can affect only the excluded unit.",
            }
        )
        write_json(manifest_path, manifest)
        self.refresh_dependency_review()

        progress_path = self.audit / "PROGRESS.json"
        progress = read_json(progress_path)
        progress["source_or_parser_limits"] = [limitation]
        write_json(progress_path, progress)

        report_path = self.audit / "audit" / "06_reports" / "FINAL_REPORT.md"
        report = report_path.read_text(encoding="utf-8")
        report = report.replace("- Results not checked: none", "- Results not checked: lem:excluded")
        report = report.replace(
            "- Tooling, extraction, or rendering limitations: none",
            f"- Tooling, extraction, or rendering limitations: {limitation}",
        )
        report_path.write_text(report, encoding="utf-8", newline="\n")

        errors, result = proofcheck.check_audit_finalization(self.audit)
        self.assertEqual("no_defect_found", result["derived_assessment"])
        self.assertFalse(
            any("parser limitation blocks no_defect_found" in error for error in errors),
            errors,
        )

        canonical_manifest = read_json(manifest_path)
        cases = {
            "unresolved": lambda review: review.update(
                {"disposition": "unresolved", "affected_units": ["lem:excluded"]}
            ),
            "empty scope": lambda review: review.__setitem__("affected_units", []),
            "in-scope unit": lambda review: review.__setitem__(
                "affected_units", ["lem:main"]
            ),
        }
        for label, mutate in cases.items():
            with self.subTest(case=label):
                changed = json.loads(json.dumps(canonical_manifest))
                mutate(changed["parser_warning_reviews"][0])
                write_json(manifest_path, changed)
                errors, result = proofcheck.check_audit_finalization(self.audit)
                self.assertEqual("inconclusive", result["derived_assessment"])
                self.assertTrue(
                    any("blocks no_defect_found" in error for error in errors),
                    errors,
                )

    def test_status_reports_a_current_usable_finalization(self) -> None:
        self.make_complete_audit()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(
                0,
                proofcheck.cmd_finalize(argparse.Namespace(root=self.audit)),
            )
        status_output = io.StringIO()
        with contextlib.redirect_stdout(status_output):
            status = proofcheck.cmd_status(
                argparse.Namespace(
                    root=self.audit,
                    format="json",
                    output=None,
                    force=False,
                )
            )
        payload = json.loads(status_output.getvalue())

        self.assertEqual(0, status)
        self.assertEqual("passed", payload["finalization"]["record_status"])
        self.assertEqual("current", payload["finalization"]["freshness"])
        self.assertTrue(payload["finalization"]["usable_finalization"])
        self.assertTrue(payload["audit_complete"])
        self.assertEqual("FINAL", payload["delivery_status"])
        self.assertEqual(0, payload["finalization_gate_error_count"])

    def test_status_marks_changed_audit_artifact_as_stale(self) -> None:
        self.make_complete_audit()
        with contextlib.redirect_stdout(io.StringIO()):
            proofcheck.cmd_finalize(argparse.Namespace(root=self.audit))
        report_path = self.audit / "audit" / "06_reports" / "FINAL_REPORT.md"
        report_path.write_text(
            report_path.read_text(encoding="utf-8") + "\nEditorial note.\n",
            encoding="utf-8",
            newline="\n",
        )

        freshness = proofcheck.check_finalization_freshness(self.audit)
        with contextlib.redirect_stdout(io.StringIO()):
            status = proofcheck.cmd_status(
                argparse.Namespace(
                    root=self.audit,
                    format="json",
                    output=None,
                    force=False,
                )
            )

        self.assertEqual(1, status)
        self.assertEqual("stale", freshness["freshness"])
        self.assertFalse(freshness["usable_finalization"])
        self.assertIn(
            "audit/06_reports/FINAL_REPORT.md",
            freshness["artifact_changes"]["changed"],
        )

    def test_external_source_drift_invalidates_finalization(self) -> None:
        self.make_complete_audit()
        with contextlib.redirect_stdout(io.StringIO()):
            proofcheck.cmd_finalize(argparse.Namespace(root=self.audit))
        self.definitions.write_text(
            "\\newtheorem{lemma}{Lemma}\n% changed after finalization\n",
            encoding="utf-8",
            newline="\n",
        )

        freshness = proofcheck.check_finalization_freshness(self.audit)

        self.assertEqual("stale", freshness["freshness"])
        self.assertFalse(freshness["usable_finalization"])
        self.assertTrue(
            any(
                "Source drift in included file" in error
                for error in freshness["current_gate_errors"]
            ),
            freshness,
        )

    def test_status_without_finalization_record_remains_nonfailing(self) -> None:
        self.make_complete_audit()
        status_output = io.StringIO()
        with contextlib.redirect_stdout(status_output):
            status = proofcheck.cmd_status(
                argparse.Namespace(
                    root=self.audit,
                    format="json",
                    output=None,
                    force=False,
                )
            )
        payload = json.loads(status_output.getvalue())

        self.assertEqual(0, status)
        self.assertEqual("missing", payload["finalization"]["record_status"])
        self.assertEqual("not_applicable", payload["finalization"]["freshness"])
        self.assertFalse(payload["finalization"]["usable_finalization"])
        self.assertFalse(payload["audit_complete"])
        self.assertEqual("NONFINAL", payload["delivery_status"])
        self.assertEqual(0, payload["finalization_gate_error_count"])

    def test_status_require_finalized_uses_strict_exit_code(self) -> None:
        self.make_complete_audit()
        parser = proofcheck.build_parser()

        def run_status() -> tuple[int, dict]:
            args = parser.parse_args(
                ["status", "--root", str(self.audit), "--require-finalized"]
            )
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                status = args.func(args)
            return status, json.loads(output.getvalue())

        status, payload = run_status()
        self.assertEqual(1, status)
        self.assertFalse(payload["audit_complete"])
        self.assertEqual("NONFINAL", payload["delivery_status"])

        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(
                0, proofcheck.cmd_finalize(argparse.Namespace(root=self.audit))
            )

        status, payload = run_status()
        self.assertEqual(0, status)
        self.assertTrue(payload["audit_complete"])
        self.assertEqual("FINAL", payload["delivery_status"])

    def test_status_exposes_a_healthy_checkpointed_work_in_progress(self) -> None:
        ledger_path = (
            self.audit / "audit" / "04_local_checks" / "lem-main.ledger.json"
        )
        with contextlib.redirect_stdout(io.StringIO()):
            proofcheck.cmd_extract(
                argparse.Namespace(
                    file=self.paper,
                    start=2,
                    end=7,
                    statement_file=self.paper,
                    statement_start=2,
                    statement_end=4,
                    separate_statement_reason=None,
                    unit_id="lem:main",
                    output=ledger_path,
                    force=False,
                )
            )
        next_action = "Populate the obligation and first atomic step for lem:main."
        with contextlib.redirect_stdout(io.StringIO()):
            proofcheck.cmd_checkpoint(
                argparse.Namespace(
                    root=self.audit,
                    active_unit="lem:main",
                    clear_active_unit=False,
                    next_action=next_action,
                )
            )

        status_output = io.StringIO()
        with contextlib.redirect_stdout(status_output):
            status = proofcheck.cmd_status(
                argparse.Namespace(
                    root=self.audit,
                    format="json",
                    output=None,
                    force=False,
                    verbose=False,
                )
            )
        payload = json.loads(status_output.getvalue())

        self.assertEqual(0, status)
        self.assertEqual("healthy_wip", payload["workflow_state"])
        self.assertFalse(payload["audit_complete"])
        self.assertEqual("NONFINAL", payload["delivery_status"])
        self.assertGreater(payload["finalization_gate_error_count"], 0)
        self.assertEqual(
            0, payload["progress"]["candidate_completion_gate_error_count"]
        )
        self.assertEqual("lem:main", payload["progress"]["active_unit"])
        self.assertEqual(next_action, payload["progress"]["next_action"])
        self.assertEqual([], payload["progress"]["drift"])
        self.assertCountEqual(
            ["lem:main"], payload["progress"]["not_started_units"]
        )

    def test_undeclared_markdown_report_blocks_finalization_and_status(self) -> None:
        self.make_complete_audit()
        report_path = (
            self.audit / "audit" / "06_reports" / "NONFINAL_AUDIT_REPORT.md"
        )
        report_path.write_text(
            "# Nonfinal audit report\n\n"
            "The source-line audit and independent challenges are complete.\n",
            encoding="utf-8",
            newline="\n",
        )
        relative_report = "audit/06_reports/NONFINAL_AUDIT_REPORT.md"
        expected_error = proofcheck.undeclared_report_error(relative_report)

        errors, _ = proofcheck.check_audit_finalization(self.audit)
        self.assertIn(expected_error, errors)

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = proofcheck.cmd_status(
                argparse.Namespace(
                    root=self.audit,
                    format="json",
                    output=None,
                    force=False,
                    verbose=False,
                )
            )
        payload = json.loads(output.getvalue())

        self.assertEqual(1, status)
        self.assertEqual("malformed_or_stale", payload["workflow_state"])
        self.assertFalse(payload["audit_complete"])
        self.assertEqual("NONFINAL", payload["delivery_status"])
        self.assertGreater(payload["finalization_gate_error_count"], 0)
        self.assertEqual("failed", payload["report_integrity"]["status"])
        self.assertEqual(
            [relative_report],
            payload["report_integrity"]["undeclared_markdown_files"],
        )
        self.assertIn(expected_error, payload["structural_errors"])

    def test_status_rejects_a_prematurely_unmarked_final_report(self) -> None:
        report_path = self.audit / "audit" / "06_reports" / "FINAL_REPORT.md"
        report = report_path.read_text(encoding="utf-8").replace(
            proofcheck.REPORT_SCAFFOLD_MARKER,
            "WORKING REPORT",
            1,
        )
        report_path.write_text(report, encoding="utf-8")

        errors, _ = proofcheck.check_audit_finalization(self.audit)
        expected_error = (
            "Final report removed the NONFINAL scaffold marker before "
            "completion.final_report_ready is true"
        )
        self.assertIn(expected_error, errors)

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = proofcheck.cmd_status(
                argparse.Namespace(
                    root=self.audit,
                    format="json",
                    output=None,
                    force=False,
                    verbose=False,
                )
            )
        payload = json.loads(output.getvalue())

        self.assertEqual(1, status)
        self.assertEqual("malformed_or_stale", payload["workflow_state"])
        self.assertEqual("NONFINAL", payload["delivery_status"])
        self.assertEqual("failed", payload["report_integrity"]["status"])
        self.assertTrue(payload["report_integrity"]["prematurely_unmarked"])
        self.assertIn(expected_error, payload["structural_errors"])

    def test_status_rejects_an_additional_nonfinal_h1(self) -> None:
        report_path = self.audit / "audit" / "06_reports" / "FINAL_REPORT.md"
        report = report_path.read_text(encoding="utf-8")
        report_path.write_text(
            "# Misleading Draft Heading\n\n" + report,
            encoding="utf-8",
            newline="\n",
        )

        errors, _ = proofcheck.check_audit_finalization(self.audit)
        expected_error = (
            "Nonfinal report must use the working title as its sole H1: "
            f"{proofcheck.WORKING_REPORT_TITLE}"
        )
        self.assertIn(expected_error, errors)

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = proofcheck.cmd_status(
                argparse.Namespace(
                    root=self.audit,
                    format="json",
                    output=None,
                    force=False,
                    verbose=False,
                )
            )
        payload = json.loads(output.getvalue())

        self.assertEqual(1, status)
        self.assertEqual("failed", payload["report_integrity"]["status"])
        self.assertTrue(payload["report_integrity"]["invalid_nonfinal_title"])
        self.assertIn(expected_error, payload["structural_errors"])

    def test_status_rejects_an_additional_setext_nonfinal_h1(self) -> None:
        report_path = self.audit / "audit" / "06_reports" / "FINAL_REPORT.md"
        report = report_path.read_text(encoding="utf-8")
        report_path.write_text(
            "Misleading Draft Heading\n=========================\n\n" + report,
            encoding="utf-8",
            newline="\n",
        )

        errors, _ = proofcheck.check_audit_finalization(self.audit)
        expected_error = (
            "Nonfinal report must use the working title as its sole H1: "
            f"{proofcheck.WORKING_REPORT_TITLE}"
        )
        self.assertIn(expected_error, errors)

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = proofcheck.cmd_status(
                argparse.Namespace(
                    root=self.audit,
                    format="json",
                    output=None,
                    force=False,
                    verbose=False,
                )
            )
        payload = json.loads(output.getvalue())

        self.assertEqual(1, status)
        self.assertTrue(payload["report_integrity"]["invalid_nonfinal_title"])

    def test_status_marks_stale_checkpoint_as_malformed_or_stale(self) -> None:
        progress_path = self.audit / "PROGRESS.json"
        progress = read_json(progress_path)
        progress["source_snapshot_sha256"] = "0" * 64
        write_json(progress_path, progress)

        status_output = io.StringIO()
        with contextlib.redirect_stdout(status_output):
            status = proofcheck.cmd_status(
                argparse.Namespace(
                    root=self.audit,
                    format="json",
                    output=None,
                    force=False,
                    verbose=False,
                )
            )
        payload = json.loads(status_output.getvalue())

        self.assertEqual(1, status)
        self.assertEqual("malformed_or_stale", payload["workflow_state"])
        self.assertTrue(payload["progress"]["drift"])
        self.assertIn(
            "source_snapshot_sha256",
            json.dumps(payload["progress"]["drift"]),
        )

    def test_status_reports_coherent_legacy_audit_as_upgrade_required(
        self,
    ) -> None:
        ledger_path = self.downgrade_complete_audit_to_schema4()

        def status_payload(verbose: bool) -> tuple[int, dict]:
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                status = proofcheck.cmd_status(
                    argparse.Namespace(
                        root=self.audit,
                        format="json",
                        output=None,
                        force=False,
                        verbose=verbose,
                    )
                )
            return status, json.loads(output.getvalue())

        concise_status, concise = status_payload(False)
        verbose_status, verbose = status_payload(True)
        expected_recorded = {
            "artifact_schema_version": 4,
            "evidence_contract_version": 3,
            "closure_contract_version": 2,
        }
        expected_current = {
            field: value
            for field, value in proofcheck.protocol_identity().items()
            if field != "validator_sha256"
        }

        self.assertEqual(1, concise_status)
        self.assertEqual(1, verbose_status)
        self.assertEqual("upgrade_required", concise["workflow_state"])
        self.assertEqual("upgrade_required", verbose["workflow_state"])
        self.assertEqual("upgrade_required", concise["protocol"]["status"])
        self.assertLessEqual(
            expected_recorded.items(), concise["protocol"]["recorded"].items()
        )
        self.assertEqual(expected_current, concise["protocol"]["current"])
        self.assertTrue(
            any(
                str(path).endswith(ledger_path.name)
                for path in concise["protocol"]["legacy_ledgers"]
            ),
            concise["protocol"],
        )
        next_action = concise["protocol"]["next_action"].lower()
        self.assertIn("migrate-ledger", next_action)
        self.assertIn("recheck", next_action)
        self.assertEqual([], concise["structural_errors"])
        self.assertEqual([], concise["invalid_ledgers"])
        self.assertLessEqual(
            len(concise["finalization"]["current_gate_errors"]), 4
        )
        self.assertTrue(
            any(
                "upgrade" in error.lower()
                or "protocol" in error.lower()
                for error in concise["finalization"]["current_gate_errors"]
            ),
            concise["finalization"],
        )
        self.assertGreater(
            concise["finalization"]["current_gate_errors_omitted"], 0
        )
        self.assertEqual(
            0, verbose["finalization"]["current_gate_errors_omitted"]
        )
        self.assertEqual(
            verbose["finalization"]["current_gate_error_count"],
            len(verbose["finalization"]["current_gate_errors"]),
        )
        self.assertEqual(
            concise["finalization"]["current_gate_error_count"],
            verbose["finalization"]["current_gate_error_count"],
        )
        self.assertGreater(
            len(verbose["finalization"]["current_gate_errors"]),
            len(concise["finalization"]["current_gate_errors"]),
        )

    def test_schema5_closure3_has_distinct_nonfinal_upgrade_path(self) -> None:
        self.make_complete_audit()
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        manifest["protocol"]["closure_contract_version"] = (
            proofcheck.PREVIOUS_CLOSURE_CONTRACT_VERSION
        )
        write_json(manifest_path, manifest)
        registry_path = (
            self.audit
            / "audit"
            / "03_dependencies"
            / "DEPENDENCY_REGISTRY.json"
        )
        registry = read_json(registry_path)
        registry["closure_contract_version"] = (
            proofcheck.PREVIOUS_CLOSURE_CONTRACT_VERSION
        )
        write_json(registry_path, registry)

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = proofcheck.cmd_status(
                argparse.Namespace(
                    root=self.audit,
                    format="json",
                    output=None,
                    force=False,
                    verbose=False,
                )
            )
        payload = json.loads(output.getvalue())

        self.assertEqual(1, status)
        self.assertEqual("closure_upgrade_required", payload["workflow_state"])
        self.assertEqual(
            "closure_upgrade_required", payload["protocol"]["status"]
        )
        self.assertEqual([], payload["protocol"]["legacy_ledgers"])
        self.assertIn("migrate-closure", payload["protocol"]["next_action"])
        self.assertFalse(payload["audit_complete"])
        self.assertEqual("NONFINAL", payload["delivery_status"])

    def test_migrate_closure_preserves_registry_and_forces_citation_recheck(
        self,
    ) -> None:
        ledger_path = self.make_complete_audit()
        self.install_external_dependency(ledger_path)
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        manifest["protocol"]["closure_contract_version"] = (
            proofcheck.PREVIOUS_CLOSURE_CONTRACT_VERSION
        )
        write_json(manifest_path, manifest)
        registry_path = (
            self.audit
            / "audit"
            / "03_dependencies"
            / "DEPENDENCY_REGISTRY.json"
        )
        registry = read_json(registry_path)
        external = registry["external_results"][0]
        self.assertTrue(external["citation_bindings"])
        external.pop("citation_binding_review")
        external["uses"][0]["dependency_contract_sha256"] = (
            proofcheck.canonical_sha256(
                proofcheck.external_result_core_contract(external)
            )
        )
        registry["closure_contract_version"] = (
            proofcheck.PREVIOUS_CLOSURE_CONTRACT_VERSION
        )
        write_json(registry_path, registry)
        legacy_bytes = registry_path.read_bytes()
        legacy_use_hash = external["uses"][0]["dependency_contract_sha256"]

        output = io.StringIO()
        errors = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            status = proofcheck.cmd_migrate_closure(
                argparse.Namespace(root=self.audit)
            )
        payload = json.loads(output.getvalue())

        self.assertEqual(0, status, errors.getvalue())
        self.assertEqual("migrated", payload["status"])
        self.assertTrue(payload["finalization_invalidated"])
        backup_path = Path(payload["legacy_registry_backup"])
        self.assertEqual(legacy_bytes, backup_path.read_bytes())
        migrated = read_json(registry_path)
        migrated_external = migrated["external_results"][0]
        self.assertEqual(
            proofcheck.CLOSURE_CONTRACT_VERSION,
            migrated["closure_contract_version"],
        )
        self.assertEqual([], migrated_external["citation_bindings"])
        self.assertEqual(
            "pending",
            migrated_external["citation_binding_review"]["status"],
        )
        self.assertEqual(
            ["smith"],
            migrated_external["citation_binding_review"]["required_keys"],
        )
        self.assertEqual(
            legacy_use_hash,
            migrated_external["uses"][0]["dependency_contract_sha256"],
        )
        self.assertEqual("not_reviewed", migrated["review"]["status"])
        migrated_manifest = read_json(manifest_path)
        self.assertEqual(
            proofcheck.CLOSURE_CONTRACT_VERSION,
            migrated_manifest["protocol"]["closure_contract_version"],
        )
        self.assertFalse(
            migrated_manifest["completion"]["dependency_registry_reviewed"]
        )
        final_errors, _ = proofcheck.check_audit_finalization(self.audit)
        self.assertTrue(
            any("citation_bindings" in error for error in final_errors),
            final_errors,
        )
        self.assertTrue(
            any("citation_binding_review.status" in error for error in final_errors),
            final_errors,
        )

    def test_migrate_closure_rejects_incompatible_already_current_state(
        self,
    ) -> None:
        self.make_complete_audit()
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        manifest["protocol"]["evidence_contract_version"] = (
            proofcheck.LEGACY_EVIDENCE_CONTRACT_VERSION
        )
        write_json(manifest_path, manifest)

        output = io.StringIO()
        errors = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            status = proofcheck.cmd_migrate_closure(
                argparse.Namespace(root=self.audit)
            )
        payload = json.loads(output.getvalue())

        self.assertEqual(1, status)
        self.assertEqual("failed", payload["status"])
        self.assertFalse(payload["updated"])
        self.assertTrue(
            any(
                "protocol.evidence_contract_version is incompatible" in error
                for error in payload["errors"]
            ),
            payload,
        )

    def test_migrate_closure_already_current_rejects_malformed_registry(
        self,
    ) -> None:
        self.make_complete_audit()
        registry_path = (
            self.audit
            / "audit"
            / "03_dependencies"
            / "DEPENDENCY_REGISTRY.json"
        )
        registry = read_json(registry_path)
        registry["external_results"] = {}
        write_json(registry_path, registry)
        registry_bytes = registry_path.read_bytes()

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(
            io.StringIO()
        ):
            status = proofcheck.cmd_migrate_closure(
                argparse.Namespace(root=self.audit)
            )
        payload = json.loads(stdout.getvalue())

        self.assertEqual(1, status)
        self.assertEqual("failed", payload["status"])
        self.assertTrue(
            any("external_results must be a list" in error for error in payload["errors"]),
            payload,
        )
        self.assertEqual(registry_bytes, registry_path.read_bytes())
        self.assertFalse((registry_path.parent / "history").exists())

    def test_migrate_closure_already_current_rejects_source_drift(
        self,
    ) -> None:
        self.make_complete_audit()
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        registry_path = (
            self.audit
            / "audit"
            / "03_dependencies"
            / "DEPENDENCY_REGISTRY.json"
        )
        manifest_bytes = manifest_path.read_bytes()
        registry_bytes = registry_path.read_bytes()
        self.paper.write_text(
            self.paper.read_text(encoding="utf-8") + "% source drift\n",
            encoding="utf-8",
            newline="\n",
        )

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(
            io.StringIO()
        ):
            status = proofcheck.cmd_migrate_closure(
                argparse.Namespace(root=self.audit)
            )
        payload = json.loads(stdout.getvalue())

        self.assertEqual(1, status)
        self.assertEqual("failed", payload["status"])
        self.assertTrue(
            any("source" in error.lower() for error in payload["errors"]),
            payload,
        )
        self.assertEqual(manifest_bytes, manifest_path.read_bytes())
        self.assertEqual(registry_bytes, registry_path.read_bytes())
        self.assertFalse((registry_path.parent / "history").exists())

    def test_migrate_closure_removes_new_backup_when_transaction_fails(
        self,
    ) -> None:
        self.make_complete_audit()
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        manifest["protocol"]["closure_contract_version"] = (
            proofcheck.PREVIOUS_CLOSURE_CONTRACT_VERSION
        )
        write_json(manifest_path, manifest)
        registry_path = (
            self.audit
            / "audit"
            / "03_dependencies"
            / "DEPENDENCY_REGISTRY.json"
        )
        registry = read_json(registry_path)
        registry["closure_contract_version"] = (
            proofcheck.PREVIOUS_CLOSURE_CONTRACT_VERSION
        )
        write_json(registry_path, registry)
        manifest_bytes = manifest_path.read_bytes()
        registry_bytes = registry_path.read_bytes()
        history_directory = registry_path.parent / "history"
        backup_path = history_directory / (
            "DEPENDENCY_REGISTRY.closure-"
            f"{proofcheck.PREVIOUS_CLOSURE_CONTRACT_VERSION}."
            f"{proofcheck.sha256_file(registry_path)}.json"
        )

        with mock.patch.object(
            proofcheck,
            "transactional_write_texts",
            side_effect=OSError("injected migration transaction failure"),
        ):
            with self.assertRaisesRegex(
                OSError, "injected migration transaction failure"
            ):
                proofcheck.cmd_migrate_closure(
                    argparse.Namespace(root=self.audit)
                )

        self.assertEqual(manifest_bytes, manifest_path.read_bytes())
        self.assertEqual(registry_bytes, registry_path.read_bytes())
        self.assertFalse(backup_path.exists())
        self.assertFalse(history_directory.exists())

    def test_migrate_closure_rejects_interleaved_registry_edit(self) -> None:
        self.make_complete_audit()
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        manifest["protocol"]["closure_contract_version"] = (
            proofcheck.PREVIOUS_CLOSURE_CONTRACT_VERSION
        )
        write_json(manifest_path, manifest)
        registry_path = (
            self.audit
            / "audit"
            / "03_dependencies"
            / "DEPENDENCY_REGISTRY.json"
        )
        registry = read_json(registry_path)
        registry["closure_contract_version"] = (
            proofcheck.PREVIOUS_CLOSURE_CONTRACT_VERSION
        )
        write_json(registry_path, registry)
        manifest_bytes = manifest_path.read_bytes()
        registry_bytes = registry_path.read_bytes()
        interleaved_bytes = registry_bytes + b" "
        original_transaction = proofcheck.transactional_write_texts

        def edit_before_commit(writes: list, **kwargs: object) -> None:
            self.assertTrue(
                proofcheck.migration_update_lock_path(self.audit).is_file()
            )
            registry_path.write_bytes(interleaved_bytes)
            original_transaction(writes, **kwargs)

        with mock.patch.object(
            proofcheck,
            "transactional_write_texts",
            side_effect=edit_before_commit,
        ):
            with self.assertRaisesRegex(
                ValueError, "Transactional baseline changed before commit"
            ):
                proofcheck.cmd_migrate_closure(
                    argparse.Namespace(root=self.audit)
                )

        self.assertEqual(manifest_bytes, manifest_path.read_bytes())
        self.assertEqual(interleaved_bytes, registry_path.read_bytes())
        self.assertFalse((registry_path.parent / "history").exists())
        self.assertFalse(
            proofcheck.migration_update_lock_path(self.audit).exists()
        )

    def test_migrate_closure_retains_lock_and_backups_for_recovery(self) -> None:
        self.make_complete_audit()
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        manifest["protocol"]["closure_contract_version"] = (
            proofcheck.PREVIOUS_CLOSURE_CONTRACT_VERSION
        )
        write_json(manifest_path, manifest)
        registry_path = (
            self.audit
            / "audit"
            / "03_dependencies"
            / "DEPENDENCY_REGISTRY.json"
        )
        registry = read_json(registry_path)
        registry["closure_contract_version"] = (
            proofcheck.PREVIOUS_CLOSURE_CONTRACT_VERSION
        )
        write_json(registry_path, registry)
        registry_bytes = registry_path.read_bytes()
        backup_path = registry_path.parent / "history" / (
            "DEPENDENCY_REGISTRY.closure-"
            f"{proofcheck.PREVIOUS_CLOSURE_CONTRACT_VERSION}."
            f"{proofcheck.sha256_file(registry_path)}.json"
        )
        original_replace = proofcheck.os.replace
        replace_calls = 0

        def fail_commit_and_rollback(source: Path, destination: Path) -> None:
            nonlocal replace_calls
            replace_calls += 1
            if replace_calls in {2, 3, 4}:
                raise OSError("injected commit or rollback failure")
            original_replace(source, destination)

        with mock.patch.object(
            proofcheck.os,
            "replace",
            side_effect=fail_commit_and_rollback,
        ):
            with self.assertRaisesRegex(
                proofcheck.MigrationRecoveryRequired,
                "rollback was incomplete",
            ):
                proofcheck.cmd_migrate_closure(
                    argparse.Namespace(root=self.audit)
                )

        lock_path = proofcheck.migration_update_lock_path(self.audit)
        self.assertTrue(lock_path.is_file())
        self.assertEqual(registry_bytes, backup_path.read_bytes())
        self.assertTrue(list(self.audit.rglob("*.proofcheck.tmp")))
        with self.assertRaisesRegex(
            ValueError, "audit migration is in progress"
        ):
            proofcheck.cmd_status(
                argparse.Namespace(
                    root=self.audit,
                    format="json",
                    output=None,
                    force=False,
                    verbose=False,
                )
            )
        finalization_errors, _ = proofcheck.check_audit_finalization(
            self.audit
        )
        self.assertTrue(
            any(
                "audit migration is in progress" in error
                for error in finalization_errors
            ),
            finalization_errors,
        )

    def test_migrate_closure_retains_lock_if_backup_cleanup_fails(self) -> None:
        self.make_complete_audit()
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        manifest["protocol"]["closure_contract_version"] = (
            proofcheck.PREVIOUS_CLOSURE_CONTRACT_VERSION
        )
        write_json(manifest_path, manifest)
        registry_path = (
            self.audit
            / "audit"
            / "03_dependencies"
            / "DEPENDENCY_REGISTRY.json"
        )
        registry = read_json(registry_path)
        registry["closure_contract_version"] = (
            proofcheck.PREVIOUS_CLOSURE_CONTRACT_VERSION
        )
        write_json(registry_path, registry)
        registry_bytes = registry_path.read_bytes()
        backup_path = registry_path.parent / "history" / (
            "DEPENDENCY_REGISTRY.closure-"
            f"{proofcheck.PREVIOUS_CLOSURE_CONTRACT_VERSION}."
            f"{proofcheck.sha256_file(registry_path)}.json"
        )
        original_unlink = Path.unlink

        def reject_backup_cleanup(path: Path, *args: object, **kwargs: object) -> None:
            if path == backup_path:
                raise OSError("injected backup cleanup failure")
            original_unlink(path, *args, **kwargs)

        with mock.patch.object(
            proofcheck,
            "transactional_write_texts",
            side_effect=OSError("injected clean transaction failure"),
        ), mock.patch.object(
            Path,
            "unlink",
            autospec=True,
            side_effect=reject_backup_cleanup,
        ):
            with self.assertRaisesRegex(
                proofcheck.MigrationRecoveryRequired,
                "backup cleanup was incomplete",
            ):
                proofcheck.cmd_migrate_closure(
                    argparse.Namespace(root=self.audit)
                )

        self.assertTrue(
            proofcheck.migration_update_lock_path(self.audit).is_file()
        )
        self.assertEqual(registry_bytes, backup_path.read_bytes())
        finalization_errors, _ = proofcheck.check_audit_finalization(
            self.audit
        )
        self.assertTrue(
            any(
                "audit migration is in progress" in error
                for error in finalization_errors
            ),
            finalization_errors,
        )

    def test_migrate_closure_retains_recovery_after_committed_cleanup_failure(
        self,
    ) -> None:
        self.make_complete_audit()
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        manifest["protocol"]["closure_contract_version"] = (
            proofcheck.PREVIOUS_CLOSURE_CONTRACT_VERSION
        )
        write_json(manifest_path, manifest)
        registry_path = (
            self.audit
            / "audit"
            / "03_dependencies"
            / "DEPENDENCY_REGISTRY.json"
        )
        registry = read_json(registry_path)
        registry["closure_contract_version"] = (
            proofcheck.PREVIOUS_CLOSURE_CONTRACT_VERSION
        )
        write_json(registry_path, registry)
        legacy_registry_bytes = registry_path.read_bytes()
        backup_path = registry_path.parent / "history" / (
            "DEPENDENCY_REGISTRY.closure-"
            f"{proofcheck.PREVIOUS_CLOSURE_CONTRACT_VERSION}."
            f"{proofcheck.sha256_file(registry_path)}.json"
        )
        original_unlink = Path.unlink

        def fail_manifest_recovery_cleanup(
            path: Path, *args: object, **kwargs: object
        ) -> None:
            if (
                path.parent == manifest_path.parent
                and path.name.startswith(".AUDIT_MANIFEST.json.")
                and path.name.endswith(".proofcheck.tmp")
            ):
                raise OSError("injected committed cleanup failure")
            original_unlink(path, *args, **kwargs)

        with mock.patch.object(
            Path,
            "unlink",
            autospec=True,
            side_effect=fail_manifest_recovery_cleanup,
        ):
            with self.assertRaisesRegex(
                proofcheck.MigrationRecoveryRequired,
                "Live writes were committed",
            ):
                proofcheck.cmd_migrate_closure(
                    argparse.Namespace(root=self.audit)
                )

        self.assertEqual(
            proofcheck.CLOSURE_CONTRACT_VERSION,
            read_json(manifest_path)["protocol"]["closure_contract_version"],
        )
        self.assertEqual(
            proofcheck.CLOSURE_CONTRACT_VERSION,
            read_json(registry_path)["closure_contract_version"],
        )
        self.assertEqual(legacy_registry_bytes, backup_path.read_bytes())
        self.assertTrue(
            list(manifest_path.parent.glob(".AUDIT_MANIFEST.json.*.proofcheck.tmp"))
        )
        self.assertTrue(
            proofcheck.migration_update_lock_path(self.audit).is_file()
        )

    def test_migrate_closure_never_overwrites_racing_backup(self) -> None:
        self.make_complete_audit()
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        manifest["protocol"]["closure_contract_version"] = (
            proofcheck.PREVIOUS_CLOSURE_CONTRACT_VERSION
        )
        write_json(manifest_path, manifest)
        registry_path = (
            self.audit
            / "audit"
            / "03_dependencies"
            / "DEPENDENCY_REGISTRY.json"
        )
        registry = read_json(registry_path)
        registry["closure_contract_version"] = (
            proofcheck.PREVIOUS_CLOSURE_CONTRACT_VERSION
        )
        write_json(registry_path, registry)
        manifest_bytes = manifest_path.read_bytes()
        registry_bytes = registry_path.read_bytes()
        conflict_bytes = b"racing conflicting backup\n"
        original_publish = proofcheck.publish_no_overwrite

        def publish_after_conflict(
            temporary: Path, destination: Path, description: str
        ) -> str:
            destination.write_bytes(conflict_bytes)
            return original_publish(temporary, destination, description)

        with mock.patch.object(
            proofcheck,
            "publish_no_overwrite",
            side_effect=publish_after_conflict,
        ):
            with self.assertRaisesRegex(
                FileExistsError, "conflicting closure registry backup"
            ):
                proofcheck.cmd_migrate_closure(
                    argparse.Namespace(root=self.audit)
                )

        history_directory = registry_path.parent / "history"
        backups = list(history_directory.glob("DEPENDENCY_REGISTRY.closure-*.json"))
        self.assertEqual(1, len(backups))
        self.assertEqual(conflict_bytes, backups[0].read_bytes())
        self.assertEqual(manifest_bytes, manifest_path.read_bytes())
        self.assertEqual(registry_bytes, registry_path.read_bytes())

    def test_sha256_file_detects_same_size_rewrite_with_restored_mtime(
        self,
    ) -> None:
        target = self.audit / "digest-probe.bin"
        target.write_bytes(b"alpha-content-0001")
        before = target.stat()
        first = proofcheck.sha256_file(target)

        target.write_bytes(b"alpha-content-0002")
        os.utime(
            target,
            ns=(before.st_atime_ns, before.st_mtime_ns),
        )

        self.assertEqual(before.st_size, target.stat().st_size)
        self.assertEqual(before.st_mtime_ns, target.stat().st_mtime_ns)
        self.assertNotEqual(first, proofcheck.sha256_file(target))

    def test_gate_digest_snapshot_hashes_each_file_once(self) -> None:
        target = self.audit / "digest-snapshot.bin"
        target.write_bytes(b"stable gate input")
        original_open = Path.open
        binary_reads = 0

        def counting_open(path: Path, *args, **kwargs):
            nonlocal binary_reads
            if path.resolve() == target.resolve() and args[:1] == ("rb",):
                binary_reads += 1
            return original_open(path, *args, **kwargs)

        with mock.patch.object(Path, "open", counting_open):
            with proofcheck.gate_digest_snapshot():
                first = proofcheck.sha256_file(target)
                second = proofcheck.sha256_file(target)
            third = proofcheck.sha256_file(target)

        self.assertEqual(first, second)
        self.assertEqual(second, third)
        self.assertEqual(2, binary_reads)

    def test_text_memo_returns_independent_copies(self) -> None:
        source = "\\section{One}\nText\n\\subsection{Two}\n"
        headings = proofcheck.scan_section_headings(source)
        self.assertTrue(headings)
        headings.clear()
        self.assertEqual(
            proofcheck._scan_section_headings_uncached(source),
            proofcheck.scan_section_headings(source),
        )

    def test_status_runs_the_full_finalization_gate_at_most_once(self) -> None:
        """Near completion, status must reuse the completion-candidate gate
        instead of running a second full gate; the reused result must equal a
        fresh freshness check exactly."""
        self.make_complete_audit()
        fresh = proofcheck.check_finalization_freshness(self.audit)
        gate_errors, _ = proofcheck.check_audit_finalization(self.audit)
        reused = proofcheck.check_finalization_freshness(
            self.audit, gate_errors=list(gate_errors)
        )
        self.assertEqual(fresh, reused)

        calls = 0
        original = proofcheck.check_audit_finalization

        def spy(root, **kwargs):
            nonlocal calls
            calls += 1
            return original(root, **kwargs)

        with mock.patch.object(
            proofcheck, "check_audit_finalization", side_effect=spy
        ):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                status = proofcheck.cmd_status(
                    argparse.Namespace(
                        root=self.audit,
                        format="json",
                        output=None,
                        force=False,
                        verbose=False,
                    )
                )
        payload = json.loads(output.getvalue())
        self.assertEqual(0, status, payload.get("structural_errors"))
        self.assertEqual(1, calls)

    def test_finalized_status_points_at_the_report_deliverable(self) -> None:
        self.make_complete_audit()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(
                0, proofcheck.cmd_finalize(argparse.Namespace(root=self.audit))
            )
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = proofcheck.cmd_status(
                argparse.Namespace(
                    root=self.audit,
                    format="json",
                    output=None,
                    force=False,
                    verbose=False,
                )
            )
        payload = json.loads(output.getvalue())
        self.assertEqual(0, status)
        self.assertTrue(payload["audit_complete"])
        self.assertEqual(
            "Audit finalized. Deliver audit/06_reports/FINAL_REPORT.md "
            "(delivery-check re-verifies the release).",
            payload["progress"]["next_action"],
        )

    def test_tex_mask_cache_replays_warnings_identically(self) -> None:
        source = (
            "\\newcommand{\\broken"  # malformed definition: warning path
            "\nText % comment\n\\verb|kept|\n"
        )
        first: list[str] = []
        second: list[str] = ["existing note"]
        masked_first = proofcheck.mask_nonexecuting_tex(
            source, warnings=first, source_name="probe.tex"
        )
        masked_second = proofcheck.mask_nonexecuting_tex(
            source, warnings=second, source_name="probe.tex"
        )
        self.assertEqual(masked_first, masked_second)
        self.assertTrue(first)
        self.assertEqual(["existing note", *first], second)
        repeat = list(second)
        proofcheck.mask_nonexecuting_tex(
            source, warnings=second, source_name="probe.tex"
        )
        self.assertEqual(repeat, second)

    def test_status_requires_explicit_same_schema_validator_revalidation(
        self,
    ) -> None:
        self.make_complete_audit()
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        newer = dict(proofcheck.protocol_identity(), validator_sha256="0" * 64)
        protocol_patch = mock.patch.object(proofcheck, "protocol_identity", return_value=newer)
        protocol_patch.start()
        self.addCleanup(protocol_patch.stop)

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = proofcheck.cmd_status(
                argparse.Namespace(
                    root=self.audit,
                    format="json",
                    output=None,
                    force=False,
                    verbose=False,
                )
            )
        payload = json.loads(output.getvalue())

        self.assertEqual(1, status)
        self.assertEqual(
            "validator_revalidation_required", payload["workflow_state"]
        )
        self.assertEqual(
            "validator_revalidation_required", payload["protocol"]["status"]
        )
        self.assertIn(
            "revalidate-protocol", payload["protocol"]["next_action"]
        )

        revalidation_output = io.StringIO()
        with contextlib.redirect_stdout(revalidation_output):
            revalidation_status = proofcheck.cmd_revalidate_protocol(
                argparse.Namespace(root=self.audit)
            )
        revalidation = json.loads(revalidation_output.getvalue())

        self.assertEqual(0, revalidation_status)
        self.assertEqual("revalidated", revalidation["status"])
        self.assertTrue(revalidation["updated"])
        self.assertEqual(
            proofcheck.protocol_identity(),
            read_json(manifest_path)["protocol"],
        )
        self.assertEqual([], proofcheck.check_audit_finalization(self.audit)[0])

    def test_release_identity_drift_routes_through_revalidation(self) -> None:
        """A skill_version bump with unchanged contracts must be reported as
        revalidation work that cmd_revalidate_protocol actually accepts, and
        identity drift it rejects must never be reported as current."""
        self.make_complete_audit()
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        previous_version = proofcheck.protocol_identity()["skill_version"]
        newer = dict(proofcheck.protocol_identity(), skill_version="next-release")
        protocol_patch = mock.patch.object(proofcheck, "protocol_identity", return_value=newer)
        protocol_patch.start()
        self.addCleanup(protocol_patch.stop)

        view = proofcheck.status_protocol_view(read_json(manifest_path), [])
        self.assertEqual("validator_revalidation_required", view["status"])
        self.assertIn("revalidate-protocol", view["next_action"])

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = proofcheck.cmd_revalidate_protocol(
                argparse.Namespace(root=self.audit)
            )
        payload = json.loads(output.getvalue())
        self.assertEqual(0, status)
        self.assertEqual("revalidated", payload["status"])
        self.assertEqual(previous_version, payload["previous_skill_version"])
        self.assertEqual(
            proofcheck.protocol_identity(),
            read_json(manifest_path)["protocol"],
        )
        self.assertEqual(
            "current",
            proofcheck.status_protocol_view(read_json(manifest_path), [])[
                "status"
            ],
        )

        for field, value in (
            ("skill_name", "another-skill"),
            ("method_interface_schema_version", 99),
        ):
            with self.subTest(field=field):
                drifted = read_json(manifest_path)
                drifted["protocol"][field] = value
                write_json(manifest_path, drifted)
                self.assertEqual(
                    "mismatch",
                    proofcheck.status_protocol_view(drifted, [])["status"],
                )
                rejection = io.StringIO()
                with contextlib.redirect_stdout(
                    rejection
                ), contextlib.redirect_stderr(io.StringIO()):
                    rejected = proofcheck.cmd_revalidate_protocol(
                        argparse.Namespace(root=self.audit)
                    )
                self.assertEqual(1, rejected)
                self.assertIn(
                    f"protocol.{field} is not compatible",
                    "".join(json.loads(rejection.getvalue())["errors"]),
                )
                restored = read_json(manifest_path)
                restored["protocol"] = proofcheck.protocol_identity()
                write_json(manifest_path, restored)

    def test_protocol_revalidation_accepts_a_valid_scaffold_wip(self) -> None:
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        manifest["protocol"]["validator_sha256"] = "0" * 64
        write_json(manifest_path, manifest)

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = proofcheck.cmd_revalidate_protocol(
                argparse.Namespace(root=self.audit)
            )

        payload = json.loads(output.getvalue())
        self.assertEqual(0, status)
        self.assertEqual("revalidated", payload["status"])
        self.assertEqual(
            proofcheck.protocol_identity(),
            read_json(manifest_path)["protocol"],
        )

    def test_protocol_revalidation_refuses_source_drift(self) -> None:
        self.make_complete_audit()
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        manifest["protocol"]["validator_sha256"] = "0" * 64
        write_json(manifest_path, manifest)
        self.paper.write_text(
            self.paper.read_text(encoding="utf-8") + "% changed source\n",
            encoding="utf-8",
            newline="\n",
        )

        output = io.StringIO()
        errors = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            status = proofcheck.cmd_revalidate_protocol(
                argparse.Namespace(root=self.audit)
            )

        self.assertEqual(1, status)
        self.assertEqual("failed", json.loads(output.getvalue())["status"])
        self.assertEqual("0" * 64, read_json(manifest_path)["protocol"]["validator_sha256"])
        self.assertIn("drift", errors.getvalue().lower())

    def test_protocol_revalidation_refuses_unreadable_canonical_records(
        self,
    ) -> None:
        self.make_complete_audit()
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        manifest["protocol"]["validator_sha256"] = "0" * 64
        write_json(manifest_path, manifest)
        canonical_records = {
            "inventory": (
                self.audit
                / "audit"
                / "01_index"
                / "theorem_inventory.json"
            ),
            "dependency registry": (
                self.audit
                / "audit"
                / "03_dependencies"
                / "DEPENDENCY_REGISTRY.json"
            ),
            "method-interface registry": (
                self.audit
                / "audit"
                / "03_dependencies"
                / "METHOD_INTERFACE_REGISTRY.json"
            ),
            "final report": (
                self.audit / "audit" / "06_reports" / "FINAL_REPORT.md"
            ),
        }
        original_bytes = {
            label: path.read_bytes()
            for label, path in canonical_records.items()
        }

        for label, path in canonical_records.items():
            with self.subTest(record=label):
                for original_label, original_path in canonical_records.items():
                    original_path.write_bytes(original_bytes[original_label])
                path.write_bytes(
                    b"\xff" if label == "final report" else b"{malformed json"
                )

                output = io.StringIO()
                errors = io.StringIO()
                with contextlib.redirect_stdout(output), contextlib.redirect_stderr(
                    errors
                ):
                    status = proofcheck.cmd_revalidate_protocol(
                        argparse.Namespace(root=self.audit)
                    )

                self.assertEqual(1, status)
                self.assertEqual("failed", json.loads(output.getvalue())["status"])
                self.assertEqual(
                    "0" * 64,
                    read_json(manifest_path)["protocol"]["validator_sha256"],
                )
                self.assertTrue(errors.getvalue(), label)

    def test_protocol_revalidation_validates_dependency_registry_shape(
        self,
    ) -> None:
        self.make_complete_audit()
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        manifest["protocol"]["validator_sha256"] = "0" * 64
        write_json(manifest_path, manifest)
        registry_path = (
            self.audit
            / "audit"
            / "03_dependencies"
            / "DEPENDENCY_REGISTRY.json"
        )
        registry = read_json(registry_path)
        registry["internal_uses"] = {}
        write_json(registry_path, registry)

        output = io.StringIO()
        errors = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            status = proofcheck.cmd_revalidate_protocol(
                argparse.Namespace(root=self.audit)
            )

        self.assertEqual(1, status)
        self.assertEqual("failed", json.loads(output.getvalue())["status"])
        self.assertEqual(
            "0" * 64,
            read_json(manifest_path)["protocol"]["validator_sha256"],
        )
        self.assertIn("internal_uses must be a list", errors.getvalue())

    def test_protocol_revalidation_refuses_foreign_finalization_pointer(
        self,
    ) -> None:
        self.make_complete_audit()
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        manifest["protocol"]["validator_sha256"] = "0" * 64
        manifest["finalization_record"] = (
            "Z:\\foreign-audit\\FINALIZATION.json"
        )
        write_json(manifest_path, manifest)

        output = io.StringIO()
        errors = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            status = proofcheck.cmd_revalidate_protocol(
                argparse.Namespace(root=self.audit)
            )

        self.assertEqual(1, status)
        self.assertEqual("failed", json.loads(output.getvalue())["status"])
        self.assertEqual(
            "0" * 64,
            read_json(manifest_path)["protocol"]["validator_sha256"],
        )
        self.assertIn("manifest.finalization_record", errors.getvalue())

    def test_protocol_revalidation_refuses_malformed_finalization_record(
        self,
    ) -> None:
        self.make_complete_audit()
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        manifest["protocol"]["validator_sha256"] = "0" * 64
        write_json(manifest_path, manifest)
        (
            self.audit / "audit" / "06_reports" / "FINALIZATION.json"
        ).write_bytes(b"{malformed json")

        output = io.StringIO()
        errors = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            status = proofcheck.cmd_revalidate_protocol(
                argparse.Namespace(root=self.audit)
            )

        self.assertEqual(1, status)
        self.assertEqual("failed", json.loads(output.getvalue())["status"])
        self.assertEqual(
            "0" * 64,
            read_json(manifest_path)["protocol"]["validator_sha256"],
        )
        self.assertIn("Cannot read finalization record", errors.getvalue())

    def test_status_rejects_incompatible_current_manifest_protocol(self) -> None:
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        manifest["protocol"]["closure_contract_version"] = 999
        write_json(manifest_path, manifest)

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = proofcheck.cmd_status(
                argparse.Namespace(
                    root=self.audit,
                    format="json",
                    output=None,
                    force=False,
                    verbose=False,
                )
            )
        payload = json.loads(output.getvalue())

        self.assertEqual(1, status)
        self.assertEqual("mismatch", payload["protocol"]["status"])
        self.assertEqual("malformed_or_stale", payload["workflow_state"])
        self.assertIn("Re-scaffold", payload["progress"]["next_action"])

    def test_upgrade_required_does_not_mask_malformed_legacy_state(
        self,
    ) -> None:
        ledger_path = self.downgrade_complete_audit_to_schema4()
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        paper_bytes = self.paper.read_bytes()
        ledger_bytes = ledger_path.read_bytes()
        manifest_bytes = manifest_path.read_bytes()

        for case in (
            "source_drift",
            "ledger_integrity",
            "structural_read",
        ):
            with self.subTest(case=case):
                self.paper.write_bytes(paper_bytes)
                ledger_path.write_bytes(ledger_bytes)
                manifest_path.write_bytes(manifest_bytes)
                if case == "source_drift":
                    self.paper.write_text(
                        self.paper.read_text(encoding="utf-8")
                        + "% changed after legacy audit\n",
                        encoding="utf-8",
                        newline="\n",
                    )
                elif case == "ledger_integrity":
                    ledger = read_json(ledger_path)
                    ledger["source_lines"][0]["sha256"] = "0" * 64
                    write_json(ledger_path, ledger)
                else:
                    manifest_path.write_text(
                        "{malformed json",
                        encoding="utf-8",
                        newline="\n",
                    )

                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    status = proofcheck.cmd_status(
                        argparse.Namespace(
                            root=self.audit,
                            format="json",
                            output=None,
                            force=False,
                            verbose=False,
                        )
                    )
                payload = json.loads(output.getvalue())

                self.assertEqual(1, status)
                self.assertEqual(
                    "malformed_or_stale", payload["workflow_state"]
                )

    def test_status_reconciles_stale_partition_and_completed_active_unit(
        self,
    ) -> None:
        complete_path = self.make_complete_audit()
        pending_path = complete_path.with_name("lem-pending.ledger.json")
        with contextlib.redirect_stdout(io.StringIO()):
            proofcheck.cmd_extract(
                argparse.Namespace(
                    file=self.paper,
                    start=2,
                    end=7,
                    statement_file=self.paper,
                    statement_start=2,
                    statement_end=4,
                    separate_statement_reason=None,
                    unit_id="lem:pending",
                    output=pending_path,
                    force=False,
                )
            )

        inventory_path = (
            self.audit / "audit" / "01_index" / "theorem_inventory.json"
        )
        inventory = read_json(inventory_path)
        pending_unit = json.loads(json.dumps(inventory["units"][0]))
        pending_unit["id"] = "lem:pending"
        pending_unit["label"] = "lem:pending"
        pending_unit["proof_association"]["target"] = "lem:pending"
        inventory["units"].append(pending_unit)
        write_json(inventory_path, inventory)

        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        manifest["audit_scope"]["in_scope_units"] = [
            "lem:main",
            "lem:pending",
        ]
        write_json(manifest_path, manifest)

        progress_path = self.audit / "PROGRESS.json"
        progress = read_json(progress_path)
        progress["completed_units"] = []
        progress["active_unit"] = "lem:main"
        write_json(progress_path, progress)

        status_output = io.StringIO()
        with contextlib.redirect_stdout(status_output):
            status = proofcheck.cmd_status(
                argparse.Namespace(
                    root=self.audit,
                    format="json",
                    output=None,
                    force=False,
                    verbose=False,
                )
            )
        payload = json.loads(status_output.getvalue())
        drift = "\n".join(payload["progress"]["drift"])

        self.assertEqual(1, status)
        self.assertEqual("malformed_or_stale", payload["workflow_state"])
        self.assertIn("completed_units:", drift)
        self.assertIn("active_unit is already completed", drift)
        self.assertCountEqual(
            ["lem:main"], payload["progress"]["completed_units"]
        )
        self.assertCountEqual(
            ["lem:pending"], payload["progress"]["not_started_units"]
        )

    def test_source_drift_blocks_checkpoint_and_marks_status_malformed(self) -> None:
        progress_path = self.audit / "PROGRESS.json"
        original_progress = read_json(progress_path)
        self.paper.write_text(
            self.paper.read_text(encoding="utf-8") + "% changed after scaffold\n",
            encoding="utf-8",
            newline="\n",
        )

        with self.assertRaisesRegex(ValueError, "Source drift"):
            proofcheck.cmd_checkpoint(
                argparse.Namespace(
                    root=self.audit,
                    active_unit="lem:main",
                    clear_active_unit=False,
                    next_action="Reconcile the changed source before continuing.",
                )
            )

        self.assertEqual(original_progress, read_json(progress_path))
        status_output = io.StringIO()
        with contextlib.redirect_stdout(status_output):
            status = proofcheck.cmd_status(
                argparse.Namespace(
                    root=self.audit,
                    format="json",
                    output=None,
                    force=False,
                    verbose=False,
                )
            )
        payload = json.loads(status_output.getvalue())

        self.assertEqual(1, status)
        self.assertEqual("malformed_or_stale", payload["workflow_state"])
        self.assertIn("Source drift", json.dumps(payload))

    def test_status_marks_a_complete_preflight_as_finalizable(self) -> None:
        self.make_complete_audit()
        status_output = io.StringIO()
        with contextlib.redirect_stdout(status_output):
            status = proofcheck.cmd_status(
                argparse.Namespace(
                    root=self.audit,
                    format="json",
                    output=None,
                    force=False,
                    verbose=False,
                )
            )
        payload = json.loads(status_output.getvalue())

        self.assertEqual(0, status)
        self.assertEqual("finalizable", payload["workflow_state"])
        self.assertEqual([], payload["progress"]["drift"])
        self.assertCountEqual(
            ["lem:main"], payload["progress"]["completed_units"]
        )

    def test_checkpoint_migrates_legacy_progress_without_in_progress_units(
        self,
    ) -> None:
        self.make_complete_audit()
        progress_path = self.audit / "PROGRESS.json"
        progress = read_json(progress_path)
        progress.pop("in_progress_units")
        write_json(progress_path, progress)

        with contextlib.redirect_stdout(io.StringIO()):
            status = proofcheck.cmd_checkpoint(
                argparse.Namespace(
                    root=self.audit,
                    active_unit=None,
                    clear_active_unit=True,
                    next_action=(
                        "Audit complete; rerun finalization after any artifact change."
                    ),
                )
            )

        migrated = read_json(progress_path)
        errors, _ = proofcheck.check_audit_finalization(self.audit)
        self.assertEqual(0, status)
        self.assertEqual([], migrated["in_progress_units"])
        self.assertEqual("complete", migrated["status"])
        self.assertEqual([], errors)

    def test_checkpoint_stages_new_next_action_before_completion_gate(self) -> None:
        self.make_complete_audit()
        progress_path = self.audit / "PROGRESS.json"
        progress = read_json(progress_path)
        progress["next_action"] = "TBD"
        write_json(progress_path, progress)
        replacement = (
            "Audit complete; rerun finalization after any source or artifact change."
        )

        with contextlib.redirect_stdout(io.StringIO()):
            status = proofcheck.cmd_checkpoint(
                argparse.Namespace(
                    root=self.audit,
                    active_unit=None,
                    clear_active_unit=True,
                    next_action=replacement,
                )
            )

        updated = read_json(progress_path)
        errors, _ = proofcheck.check_audit_finalization(self.audit)
        self.assertEqual(0, status)
        self.assertEqual(replacement, updated["next_action"])
        self.assertEqual(8, updated["current_pass"])
        self.assertEqual("complete", updated["status"])
        self.assertEqual([], errors)

    def test_checkpoint_rejects_an_already_completed_active_unit(self) -> None:
        self.make_complete_audit()
        progress_path = self.audit / "PROGRESS.json"
        original = read_json(progress_path)

        with self.assertRaisesRegex(ValueError, "active unit is already completed"):
            proofcheck.cmd_checkpoint(
                argparse.Namespace(
                    root=self.audit,
                    active_unit="lem:main",
                    clear_active_unit=False,
                    next_action="Continue work on a unit that is already complete.",
                )
            )

        self.assertEqual(original, read_json(progress_path))

    def test_checkpoint_derives_passes_five_through_eight(self) -> None:
        self.make_complete_audit()
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        progress_path = self.audit / "PROGRESS.json"
        ledger_path = (
            self.audit
            / "audit"
            / "04_local_checks"
            / "lem-main.ledger.json"
        )
        complete_ledger = ledger_path.read_bytes()

        def checkpoint(next_action: str) -> tuple[int, str]:
            with contextlib.redirect_stdout(io.StringIO()):
                proofcheck.cmd_checkpoint(
                    argparse.Namespace(
                        root=self.audit,
                        active_unit=None,
                        clear_active_unit=True,
                        next_action=next_action,
                    )
                )
            progress = read_json(progress_path)
            return progress["current_pass"], progress["status"]

        manifest = read_json(manifest_path)
        manifest["completion"]["dependency_registry_reviewed"] = False
        write_json(manifest_path, manifest)
        pass_five = checkpoint("Complete the remaining system-level reviews.")

        manifest = read_json(manifest_path)
        manifest["completion"]["dependency_registry_reviewed"] = True
        write_json(manifest_path, manifest)
        ledger = read_json(ledger_path)
        ledger["independent_check"].update(
            {
                "required": False,
                "status": "not_required",
                "independence_level": "none",
                "challenger_verdict": "not_checked",
                "reconciled_verdict": "verified",
                "artifact": "",
                "covered_issue_ids": [],
                "source_snapshot_sha256": "",
                "challenged_ledger_sha256": "",
                "challenge_context_sha256": "",
                "challenge_artifact_sha256": "",
                "issue_assessments": [],
                "generated_utc": "",
                "disagreements": [],
                "resolution": "",
            }
        )
        write_json(ledger_path, ledger)
        pass_six = checkpoint("Complete every in-scope independent check.")

        ledger_path.write_bytes(complete_ledger)
        manifest = read_json(manifest_path)
        manifest["completion"]["final_report_ready"] = False
        write_json(manifest_path, manifest)
        pass_seven = checkpoint("Finish and reconcile the final report.")

        manifest = read_json(manifest_path)
        manifest["completion"]["final_report_ready"] = True
        write_json(manifest_path, manifest)
        pass_eight = checkpoint(
            "Audit complete; rerun finalization after any source or artifact change."
        )

        self.assertEqual([5, 6, 7, 8], [
            pass_five[0],
            pass_six[0],
            pass_seven[0],
            pass_eight[0],
        ])
        self.assertEqual(
            ["in_progress", "in_progress", "in_progress", "complete"],
            [pass_five[1], pass_six[1], pass_seven[1], pass_eight[1]],
        )

    def test_checkpoint_does_not_claim_completion_when_strict_gates_fail(
        self,
    ) -> None:
        self.make_complete_audit()
        report_path = self.audit / "audit" / "06_reports" / "FINAL_REPORT.md"
        report = report_path.read_text(encoding="utf-8").replace(
            "Overall assessment code: no_defect_found",
            "Overall assessment code: defects_found",
        )
        report_path.write_text(report, encoding="utf-8", newline="\n")
        progress_path = self.audit / "PROGRESS.json"
        progress = read_json(progress_path)
        progress["status"] = "in_progress"
        progress["current_pass"] = 7
        write_json(progress_path, progress)

        with contextlib.redirect_stdout(io.StringIO()):
            checkpoint_status = proofcheck.cmd_checkpoint(
                argparse.Namespace(
                    root=self.audit,
                    active_unit=None,
                    clear_active_unit=True,
                    next_action="Correct the final report assessment before finalization.",
                )
            )
        checkpoint = read_json(progress_path)

        status_output = io.StringIO()
        with contextlib.redirect_stdout(status_output):
            status = proofcheck.cmd_status(
                argparse.Namespace(
                    root=self.audit,
                    format="json",
                    output=None,
                    force=False,
                    verbose=False,
                )
            )
        payload = json.loads(status_output.getvalue())

        self.assertEqual(0, checkpoint_status)
        self.assertNotEqual("complete", checkpoint["status"])
        self.assertEqual(1, status)
        self.assertEqual("malformed_or_stale", payload["workflow_state"])
        self.assertIn("Final report assessment disagrees", json.dumps(payload))

    def test_failed_finalization_record_makes_status_nonzero(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(
            io.StringIO()
        ):
            self.assertEqual(
                1,
                proofcheck.cmd_finalize(argparse.Namespace(root=self.audit)),
            )
        with contextlib.redirect_stdout(io.StringIO()):
            status = proofcheck.cmd_status(
                argparse.Namespace(
                    root=self.audit,
                    format="json",
                    output=None,
                    force=False,
                )
            )
        freshness = proofcheck.check_finalization_freshness(self.audit)

        self.assertEqual(1, status)
        self.assertEqual("failed", freshness["record_status"])
        self.assertEqual("current", freshness["freshness"])
        self.assertFalse(freshness["usable_finalization"])

    def test_legacy_finalization_record_can_still_be_verified(self) -> None:
        self.make_complete_audit()
        with contextlib.redirect_stdout(io.StringIO()):
            proofcheck.cmd_finalize(argparse.Namespace(root=self.audit))
        record_path = self.audit / "audit" / "06_reports" / "FINALIZATION.json"
        record = read_json(record_path)
        record.pop("finalization_schema_version")
        record.pop("artifact_manifest")
        record.pop("record_payload_sha256")
        write_json(record_path, record)

        freshness = proofcheck.check_finalization_freshness(self.audit)

        self.assertEqual("current", freshness["freshness"])
        self.assertTrue(freshness["usable_finalization"])

    def test_status_refuses_to_mutate_a_finalized_audit_root(self) -> None:
        self.make_complete_audit()
        with contextlib.redirect_stdout(io.StringIO()):
            proofcheck.cmd_finalize(argparse.Namespace(root=self.audit))

        with self.assertRaisesRegex(ValueError, "inside an audit root"):
            proofcheck.cmd_status(
                argparse.Namespace(
                    root=self.audit,
                    format="json",
                    output=self.audit / "STATUS.json",
                    force=False,
                )
            )

    def test_malformed_finalization_record_path_is_invalid(self) -> None:
        self.make_complete_audit()
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        manifest["finalization_record"] = {"file": "not-a-string"}
        write_json(manifest_path, manifest)

        freshness = proofcheck.check_finalization_freshness(self.audit)
        with contextlib.redirect_stdout(io.StringIO()):
            status = proofcheck.cmd_status(
                argparse.Namespace(
                    root=self.audit,
                    format="json",
                    output=None,
                    force=False,
                )
            )

        self.assertEqual(1, status)
        self.assertEqual("invalid", freshness["record_status"])
        self.assertEqual("unknown", freshness["freshness"])
        self.assertTrue(
            any(
                "finalization_record" in reason
                for reason in freshness["stale_reasons"]
            ),
            freshness,
        )

    def test_markdown_status_keeps_key_gate_error_when_bounded(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(
            io.StringIO()
        ):
            self.assertEqual(
                1,
                proofcheck.cmd_finalize(argparse.Namespace(root=self.audit)),
            )
        status_output = io.StringIO()
        with contextlib.redirect_stdout(status_output):
            status = proofcheck.cmd_status(
                argparse.Namespace(
                    root=self.audit,
                    format="markdown",
                    output=None,
                    force=False,
                    verbose=False,
                )
            )

        markdown = status_output.getvalue()
        self.assertEqual(1, status)
        self.assertIn("at least one proof-unit ledger", markdown)
        self.assertIn("additional errors omitted; rerun status --verbose", markdown)
        self.assertLessEqual(len(markdown.splitlines()), 80)

    def test_explicit_missing_local_package_emits_warning(self) -> None:
        root = self.base / "missing-package.tex"
        root.write_text(
            "\\usepackage{./missing}\n",
            encoding="utf-8",
            newline="\n",
        )

        closure = proofcheck.discover_source_closure(root)

        self.assertTrue(
            any(
                "Explicit local class or package not found" in warning
                for warning in closure["warnings"]
            ),
            closure,
        )

    def test_fls_missing_main_paper_emits_warning(self) -> None:
        recorder_source = self.base / "only-dependency.sty"
        recorder_source.write_text(
            "\\ProvidesPackage{only-dependency}\n",
            encoding="utf-8",
            newline="\n",
        )
        fls = self.base / "incomplete.fls"
        fls.write_text(
            f"PWD {self.base}\nINPUT {recorder_source}\n",
            encoding="utf-8",
            newline="\n",
        )

        closure = proofcheck.discover_source_closure(
            self.paper,
            fls_file=fls,
            project_root=self.base,
        )

        self.assertTrue(
            any(
                "does not include the main paper" in warning.lower()
                for warning in closure["warnings"]
            ),
            closure,
        )

    def test_finalization_result_counts_the_full_parser_warning_set(self) -> None:
        self.paper.write_text(
            self.paper.read_text(encoding="utf-8").replace(
                "\\cite{smith}.",
                "\\cite{smith} and \\mycite{unknown}.",
            ),
            encoding="utf-8",
            newline="\n",
        )
        self.audit = self.base / "inventory-warning-audit"
        with contextlib.redirect_stdout(io.StringIO()):
            proofcheck.cmd_scaffold(
                argparse.Namespace(paper=self.paper, output=self.audit, report_format="markdown")
            )
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        manifest["protocol"].pop("challenge_contract_version", None)
        write_json(manifest_path, manifest)
        self.make_complete_audit()
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        self.assertTrue(manifest["parser_warnings"])
        for review in manifest["parser_warning_reviews"]:
            review.update(
                {
                    "disposition": "confirmed_non_load_bearing",
                    "affected_units": ["lem:main"],
                    "evidence": "The unsupported citation macro affects attribution only.",
                }
            )
        write_json(manifest_path, manifest)

        errors, result = proofcheck.check_audit_finalization(self.audit)

        self.assertEqual([], errors)
        self.assertEqual(
            len(manifest["parser_warnings"]),
            result["parser_warnings"],
        )

    def test_unreadable_local_style_is_locked_and_reported(self) -> None:
        unreadable_style = self.base / "unreadable.sty"
        unreadable_style.write_bytes(b"\\ProvidesPackage{unreadable}\n\xff\xfe\n")
        self.paper.write_text(
            self.paper.read_text(encoding="utf-8")
            + "\\usepackage{./unreadable}\n",
            encoding="utf-8",
            newline="\n",
        )
        self.audit = self.base / "unreadable-style-audit"
        with contextlib.redirect_stdout(io.StringIO()):
            proofcheck.cmd_scaffold(
                argparse.Namespace(paper=self.paper, output=self.audit, report_format="markdown")
            )

        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        manifest["protocol"].pop("challenge_contract_version", None)
        write_json(manifest_path, manifest)
        locked_files = {
            proofcheck.resolve_stored_path(row["file"], self.audit)
            for row in manifest["source_snapshot"]["files"]
        }
        self.assertIn(unreadable_style.resolve(), locked_files)
        self.assertTrue(
            any("Cannot decode" in warning for warning in manifest["parser_warnings"]),
            manifest,
        )

        self.make_complete_audit()
        manifest = read_json(manifest_path)
        for review in manifest["parser_warning_reviews"]:
            review.update(
                {
                    "disposition": "confirmed_non_load_bearing",
                    "affected_units": [],
                    "evidence": "The unreadable style defines no audited proof content.",
                }
            )
        write_json(manifest_path, manifest)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(
            io.StringIO()
        ):
            status = proofcheck.cmd_finalize(argparse.Namespace(root=self.audit))

        self.assertEqual(0, status)
        record = read_json(
            self.audit / "audit" / "06_reports" / "FINALIZATION.json"
        )
        self.assertEqual("passed", record["status"])

    def test_invalid_utf8_manifest_returns_errors(self) -> None:
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        manifest_path.write_bytes(b"{\xff}")

        errors, result = proofcheck.check_audit_finalization(self.audit)
        freshness = proofcheck.check_finalization_freshness(self.audit)

        self.assertTrue(any("Cannot read audit manifest" in error for error in errors))
        self.assertEqual(len(errors), result["errors"])
        self.assertEqual("invalid", freshness["record_status"])
        self.assertEqual("unknown", freshness["freshness"])

    def test_invalid_utf8_finalization_record_returns_errors(self) -> None:
        self.make_complete_audit()
        with contextlib.redirect_stdout(io.StringIO()):
            proofcheck.cmd_finalize(argparse.Namespace(root=self.audit))
        record_path = self.audit / "audit" / "06_reports" / "FINALIZATION.json"
        record_path.write_bytes(b"{\xff}")

        freshness = proofcheck.check_finalization_freshness(self.audit)
        with contextlib.redirect_stdout(io.StringIO()):
            status = proofcheck.cmd_status(
                argparse.Namespace(
                    root=self.audit,
                    format="json",
                    output=None,
                    force=False,
                )
            )

        self.assertEqual(1, status)
        self.assertEqual("invalid", freshness["record_status"])
        self.assertEqual("unknown", freshness["freshness"])
        self.assertTrue(
            any(
                "Cannot read finalization record" in reason
                for reason in freshness["stale_reasons"]
            ),
            freshness,
        )

    def test_invalid_utf8_ledger_returns_errors(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger_path.write_bytes(b"{\xff}")

        errors, result = proofcheck.check_audit_finalization(self.audit)

        self.assertTrue(any("Cannot read ledger" in error for error in errors), errors)
        self.assertGreater(result["errors"], 0)

    def test_invalid_utf8_issue_log_returns_errors(self) -> None:
        self.make_complete_audit()
        issue_path = self.audit / "audit" / "06_reports" / "ISSUE_LOG.json"
        issue_path.write_bytes(b"{\xff}")

        errors, result = proofcheck.check_audit_finalization(self.audit)

        self.assertTrue(any("Cannot read issue log" in error for error in errors), errors)
        self.assertGreater(result["errors"], 0)

    def test_invalid_utf8_canonical_text_artifacts_return_controlled_errors(
        self,
    ) -> None:
        self.make_complete_audit()
        paths = (
            self.audit / "audit" / "06_reports" / "FINAL_REPORT.md",
            self.audit / "audit" / "06_reports" / "ISSUE_SUMMARY.md",
            self.audit / "audit" / "01_index" / "cross_reference_audit.md",
        )
        baselines = {path: path.read_bytes() for path in paths}
        for path in paths:
            with self.subTest(path=path.name):
                path.write_bytes(b"\xff\xfe")

                errors, result = proofcheck.check_audit_finalization(
                    self.audit
                )

                self.assertTrue(
                    any(
                        "Unreadable UTF-8 text artifact" in error
                        and path.name in error
                        for error in errors
                    ),
                    errors,
                )
                self.assertGreater(result["errors"], 0)
                path.write_bytes(baselines[path])

    def test_invalid_utf8_declared_report_returns_controlled_error(self) -> None:
        canonical_report, user_report = (
            self.install_declared_user_report_with_orientation(
                "This reader-facing orientation remains within audit scope."
            )
        )
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        old_digest = manifest["report_deliverables"][0]["sha256"]
        user_report.write_bytes(b"\xff\xfe")
        new_digest = proofcheck.sha256_file(user_report)
        manifest["report_deliverables"][0]["sha256"] = new_digest
        write_json(manifest_path, manifest)
        canonical_report.write_text(
            canonical_report.read_text(encoding="utf-8").replace(
                old_digest,
                new_digest,
                1,
            ),
            encoding="utf-8",
            newline="\n",
        )

        errors, result = proofcheck.check_audit_finalization(self.audit)

        self.assertTrue(
            any(
                "report_deliverables[1]" in error
                and "Unreadable UTF-8 text artifact" in error
                and "USER_REPORT.md" in error
                for error in errors
            ),
            errors,
        )
        self.assertGreater(result["errors"], 0)

    def test_invalid_utf8_source_file_returns_controlled_error(self) -> None:
        self.make_complete_audit()
        self.paper.write_bytes(b"\xff\xfe")

        errors, result = proofcheck.check_audit_finalization(self.audit)

        self.assertTrue(
            any(
                "Unreadable UTF-8 text artifact" in error
                and self.paper.name in error
                for error in errors
            ),
            errors,
        )
        self.assertGreater(result["errors"], 0)

    def test_nested_input_resolution_locks_both_ambiguous_candidates(self) -> None:
        sections = self.base / "sections"
        sections.mkdir()
        root = self.base / "nested-main.tex"
        nested = sections / "part.tex"
        containing_candidate = sections / "shared.tex"
        project_candidate = self.base / "shared.tex"
        root.write_text(
            "\\input{sections/part}\n",
            encoding="utf-8",
            newline="\n",
        )
        nested.write_text(
            "\\input{shared}\n",
            encoding="utf-8",
            newline="\n",
        )
        containing_candidate.write_text(
            "Containing-file candidate.\n",
            encoding="utf-8",
            newline="\n",
        )
        project_candidate.write_text(
            "Project-root candidate.\n",
            encoding="utf-8",
            newline="\n",
        )

        closure = proofcheck.discover_source_closure(
            root,
            project_root=self.base,
        )

        self.assertIn(containing_candidate.resolve(), closure["files"])
        self.assertIn(project_candidate.resolve(), closure["files"])
        self.assertTrue(
            any(
                "Ambiguous include resolution" in warning
                for warning in closure["warnings"]
            ),
            closure,
        )

    def assert_scaffold_rejected_before_output(
        self,
        output: Path,
        expected_exception: type[Exception],
        *,
        additional_source: list[tuple[str, str, str]] | None = None,
        fls: Path | None = None,
    ) -> None:
        self.assertFalse(output.exists())
        with self.assertRaises(expected_exception):
            proofcheck.cmd_scaffold(
                argparse.Namespace(
                    paper=self.paper,
                    output=output,
                    additional_source=additional_source,
                    fls=fls,
                )
            )
        self.assertFalse(output.exists())

    def test_scaffold_rejects_missing_additional_source_before_writing(self) -> None:
        self.assert_scaffold_rejected_before_output(
            self.base / "missing-additional-audit",
            FileNotFoundError,
            additional_source=[
                (
                    str(self.base / "missing-supplement.tex"),
                    "The file was declared as proof context.",
                    "The declaration came from the audit plan.",
                )
            ],
        )

    def test_scaffold_rejects_duplicate_additional_source_before_writing(self) -> None:
        additional = self.base / "duplicate-supplement.tex"
        additional.write_text("Supplement.\n", encoding="utf-8", newline="\n")
        self.assert_scaffold_rejected_before_output(
            self.base / "duplicate-additional-audit",
            ValueError,
            additional_source=[
                (
                    str(additional),
                    "First declaration.",
                    "First evidence record.",
                ),
                (
                    str(additional.resolve()),
                    "Second declaration.",
                    "Second evidence record.",
                ),
            ],
        )

    def test_scaffold_rejects_blank_additional_metadata_before_writing(self) -> None:
        additional = self.base / "metadata-supplement.tex"
        additional.write_text("Supplement.\n", encoding="utf-8", newline="\n")
        cases = {
            "reason": ("   ", "Evidence is present."),
            "evidence": ("Reason is present.", "   "),
        }
        for label, (reason, evidence) in cases.items():
            with self.subTest(field=label):
                self.assert_scaffold_rejected_before_output(
                    self.base / f"blank-{label}-audit",
                    ValueError,
                    additional_source=[
                        (str(additional), reason, evidence)
                    ],
                )

    def test_scaffold_rejects_missing_fls_before_writing(self) -> None:
        self.assert_scaffold_rejected_before_output(
            self.base / "missing-fls-audit",
            FileNotFoundError,
            fls=self.base / "missing-paper.fls",
        )

    def test_external_finalization_target_is_not_overwritten(self) -> None:
        self.make_complete_audit()
        outside_record = self.base / "outside-finalization.json"
        outside_record.write_text(
            "outside sentinel\n",
            encoding="utf-8",
            newline="\n",
        )
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        manifest["finalization_record"] = proofcheck.relative_or_absolute(
            outside_record,
            self.audit,
        )
        write_json(manifest_path, manifest)

        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(
            io.StringIO()
        ):
            finalize_status = proofcheck.cmd_finalize(
                argparse.Namespace(root=self.audit)
            )
        with contextlib.redirect_stdout(io.StringIO()):
            status = proofcheck.cmd_status(
                argparse.Namespace(
                    root=self.audit,
                    format="json",
                    output=None,
                    force=False,
                )
            )
        freshness = proofcheck.check_finalization_freshness(self.audit)

        self.assertEqual(1, finalize_status)
        self.assertEqual(1, status)
        self.assertEqual("outside sentinel\n", outside_record.read_text(encoding="utf-8"))
        self.assertEqual("invalid", freshness["record_status"])
        self.assertEqual("unknown", freshness["freshness"])
        self.assertTrue(
            any("must resolve to" in reason for reason in freshness["stale_reasons"]),
            freshness,
        )

    def test_external_dependency_registry_cannot_be_finalized_or_stay_current(
        self,
    ) -> None:
        self.make_complete_audit()
        registry_path = (
            self.audit
            / "audit"
            / "03_dependencies"
            / "DEPENDENCY_REGISTRY.json"
        )
        outside_registry = self.base / "outside-dependency-registry.json"
        outside_registry.write_bytes(registry_path.read_bytes())
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        manifest["dependency_registry"] = "../outside-dependency-registry.json"
        write_json(manifest_path, manifest)

        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(
            io.StringIO()
        ):
            finalize_status = proofcheck.cmd_finalize(
                argparse.Namespace(root=self.audit)
            )
        changed = read_json(outside_registry)
        changed["review"]["evidence"] = [
            "This external evidence changed after finalization."
        ]
        write_json(outside_registry, changed)
        freshness = proofcheck.check_finalization_freshness(self.audit)

        self.assertEqual(1, finalize_status)
        self.assertFalse(freshness["usable_finalization"], freshness)
        self.assertTrue(
            any(
                "manifest.dependency_registry must resolve to" in error
                for error in freshness["current_gate_errors"]
            ),
            freshness,
        )

    def test_manifest_artifact_paths_require_exact_canonical_locations(self) -> None:
        self.make_complete_audit()
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        original = read_json(manifest_path)
        cases = {
            "inventory_file": "../outside-inventory.json",
            "dependency_registry": "../outside-dependencies.json",
            "method_interface_registry": "../outside-interfaces.json",
            "finalization_record": "../outside-finalization.json",
        }
        for field, value in cases.items():
            with self.subTest(field=field):
                changed = json.loads(json.dumps(original))
                changed[field] = value
                write_json(manifest_path, changed)
                errors, _ = proofcheck.check_audit_finalization(self.audit)
                self.assertTrue(
                    any(
                        f"manifest.{field} must resolve to" in error
                        for error in errors
                    ),
                    errors,
                )

        changed = json.loads(json.dumps(original))
        changed["dependency_registry"] = (
            "audit/03_dependencies/../dependencies/DEPENDENCY_REGISTRY.json"
        )
        write_json(manifest_path, changed)
        traversal_errors, _ = proofcheck.check_audit_finalization(self.audit)
        self.assertTrue(
            any(
                "manifest.dependency_registry must resolve to" in error
                for error in traversal_errors
            ),
            traversal_errors,
        )

        changed = json.loads(json.dumps(original))
        changed["inventory_file"] = original["inventory_file"].replace("/", "\\")
        write_json(manifest_path, changed)
        legacy_separator_errors, _ = proofcheck.check_audit_finalization(
            self.audit
        )
        self.assertFalse(
            any(
                "manifest.inventory_file" in error
                for error in legacy_separator_errors
            ),
            legacy_separator_errors,
        )

    def test_status_reports_foreign_and_malformed_artifact_paths_structurally(
        self,
    ) -> None:
        self.make_complete_audit()
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        original = read_json(manifest_path)
        cases = (
            "Z:\\foreign-audit\\theorem_inventory.json",
            {"file": "audit/01_index/theorem_inventory.json"},
        )
        for value in cases:
            with self.subTest(value=repr(value)):
                changed = json.loads(json.dumps(original))
                changed["inventory_file"] = value
                write_json(manifest_path, changed)
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    status = proofcheck.cmd_status(
                        argparse.Namespace(
                            root=self.audit,
                            format="json",
                            output=None,
                            force=False,
                            verbose=True,
                        )
                    )
                payload = json.loads(output.getvalue())
                self.assertEqual(1, status)
                self.assertEqual("malformed_or_stale", payload["workflow_state"])
                self.assertTrue(
                    any(
                        "manifest.inventory_file" in error
                        for error in payload["structural_errors"]
                    ),
                    payload,
                )

    def test_fixed_canonical_artifacts_reject_redirecting_components(self) -> None:
        self.make_complete_audit()
        targets = {
            "audit manifest": self.audit / "AUDIT_MANIFEST.json",
            "proof-unit inventory": (
                self.audit / "audit" / "01_index" / "theorem_inventory.json"
            ),
            "cross-reference audit JSON": (
                self.audit
                / "audit"
                / "01_index"
                / "cross_reference_audit.json"
            ),
            "cross-reference audit Markdown": (
                self.audit
                / "audit"
                / "01_index"
                / "cross_reference_audit.md"
            ),
            "dependency registry": (
                self.audit
                / "audit"
                / "03_dependencies"
                / "DEPENDENCY_REGISTRY.json"
            ),
            "method-interface registry": (
                self.audit
                / "audit"
                / "03_dependencies"
                / "METHOD_INTERFACE_REGISTRY.json"
            ),
            "issue log": (
                self.audit / "audit" / "06_reports" / "ISSUE_LOG.json"
            ),
            "issue summary": (
                self.audit / "audit" / "06_reports" / "ISSUE_SUMMARY.md"
            ),
            "progress record": self.audit / "PROGRESS.json",
            "final report": (
                self.audit / "audit" / "06_reports" / "FINAL_REPORT.md"
            ),
            "finalization record": (
                self.audit / "audit" / "06_reports" / "FINALIZATION.json"
            ),
        }
        original_redirect_kind = proofcheck.path_redirect_kind
        for label, target in targets.items():
            with self.subTest(label=label):
                def simulated_redirect_kind(path: Path) -> str | None:
                    if path == target:
                        return "junction"
                    return original_redirect_kind(path)

                with mock.patch.object(
                    proofcheck,
                    "path_redirect_kind",
                    side_effect=simulated_redirect_kind,
                ):
                    errors, _ = proofcheck.check_audit_finalization(self.audit)
                self.assertTrue(
                    any(
                        f"Canonical {label} location traverses a junction"
                        in error
                        for error in errors
                    ),
                    errors,
                )

    def test_canonical_artifacts_reject_redirecting_ancestor(self) -> None:
        self.make_complete_audit()
        redirected_ancestor = self.audit / "audit" / "03_dependencies"
        original_redirect_kind = proofcheck.path_redirect_kind

        def simulated_redirect_kind(path: Path) -> str | None:
            if path == redirected_ancestor:
                return "junction"
            return original_redirect_kind(path)

        with mock.patch.object(
            proofcheck,
            "path_redirect_kind",
            side_effect=simulated_redirect_kind,
        ):
            errors, _ = proofcheck.check_audit_finalization(self.audit)

        self.assertTrue(
            any(
                "Canonical dependency registry location traverses a junction"
                in error
                for error in errors
            ),
            errors,
        )
        self.assertTrue(
            any(
                "Canonical method-interface registry location traverses a junction"
                in error
                for error in errors
            ),
            errors,
        )

    def test_manifest_cannot_be_used_as_finalization_target(self) -> None:
        self.make_complete_audit()
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        manifest["finalization_record"] = "AUDIT_MANIFEST.json"
        write_json(manifest_path, manifest)
        sentinel = manifest_path.read_bytes()

        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(
            io.StringIO()
        ):
            finalize_status = proofcheck.cmd_finalize(
                argparse.Namespace(root=self.audit)
            )

        self.assertEqual(1, finalize_status)
        self.assertEqual(sentinel, manifest_path.read_bytes())
        self.assertTrue(
            (self.audit / "audit" / "06_reports" / "FINALIZATION.json").is_file()
        )

    def test_finalization_schema_rejects_bool_and_float_one(self) -> None:
        self.make_complete_audit()
        with contextlib.redirect_stdout(io.StringIO()):
            proofcheck.cmd_finalize(argparse.Namespace(root=self.audit))
        record_path = self.audit / "audit" / "06_reports" / "FINALIZATION.json"
        original = read_json(record_path)

        for schema_value in (True, 1.0):
            with self.subTest(schema_value=repr(schema_value)):
                changed = json.loads(json.dumps(original))
                changed["finalization_schema_version"] = schema_value
                write_json(record_path, changed)

                freshness = proofcheck.check_finalization_freshness(self.audit)

                self.assertEqual("invalid", freshness["record_status"])
                self.assertEqual("unknown", freshness["freshness"])
                self.assertTrue(
                    any(
                        "unsupported finalization_schema_version" in reason
                        for reason in freshness["stale_reasons"]
                    ),
                    freshness,
                )

    def test_schema_one_finalization_requires_generated_utc(self) -> None:
        self.make_complete_audit()
        with contextlib.redirect_stdout(io.StringIO()):
            proofcheck.cmd_finalize(argparse.Namespace(root=self.audit))
        record_path = self.audit / "audit" / "06_reports" / "FINALIZATION.json"
        record = read_json(record_path)
        record.pop("generated_utc")
        write_json(record_path, record)

        freshness = proofcheck.check_finalization_freshness(self.audit)

        self.assertEqual("invalid", freshness["record_status"])
        self.assertEqual("unknown", freshness["freshness"])
        self.assertTrue(
            any("requires generated_utc" in reason for reason in freshness["stale_reasons"]),
            freshness,
        )

    def test_parser_warning_affected_units_reject_duplicates(self) -> None:
        manifest_path = self.rebuild_with_parser_warning()
        manifest = read_json(manifest_path)
        manifest["parser_warning_reviews"][0].update(
            {
                "disposition": "confirmed_non_load_bearing",
                "affected_units": ["lem:main", "lem:main"],
                "evidence": "The warning was reviewed against the only proof unit.",
            }
        )
        write_json(manifest_path, manifest)

        errors, _ = proofcheck.check_audit_finalization(self.audit)

        self.assertTrue(
            any("affected_units contains duplicates" in error for error in errors),
            errors,
        )

    def test_parser_warning_malformed_affected_units_returns_errors(self) -> None:
        manifest_path = self.rebuild_with_parser_warning()
        original = read_json(manifest_path)
        malformed_values = (None, {"lem:main": True}, [{}])
        for value in malformed_values:
            with self.subTest(value=repr(value)):
                manifest = json.loads(json.dumps(original))
                manifest["parser_warning_reviews"][0].update(
                    {
                        "disposition": "confirmed_non_load_bearing",
                        "affected_units": value,
                        "evidence": (
                            "The warning was reviewed against the focused proof unit."
                        ),
                    }
                )
                write_json(manifest_path, manifest)
                try:
                    errors, _ = proofcheck.check_audit_finalization(self.audit)
                except (TypeError, ValueError) as exc:
                    self.fail(f"Malformed affected_units raised {type(exc).__name__}: {exc}")
                self.assertTrue(
                    any("affected_units" in error for error in errors),
                    errors,
                )

    def test_global_consistency_placeholder_evidence_fails(self) -> None:
        self.make_complete_audit()
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        manifest["completion"]["global_consistency_pass"]["checks"][0][
            "evidence"
        ] = "TBD"
        write_json(manifest_path, manifest)

        errors, _ = proofcheck.check_audit_finalization(self.audit)

        self.assertTrue(
            any(
                "global_consistency_pass" in error and "evidence" in error
                for error in errors
            ),
            errors,
        )

    def test_adversarial_pass_placeholder_evidence_fails(self) -> None:
        self.make_complete_audit()
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        manifest["completion"]["adversarial_pass"]["evidence"] = ["TBD"]
        write_json(manifest_path, manifest)

        errors, _ = proofcheck.check_audit_finalization(self.audit)

        self.assertTrue(
            any(
                "adversarial_pass.evidence" in error
                and "substantive" in error.lower()
                for error in errors
            ),
            errors,
        )

    def test_dependency_registry_review_binding_is_exact(self) -> None:
        self.make_complete_audit()
        registry_path = (
            self.audit
            / "audit"
            / "03_dependencies"
            / "DEPENDENCY_REGISTRY.json"
        )
        original = read_json(registry_path)
        cases = {
            "status": lambda item: item["review"].__setitem__(
                "status", "not_reviewed"
            ),
            "source_snapshot_sha256": lambda item: item["review"].__setitem__(
                "source_snapshot_sha256", "0" * 64
            ),
            "inventory_sha256": lambda item: item["review"].__setitem__(
                "inventory_sha256", "0" * 64
            ),
            "in_scope_units": lambda item: item["review"].__setitem__(
                "in_scope_units", []
            ),
            "evidence": lambda item: item["review"].__setitem__(
                "evidence", ["TBD"]
            ),
            "closure_contract_version": lambda item: item.__setitem__(
                "closure_contract_version", 999
            ),
        }
        for field, mutate in cases.items():
            with self.subTest(field=field):
                registry = json.loads(json.dumps(original))
                mutate(registry)
                write_json(registry_path, registry)
                errors, _ = proofcheck.check_audit_finalization(self.audit)
                self.assertTrue(
                    any(field in error for error in errors),
                    errors,
                )

    def test_progress_state_must_be_an_exact_partition(self) -> None:
        self.make_complete_audit()
        progress_path = self.audit / "PROGRESS.json"
        original = read_json(progress_path)
        cases = {
            "unknown completed unit": lambda item: item["completed_units"].append(
                "lem:ghost"
            ),
            "conditional and completed": lambda item: item[
                "conditional_units"
            ].append("lem:main"),
            "not started and completed": lambda item: item[
                "not_started_units"
            ].append("lem:main"),
            "stale source snapshot": lambda item: item.__setitem__(
                "source_snapshot_sha256", "0" * 64
            ),
        }
        for label, mutate in cases.items():
            with self.subTest(case=label):
                progress = json.loads(json.dumps(original))
                mutate(progress)
                write_json(progress_path, progress)
                errors, _ = proofcheck.check_audit_finalization(self.audit)
                self.assertTrue(
                    any("PROGRESS.json" in error for error in errors),
                    errors,
                )

    def test_progress_scaffold_pass_zero_blocks_finalization(self) -> None:
        self.make_complete_audit()
        progress_path = self.audit / "PROGRESS.json"
        progress = read_json(progress_path)
        progress["current_pass"] = 0
        write_json(progress_path, progress)

        errors, _ = proofcheck.check_audit_finalization(self.audit)

        self.assertTrue(
            any("current_pass" in error and "8" in error for error in errors),
            errors,
        )

    def test_full_audit_cannot_exclude_a_proof_unit(self) -> None:
        self.make_complete_audit()
        inventory_path = (
            self.audit / "audit" / "01_index" / "theorem_inventory.json"
        )
        inventory = read_json(inventory_path)
        excluded = json.loads(json.dumps(inventory["units"][0]))
        excluded["id"] = "lem:excluded"
        excluded["label"] = "lem:excluded"
        inventory["units"].append(excluded)
        write_json(inventory_path, inventory)

        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        manifest["audit_scope"]["depth"] = "full"
        manifest["audit_scope"]["excluded_units"] = [
            {
                "id": "lem:excluded",
                "reason": "The proof unit was intentionally excluded for this test.",
            }
        ]
        manifest["audit_scope"]["inventory_overrides"] = [
            {
                "unit_id": "lem:excluded",
                "kind": "manual_unit",
                "reason": "Rendered-source review identified a companion proof unit.",
                "evidence": "The statement and proof are visible in the rendered source.",
            }
        ]
        write_json(manifest_path, manifest)
        self.refresh_dependency_review()

        errors, _ = proofcheck.check_audit_finalization(self.audit)

        self.assertTrue(
            any("full" in error.lower() and "exclud" in error.lower() for error in errors),
            errors,
        )

    def test_final_report_rejects_duplicate_singleton_fields(self) -> None:
        self.make_complete_audit()
        report_path = self.audit / "audit" / "06_reports" / "FINAL_REPORT.md"
        report = report_path.read_text(encoding="utf-8").replace(
            "- Overall judgment:",
            "- Overall assessment code: defects_found\n- Overall judgment:",
        )
        report_path.write_text(report, encoding="utf-8", newline="\n")

        errors, _ = proofcheck.check_audit_finalization(self.audit)

        self.assertTrue(
            any("duplicate" in error.lower() and "Overall assessment code" in error for error in errors),
            errors,
        )

    def test_final_report_keeps_answer_fields_inside_summary(self) -> None:
        self.make_complete_audit()
        report_path = self.audit / "audit" / "06_reports" / "FINAL_REPORT.md"
        report = report_path.read_text(encoding="utf-8")
        main_reason = next(
            line for line in report.splitlines() if line.startswith("- Main reason:")
        )
        report = report.replace(main_reason + "\n", "", 1).replace(
            "## Scope and assurance\n",
            "## Scope and assurance\n\n" + main_reason + "\n",
            1,
        )
        report_path.write_text(report, encoding="utf-8", newline="\n")

        errors, _ = proofcheck.check_audit_finalization(self.audit)

        self.assertIn(
            "Final report Main reason must appear exactly once within ## Summary",
            errors,
        )

    def test_hidden_report_contract_cannot_satisfy_required_content(self) -> None:
        self.make_complete_audit()
        report_path = self.audit / "audit" / "06_reports" / "FINAL_REPORT.md"
        baseline = report_path.read_text(encoding="utf-8")
        wrappers = {
            "html-comment": f"<!--\n{baseline}\n-->\n",
            "fenced-code": f"```markdown\n{baseline}\n```\n",
            "hidden-div": f"<div hidden>\n{baseline}\n</div>\n",
            "pre-block": f"<pre>\n{baseline}\n</pre>\n",
        }
        for case, hidden_report in wrappers.items():
            with self.subTest(case=case):
                report_path.write_text(
                    hidden_report,
                    encoding="utf-8",
                    newline="\n",
                )

                errors, _ = proofcheck.check_audit_finalization(self.audit)

                if case in {"hidden-div", "pre-block"}:
                    self.assertTrue(
                        any(
                            "active raw HTML" in error
                            for error in errors
                        ),
                        errors,
                    )
                    continue
                self.assertTrue(
                    any(
                        "missing the Overall assessment code field" in error
                        for error in errors
                    ),
                    errors,
                )
                self.assertTrue(
                    any(
                        "must contain exactly these four H2 sections" in error
                        for error in errors
                    ),
                    errors,
                )
        report_path.write_text(baseline, encoding="utf-8", newline="\n")

    def test_markdown_visibility_lexer_distinguishes_literals_from_raw_blocks(
        self,
    ) -> None:
        self.make_complete_audit()
        report_path = self.audit / "audit" / "06_reports" / "FINAL_REPORT.md"
        baseline = report_path.read_text(encoding="utf-8")

        def add_scope_text(addition: str) -> str:
            return baseline.replace(
                "\n### Independent verification\n",
                addition + "\n### Independent verification\n",
                1,
            )

        safe_literals = {
            "fenced-unmatched-comment": "\n```markdown\n<!--\n```\n",
            "inline-details": "\nThe literal `<details>` tag is discussed.\n",
            "fenced-details": "\n```html\n<details>\n```\n",
            "math-less-than-a": "\nThe admissible range is $x<a>0$.\n",
        }
        for case, addition in safe_literals.items():
            with self.subTest(case=case):
                report_path.write_text(
                    add_scope_text(addition),
                    encoding="utf-8",
                    newline="\n",
                )

                errors, _ = proofcheck.check_audit_finalization(self.audit)

                self.assertEqual([], errors)

        active_raw_blocks = {
            "nested-hidden-div": (
                "\n<div>\n<div hidden>Hidden canonical content.</div>\n"
                "</div>\n"
            ),
            "visible-div": "\n<div>Visible block content.</div>\n",
            "pre": "\n<pre>Hidden canonical content.</pre>\n",
            "textarea": "\n<textarea>Hidden canonical content.</textarea>\n",
            "visibility-hidden": (
                "\n<span style=\"visibility:hidden\">"
                "Hidden canonical content.</span>\n"
            ),
        }
        for case, addition in active_raw_blocks.items():
            with self.subTest(case=case):
                report_path.write_text(
                    add_scope_text(addition),
                    encoding="utf-8",
                    newline="\n",
                )

                errors, _ = proofcheck.check_audit_finalization(self.audit)

                self.assertTrue(
                    any("active raw HTML" in error for error in errors),
                    errors,
                )
        report_path.write_text(baseline, encoding="utf-8", newline="\n")

    def test_indented_canonical_tables_cannot_satisfy_report_contract(
        self,
    ) -> None:
        self.make_complete_audit()
        report_path = self.audit / "audit" / "06_reports" / "FINAL_REPORT.md"
        report = report_path.read_text(encoding="utf-8")
        indented = "\n".join(
            f"    {line}" if line.startswith("|") else line
            for line in report.splitlines()
        ) + "\n"
        report_path.write_text(
            indented,
            encoding="utf-8",
            newline="\n",
        )

        errors, _ = proofcheck.check_audit_finalization(self.audit)

        self.assertTrue(
            any(
                "Results and impact disagrees" in error
                or "Independent verification disagrees" in error
                for error in errors
            ),
            errors,
        )

    def test_visible_report_contract_ignores_hidden_duplicates(self) -> None:
        self.make_complete_audit()
        report_path = self.audit / "audit" / "06_reports" / "FINAL_REPORT.md"
        baseline = report_path.read_text(encoding="utf-8")
        hidden_duplicates = (
            "\n<!--\n"
            "- Overall assessment code: defects_found\n"
            "## Results and impact\n"
            "-->\n"
            "```markdown\n"
            "- Overall assessment code: inconclusive\n"
            "## Results and impact\n"
            "```\n"
        )
        report_path.write_text(
            baseline + hidden_duplicates,
            encoding="utf-8",
            newline="\n",
        )

        errors, _ = proofcheck.check_audit_finalization(self.audit)

        self.assertEqual([], errors)

    def test_final_report_rejects_unqualified_correctness_overclaim(self) -> None:
        self.make_complete_audit()
        report_path = self.audit / "audit" / "06_reports" / "FINAL_REPORT.md"
        report = report_path.read_text(encoding="utf-8").replace(
            "No load-bearing defect found under the stated non-formal protocol.",
            "Every theorem and proof in the paper is mathematically correct.",
        )
        report_path.write_text(report, encoding="utf-8", newline="\n")

        errors, _ = proofcheck.check_audit_finalization(self.audit)

        self.assertTrue(
            any("overclaim" in error.lower() or "unsupported" in error.lower() for error in errors),
            errors,
        )

    def test_final_report_rejects_active_correctness_overclaim(self) -> None:
        self.make_complete_audit()
        report_path = self.audit / "audit" / "06_reports" / "FINAL_REPORT.md"
        report = report_path.read_text(encoding="utf-8").replace(
            "\n### Independent verification\n",
            "\nThe theorem and its proof are correct.\n\n"
            "### Independent verification\n",
            1,
        )
        report_path.write_text(
            report,
            encoding="utf-8",
            newline="\n",
        )

        errors, _ = proofcheck.check_audit_finalization(self.audit)

        self.assertTrue(
            any("correctness overclaim" in error for error in errors),
            errors,
        )

    def test_final_report_allows_quoted_disclaimed_and_exact_evidence_phrases(
        self,
    ) -> None:
        self.make_complete_audit()
        report_path = self.audit / "audit" / "06_reports" / "FINAL_REPORT.md"
        baseline = report_path.read_text(encoding="utf-8")
        additions = {
            "quoted": (
                "\n> Exact manuscript quotation: The theorem and its proof "
                "are correct.\n"
            ),
            "disclaimed": (
                "\nThis audit does not claim that the theorem and its proof "
                "are correct.\n"
            ),
            "exact-evidence": (
                "\n| Failure evidence |\n"
                "|---|\n"
                "| The theorem and its proof are correct. |\n"
            ),
            "unclear-whether": (
                "\nIt remains unclear whether the theorem and its proof "
                "are correct.\n"
            ),
            "unresolved-whether": (
                "\nWhether the lemma and its argument are valid remains "
                "unresolved.\n"
            ),
            "no-evidence": (
                "\nThere is no evidence that the proposition and its "
                "derivation are correct.\n"
            ),
        }
        for case, addition in additions.items():
            with self.subTest(case=case):
                report_path.write_text(
                    baseline.replace(
                        "\n### Independent verification\n",
                        addition + "\n### Independent verification\n",
                        1,
                    ),
                    encoding="utf-8",
                    newline="\n",
                )

                errors, _ = proofcheck.check_audit_finalization(self.audit)

                self.assertEqual([], errors)
        report_path.write_text(baseline, encoding="utf-8", newline="\n")

    def test_final_report_rejects_direct_correctness_claims_for_proof_objects(
        self,
    ) -> None:
        self.make_complete_audit()
        report_path = self.audit / "audit" / "06_reports" / "FINAL_REPORT.md"
        baseline = report_path.read_text(encoding="utf-8")
        claims = {
            "lemma": "The lemma is correct.",
            "proposition": "This proposition is valid.",
            "corollary": "The corollary is mathematically correct.",
            "result": "This result is valid.",
            "argument": "The argument is correct.",
            "derivation": "This derivation is valid.",
        }
        for case, claim in claims.items():
            with self.subTest(case=case):
                report_path.write_text(
                    baseline.replace(
                        "\n### Independent verification\n",
                        f"\n{claim}\n\n### Independent verification\n",
                        1,
                    ),
                    encoding="utf-8",
                    newline="\n",
                )

                errors, _ = proofcheck.check_audit_finalization(self.audit)

                self.assertTrue(
                    any(
                        "unsupported correctness overclaim" in error
                        for error in errors
                    ),
                    errors,
                )
        report_path.write_text(baseline, encoding="utf-8", newline="\n")

    def test_final_report_checked_scope_must_match_manifest(self) -> None:
        self.make_complete_audit()
        report_path = self.audit / "audit" / "06_reports" / "FINAL_REPORT.md"
        report = report_path.read_text(encoding="utf-8").replace(
            "- Checked scope: lem:main",
            "- Checked scope: none",
        )
        report_path.write_text(report, encoding="utf-8", newline="\n")

        errors, _ = proofcheck.check_audit_finalization(self.audit)

        self.assertTrue(
            any("Checked scope" in error for error in errors),
            errors,
        )

    def test_final_report_summary_is_first_and_substantive(self) -> None:
        self.make_complete_audit()
        report_path = self.audit / "audit" / "06_reports" / "FINAL_REPORT.md"
        report = report_path.read_text(encoding="utf-8")
        self.assertEqual(
            "## Summary",
            re.search(r"^## .*", report, re.MULTILINE).group(0),
        )
        main_reason = next(
            line
            for line in report.splitlines()
            if line.startswith("- Main reason:")
        )
        report_path.write_text(
            report.replace(main_reason, "- Main reason: none", 1),
            encoding="utf-8",
            newline="\n",
        )
        errors, _ = proofcheck.check_audit_finalization(self.audit)
        self.assertTrue(
            any("Main reason must be substantive" in error for error in errors),
            errors,
        )

    def test_final_report_independence_must_match_in_scope_ledger(self) -> None:
        self.make_complete_audit()
        report_path = self.audit / "audit" / "06_reports" / "FINAL_REPORT.md"
        report = report_path.read_text(encoding="utf-8").replace(
            "fresh_context_same_model",
            "none",
        )
        report_path.write_text(report, encoding="utf-8", newline="\n")

        errors, _ = proofcheck.check_audit_finalization(self.audit)

        self.assertTrue(
            any("Independent check levels" in error for error in errors),
            errors,
        )

    def test_independent_challenge_report_row_must_match_ledger(self) -> None:
        self.make_complete_audit()
        report_path = self.audit / "audit" / "06_reports" / "FINAL_REPORT.md"
        report = report_path.read_text(encoding="utf-8")
        heading = "### Independent verification"
        scope = proofcheck.report_section(
            report, "## Scope and assurance"
        ) or ""
        rows = proofcheck.markdown_table_rows(
            proofcheck.report_nested_section(scope, heading) or ""
        )
        changed_row = list(rows[2])
        changed_row[5] = "incorrect"
        report = proofcheck.replace_report_nested_section_text(
            report,
            heading,
            proofcheck.render_markdown_table(rows[0], [changed_row]),
        )
        report_path.write_text(report, encoding="utf-8", newline="\n")

        errors, _ = proofcheck.check_audit_finalization(self.audit)

        self.assertTrue(
            any(
                "verification" in error.lower()
                and ("row" in error.lower() or "ledger" in error.lower())
                for error in errors
            ),
            errors,
        )

    def test_final_report_rejects_fabricated_table_delimiter_row(self) -> None:
        self.make_complete_audit()
        report_path = self.audit / "audit" / "06_reports" / "FINAL_REPORT.md"
        report = report_path.read_text(encoding="utf-8")
        heading = "### Independent verification"
        scope = proofcheck.report_section(
            report, "## Scope and assurance"
        ) or ""
        section = proofcheck.report_nested_section(scope, heading) or ""
        lines = section.splitlines()
        header_index = next(
            index
            for index, line in enumerate(lines)
            if line.strip().startswith("| Result | Check status |")
        )
        width = lines[header_index].count("|") - 1
        lines[header_index + 1] = (
            "| " + " | ".join(["fabricated data"] * width) + " |"
        )
        report_path.write_text(
            proofcheck.replace_report_nested_section_text(
                report,
                heading,
                "\n".join(lines),
            ),
            encoding="utf-8",
            newline="\n",
        )

        errors, _ = proofcheck.check_audit_finalization(self.audit)

        self.assertTrue(
            any(
                "Independent verification" in error
                for error in errors
            ),
            errors,
        )

    def test_independent_verification_report_is_concise_and_reconciled(
        self,
    ) -> None:
        self.make_complete_audit()
        report_path = self.audit / "audit" / "06_reports" / "FINAL_REPORT.md"
        original_report = report_path.read_text(encoding="utf-8")
        scope = proofcheck.report_section(
            original_report, "## Scope and assurance"
        ) or ""
        section_rows = proofcheck.markdown_table_rows(
            proofcheck.report_nested_section(
                scope,
                "### Independent verification",
            )
            or ""
        )
        self.assertEqual(6, len(section_rows[0]))
        self.assertNotIn("Artifact", section_rows[0])
        self.assertNotIn("SHA256", " ".join(section_rows[0]))
        self.assertEqual("agreed", section_rows[2][5])

        changed_row = list(section_rows[2])
        changed_row[5] = "fabricated reconciliation"
        report_path.write_text(
            proofcheck.replace_report_nested_section_text(
                original_report,
                "### Independent verification",
                proofcheck.render_markdown_table(
                    section_rows[0],
                    [changed_row],
                ),
            ),
            encoding="utf-8",
            newline="\n",
        )
        errors, _ = proofcheck.check_audit_finalization(self.audit)
        self.assertTrue(
            any("Independent verification disagrees" in error for error in errors),
            errors,
        )

    def test_preliminary_dependency_steps_are_packet_only(self) -> None:
        ledger_path = self.make_complete_audit()
        self.install_internal_dependency(ledger_path)
        saved_ledger = read_json(ledger_path)
        registry_path = (
            self.audit
            / "audit"
            / "03_dependencies"
            / "DEPENDENCY_REGISTRY.json"
        )
        registry = read_json(registry_path)
        use = registry["internal_uses"][0]
        use["status"] = "unchecked"
        use["step_ids"] = []
        write_json(registry_path, registry)
        ledger_path.unlink()

        packet = proofcheck.build_context_packet(
            self.audit, "lem:main", "primary"
        )

        direct_use = packet["dependencies"]["direct_internal_uses"][0]
        self.assertEqual("unchecked", direct_use["status"])
        self.assertEqual([], direct_use["step_ids"])

        registry = read_json(registry_path)
        registry["internal_uses"][0]["status"] = "verified"
        write_json(registry_path, registry)
        with self.assertRaisesRegex(ValueError, "step_ids must not be empty"):
            proofcheck.build_context_packet(self.audit, "lem:main", "primary")

        registry["internal_uses"][0]["status"] = "unchecked"
        write_json(registry_path, registry)
        write_json(ledger_path, saved_ledger)
        with self.assertRaisesRegex(ValueError, "step_ids must not be empty"):
            proofcheck.build_context_packet(self.audit, "lem:main", "primary")

    def test_dependency_work_context_omits_only_output_mirrors(self) -> None:
        projected = proofcheck.packet_semantic_dependencies(
            {
                "direct_internal_uses": [
                    {
                        "use_id": "D001",
                        "step_ids": ["S002"],
                        "status": "verified",
                        "needed_form": "The exact prerequisite conclusion.",
                    }
                ],
                "downstream_internal_uses": [
                    {
                        "use_id": "D002",
                        "step_ids": ["S003"],
                        "status": "incorrect",
                        "issue_ids": ["I-001"],
                        "compatibility_check": "The use was checked.",
                        "compatibility_checks": [{"aspect": "domain"}],
                        "needed_form": "The exact downstream form.",
                    }
                ],
            }
        )

        direct = projected["direct_internal_uses"][0]
        downstream = projected["downstream_internal_uses"][0]
        self.assertNotIn("step_ids", direct)
        self.assertEqual("verified", direct["status"])
        self.assertEqual(
            "The exact prerequisite conclusion.", direct["needed_form"]
        )
        for field in (
            "step_ids",
            "status",
            "issue_ids",
            "compatibility_check",
            "compatibility_checks",
        ):
            self.assertNotIn(field, downstream)
        self.assertEqual("The exact downstream form.", downstream["needed_form"])

    def test_final_report_declared_deliverables_scalar_must_match_manifest(
        self,
    ) -> None:
        self.make_complete_audit()
        report_path = self.audit / "audit" / "06_reports" / "FINAL_REPORT.md"
        report_path.write_text(
            report_path.read_text(encoding="utf-8").replace(
                "- Declared external deliverables: none",
                "- Declared external deliverables: R001",
                1,
            ),
            encoding="utf-8",
            newline="\n",
        )

        errors, _ = proofcheck.check_audit_finalization(self.audit)

        self.assertTrue(
            any(
                "Declared external deliverables field disagrees" in error
                for error in errors
            ),
            errors,
        )

    def test_main_chain_row_must_match_ledger_components(self) -> None:
        self.make_complete_audit()
        report_path = self.audit / "audit" / "06_reports" / "FINAL_REPORT.md"
        report = report_path.read_text(encoding="utf-8").replace(
            "| lem:main | C001: x equals x | verified | valid | established |",
            "| lem:main | C001: x equals x | verified | invalid | established |",
            1,
        )
        report_path.write_text(report, encoding="utf-8", newline="\n")

        errors, _ = proofcheck.check_audit_finalization(self.audit)

        self.assertTrue(
            any("Results and impact disagrees" in error for error in errors),
            errors,
        )

    def test_complete_internal_dependency_closure_passes(self) -> None:
        ledger_path = self.make_complete_audit()
        self.install_internal_dependency(ledger_path)
        self.seal_schema5_challenge(ledger_path, read_json(ledger_path))

        errors, _ = proofcheck.check_audit_finalization(self.audit)

        self.assertEqual([], errors)

    def test_missing_internal_use_fails_closure(self) -> None:
        ledger_path = self.make_complete_audit()
        self.install_internal_dependency(ledger_path)
        registry_path = (
            self.audit
            / "audit"
            / "03_dependencies"
            / "DEPENDENCY_REGISTRY.json"
        )
        registry = read_json(registry_path)
        registry["internal_uses"] = []
        write_json(registry_path, registry)

        errors, _ = proofcheck.check_audit_finalization(self.audit)

        self.assertTrue(
            any("internal use" in error.lower() and "missing" in error.lower() for error in errors),
            errors,
        )

    def test_duplicate_internal_use_fails_closure(self) -> None:
        ledger_path = self.make_complete_audit()
        _, use = self.install_internal_dependency(ledger_path)
        registry_path = (
            self.audit
            / "audit"
            / "03_dependencies"
            / "DEPENDENCY_REGISTRY.json"
        )
        registry = read_json(registry_path)
        registry["internal_uses"].append(json.loads(json.dumps(use)))
        write_json(registry_path, registry)

        errors, _ = proofcheck.check_audit_finalization(self.audit)

        self.assertTrue(
            any("duplicate" in error.lower() and "internal" in error.lower() for error in errors),
            errors,
        )

    def test_dependency_use_ids_are_unique_across_the_whole_audit(
        self,
    ) -> None:
        ledger_path = self.make_complete_audit()
        _, use = self.install_internal_dependency(ledger_path)
        registry_path = (
            self.audit
            / "audit"
            / "03_dependencies"
            / "DEPENDENCY_REGISTRY.json"
        )
        registry = read_json(registry_path)
        cross_unit_duplicate = json.loads(json.dumps(use))
        cross_unit_duplicate["dependent_unit"] = "lem:prior"
        cross_unit_duplicate["dependency_id"] = "lem:main"
        cross_unit_duplicate["step_ids"] = ["S001"]
        registry["internal_uses"].append(cross_unit_duplicate)
        write_json(registry_path, registry)

        errors, _ = proofcheck.check_audit_finalization(self.audit)

        self.assertTrue(
            any(
                "Dependency use ID D001 is not audit-globally unique"
                in error
                for error in errors
            ),
            errors,
        )

    def test_stale_internal_use_fails_closure(self) -> None:
        ledger_path = self.make_complete_audit()
        _, use = self.install_internal_dependency(ledger_path)
        registry_path = (
            self.audit
            / "audit"
            / "03_dependencies"
            / "DEPENDENCY_REGISTRY.json"
        )
        registry = read_json(registry_path)
        stale = json.loads(json.dumps(use))
        stale["dependent_unit"] = "lem:prior"
        registry["internal_uses"].append(stale)
        write_json(registry_path, registry)

        errors, _ = proofcheck.check_audit_finalization(self.audit)

        self.assertTrue(
            any(
                "internal use" in error.lower()
                and ("stale" in error.lower() or "unused" in error.lower())
                for error in errors
            ),
            errors,
        )

    def test_internal_use_contract_hash_and_needed_form_are_exact(self) -> None:
        ledger_path = self.make_complete_audit()
        self.install_internal_dependency(ledger_path)
        registry_path = (
            self.audit
            / "audit"
            / "03_dependencies"
            / "DEPENDENCY_REGISTRY.json"
        )
        original = read_json(registry_path)
        cases = {
            "dependency_contract_sha256": lambda use: use.__setitem__(
                "dependency_contract_sha256", "0" * 64
            ),
            "needed_form": lambda use: use.__setitem__(
                "needed_form", "A stronger conclusion not used by the proof."
            ),
        }
        for field, mutate in cases.items():
            with self.subTest(field=field):
                registry = json.loads(json.dumps(original))
                mutate(registry["internal_uses"][0])
                write_json(registry_path, registry)
                errors, _ = proofcheck.check_audit_finalization(self.audit)
                self.assertTrue(
                    any(field in error for error in errors),
                    errors,
                )

    def test_internal_source_status_is_conclusion_aware(self) -> None:
        cases = (
            ("verified", "valid", "verified", "established", "verified"),
            (
                "conditionally_verified",
                "valid",
                "verified",
                "established",
                "conditional",
            ),
            ("verified", "invalid", "verified", "established", "gap"),
            ("verified", "invalid", "verified", "refuted", "incorrect"),
            ("verified", "gap", "verified", "not_established", "gap"),
            ("unclear", "unclear", "unclear", "unclear", "unclear"),
            (
                "not_checked",
                "not_checked",
                "not_checked",
                "not_assessed",
                "unchecked",
            ),
        )
        for contract, argument, closure, statement_status, expected in cases:
            with self.subTest(
                contract=contract,
                statement_status=statement_status,
            ):
                summary = {
                    "conclusion_results": [
                        {
                            "conclusion_id": "C001",
                            "contract_fidelity": contract,
                            "argument_status": argument,
                            "dependency_closure": closure,
                            "statement_status": statement_status,
                        }
                    ],
                }
                self.assertEqual(
                    expected,
                    proofcheck.internal_dependency_status(summary, "C001"),
                )

    def test_compatibility_status_must_propagate_to_internal_use(self) -> None:
        ledger_path = self.make_complete_audit()
        self.install_internal_dependency(ledger_path)
        registry_path = (
            self.audit
            / "audit"
            / "03_dependencies"
            / "DEPENDENCY_REGISTRY.json"
        )
        registry = read_json(registry_path)
        registry["internal_uses"][0]["compatibility_checks"][0][
            "status"
        ] = "conditional"
        write_json(registry_path, registry)

        errors, _ = proofcheck.check_audit_finalization(self.audit)

        self.assertTrue(
            any("compatibility" in error.lower() and "status" in error.lower() for error in errors),
            errors,
        )

    def test_dependency_closure_is_derived_from_effective_uses(self) -> None:
        ledger_path = self.make_complete_audit()
        self.install_internal_dependency(ledger_path)
        registry_path = (
            self.audit
            / "audit"
            / "03_dependencies"
            / "DEPENDENCY_REGISTRY.json"
        )
        registry = read_json(registry_path)
        use = registry["internal_uses"][0]
        use["compatibility_checks"][0]["status"] = "conditional"
        use["status"] = "conditional"
        write_json(registry_path, registry)

        errors, _ = proofcheck.check_audit_finalization(self.audit)

        self.assertTrue(
            any("dependency_closure" in error for error in errors),
            errors,
        )

    def test_complete_external_dependency_closure_passes(self) -> None:
        ledger_path = self.make_complete_audit()
        self.install_external_dependency(ledger_path)

        errors, _ = proofcheck.check_audit_finalization(self.audit)

        self.assertEqual([], errors)

    def test_duplicate_bibliography_keys_across_source_closure_fail(self) -> None:
        first = self.base / "references-a.bib"
        second = self.base / "references-b.bib"
        for path, title in ((first, "First identity"), (second, "Second identity")):
            path.write_text(
                "@article{smith,\n"
                "  author = {Smith, A.},\n"
                f"  title = {{{title}}},\n"
                "  year = {2026}\n"
                "}\n",
                encoding="utf-8",
                newline="\n",
            )
        self.audit = self.base / "duplicate-bibliography-audit"
        with contextlib.redirect_stdout(io.StringIO()):
            status = proofcheck.cmd_scaffold(
                argparse.Namespace(
                    paper=self.paper,
                    output=self.audit,
                    input_kind="latex",
                    publisher_pdf=None,
                    visual_review_status="not_started",
                    visual_review_notes="",
                    portable_sources=False,
                    additional_source=[
                        (
                            first,
                            "Bibliography source",
                            "The manuscript citation key is resolved from this file.",
                        ),
                        (
                            second,
                            "Bibliography source",
                            "The manuscript citation key is also defined in this file.",
                        ),
                    ],
                    fls=None,
                    project_root=self.base,
                )
            )
        self.assertEqual(0, status)
        ledger_path = self.make_complete_audit()
        self.install_external_dependency(
            ledger_path,
            reconcile_report_views=False,
        )

        errors, _ = proofcheck.check_audit_finalization(self.audit)

        self.assertTrue(
            any(
                "bibliography key 'smith' is ambiguous across the authoritative "
                "source snapshot" in error
                for error in errors
            ),
            errors,
        )

    def test_external_restatement_without_inline_citation_passes(self) -> None:
        self.make_external_restatement_audit()

        errors, _ = proofcheck.check_audit_finalization(self.audit)

        self.assertEqual([], errors)

    def test_external_restatement_with_bound_inline_citation_passes(self) -> None:
        self.make_external_restatement_audit(with_statement_citation=True)

        errors, _ = proofcheck.check_audit_finalization(self.audit)

        self.assertEqual([], errors)

    def test_external_restatement_citation_must_bind_to_designated_use(
        self,
    ) -> None:
        ledger_path = self.make_external_restatement_audit(
            with_statement_citation=True
        )
        ledger = read_json(ledger_path)
        ledger["review"]["citation_dispositions"] = [
            {
                "key": "smith",
                "disposition": "bibliographic_only",
                "evidence": (
                    "The citation was deliberately misclassified for this "
                    "negative control."
                ),
            }
        ]
        write_json(ledger_path, ledger)
        registry_path = (
            self.audit
            / "audit"
            / "03_dependencies"
            / "DEPENDENCY_REGISTRY.json"
        )
        registry = read_json(registry_path)
        registry["external_results"][0]["uses"][0]["citation_keys"] = []
        write_json(registry_path, registry)

        errors, _ = proofcheck.check_audit_finalization(self.audit)

        self.assertIn(
            "lem:main: external_restatement citation smith must map to its "
            "designated external dependency use D001",
            errors,
        )

    def test_external_restatement_requires_an_explicit_override(self) -> None:
        self.make_external_restatement_audit()
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        manifest["audit_scope"]["inventory_overrides"] = []
        write_json(manifest_path, manifest)

        errors, _ = proofcheck.check_audit_finalization(self.audit)

        self.assertTrue(
            any(
                "external_restatement ledger coverage requires an explicit "
                "reviewed inventory override" in error
                for error in errors
            ),
            errors,
        )

    def test_external_restatement_override_is_source_and_use_bound(self) -> None:
        self.make_external_restatement_audit()
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        original = read_json(manifest_path)
        cases = {
            "statement_sha256": (
                "0" * 64,
                "statement_sha256 is stale",
            ),
            "external_dependency_use_id": (
                "D002",
                "ledger external_dependency_use_id does not match",
            ),
        }
        for field, (value, expected) in cases.items():
            with self.subTest(field=field):
                manifest = json.loads(json.dumps(original))
                manifest["audit_scope"]["inventory_overrides"][0][field] = value
                write_json(manifest_path, manifest)

                errors, _ = proofcheck.check_audit_finalization(self.audit)

                self.assertTrue(
                    any(expected in error for error in errors),
                    errors,
                )

    def test_external_restatement_must_support_each_conclusion(self) -> None:
        ledger_path = self.make_external_restatement_audit()
        ledger = read_json(ledger_path)
        ledger["review"]["conclusion_results"][0][
            "dependency_use_ids"
        ] = []
        write_json(ledger_path, ledger)

        errors, _ = proofcheck.check_audit_finalization(self.audit)

        self.assertTrue(
            any(
                "external_restatement dependency is absent from the "
                "conclusion support closure" in error
                for error in errors
            ),
            errors,
        )

    def test_external_restatement_requires_its_missing_proof_warning_review(
        self,
    ) -> None:
        self.make_external_restatement_audit()
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        review = next(
            row
            for row in manifest["parser_warning_reviews"]
            if row["disposition"] == "external_restatement"
        )
        review["disposition"] = "confirmed_non_load_bearing"
        review["affected_units"] = []
        write_json(manifest_path, manifest)

        errors, _ = proofcheck.check_audit_finalization(self.audit)

        self.assertTrue(
            any(
                "External restatement overrides lack matching missing-proof "
                "warning reviews" in error
                for error in errors
            ),
            errors,
        )

    def test_external_result_requires_substantive_source_evidence(self) -> None:
        ledger_path = self.make_complete_audit()
        self.install_external_dependency(ledger_path)
        registry_path = (
            self.audit
            / "audit"
            / "03_dependencies"
            / "DEPENDENCY_REGISTRY.json"
        )
        registry = read_json(registry_path)
        external = registry["external_results"][0]
        external["source_evidence"][0]["locator"] = "TBD"
        contract_payload = {
            field: external[field]
            for field in (
                "source_identity",
                "version",
                "theorem_location",
                "exact_statement",
                "source_evidence",
            )
        }
        external["uses"][0]["dependency_contract_sha256"] = (
            proofcheck.canonical_sha256(contract_payload)
        )
        write_json(registry_path, registry)

        errors, _ = proofcheck.check_audit_finalization(self.audit)

        self.assertTrue(
            any("source_evidence" in error and "locator" in error for error in errors),
            errors,
        )

    def test_external_result_requires_locked_source_evidence(self) -> None:
        ledger_path = self.make_complete_audit()
        self.install_external_dependency(ledger_path)
        registry_path = (
            self.audit
            / "audit"
            / "03_dependencies"
            / "DEPENDENCY_REGISTRY.json"
        )
        registry = read_json(registry_path)
        registry["external_results"][0]["source_evidence"] = []
        write_json(registry_path, registry)

        errors, _ = proofcheck.check_audit_finalization(self.audit)

        self.assertTrue(
            any("source_evidence" in error for error in errors),
            errors,
        )

    def test_external_source_evidence_drift_fails(self) -> None:
        ledger_path = self.make_complete_audit()
        source_path, _ = self.install_external_dependency(ledger_path)
        source_path.write_text(
            "External Result 1\nFor every real x, x is nonnegative.\n",
            encoding="utf-8",
            newline="\n",
        )

        errors, _ = proofcheck.check_audit_finalization(self.audit)

        self.assertTrue(
            any("source drift" in error.lower() for error in errors),
            errors,
        )

    def test_external_bibtex_identity_binding_is_finalizable(self) -> None:
        ledger_path = self.make_complete_audit()
        self.install_external_dependency(ledger_path)

        errors, _ = proofcheck.check_audit_finalization(self.audit)

        self.assertEqual([], errors)

    def test_citation_binding_must_lock_the_authoritative_snapshot_entry(
        self,
    ) -> None:
        ledger_path = self.make_complete_audit()
        self.install_external_dependency(ledger_path)
        registry_path = (
            self.audit
            / "audit"
            / "03_dependencies"
            / "DEPENDENCY_REGISTRY.json"
        )
        original = read_json(registry_path)
        authoritative_binding = original["external_results"][0][
            "citation_bindings"
        ][0]

        foreign_path = self.base / "foreign-duplicate.bib"
        foreign_path.write_text(
            proofcheck.resolve_stored_path(
                authoritative_binding["file"], self.audit
            ).read_text(encoding="utf-8"),
            encoding="utf-8",
            newline="\n",
        )

        def with_binding(mutate) -> list[str]:
            registry = json.loads(json.dumps(original))
            external = registry["external_results"][0]
            binding = external["citation_bindings"][0]
            mutate(binding)
            external["uses"][0]["dependency_contract_sha256"] = (
                proofcheck.canonical_sha256(
                    proofcheck.external_result_contract(external)
                )
            )
            write_json(registry_path, registry)
            errors, _ = proofcheck.check_audit_finalization(self.audit)
            return errors

        def foreign_file(binding):
            binding["file"] = proofcheck.relative_or_absolute(
                foreign_path, self.audit
            )
            binding["sha256"] = proofcheck.source_span_sha256(
                foreign_path, binding["start_line"], binding["end_line"]
            )

        errors = with_binding(foreign_file)
        self.assertTrue(
            any(
                "must equal the unique authoritative snapshot entry" in error
                for error in errors
            ),
            errors,
        )

        def rendered_shadow(binding):
            binding["source_kind"] = "rendered_reference"

        errors = with_binding(rendered_shadow)
        self.assertTrue(
            any(
                "bind that entry instead of a rendered transcription" in error
                for error in errors
            ),
            errors,
        )

        registry = json.loads(json.dumps(original))
        external = registry["external_results"][0]
        external["uses"][0]["citation_keys"] = ["ghost"]
        binding = external["citation_bindings"][0]
        binding["key"] = "ghost"
        external["citation_binding_review"]["required_keys"] = ["ghost"]
        external["uses"][0]["dependency_contract_sha256"] = (
            proofcheck.canonical_sha256(
                proofcheck.external_result_contract(external)
            )
        )
        write_json(registry_path, registry)
        ledger = read_json(ledger_path)
        ledger["review"]["citation_dispositions"][0]["key"] = "ghost"
        write_json(ledger_path, ledger)
        errors, _ = proofcheck.check_audit_finalization(self.audit)
        self.assertTrue(
            any(
                "does not resolve to any authoritative entry" in error
                for error in errors
            ),
            errors,
        )

    def test_evidence_upgrade_path_reaches_closure_migration(self) -> None:
        ledger_path = self.make_complete_audit()
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        registry_path = (
            self.audit
            / "audit"
            / "03_dependencies"
            / "DEPENDENCY_REGISTRY.json"
        )
        manifest = read_json(manifest_path)
        manifest["protocol"]["evidence_contract_version"] = (
            proofcheck.PREVIOUS_EVIDENCE_CONTRACT_VERSION
        )
        manifest["protocol"]["closure_contract_version"] = (
            proofcheck.PREVIOUS_CLOSURE_CONTRACT_VERSION
        )
        write_json(manifest_path, manifest)
        registry = read_json(registry_path)
        registry["closure_contract_version"] = (
            proofcheck.PREVIOUS_CLOSURE_CONTRACT_VERSION
        )
        write_json(registry_path, registry)
        ledger = read_json(ledger_path)
        ledger["evidence_contract_version"] = (
            proofcheck.PREVIOUS_EVIDENCE_CONTRACT_VERSION
        )
        legacy_ledger_bytes = (
            (json.dumps(ledger, ensure_ascii=False, indent=2) + "\n")
            .replace("\n", "\r\n")
            .encode("utf-8")
        )
        ledger_path.write_bytes(legacy_ledger_bytes)

        view = proofcheck.status_protocol_view(read_json(manifest_path), [])
        self.assertEqual("evidence_upgrade_required", view["status"])
        self.assertIn("migrate-evidence", view["next_action"])
        version_probe = read_json(manifest_path)
        with mock.patch.object(
            proofcheck, "PREVIOUS_CLOSURE_CONTRACT_VERSION", 17
        ):
            version_probe["protocol"]["closure_contract_version"] = 17
            patched_view = proofcheck.status_protocol_view(version_probe, [])
        self.assertEqual("evidence_upgrade_required", patched_view["status"])
        self.assertIn("closure contract is still 17", patched_view["next_action"])

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            status = proofcheck.cmd_status(
                argparse.Namespace(
                    root=self.audit,
                    format="json",
                    output=None,
                    force=False,
                    verbose=False,
                )
            )
        status_payload = json.loads(stdout.getvalue())
        self.assertEqual(1, status)
        self.assertEqual(
            "evidence_upgrade_required", status_payload["workflow_state"]
        )
        self.assertIn(
            "migrate-evidence", status_payload["progress"]["next_action"]
        )
        self.assertEqual([], status_payload["progress"]["drift"])

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(
            io.StringIO()
        ):
            status = proofcheck.cmd_migrate_closure(
                argparse.Namespace(root=self.audit)
            )
        self.assertEqual(1, status)
        self.assertIn(
            "run migrate-evidence before migrate-closure", stdout.getvalue()
        )

        historical_path = (
            self.audit
            / "audit"
            / "04_local_checks"
            / "history"
            / "old.ledger.json"
        )
        historical_path.parent.mkdir(parents=True)
        historical = json.loads(json.dumps(ledger))
        historical["unit_id"] = "historical-only"
        historical["evidence_contract_version"] = (
            proofcheck.LEGACY_EVIDENCE_CONTRACT_VERSION
        )
        write_json(historical_path, historical)
        historical_bytes = historical_path.read_bytes()

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            status = proofcheck.cmd_migrate_evidence(
                argparse.Namespace(root=self.audit)
            )
        self.assertEqual(0, status)
        result = json.loads(stdout.getvalue())
        self.assertEqual("migrated", result["status"])
        self.assertGreaterEqual(result["restamped_artifacts"], 1)
        self.assertEqual(
            result["restamped_artifacts"],
            len(result["legacy_artifact_backups"]),
        )
        migrated_manifest = read_json(manifest_path)
        self.assertEqual(
            proofcheck.EVIDENCE_CONTRACT_VERSION,
            migrated_manifest["protocol"]["evidence_contract_version"],
        )
        self.assertEqual(
            proofcheck.PREVIOUS_CLOSURE_CONTRACT_VERSION,
            migrated_manifest["protocol"]["closure_contract_version"],
        )
        self.assertEqual(
            proofcheck.EVIDENCE_CONTRACT_VERSION,
            read_json(ledger_path)["evidence_contract_version"],
        )
        ledger_migration = next(
            row
            for row in migrated_manifest["evidence_migration"][
                "restamped_artifacts"
            ]
            if row["file"].endswith(ledger_path.name)
        )
        backup_path = proofcheck.resolve_stored_path(
            ledger_migration["legacy_backup"], self.audit
        )
        self.assertEqual(legacy_ledger_bytes, backup_path.read_bytes())
        self.assertEqual(historical_bytes, historical_path.read_bytes())
        self.assertEqual(
            proofcheck.PREVIOUS_EVIDENCE_CONTRACT_VERSION,
            migrated_manifest["evidence_migration"]["from_version"],
        )

        view = proofcheck.status_protocol_view(migrated_manifest, [])
        self.assertEqual("closure_upgrade_required", view["status"])

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            status = proofcheck.cmd_migrate_evidence(
                argparse.Namespace(root=self.audit)
            )
        self.assertEqual(0, status)
        self.assertEqual(
            "already_current", json.loads(stdout.getvalue())["status"]
        )

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            status = proofcheck.cmd_migrate_closure(
                argparse.Namespace(root=self.audit)
            )
        self.assertEqual(0, status)
        closure_result = json.loads(stdout.getvalue())
        self.assertEqual("migrated", closure_result["status"])
        migrated_manifest = read_json(manifest_path)
        self.assertEqual(
            proofcheck.protocol_identity(), migrated_manifest["protocol"]
        )
        self.assertEqual(
            proofcheck.CLOSURE_CONTRACT_VERSION,
            read_json(registry_path)["closure_contract_version"],
        )
        self.assertEqual(
            "current",
            proofcheck.status_protocol_view(migrated_manifest, [])["status"],
        )

        parser = proofcheck.build_parser()
        args = parser.parse_args(["migrate-evidence", "--root", "x"])
        self.assertIs(args.func, proofcheck.cmd_migrate_evidence)

    def test_evidence_upgrade_rejects_registry_closure_mismatch(self) -> None:
        ledger_path = self.make_complete_audit()
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        manifest["protocol"]["evidence_contract_version"] = (
            proofcheck.PREVIOUS_EVIDENCE_CONTRACT_VERSION
        )
        manifest["protocol"]["closure_contract_version"] = (
            proofcheck.PREVIOUS_CLOSURE_CONTRACT_VERSION
        )
        write_json(manifest_path, manifest)
        ledger = read_json(ledger_path)
        ledger["evidence_contract_version"] = (
            proofcheck.PREVIOUS_EVIDENCE_CONTRACT_VERSION
        )
        write_json(ledger_path, ledger)
        manifest_bytes = manifest_path.read_bytes()
        ledger_bytes = ledger_path.read_bytes()

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            status = proofcheck.cmd_status(
                argparse.Namespace(
                    root=self.audit,
                    format="json",
                    output=None,
                    force=False,
                    verbose=False,
                )
            )
        status_payload = json.loads(stdout.getvalue())
        self.assertEqual(1, status)
        self.assertEqual(
            "evidence_upgrade_required", status_payload["protocol"]["status"]
        )
        self.assertEqual("malformed_or_stale", status_payload["workflow_state"])
        self.assertTrue(
            any(
                "registry closure_contract_version" in error
                for error in status_payload["structural_errors"]
            ),
            status_payload,
        )

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(
            io.StringIO()
        ):
            status = proofcheck.cmd_migrate_evidence(
                argparse.Namespace(root=self.audit)
            )
        migration_payload = json.loads(stdout.getvalue())
        self.assertEqual(1, status)
        self.assertTrue(
            any(
                "registry closure_contract_version" in error
                for error in migration_payload["errors"]
            ),
            migration_payload,
        )
        self.assertEqual(manifest_bytes, manifest_path.read_bytes())
        self.assertEqual(ledger_bytes, ledger_path.read_bytes())
        self.assertFalse((ledger_path.parent / "history").exists())

    def test_migrate_evidence_rejects_incompatible_live_artifact_atomically(
        self,
    ) -> None:
        ledger_path = self.make_complete_audit()
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        manifest["protocol"]["evidence_contract_version"] = (
            proofcheck.PREVIOUS_EVIDENCE_CONTRACT_VERSION
        )
        write_json(manifest_path, manifest)
        ledger = read_json(ledger_path)
        ledger["evidence_contract_version"] = (
            proofcheck.LEGACY_EVIDENCE_CONTRACT_VERSION
        )
        write_json(ledger_path, ledger)
        manifest_bytes = manifest_path.read_bytes()
        ledger_bytes = ledger_path.read_bytes()
        history_directory = ledger_path.parent / "history"

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(
            io.StringIO()
        ):
            status = proofcheck.cmd_migrate_evidence(
                argparse.Namespace(root=self.audit)
            )
        payload = json.loads(stdout.getvalue())

        self.assertEqual(1, status)
        self.assertEqual("failed", payload["status"])
        self.assertTrue(
            any(
                "evidence_contract_version must be"
                in error
                for error in payload["errors"]
            ),
            payload,
        )
        self.assertEqual(manifest_bytes, manifest_path.read_bytes())
        self.assertEqual(ledger_bytes, ledger_path.read_bytes())
        self.assertFalse(history_directory.exists())

    def test_migrate_evidence_removes_new_backups_when_transaction_fails(
        self,
    ) -> None:
        ledger_path = self.make_complete_audit()
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        manifest["protocol"]["evidence_contract_version"] = (
            proofcheck.PREVIOUS_EVIDENCE_CONTRACT_VERSION
        )
        write_json(manifest_path, manifest)
        ledger = read_json(ledger_path)
        ledger["evidence_contract_version"] = (
            proofcheck.PREVIOUS_EVIDENCE_CONTRACT_VERSION
        )
        write_json(ledger_path, ledger)
        manifest_bytes = manifest_path.read_bytes()
        ledger_bytes = ledger_path.read_bytes()
        history_directory = ledger_path.parent / "history"

        with mock.patch.object(
            proofcheck,
            "transactional_write_texts",
            side_effect=OSError("injected evidence transaction failure"),
        ):
            with self.assertRaisesRegex(
                OSError, "injected evidence transaction failure"
            ):
                proofcheck.cmd_migrate_evidence(
                    argparse.Namespace(root=self.audit)
                )

        self.assertEqual(manifest_bytes, manifest_path.read_bytes())
        self.assertEqual(ledger_bytes, ledger_path.read_bytes())
        self.assertFalse(history_directory.exists())

    def test_migrate_evidence_rejects_interleaved_manifest_edit(self) -> None:
        ledger_path = self.make_complete_audit()
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        manifest["protocol"]["evidence_contract_version"] = (
            proofcheck.PREVIOUS_EVIDENCE_CONTRACT_VERSION
        )
        manifest["protocol"]["closure_contract_version"] = (
            proofcheck.PREVIOUS_CLOSURE_CONTRACT_VERSION
        )
        write_json(manifest_path, manifest)
        registry_path = (
            self.audit
            / "audit"
            / "03_dependencies"
            / "DEPENDENCY_REGISTRY.json"
        )
        registry = read_json(registry_path)
        registry["closure_contract_version"] = (
            proofcheck.PREVIOUS_CLOSURE_CONTRACT_VERSION
        )
        write_json(registry_path, registry)
        ledger = read_json(ledger_path)
        ledger["evidence_contract_version"] = (
            proofcheck.PREVIOUS_EVIDENCE_CONTRACT_VERSION
        )
        write_json(ledger_path, ledger)
        manifest_bytes = manifest_path.read_bytes()
        ledger_bytes = ledger_path.read_bytes()
        interleaved_bytes = manifest_bytes + b" "
        original_transaction = proofcheck.transactional_write_texts

        def edit_before_commit(writes: list, **kwargs: object) -> None:
            self.assertTrue(
                proofcheck.migration_update_lock_path(self.audit).is_file()
            )
            self.assertEqual(manifest_path, writes[-1][0])
            self.assertIn(ledger_path, [path for path, _ in writes[:-1]])
            manifest_path.write_bytes(interleaved_bytes)
            original_transaction(writes, **kwargs)

        with mock.patch.object(
            proofcheck,
            "transactional_write_texts",
            side_effect=edit_before_commit,
        ):
            with self.assertRaisesRegex(
                ValueError, "Transactional baseline changed before commit"
            ):
                proofcheck.cmd_migrate_evidence(
                    argparse.Namespace(root=self.audit)
                )

        self.assertEqual(interleaved_bytes, manifest_path.read_bytes())
        self.assertEqual(ledger_bytes, ledger_path.read_bytes())
        self.assertFalse((ledger_path.parent / "history").exists())
        self.assertFalse(
            proofcheck.migration_update_lock_path(self.audit).exists()
        )

    def test_migrate_evidence_rejects_interleaved_artifact_edit(self) -> None:
        ledger_path = self.make_complete_audit()
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        manifest["protocol"]["evidence_contract_version"] = (
            proofcheck.PREVIOUS_EVIDENCE_CONTRACT_VERSION
        )
        manifest["protocol"]["closure_contract_version"] = (
            proofcheck.PREVIOUS_CLOSURE_CONTRACT_VERSION
        )
        write_json(manifest_path, manifest)
        registry_path = (
            self.audit
            / "audit"
            / "03_dependencies"
            / "DEPENDENCY_REGISTRY.json"
        )
        registry = read_json(registry_path)
        registry["closure_contract_version"] = (
            proofcheck.PREVIOUS_CLOSURE_CONTRACT_VERSION
        )
        write_json(registry_path, registry)
        ledger = read_json(ledger_path)
        ledger["evidence_contract_version"] = (
            proofcheck.PREVIOUS_EVIDENCE_CONTRACT_VERSION
        )
        write_json(ledger_path, ledger)
        manifest_bytes = manifest_path.read_bytes()
        ledger_bytes = ledger_path.read_bytes()
        interleaved_bytes = ledger_bytes + b" "
        original_transaction = proofcheck.transactional_write_texts

        def edit_before_commit(writes: list, **kwargs: object) -> None:
            self.assertTrue(
                proofcheck.migration_update_lock_path(self.audit).is_file()
            )
            ledger_path.write_bytes(interleaved_bytes)
            original_transaction(writes, **kwargs)

        with mock.patch.object(
            proofcheck,
            "transactional_write_texts",
            side_effect=edit_before_commit,
        ):
            with self.assertRaisesRegex(
                ValueError, "Transactional baseline changed before commit"
            ):
                proofcheck.cmd_migrate_evidence(
                    argparse.Namespace(root=self.audit)
                )

        self.assertEqual(manifest_bytes, manifest_path.read_bytes())
        self.assertEqual(interleaved_bytes, ledger_path.read_bytes())
        self.assertFalse((ledger_path.parent / "history").exists())
        self.assertFalse(
            proofcheck.migration_update_lock_path(self.audit).exists()
        )

    def test_migrate_evidence_retains_recovery_after_committed_cleanup_failure(
        self,
    ) -> None:
        ledger_path = self.make_complete_audit()
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        manifest["protocol"]["evidence_contract_version"] = (
            proofcheck.PREVIOUS_EVIDENCE_CONTRACT_VERSION
        )
        manifest["protocol"]["closure_contract_version"] = (
            proofcheck.PREVIOUS_CLOSURE_CONTRACT_VERSION
        )
        write_json(manifest_path, manifest)
        registry_path = (
            self.audit
            / "audit"
            / "03_dependencies"
            / "DEPENDENCY_REGISTRY.json"
        )
        registry = read_json(registry_path)
        registry["closure_contract_version"] = (
            proofcheck.PREVIOUS_CLOSURE_CONTRACT_VERSION
        )
        write_json(registry_path, registry)
        ledger = read_json(ledger_path)
        ledger["evidence_contract_version"] = (
            proofcheck.PREVIOUS_EVIDENCE_CONTRACT_VERSION
        )
        write_json(ledger_path, ledger)
        legacy_ledger_bytes = ledger_path.read_bytes()
        backup_path = ledger_path.parent / "history" / (
            f"{ledger_path.name}.evidence-"
            f"{proofcheck.PREVIOUS_EVIDENCE_CONTRACT_VERSION}."
            f"{proofcheck.sha256_file(ledger_path)}.json"
        )
        original_unlink = Path.unlink

        def fail_manifest_recovery_cleanup(
            path: Path, *args: object, **kwargs: object
        ) -> None:
            if (
                path.parent == manifest_path.parent
                and path.name.startswith(".AUDIT_MANIFEST.json.")
                and path.name.endswith(".proofcheck.tmp")
            ):
                raise OSError("injected committed cleanup failure")
            original_unlink(path, *args, **kwargs)

        with mock.patch.object(
            Path,
            "unlink",
            autospec=True,
            side_effect=fail_manifest_recovery_cleanup,
        ):
            with self.assertRaisesRegex(
                proofcheck.MigrationRecoveryRequired,
                "Live writes were committed",
            ):
                proofcheck.cmd_migrate_evidence(
                    argparse.Namespace(root=self.audit)
                )

        migrated_manifest = read_json(manifest_path)
        self.assertEqual(
            proofcheck.EVIDENCE_CONTRACT_VERSION,
            migrated_manifest["protocol"]["evidence_contract_version"],
        )
        self.assertEqual(
            proofcheck.EVIDENCE_CONTRACT_VERSION,
            read_json(ledger_path)["evidence_contract_version"],
        )
        self.assertEqual(legacy_ledger_bytes, backup_path.read_bytes())
        self.assertTrue(
            list(manifest_path.parent.glob(".AUDIT_MANIFEST.json.*.proofcheck.tmp"))
        )
        self.assertTrue(
            proofcheck.migration_update_lock_path(self.audit).is_file()
        )

    def test_migrate_evidence_reuses_exact_racing_backup(self) -> None:
        ledger_path = self.make_complete_audit()
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        manifest["protocol"]["evidence_contract_version"] = (
            proofcheck.PREVIOUS_EVIDENCE_CONTRACT_VERSION
        )
        write_json(manifest_path, manifest)
        ledger = read_json(ledger_path)
        ledger["evidence_contract_version"] = (
            proofcheck.PREVIOUS_EVIDENCE_CONTRACT_VERSION
        )
        write_json(ledger_path, ledger)
        legacy_bytes = ledger_path.read_bytes()
        original_publish = proofcheck.publish_no_overwrite

        def publish_after_exact_retry(
            temporary: Path, destination: Path, description: str
        ) -> str:
            destination.write_bytes(temporary.read_bytes())
            return original_publish(temporary, destination, description)

        stdout = io.StringIO()
        with mock.patch.object(
            proofcheck,
            "publish_no_overwrite",
            side_effect=publish_after_exact_retry,
        ), contextlib.redirect_stdout(stdout):
            status = proofcheck.cmd_migrate_evidence(
                argparse.Namespace(root=self.audit)
            )
        payload = json.loads(stdout.getvalue())

        self.assertEqual(0, status)
        self.assertEqual("migrated", payload["status"])
        self.assertEqual(1, len(payload["legacy_artifact_backups"]))
        backup_path = Path(payload["legacy_artifact_backups"][0])
        self.assertEqual(legacy_bytes, backup_path.read_bytes())
        self.assertEqual(
            proofcheck.EVIDENCE_CONTRACT_VERSION,
            read_json(ledger_path)["evidence_contract_version"],
        )

    def test_migrate_evidence_already_current_still_validates_state(
        self,
    ) -> None:
        ledger_path = self.make_complete_audit()
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        original_manifest = read_json(manifest_path)
        original_ledger = read_json(ledger_path)

        def run_migration() -> tuple[int, dict]:
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(
                io.StringIO()
            ):
                status = proofcheck.cmd_migrate_evidence(
                    argparse.Namespace(root=self.audit)
                )
            return status, json.loads(stdout.getvalue())

        invalid_closure = json.loads(json.dumps(original_manifest))
        invalid_closure["protocol"]["closure_contract_version"] = 999
        write_json(manifest_path, invalid_closure)
        status, payload = run_migration()
        self.assertEqual(1, status)
        self.assertTrue(
            any("closure_contract_version" in error for error in payload["errors"]),
            payload,
        )

        write_json(manifest_path, original_manifest)
        write_json(
            ledger_path,
            {
                "schema_version": proofcheck.SCHEMA_VERSION,
                "evidence_contract_version": (
                    proofcheck.EVIDENCE_CONTRACT_VERSION
                ),
                "unit_id": "lem:main",
            },
        )
        status, payload = run_migration()
        self.assertEqual(1, status)
        self.assertTrue(
            any(
                "Missing source object" in error
                for error in payload["errors"]
            ),
            payload,
        )

        write_json(ledger_path, original_ledger)
        self.paper.write_text(
            self.paper.read_text(encoding="utf-8") + "% source drift\n",
            encoding="utf-8",
            newline="\n",
        )
        status, payload = run_migration()
        self.assertEqual(1, status)
        self.assertTrue(
            any("source" in error.lower() for error in payload["errors"]),
            payload,
        )
        self.assertFalse((ledger_path.parent / "history").exists())

    def test_migration_lock_blocks_status_and_finalization_reads(self) -> None:
        self.make_complete_audit()
        lock, payload = proofcheck.acquire_migration_update_lock(
            self.audit, "test-migration"
        )
        try:
            with mock.patch.object(
                proofcheck, "audit_internal_redirect_errors"
            ) as status_reader:
                with self.assertRaisesRegex(
                    ValueError, "audit migration is in progress"
                ):
                    proofcheck.cmd_status(
                        argparse.Namespace(
                            root=self.audit,
                            format="json",
                            output=None,
                            force=False,
                            verbose=False,
                        )
                    )
                status_reader.assert_not_called()

            with mock.patch.object(
                proofcheck, "_check_audit_finalization"
            ) as finalization_reader:
                errors, result = proofcheck.check_audit_finalization(
                    self.audit
                )
                finalization_reader.assert_not_called()
            self.assertTrue(
                any("audit migration is in progress" in error for error in errors),
                errors,
            )
            self.assertEqual(errors[0], result["read_error"])

            with mock.patch.object(
                proofcheck, "sync_workflow_views"
            ) as view_writer:
                with self.assertRaisesRegex(
                    ValueError, "audit migration is in progress"
                ):
                    proofcheck.cmd_finalize(argparse.Namespace(root=self.audit))
                view_writer.assert_not_called()

            with mock.patch.object(
                proofcheck, "load_workflow_records"
            ) as packet_reader:
                with self.assertRaisesRegex(
                    ValueError, "audit migration is in progress"
                ):
                    proofcheck.build_context_packet(
                        self.audit, "lem:main", "primary"
                    )
                packet_reader.assert_not_called()

            with self.assertRaisesRegex(
                ValueError, "audit migration is in progress"
            ):
                proofcheck.sync_workflow_views(self.audit)
            with self.assertRaisesRegex(
                ValueError, "audit migration is in progress"
            ):
                proofcheck.cmd_checkpoint(
                    argparse.Namespace(root=self.audit)
                )
            with self.assertRaisesRegex(
                ValueError, "audit migration is in progress"
            ):
                proofcheck.cmd_revalidate_protocol(
                    argparse.Namespace(root=self.audit)
                )
            with self.assertRaisesRegex(
                ValueError, "audit migration is in progress"
            ):
                proofcheck.calibration_audit_binding(self.audit)

            skeleton_path = (
                self.audit
                / "audit"
                / "04_local_checks"
                / "locked.skeleton.json"
            )
            with self.assertRaisesRegex(
                ValueError, "audit migration is in progress"
            ):
                proofcheck.cmd_extract(
                    argparse.Namespace(
                        file=self.paper,
                        output=skeleton_path,
                    )
                )
            self.assertFalse(skeleton_path.exists())
        finally:
            proofcheck.release_migration_update_lock(lock, payload)

        self.assertFalse(lock.exists())

    def test_status_does_not_mask_fatal_ledger_as_evidence_upgrade(
        self,
    ) -> None:
        ledger_path = self.make_complete_audit()
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        manifest["protocol"]["evidence_contract_version"] = (
            proofcheck.PREVIOUS_EVIDENCE_CONTRACT_VERSION
        )
        write_json(manifest_path, manifest)
        ledger_path.write_text("{", encoding="utf-8", newline="\n")

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            status = proofcheck.cmd_status(
                argparse.Namespace(
                    root=self.audit,
                    format="json",
                    output=None,
                    force=False,
                    verbose=False,
                )
            )
        payload = json.loads(stdout.getvalue())

        self.assertEqual(1, status)
        self.assertEqual(
            "evidence_upgrade_required", payload["protocol"]["status"]
        )
        self.assertEqual("malformed_or_stale", payload["workflow_state"])
        self.assertGreater(payload["ledger_errors"], 0)

    def test_external_citation_binding_is_required_and_unique(self) -> None:
        ledger_path = self.make_complete_audit()
        self.install_external_dependency(ledger_path)
        registry_path = (
            self.audit
            / "audit"
            / "03_dependencies"
            / "DEPENDENCY_REGISTRY.json"
        )
        original = read_json(registry_path)
        cases = {
            "missing": [],
            "duplicate": [
                original["external_results"][0]["citation_bindings"][0],
                original["external_results"][0]["citation_bindings"][0],
            ],
        }
        for name, bindings in cases.items():
            with self.subTest(name=name):
                registry = json.loads(json.dumps(original))
                external = registry["external_results"][0]
                external["citation_bindings"] = bindings
                external["uses"][0]["dependency_contract_sha256"] = (
                    proofcheck.canonical_sha256(
                        proofcheck.external_result_contract(external)
                    )
                )
                write_json(registry_path, registry)

                errors, _ = proofcheck.check_audit_finalization(self.audit)

                self.assertTrue(
                    any("citation_bindings" in error for error in errors),
                    errors,
                )

    def test_external_citation_binding_rejects_wrong_or_changed_key(self) -> None:
        ledger_path = self.make_complete_audit()
        self.install_external_dependency(ledger_path)
        registry_path = (
            self.audit
            / "audit"
            / "03_dependencies"
            / "DEPENDENCY_REGISTRY.json"
        )
        original = read_json(registry_path)
        binding = original["external_results"][0]["citation_bindings"][0]
        bibliography_path = proofcheck.resolve_stored_path(
            binding["file"], self.audit
        )

        wrong = json.loads(json.dumps(original))
        wrong_external = wrong["external_results"][0]
        wrong_external["citation_bindings"][0]["key"] = "wrong"
        wrong_external["uses"][0]["dependency_contract_sha256"] = (
            proofcheck.canonical_sha256(
                proofcheck.external_result_contract(wrong_external)
            )
        )
        write_json(registry_path, wrong)
        wrong_errors, _ = proofcheck.check_audit_finalization(self.audit)
        self.assertTrue(
            any(
                "expected ['smith'], found ['wrong']" in error
                or "bibliography key 'wrong'" in error
                for error in wrong_errors
            ),
            wrong_errors,
        )

        changed = json.loads(json.dumps(original))
        bibliography_path.write_text(
            "@article{smyth,\n"
            "  author = {Smith, A.},\n"
            "  title = {Reflexivity of equality},\n"
            "  year = {2026}\n"
            "}\n",
            encoding="utf-8",
            newline="\n",
        )
        changed_external = changed["external_results"][0]
        changed_binding = changed_external["citation_bindings"][0]
        changed_binding["sha256"] = proofcheck.source_span_sha256(
            bibliography_path, 1, 5
        )
        changed_external["uses"][0]["dependency_contract_sha256"] = (
            proofcheck.canonical_sha256(
                proofcheck.external_result_contract(changed_external)
            )
        )
        write_json(registry_path, changed)
        changed_errors, _ = proofcheck.check_audit_finalization(self.audit)
        self.assertTrue(
            any(
                "bibliography key 'smith' must resolve exactly once; found 0"
                in error
                for error in changed_errors
            ),
            changed_errors,
        )

    def test_external_citation_binding_rejects_duplicate_bibtex_key(self) -> None:
        ledger_path = self.make_complete_audit()
        self.install_external_dependency(ledger_path)
        registry = read_json(
            self.audit
            / "audit"
            / "03_dependencies"
            / "DEPENDENCY_REGISTRY.json"
        )
        binding = registry["external_results"][0]["citation_bindings"][0]
        bibliography_path = proofcheck.resolve_stored_path(
            binding["file"], self.audit
        )
        with bibliography_path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(
                "@book{smith,\n"
                "  author = {Smith, B.},\n"
                "  title = {Another source},\n"
                "  year = {2025}\n"
                "}\n"
            )

        errors, _ = proofcheck.check_audit_finalization(self.audit)

        self.assertTrue(
            any(
                "bibliography key 'smith' must resolve exactly once; found 2"
                in error
                for error in errors
            ),
            errors,
        )

    def test_external_citation_binding_ignores_commented_bibtex_entry(self) -> None:
        ledger_path = self.make_complete_audit()
        self.install_external_dependency(ledger_path)
        registry = read_json(
            self.audit
            / "audit"
            / "03_dependencies"
            / "DEPENDENCY_REGISTRY.json"
        )
        binding = registry["external_results"][0]["citation_bindings"][0]
        bibliography_path = proofcheck.resolve_stored_path(
            binding["file"], self.audit
        )
        with bibliography_path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write("% @article{smith, title={Commented duplicate}}\n")
        self.add_snapshot_source(bibliography_path, ledger_path)

        errors, _ = proofcheck.check_audit_finalization(self.audit)

        self.assertEqual([], errors)

    def test_bibtex_parser_ignores_literal_escaped_braces(self) -> None:
        bibliography_path = self.base / "escaped-braces.bib"
        bibliography_path.write_text(
            "@article{smith,\n"
            "  title = {Literal \\{left\\} braces},\n"
            "  year = {2026}\n"
            "}\n",
            encoding="utf-8",
        )

        entries = proofcheck.bibtex_entry_spans(bibliography_path)

        self.assertEqual(
            [("smith", 1, 4)],
            [(entry["key"], entry["start_line"], entry["end_line"]) for entry in entries],
        )

    def test_bibtex_parser_preserves_crlf_offsets_across_entries(self) -> None:
        bibliography_path = self.base / "crlf-entries.bib"
        text = (
            "@article{first,\r\n"
            "  title = {First entry},\r\n"
            "  year = {2025}\r\n"
            "}\r\n"
            "% masked comment between entries\r\n"
            "\r\n"
            "@book{second,\r\n"
            "  title = {Second entry},\r\n"
            "  year = {2026}\r\n"
            "}\r\n"
        )
        bibliography_path.write_bytes(text.encode("utf-8"))

        with mock.patch.object(proofcheck, "read_text", return_value=text):
            entries = proofcheck.bibtex_entry_spans(bibliography_path)

        self.assertEqual(
            [("first", 1, 4), ("second", 7, 10)],
            [
                (entry["key"], entry["start_line"], entry["end_line"])
                for entry in entries
            ],
        )
        self.assertEqual(
            [
                "@article{first,\r\n"
                "  title = {First entry},\r\n"
                "  year = {2025}\r\n"
                "}",
                "@book{second,\r\n"
                "  title = {Second entry},\r\n"
                "  year = {2026}\r\n"
                "}",
            ],
            [
                text[entry["start_offset"] : entry["end_offset"] + 1]
                for entry in entries
            ],
        )

    def test_bibitem_parser_indexes_only_thebibliography_items(self) -> None:
        bibliography_path = self.base / "scoped-bibitems.bbl"
        bibliography_path.write_text(
            "\\bibitem{outside-before} Not a bibliography item.\n"
            "\\begin{thebibliography}{1}\n"
            "\\bibitem{inside} A. Smith. Reflexivity of equality. 2026.\n"
            "\\end{thebibliography}\n"
            "\\bibitem{outside-after} Also not a bibliography item.\n",
            encoding="utf-8",
            newline="\n",
        )

        entries = proofcheck.bibitem_entry_spans(bibliography_path)

        self.assertEqual(
            [("inside", 3, 3)],
            [
                (entry["key"], entry["start_line"], entry["end_line"])
                for entry in entries
            ],
        )
        malformed_path = self.base / "malformed-bibitem.bbl"
        malformed_path.write_text(
            "\\begin{thebibliography}{1}\n"
            "\\bibitem missing-braces\n"
            "\\end{thebibliography}\n",
            encoding="utf-8",
            newline="\n",
        )
        with self.assertRaisesRegex(ValueError, "malformed bibitem command"):
            proofcheck.bibitem_entry_spans(malformed_path)

    def test_source_bibliography_index_fails_closed_on_parse_and_read_errors(
        self,
    ) -> None:
        self.make_complete_audit()
        malformed = self.base / "malformed.bib"
        malformed.write_text(
            "@article{smith,\n  title = {Unterminated entry}\n",
            encoding="utf-8",
            newline="\n",
        )
        malformed_header = self.base / "malformed-header.bib"
        malformed_header.write_text(
            "@article{smith\n  title = {Missing key delimiter}\n}\n",
            encoding="utf-8",
            newline="\n",
        )
        unreadable = self.base / "unreadable.bib"
        unreadable.write_bytes(b"\xff\xfe\x00")
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        for path in (malformed, malformed_header, unreadable):
            manifest["source_snapshot"]["files"].append(
                {
                    "file": proofcheck.relative_or_absolute(path, self.audit),
                    "sha256": proofcheck.sha256_file(path),
                }
            )
        manifest["source_snapshot"]["sha256"] = proofcheck.canonical_sha256(
            manifest["source_snapshot"]["files"]
        )
        write_json(manifest_path, manifest)
        errors: list[str] = []

        proofcheck.source_snapshot_bibliography_key_locations(self.audit, errors)

        self.assertTrue(
            any("unterminated BibTeX directive" in error for error in errors),
            errors,
        )
        self.assertTrue(
            any("malformed BibTeX entry header" in error for error in errors),
            errors,
        )
        self.assertTrue(
            any("Unreadable UTF-8 text artifact" in error for error in errors),
            errors,
        )

    def test_rendered_reference_requires_machine_checked_snapshot_mapping(
        self,
    ) -> None:
        ledger_path = self.make_complete_audit()
        self.install_external_dependency(ledger_path)
        registry_path = (
            self.audit
            / "audit"
            / "03_dependencies"
            / "DEPENDENCY_REGISTRY.json"
        )
        bibliography_path = self.base / "external-reflexivity.bib"
        bibliography_path.write_text(
            "@article{other,\n"
            "  author = {Other, B.},\n"
            "  title = {A different result},\n"
            "  year = {2026}\n"
            "}\n",
            encoding="utf-8",
            newline="\n",
        )
        self.add_snapshot_source(bibliography_path, ledger_path)

        rendered_path = self.base / "rendered-references.txt"
        rendered_path.write_text(
            "[1] A. Smith. Reflexivity of equality. 2026.\n",
            encoding="utf-8",
            newline="\n",
        )
        unrelated_path = self.base / "unrelated-rendered-reference.txt"
        unrelated_path.write_text(
            "[2] B. Other. A different result. 2026.\n",
            encoding="utf-8",
            newline="\n",
        )
        self.add_snapshot_source(rendered_path, ledger_path)
        self.add_snapshot_source(unrelated_path, ledger_path)

        rendered_file = proofcheck.relative_or_absolute(rendered_path, self.audit)
        rendered_sha = proofcheck.source_span_sha256(rendered_path, 1, 1)
        mapping_path = self.base / "rendered-reference-map.json"
        mapping_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "citation_key": "smith",
                    "rendered_reference": {
                        "file": rendered_file,
                        "start_line": 1,
                        "end_line": 1,
                        "sha256": rendered_sha,
                    },
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
            newline="\n",
        )
        self.add_snapshot_source(mapping_path, ledger_path)

        manifest = read_json(self.audit / "AUDIT_MANIFEST.json")
        registry = read_json(registry_path)
        external = registry["external_results"][0]
        binding = external["citation_bindings"][0]
        binding.update(
            {
                "source_kind": "rendered_reference",
                "file": rendered_file,
                "start_line": 1,
                "end_line": 1,
                "sha256": rendered_sha,
                "locator": "Rendered reference list item 1",
                "rendered_provenance": {
                    "authority": "source_snapshot",
                    "source_snapshot_sha256": manifest["source_snapshot"]["sha256"],
                    "source_file_sha256": proofcheck.sha256_file(rendered_path),
                    "key_mapping": {
                        "file": proofcheck.relative_or_absolute(
                            mapping_path, self.audit
                        ),
                        "start_line": 1,
                        "end_line": 1,
                        "sha256": proofcheck.source_span_sha256(
                            mapping_path, 1, 1
                        ),
                        "role": "rendered_reference_key_mapping",
                    },
                },
            }
        )
        external["citation_binding_review"]["evidence"] = (
            "The authoritative snapshot mapping binds citation key smith to "
            "the exact rendered reference span for the external result."
        )
        external["uses"][0]["dependency_contract_sha256"] = (
            proofcheck.canonical_sha256(
                proofcheck.external_result_contract(external)
            )
        )

        errors: list[str] = []
        proofcheck.validate_external_result_catalog(registry, self.audit, errors)
        self.assertEqual([], errors)

        missing_mapping = json.loads(json.dumps(registry))
        del missing_mapping["external_results"][0]["citation_bindings"][0][
            "rendered_provenance"
        ]["key_mapping"]
        missing_errors: list[str] = []
        proofcheck.validate_external_result_catalog(
            missing_mapping, self.audit, missing_errors
        )
        self.assertTrue(
            any("key_mapping" in error for error in missing_errors),
            missing_errors,
        )

        unrelated = json.loads(json.dumps(registry))
        unrelated_binding = unrelated["external_results"][0]["citation_bindings"][0]
        unrelated_binding.update(
            {
                "file": proofcheck.relative_or_absolute(
                    unrelated_path, self.audit
                ),
                "sha256": proofcheck.source_span_sha256(
                    unrelated_path, 1, 1
                ),
            }
        )
        unrelated_binding["rendered_provenance"]["source_file_sha256"] = (
            proofcheck.sha256_file(unrelated_path)
        )
        unrelated_errors: list[str] = []
        proofcheck.validate_external_result_catalog(
            unrelated, self.audit, unrelated_errors
        )
        self.assertTrue(
            any(
                "does not map to this rendered_reference span" in error
                for error in unrelated_errors
            ),
            unrelated_errors,
        )

    def test_external_citation_binding_is_tied_to_result_identity(self) -> None:
        ledger_path = self.make_complete_audit()
        self.install_external_dependency(ledger_path)
        registry_path = (
            self.audit
            / "audit"
            / "03_dependencies"
            / "DEPENDENCY_REGISTRY.json"
        )
        registry = read_json(registry_path)
        external = registry["external_results"][0]
        external["source_identity"] = "doi:10.0000/different-result"
        external["uses"][0]["dependency_contract_sha256"] = (
            proofcheck.canonical_sha256(
                proofcheck.external_result_contract(external)
            )
        )
        write_json(registry_path, registry)

        errors, _ = proofcheck.check_audit_finalization(self.audit)

        self.assertTrue(
            any("external_identity_sha256 is stale" in error for error in errors),
            errors,
        )

    def test_external_result_requires_one_closure_record_per_use(self) -> None:
        ledger_path = self.make_complete_audit()
        self.install_external_dependency(ledger_path)
        registry_path = (
            self.audit
            / "audit"
            / "03_dependencies"
            / "DEPENDENCY_REGISTRY.json"
        )
        registry = read_json(registry_path)
        registry["external_results"][0]["uses"] = []
        write_json(registry_path, registry)

        errors, _ = proofcheck.check_audit_finalization(self.audit)

        self.assertTrue(
            any("external use" in error.lower() and "missing" in error.lower() for error in errors),
            errors,
        )

    def test_fully_valid_but_unused_external_catalog_record_fails(self) -> None:
        ledger_path = self.make_complete_audit()
        self.install_external_dependency(ledger_path)

        ledger = read_json(ledger_path)
        step = ledger["steps"][2]
        step["dependencies"] = []
        step["premise_uses"] = [
            premise
            for premise in step["premise_uses"]
            if premise.get("id") != "P002"
        ]
        step["inference"]["moves"][0]["premise_ids"] = ["P001"]
        ledger["review"]["direct_dependencies"] = []
        ledger["review"]["citation_dispositions"][0] = {
            "key": "smith",
            "disposition": "bibliographic_only",
            "evidence": "The citation supplies attribution and no proof premise.",
        }
        write_json(ledger_path, ledger)

        registry_path = (
            self.audit
            / "audit"
            / "03_dependencies"
            / "DEPENDENCY_REGISTRY.json"
        )
        registry = read_json(registry_path)
        registry["external_results"][0]["uses"] = []
        write_json(registry_path, registry)

        report_path = self.audit / "audit" / "06_reports" / "FINAL_REPORT.md"
        report = report_path.read_text(encoding="utf-8")
        external_row = (
            "| lem:main | ext:reflexivity | external_result | verified | passed | "
            "verified | none |"
        )
        report = report.replace(external_row, "None.")
        report_path.write_text(report, encoding="utf-8", newline="\n")

        errors, _ = proofcheck.check_audit_finalization(self.audit)

        self.assertTrue(
            any(
                "ext:reflexivity" in error
                and "unused" in error.lower()
                for error in errors
            ),
            errors,
        )

    def test_resolved_issue_rejects_placeholder_evidence(self) -> None:
        ledger_path = self.make_complete_audit()
        manifest = read_json(self.audit / "AUDIT_MANIFEST.json")
        issue = {
            "id": "I-001",
            "severity": "S3",
            "confidence": "high",
            "status": "resolved",
            "finding_status": "resolved",
            "scope": "unit",
            "load_bearing": False,
            "location": "TBD",
            "affected_result": "lem:main",
            "affected_results": ["lem:main"],
            "summary": "TBD",
            "evidence": ["TBD"],
            "downstream_consequences": ["TBD"],
            "possible_repair": "TBD",
            "resolution": "TBD",
            "source_revision": "TBD",
            "recheck_evidence": ["TBD"],
            "source_snapshot_sha256": manifest["source_snapshot"]["sha256"],
            "rechecked_units": ["lem:main"],
        }
        self.install_canonical_issue(
            issue,
            ledger_path=ledger_path,
            reconcile_report_views=False,
        )

        errors, _ = proofcheck.check_audit_finalization(self.audit)

        self.assertTrue(
            any(
                "I-001" in error
                and ("substantive" in error.lower() or "placeholder" in error.lower())
                for error in errors
            ),
            errors,
        )

    def test_unit_issue_affected_result_must_match_ledger(self) -> None:
        ledger_path = self.make_complete_audit()
        issue = {
            "id": "I-001",
            "severity": "S3",
            "confidence": "high",
            "status": "open",
            "finding_status": "inconclusive",
            "scope": "unit",
            "load_bearing": False,
            "location": "paper.tex:2-4",
            "affected_result": "lem:ghost",
            "affected_results": ["lem:ghost"],
            "summary": "The issue is intentionally linked to the wrong unit.",
            "evidence": ["The ledger link and affected result disagree."],
            "downstream_consequences": ["The recorded scope is unreliable."],
            "possible_repair": "Link the issue to the affected proof unit.",
        }
        self.install_canonical_issue(
            issue,
            ledger_path=ledger_path,
            reconcile_report_views=False,
        )

        errors, _ = proofcheck.check_audit_finalization(self.audit)

        self.assertTrue(
            any(
                "affected_results omits linked ledger lem:main" in error
                for error in errors
            ),
            errors,
        )

    def test_downstream_ledger_can_reuse_one_canonical_issue_id(self) -> None:
        ledger_path = self.make_complete_audit()
        prior_path, _ = self.install_internal_dependency(ledger_path)
        issue = {
            "id": "I-001",
            "severity": "S3",
            "confidence": "high",
            "status": "open",
            "finding_status": "inconclusive",
            "scope": "unit",
            "load_bearing": True,
            "affected_result": "lem:prior",
            "affected_results": ["lem:main", "lem:prior"],
            "summary": (
                "One canonical prerequisite issue is propagated to its dependent."
            ),
        }
        prior = read_json(prior_path)
        prior["steps"][0]["status"] = "conditionally_verified"
        prior["review"]["unit_status"] = "conditionally_verified"
        prior["review"]["argument_status"] = "conditional"
        prior_result = prior["review"]["conclusion_results"][0]
        prior_result["argument_status"] = "conditional"
        write_json(prior_path, prior)

        ledger = read_json(ledger_path)
        downstream_step = next(
            step for step in ledger["steps"] if step["id"] == "S003"
        )
        downstream_step["status"] = "conditionally_verified"
        downstream_step["issue_ids"] = ["I-001"]
        downstream_step["dependencies"][0]["status"] = "conditional"
        ledger["review"]["unit_status"] = "conditionally_verified"
        ledger["review"]["dependency_closure"] = "conditionally_verified"
        ledger["review"]["direct_dependencies"][0]["status"] = "conditional"
        downstream_result = ledger["review"]["conclusion_results"][0]
        downstream_result["dependency_closure"] = "conditionally_verified"
        downstream_result["issue_ids"] = ["I-001"]
        write_json(ledger_path, ledger)

        registry_path = (
            self.audit
            / "audit"
            / "03_dependencies"
            / "DEPENDENCY_REGISTRY.json"
        )
        registry = read_json(registry_path)
        registry["internal_uses"][0]["status"] = "conditional"
        registry["internal_uses"][0]["issue_ids"] = ["I-001"]
        write_json(registry_path, registry)

        self.install_canonical_issue(
            issue,
            ledger_path=prior_path,
            reconcile_report_views=False,
        )

        errors, _ = proofcheck.check_audit_finalization(self.audit)

        self.assertFalse(
            any(
                "downstream ledger issue link lem:main:S003 lacks a matching "
                "canonical dependency edge" in error
                for error in errors
            ),
            errors,
        )

        ledger = read_json(ledger_path)
        ledger["steps"][0]["issue_ids"] = ["I-001"]
        write_json(ledger_path, ledger)

        errors, _ = proofcheck.check_audit_finalization(self.audit)

        self.assertIn(
            "I-001: downstream ledger issue link lem:main:S001 lacks a "
            "matching canonical dependency edge",
            errors,
        )

    def test_issue_does_not_propagate_through_an_unaffected_conclusion(self) -> None:
        ledger_path = self.make_complete_audit()
        self.install_internal_dependency(ledger_path)
        issue = {
            "id": "I-001",
            "severity": "S3",
            "confidence": "high",
            "status": "open",
            "finding_status": "inconclusive",
            "scope": "global",
            "load_bearing": True,
            "location": "lem:prior",
            "affected_result": "lem:prior",
            "affected_results": ["lem:prior"],
            "summary": "A prerequisite concern can propagate to its dependent result.",
            "evidence": ["lem:main directly depends on lem:prior."],
            "downstream_consequences": ["lem:main may inherit the concern."],
            "possible_repair": "Resolve the prerequisite and recheck its dependents.",
        }
        self.install_canonical_issue(issue)

        errors, _ = proofcheck.check_audit_finalization(self.audit)

        self.assertFalse(
            any("affected_results" in error for error in errors),
            errors,
        )

    def test_issue_propagates_through_an_affected_conclusion_edge(self) -> None:
        ledger_path = self.make_complete_audit()
        self.install_internal_dependency(ledger_path)
        _, summaries, _ = proofcheck.audit_ledgers(self.audit, True)
        issue = self.make_global_issue(
            finding_status="inconclusive",
            load_bearing=True,
            affected_result="lem:prior",
            affected_results=["lem:prior"],
            severity="S3",
        )
        reverse_graph = {
            "lem:main": set(),
            "lem:prior": {"lem:main"},
        }
        dependency_edges = [
            {
                "dependent_unit": "lem:main",
                "dependency_id": "lem:prior",
                "dependency_conclusion_id": "C001",
                "issue_ids": ["I-001"],
            }
        ]

        errors, _ = proofcheck.validate_issues(
            [issue],
            set(),
            True,
            evidence_base=self.audit,
            in_scope=["lem:main", "lem:prior"],
            reverse_graph=reverse_graph,
            ledger_summaries=summaries,
            dependency_edges=dependency_edges,
        )

        self.assertTrue(
            any(
                "affected_results" in error and "lem:main" in error
                for error in errors
            ),
            errors,
        )

    def test_issue_summary_preserves_finding_status_and_affected_results(self) -> None:
        issue = self.make_global_issue(
            finding_status="defect",
            load_bearing=True,
            affected_result="lem:prior",
            affected_results=["lem:main", "lem:prior"],
        )

        summary = proofcheck.render_issue_summary([issue])

        self.assertIn("Finding", summary)
        self.assertIn("Affected results", summary)
        self.assertIn("defect", summary)
        self.assertIn("lem:main, lem:prior", summary)

    def test_non_load_bearing_issue_remains_root_only(self) -> None:
        ledger_path = self.make_complete_audit()
        self.install_internal_dependency(ledger_path)
        _, summaries, _ = proofcheck.audit_ledgers(self.audit, True)
        issue = self.make_global_issue(
            finding_status="inconclusive",
            load_bearing=False,
            affected_result="lem:prior",
            affected_results=["lem:prior"],
            severity="S3",
        )
        reverse_graph = {
            "lem:main": set(),
            "lem:prior": {"lem:main"},
        }

        errors, _ = proofcheck.validate_issues(
            [issue],
            set(),
            True,
            evidence_base=self.audit,
            in_scope=["lem:main", "lem:prior"],
            reverse_graph=reverse_graph,
            ledger_summaries=summaries,
        )
        self.assertEqual([], errors)

        issue["affected_results"] = ["lem:main", "lem:prior"]
        errors, _ = proofcheck.validate_issues(
            [issue],
            set(),
            True,
            evidence_base=self.audit,
            in_scope=["lem:main", "lem:prior"],
            reverse_graph=reverse_graph,
            ledger_summaries=summaries,
        )
        self.assertTrue(
            any("conclusion-specific dependency closure" in error for error in errors),
            errors,
        )

    def test_load_bearing_issue_weakens_every_reached_unit(self) -> None:
        ledger_path = self.make_complete_audit()
        self.install_internal_dependency(ledger_path)
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        report_path = self.audit / "audit" / "06_reports" / "FINAL_REPORT.md"
        clean_manifest = read_json(manifest_path)
        clean_report = report_path.read_text(encoding="utf-8")
        registry_path = (
            self.audit
            / "audit"
            / "03_dependencies"
            / "DEPENDENCY_REGISTRY.json"
        )
        registry = read_json(registry_path)
        registry["internal_uses"][0]["issue_ids"] = ["I-001"]
        write_json(registry_path, registry)
        cases = {
            "inconclusive": "inconclusive",
            "defect": "defects_found",
        }
        for finding_status, assessment in cases.items():
            with self.subTest(finding_status=finding_status):
                write_json(manifest_path, clean_manifest)
                report_path.write_text(clean_report, encoding="utf-8", newline="\n")
                self.set_expected_assessment(assessment)
                issue = self.make_global_issue(
                    finding_status=finding_status,
                    load_bearing=True,
                    affected_result="lem:prior",
                    affected_results=["lem:main", "lem:prior"],
                )
                self.install_canonical_issue(
                    issue,
                    reconcile_report_views=False,
                )

                errors, result = proofcheck.check_audit_finalization(self.audit)

                self.assertEqual(assessment, result["derived_assessment"])
                for unit_id in ("lem:main", "lem:prior"):
                    self.assertTrue(
                        any(
                            "load-bearing" in error
                            and unit_id in error
                            for error in errors
                        ),
                        errors,
                    )

    def test_finding_status_controls_conditional_propagation_strength(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        step = self.mark_s003_conditional(ledger)
        step["side_conditions"] = [
            {
                "id": "SC001",
                "generated_by": "M001",
                "condition": "Assume x lies in the required support.",
                "status": "open",
            }
        ]
        step["conditions"] = [
            {
                "kind": "side_condition",
                "reference": "SC001",
                "condition": (
                    "Validity is conditional on the stated support condition."
                ),
            }
        ]
        write_json(ledger_path, ledger)

        progress_path = self.audit / "PROGRESS.json"
        progress = read_json(progress_path)
        progress["conditional_units"] = ["lem:main"]
        write_json(progress_path, progress)

        report_path = self.audit / "audit" / "06_reports" / "FINAL_REPORT.md"
        report = report_path.read_text(encoding="utf-8")
        report = report.replace(
            "| lem:main | verified | verified | valid | established | verified |",
            "| lem:main | conditionally_verified | verified | conditional | conditional | verified |",
        )
        report = report.replace(
            "| lem:main | agreed | fresh_context_same_model | verified | verified |",
            "| lem:main | agreed | fresh_context_same_model | conditionally_verified | conditionally_verified |",
        )
        report_path.write_text(report, encoding="utf-8", newline="\n")

        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        clean_manifest = read_json(manifest_path)
        clean_report = report_path.read_text(encoding="utf-8")
        cases = {
            "inconclusive": "inconclusive",
            "defect": "defects_found",
        }
        for finding_status, assessment in cases.items():
            with self.subTest(finding_status=finding_status):
                write_json(manifest_path, clean_manifest)
                report_path.write_text(clean_report, encoding="utf-8", newline="\n")
                self.set_expected_assessment(assessment)
                issue = self.make_global_issue(
                    finding_status=finding_status,
                    load_bearing=True,
                )
                self.install_canonical_issue(
                    issue,
                    reconcile_report_views=False,
                )

                errors, result = proofcheck.check_audit_finalization(self.audit)

                self.assertEqual(assessment, result["derived_assessment"])
                propagation_errors = [
                    error
                    for error in errors
                    if "load-bearing" in error and "lem:main" in error
                ]
                if finding_status == "inconclusive":
                    self.assertEqual([], propagation_errors, errors)
                else:
                    self.assertTrue(propagation_errors, errors)

    def test_malformed_issue_affected_results_fails_closed(self) -> None:
        self.make_complete_audit()
        report_path = self.audit / "audit" / "06_reports" / "FINAL_REPORT.md"
        clean_report = report_path.read_text(encoding="utf-8")
        malformed_values = (None, [{}])
        for value in malformed_values:
            with self.subTest(value=repr(value)):
                report_path.write_text(clean_report, encoding="utf-8", newline="\n")
                issue = self.make_global_issue(load_bearing=False, severity="S3")
                issue["affected_results"] = value
                self.install_canonical_issue(
                    issue,
                    reconcile_report_views=False,
                )
                try:
                    errors, _ = proofcheck.check_audit_finalization(self.audit)
                except (TypeError, ValueError) as exc:
                    self.fail(
                        "Malformed affected_results raised "
                        f"{type(exc).__name__}: {exc}"
                    )
                self.assertTrue(errors)
                self.assertTrue(
                    any("affected_results" in error for error in errors),
                    errors,
                )

    def test_new_pass3_enum_fields_fail_closed_on_object_values(self) -> None:
        source_path = self.base / "enum-source.txt"
        source_path.write_text(
            "External theorem statement.\n",
            encoding="utf-8",
            newline="\n",
        )

        def external_case(errors: list[str]) -> None:
            proofcheck.validate_external_result_catalog(
                {
                    "external_results": [
                        {
                            "id": "ext:enum",
                            "status": {},
                            "source_identity": "doi:10.0000/enum",
                            "version": "version 1",
                            "theorem_location": "Theorem 1",
                            "exact_statement": "External theorem statement.",
                            "source_evidence": [
                                {
                                    "file": str(source_path),
                                    "sha256": proofcheck.sha256_file(source_path),
                                    "locator": "line 1",
                                    "role": "authoritative_theorem_source",
                                }
                            ],
                            "issue_ids": [],
                            "uses": [],
                        }
                    ]
                },
                self.audit,
                errors,
            )

        def global_case(errors: list[str]) -> None:
            checks = make_global_consistency_checks()
            checks[0]["status"] = {}
            proofcheck.validate_global_consistency_pass(
                {"status": "completed", "checks": checks},
                ["lem:main"],
                errors,
            )

        def cross_reference_case(errors: list[str]) -> None:
            locations = [{"file": "paper.tex", "line": 6}]
            proofcheck.validate_cross_reference_reviews(
                [
                    {
                        "kind": "broken_reference",
                        "key": "lem:missing",
                        "locations": locations,
                        "status": {},
                        "evidence": "The anomaly was reviewed for this negative control.",
                        "affected_units": [],
                        "issue_ids": [],
                    }
                ],
                {"broken_references": {"lem:missing": locations}},
                ["lem:main"],
                errors,
            )

        def issue_case(errors: list[str]) -> None:
            issue = self.make_global_issue(load_bearing=False, severity="S3")
            issue["finding_status"] = {}
            found, _ = proofcheck.validate_issues([issue], set(), True)
            errors.extend(found)

        cases = {
            "external result status": external_case,
            "global row status": global_case,
            "cross-reference status": cross_reference_case,
            "issue finding_status": issue_case,
        }
        for label, invoke in cases.items():
            with self.subTest(field=label):
                errors: list[str] = []
                try:
                    invoke(errors)
                except (TypeError, ValueError) as exc:
                    self.fail(f"{label} raised {type(exc).__name__}: {exc}")
                self.assertTrue(errors, label)

    def test_cross_reference_findings_reconcile_with_source_resolution(self) -> None:
        self.paper.write_text(
            self.paper.read_text(encoding="utf-8").replace(
                "and \\cite{smith}.",
                "and \\cite{smith}; compare \\ref{lem:missing}.",
            ),
            encoding="utf-8",
            newline="\n",
        )
        self.audit = self.base / "cross-reference-finding-audit"
        with contextlib.redirect_stdout(io.StringIO()):
            proofcheck.cmd_scaffold(
                argparse.Namespace(paper=self.paper, output=self.audit)
            )
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        inventory = read_json(
            self.audit / "audit" / "01_index" / "theorem_inventory.json"
        )
        occurrence = next(
            row
            for row in inventory["units"][0]["reference_occurrences"]
            if row["target"] == "lem:missing"
        )
        ledger["review"]["source_reference_dispositions"].append(
            {
                "occurrence_id": occurrence["occurrence_id"],
                "id": "lem:missing",
                "target": occurrence["target"],
                "command": occurrence["command"],
                "disposition": "non_load_bearing",
                "evidence": (
                    "The broken display reference supplies no premise to the proof."
                ),
            }
        )
        write_json(ledger_path, ledger)

        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        self.assertEqual(1, len(manifest["cross_reference_reviews"]))
        manifest["cross_reference_reviews"][0].update(
            {
                "status": "defect",
                "evidence": "The source contains a broken reference.",
                "affected_units": ["lem:main"],
                "issue_ids": ["I-001"],
            }
        )
        source_resolution = next(
            row
            for row in manifest["completion"]["global_consistency_pass"]["checks"]
            if row["aspect"] == "source_resolution"
        )
        source_resolution.update(
            {
                "status": "defect",
                "evidence": "The broken reference is recorded as a source defect.",
                "affected_units": ["lem:main"],
                "issue_ids": ["I-001"],
            }
        )
        manifest["completion"]["global_consistency_pass"]["status"] = (
            "completed_with_findings"
        )
        write_json(manifest_path, manifest)
        self.set_expected_assessment("defects_found")
        self.install_canonical_issue(
            self.make_global_issue(
                finding_status="defect",
                load_bearing=False,
                severity="S3",
                summary="The manuscript contains a broken result reference.",
            )
        )

        report_path = self.audit / "audit" / "06_reports" / "FINAL_REPORT.md"
        canonical_manifest = read_json(manifest_path)
        canonical_report = report_path.read_text(encoding="utf-8")
        cases = {
            "status": lambda row: row.__setitem__("status", "inconclusive"),
            "affected_units": lambda row: row.__setitem__("affected_units", []),
            "issue_ids": lambda row: row.__setitem__("issue_ids", []),
        }
        for field, mutate in cases.items():
            with self.subTest(field=field):
                changed = json.loads(json.dumps(canonical_manifest))
                row = next(
                    item
                    for item in changed["completion"]["global_consistency_pass"]["checks"]
                    if item["aspect"] == "source_resolution"
                )
                mutate(row)
                write_json(manifest_path, changed)
                report_path.write_text(
                    canonical_report,
                    encoding="utf-8",
                    newline="\n",
                )

                errors, _ = proofcheck.check_audit_finalization(self.audit)

                self.assertTrue(
                    any(
                        "source_resolution" in error
                        and field in error
                        and "cross-reference" in error
                        for error in errors
                    ),
                    errors,
                )

    def test_issue_summary_newline_is_rejected_for_canonical_heading(
        self,
    ) -> None:
        self.make_complete_audit()
        issue = self.make_global_issue(
            load_bearing=False,
            severity="S3",
            summary="The first line\nand the second | clause form one summary.",
        )
        self.install_canonical_issue(
            issue,
            reconcile_report_views=False,
        )

        errors, _ = proofcheck.check_audit_finalization(self.audit)
        self.assertTrue(
            any(
                "summary must be one line for the canonical finding heading"
                in error
                for error in errors
            ),
            errors,
        )

    def test_issue_summary_with_angle_comparison_is_safely_rendered(self) -> None:
        self.make_complete_audit()
        issue = self.make_global_issue(
            load_bearing=False,
            severity="S3",
            summary="The claimed bound fails in the n<p regime.",
        )
        self.install_canonical_issue(issue)

        report = (
            self.audit / "audit" / "06_reports" / "FINAL_REPORT.md"
        ).read_text(encoding="utf-8")
        errors, _ = proofcheck.check_audit_finalization(self.audit)

        self.assertIn("n&lt;p", report)
        self.assertFalse(
            any("active raw HTML" in error for error in errors), errors
        )
        self.assertFalse(
            any("heading is stale" in error for error in errors), errors
        )

    def test_fresh_report_template_has_no_active_raw_html_placeholder(self) -> None:
        report = (
            self.audit / "audit" / "06_reports" / "FINAL_REPORT.md"
        ).read_text(encoding="utf-8")
        self.assertIn(proofcheck.REPORT_SCAFFOLD_MARKER, report)
        self.assertEqual(
            proofcheck.WORKING_REPORT_TITLE,
            report.splitlines()[0],
        )
        errors, _ = proofcheck.check_audit_finalization(self.audit)

        self.assertFalse(
            any("active raw HTML" in error for error in errors), errors
        )

    def test_final_report_ready_rejects_nonfinal_scaffold_marker(self) -> None:
        self.make_complete_audit()
        report_path = self.audit / "audit" / "06_reports" / "FINAL_REPORT.md"
        report_path.write_text(
            f"> **{proofcheck.REPORT_SCAFFOLD_MARKER}:** Working template.\n\n"
            + report_path.read_text(encoding="utf-8"),
            encoding="utf-8",
            newline="\n",
        )

        errors, _ = proofcheck.check_audit_finalization(self.audit)

        self.assertIn(
            "Final report still contains the NONFINAL scaffold marker", errors
        )

    def test_final_report_ready_requires_the_exact_final_title(self) -> None:
        self.make_complete_audit()
        report_path = self.audit / "audit" / "06_reports" / "FINAL_REPORT.md"
        report = report_path.read_text(encoding="utf-8").replace(
            proofcheck.FINAL_REPORT_TITLE,
            proofcheck.WORKING_REPORT_TITLE,
            1,
        )
        report_path.write_text(report, encoding="utf-8")

        errors, _ = proofcheck.check_audit_finalization(self.audit)

        self.assertIn(
            "Final report must use the final title as its sole H1: "
            f"{proofcheck.FINAL_REPORT_TITLE}",
            errors,
        )

    def test_final_report_rejects_an_additional_h1(self) -> None:
        self.make_complete_audit()
        report_path = self.audit / "audit" / "06_reports" / "FINAL_REPORT.md"
        report = report_path.read_text(encoding="utf-8")
        report_path.write_text(
            "# Misleading Final Heading\n\n" + report,
            encoding="utf-8",
            newline="\n",
        )

        errors, _ = proofcheck.check_audit_finalization(self.audit)

        self.assertIn(
            "Final report must use the final title as its sole H1: "
            f"{proofcheck.FINAL_REPORT_TITLE}",
            errors,
        )

    def test_final_report_rejects_an_additional_setext_h1(self) -> None:
        self.make_complete_audit()
        report_path = self.audit / "audit" / "06_reports" / "FINAL_REPORT.md"
        report = report_path.read_text(encoding="utf-8")
        report_path.write_text(
            "Misleading Final Heading\n=========================\n\n" + report,
            encoding="utf-8",
            newline="\n",
        )

        errors, _ = proofcheck.check_audit_finalization(self.audit)

        self.assertIn(
            "Final report must use the final title as its sole H1: "
            f"{proofcheck.FINAL_REPORT_TITLE}",
            errors,
        )

    def test_findings_and_repairs_order_by_severity_then_issue_id(self) -> None:
        issues = [
            {
                "id": "I-001",
                "severity": "S3",
                "summary": "Lower-severity finding with the first ID.",
                "affected_result": "lem:main",
                "affected_results": ["lem:main"],
            },
            {
                "id": "I-003",
                "severity": "S1",
                "summary": "Higher-severity finding with the later ID.",
                "affected_result": "lem:main",
                "affected_results": ["lem:main"],
            },
            {
                "id": "I-002",
                "severity": "S1",
                "summary": "Higher-severity finding with the earlier ID.",
                "affected_result": "lem:main",
                "affected_results": ["lem:main"],
            },
        ]

        details = proofcheck.render_findings_and_repairs(
            issues,
            {},
            [],
            [],
            [],
            "defects_found",
        )
        headings = [
            line.split()[1]
            for line in details.splitlines()
            if line.startswith("### I-")
        ]

        self.assertEqual(["I-002", "I-003", "I-001"], headings)

    def test_issue_report_views_require_final_mode(self) -> None:
        self.make_complete_audit()
        report_path = self.audit / "audit" / "06_reports" / "FINAL_REPORT.md"
        before = report_path.read_text(encoding="utf-8")
        output = io.StringIO()
        errors = io.StringIO()

        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            status = proofcheck.cmd_issues(
                argparse.Namespace(
                    root=self.audit,
                    write_summary=False,
                    write_report_views=True,
                    final=False,
                )
            )
        payload = json.loads(output.getvalue())

        self.assertEqual(1, status)
        self.assertFalse(payload["report_views_written"])
        self.assertIn("--write-report-views requires --final", errors.getvalue())
        self.assertEqual(before, report_path.read_text(encoding="utf-8"))

    def test_failed_final_issue_reconciliation_preserves_all_views(self) -> None:
        self.make_complete_audit()
        summary_path = self.audit / "audit" / "06_reports" / "ISSUE_SUMMARY.md"
        report_path = self.audit / "audit" / "06_reports" / "FINAL_REPORT.md"
        summary_before = summary_path.read_bytes()
        report_before = report_path.read_bytes()
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        manifest["audit_scope"]["status"] = "draft"
        write_json(manifest_path, manifest)

        output = io.StringIO()
        errors = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            status = proofcheck.cmd_issues(
                argparse.Namespace(
                    root=self.audit,
                    write_summary=True,
                    write_report_views=True,
                    final=True,
                )
            )

        self.assertEqual(1, status)
        self.assertFalse(json.loads(output.getvalue())["report_views_written"])
        self.assertTrue(errors.getvalue())
        self.assertEqual(summary_before, summary_path.read_bytes())
        self.assertEqual(report_before, report_path.read_bytes())

    def test_issue_view_transaction_rolls_back_each_failed_commit(self) -> None:
        self.make_complete_audit()
        summary_path = self.audit / "audit" / "06_reports" / "ISSUE_SUMMARY.md"
        report_path = self.audit / "audit" / "06_reports" / "FINAL_REPORT.md"
        report = report_path.read_text(encoding="utf-8")
        report = proofcheck.replace_report_section_text(
            report, "## Results and impact", "stale results"
        )
        report = proofcheck.replace_report_section_text(
            report, "## Findings and repairs", "stale findings"
        )
        report_path.write_text(report, encoding="utf-8", newline="\n")
        summary_path.write_text(
            "stale issue summary\n", encoding="utf-8", newline="\n"
        )
        summary_before = summary_path.read_bytes()
        report_before = report_path.read_bytes()
        original_replace = proofcheck.os.replace

        for failed_path in (report_path, summary_path):
            with self.subTest(failed_destination=failed_path.name):
                events: list[tuple[str, Path]] = []
                injected = False

                def fail_commit(source: Path, destination: Path) -> None:
                    nonlocal injected
                    destination_path = Path(destination).resolve()
                    if (
                        destination_path == failed_path.resolve()
                        and not injected
                    ):
                        injected = True
                        events.append(("failed", destination_path))
                        raise OSError(
                            f"simulated {failed_path.name} commit failure"
                        )
                    original_replace(source, destination)
                    events.append(("replaced", destination_path))

                with mock.patch.object(
                    proofcheck.os, "replace", side_effect=fail_commit
                ):
                    with self.assertRaisesRegex(
                        OSError, f"simulated {re.escape(failed_path.name)}"
                    ):
                        proofcheck.cmd_issues(
                            argparse.Namespace(
                                root=self.audit,
                                write_summary=True,
                                write_report_views=True,
                                final=True,
                            )
                        )

                self.assertEqual(summary_before, summary_path.read_bytes())
                self.assertEqual(report_before, report_path.read_bytes())
                self.assertEqual(
                    [],
                    list(report_path.parent.glob(".*.proofcheck.tmp")),
                )
                if failed_path == summary_path:
                    self.assertEqual(
                        [
                            ("replaced", report_path.resolve()),
                            ("failed", summary_path.resolve()),
                            ("replaced", summary_path.resolve()),
                            ("replaced", report_path.resolve()),
                        ],
                        events,
                    )
                else:
                    self.assertEqual(
                        [
                            ("failed", report_path.resolve()),
                            ("replaced", report_path.resolve()),
                        ],
                        events,
                    )

    def test_transaction_rolls_back_when_replace_raises_after_rename(self) -> None:
        first = self.base / "first.txt"
        second = self.base / "second.txt"
        first.write_text("old first\n", encoding="utf-8", newline="\n")
        second.write_text("old second\n", encoding="utf-8", newline="\n")
        original_replace = proofcheck.os.replace
        injected = False

        def replace_then_raise(source: Path, destination: Path) -> None:
            nonlocal injected
            original_replace(source, destination)
            if not injected:
                injected = True
                raise OSError("simulated post-rename interruption")

        with mock.patch.object(
            proofcheck.os, "replace", side_effect=replace_then_raise
        ):
            with self.assertRaisesRegex(OSError, "post-rename interruption"):
                proofcheck.transactional_write_texts(
                    [(first, "new first\n"), (second, "new second\n")]
                )

        self.assertEqual(b"old first\n", first.read_bytes())
        self.assertEqual(b"old second\n", second.read_bytes())
        self.assertEqual([], list(self.base.glob(".*.proofcheck.tmp")))

    def test_report_views_generate_exact_empty_sections_only(
        self,
    ) -> None:
        self.make_complete_audit()
        report_path = self.audit / "audit" / "06_reports" / "FINAL_REPORT.md"
        before = report_path.read_text(encoding="utf-8")
        before = proofcheck.replace_report_section_text(
            before, "## Results and impact", "stale results"
        )
        before = proofcheck.replace_report_section_text(
            before, "## Findings and repairs", "stale findings"
        )
        report_path.write_text(before, encoding="utf-8", newline="\n")
        output = io.StringIO()

        with contextlib.redirect_stdout(output):
            status = proofcheck.cmd_issues(
                argparse.Namespace(
                    root=self.audit,
                    write_summary=True,
                    write_report_views=True,
                    final=True,
                )
            )
        payload = json.loads(output.getvalue())
        after = report_path.read_text(encoding="utf-8")

        self.assertEqual(0, status)
        self.assertTrue(payload["report_views_written"])
        _, summaries, _ = proofcheck.audit_ledgers(self.audit, True)
        expected_results = proofcheck.render_results_and_impact(
            {summary["unit_id"]: summary for summary in summaries},
            ["lem:main"],
        )
        self.assertEqual(
            expected_results,
            (
                proofcheck.report_section(after, "## Results and impact") or ""
            ).strip(),
        )
        self.assertEqual(
            "No issues.",
            (
                proofcheck.report_section(after, "## Findings and repairs") or ""
            ).strip(),
        )
        for heading in ("## Results and impact", "## Findings and repairs"):
            before = proofcheck.replace_report_section_text(
                before, heading, "<generated>"
            )
            after = proofcheck.replace_report_section_text(
                after, heading, "<generated>"
            )
        self.assertEqual(before, after)

    def test_report_views_generate_schema5_sections_accepted_by_finalization(
        self,
    ) -> None:
        self.make_complete_audit()
        issue = self.make_global_issue(
            load_bearing=False,
            severity="S3",
            summary="A canonical schema-five finding.",
        )
        self.install_canonical_issue(issue)
        report_path = self.audit / "audit" / "06_reports" / "FINAL_REPORT.md"
        before = report_path.read_text(encoding="utf-8")
        before = proofcheck.replace_report_section_text(
            before, "## Results and impact", "stale results"
        )
        before = proofcheck.replace_report_section_text(
            before, "## Findings and repairs", "stale findings"
        )
        report_path.write_text(before, encoding="utf-8", newline="\n")
        output = io.StringIO()

        with contextlib.redirect_stdout(output):
            status = proofcheck.cmd_issues(
                argparse.Namespace(
                    root=self.audit,
                    write_summary=True,
                    write_report_views=True,
                    final=True,
                )
            )
        payload = json.loads(output.getvalue())
        after = report_path.read_text(encoding="utf-8")
        _, summaries, _ = proofcheck.audit_ledgers(self.audit, True)
        summaries_by_id = {
            summary["unit_id"]: summary for summary in summaries
        }
        manifest = read_json(self.audit / "AUDIT_MANIFEST.json")
        required_challenges, _ = proofcheck.required_challenge_requirements(
            manifest, [issue]
        )
        expected_results = proofcheck.render_results_and_impact(
            summaries_by_id,
            manifest["audit_scope"]["in_scope_units"],
        )
        expected_findings = proofcheck.render_findings_and_repairs(
            [issue],
            summaries_by_id,
            [],
            required_challenges,
            manifest.get("report_deliverables", []),
            manifest["audit_scope"]["overall_assessment"],
        )

        self.assertEqual(0, status)
        self.assertTrue(payload["report_views_written"])
        self.assertEqual(
            expected_results,
            (
                proofcheck.report_section(after, "## Results and impact") or ""
            ).strip(),
        )
        self.assertEqual(
            expected_findings,
            (
                proofcheck.report_section(after, "## Findings and repairs") or ""
            ).strip(),
        )
        for heading in ("## Results and impact", "## Findings and repairs"):
            before = proofcheck.replace_report_section_text(
                before, heading, "<generated>"
            )
            after = proofcheck.replace_report_section_text(
                after, heading, "<generated>"
            )
        self.assertEqual(before, after)
        final_errors, _ = proofcheck.check_audit_finalization(self.audit)
        self.assertEqual([], final_errors)

    def test_ledger_move_report_preserves_exact_quote_and_failure_evidence(
        self,
    ) -> None:
        _, _, failure_evidence = self.make_ledger_move_defect_audit()
        final_errors, _ = proofcheck.check_audit_finalization(self.audit)
        self.assertEqual([], final_errors)
        report = (
            self.audit / "audit" / "06_reports" / "FINAL_REPORT.md"
        ).read_text(encoding="utf-8")
        details = proofcheck.report_section(report, "## Findings and repairs") or ""
        failure_table = proofcheck.markdown_tables(details)[0]
        failure_row = failure_table[2]
        self.assertEqual(
            ["Location", "Step or move", "Exact locked quote"],
            failure_table[0],
        )
        self.assertEqual("S003/M001", failure_row[1])
        self.assertTrue(failure_row[2])
        self.assertIn(failure_evidence, details)
        self.assertIn("Rule checked: Reflexivity of equality", details)
        self.assertNotIn('"premises"', details)

    def test_ledger_move_report_rejects_stale_visible_evidence(
        self,
    ) -> None:
        self.make_ledger_move_defect_audit()
        report_path = self.audit / "audit" / "06_reports" / "FINAL_REPORT.md"
        baseline = report_path.read_text(encoding="utf-8")
        details = proofcheck.report_section(
            baseline, "## Findings and repairs"
        ) or ""
        failure_row = proofcheck.markdown_tables(details)[0][2]
        self.assertEqual([], proofcheck.check_audit_finalization(self.audit)[0])

        for field, value, stale in (
            ("Exact locked quote", failure_row[2], "stale locked quote"),
            (
                "Failure evidence",
                "Rule checked: Reflexivity of equality",
                "Rule checked: invalid rule",
            ),
        ):
            with self.subTest(field=field):
                self.assertIn(value, baseline)
                report_path.write_text(
                    baseline.replace(value, stale, 1),
                    encoding="utf-8",
                    newline="\n",
                )
                errors, _ = proofcheck.check_audit_finalization(self.audit)
                self.assertTrue(
                    any(
                        "Findings and repairs disagrees with canonical issues"
                        in error
                        for error in errors
                    ),
                    errors,
                )

    def test_challenge_issue_target_is_exact_neutral_and_relevantly_bound(
        self,
    ) -> None:
        ledger_path, issue, failure_evidence = (
            self.make_ledger_move_defect_audit()
        )
        issue_path = self.audit / "audit" / "06_reports" / "ISSUE_LOG.json"
        issue_record = read_json(issue_path)
        issue_record["issues"][0]["severity"] = "S1"
        write_json(issue_path, issue_record)
        ledger = read_json(ledger_path)
        self.seal_schema5_challenge(
            ledger_path, ledger, covered_issue_ids=["I-001"]
        )

        packet = proofcheck.build_context_packet(
            self.audit, "lem:main", "challenge"
        )
        self.assertEqual(1, len(packet["issue_triggers"]))
        trigger = packet["issue_triggers"][0]
        target = trigger["target_contract"]
        current = target["current_target"]
        self.assertEqual("I-001", trigger["id"])
        self.assertNotIn("severity", trigger)
        self.assertEqual(
            trigger["target_contract_sha256"],
            proofcheck.canonical_sha256(target),
        )
        self.assertEqual("ledger_move", current["reference"]["kind"])
        self.assertEqual("x equals x", current["claim"])
        self.assertEqual("Reflexivity of equality", current["rule"])
        self.assertEqual(["For every real x."], [
            row["claim"] for row in current["premises"]
        ])
        premise_origin = current["premises"][0]["origin"]
        self.assertEqual("obligation", premise_origin["kind"])
        self.assertTrue(premise_origin["anchor"]["source"]["lines"])
        self.assertTrue(current["source_anchor"]["lines"])
        self.assertEqual([], target["propagation"]["uses"])
        self.assertTrue(target["contracts"][0]["source_anchors"])
        serialized = json.dumps(trigger, ensure_ascii=False)
        self.assertNotIn(issue["summary"], serialized)
        self.assertNotIn(failure_evidence, serialized)
        for forbidden in (
            "finding_status",
            "invalidation_kind",
            "suggested_changes",
            "failure",
            "justification",
        ):
            self.assertNotIn(f'"{forbidden}"', serialized)

        original_context = packet["context_binding_sha256"]
        issue_record = read_json(issue_path)
        issue_record["issues"][0]["contract_refs"].append(
            {
                "kind": "obligation_pointer",
                "unit_id": "lem:main",
                "pointer": "/quantifier_scope",
            }
        )
        write_json(issue_path, issue_record)
        self.seal_schema5_challenge(
            ledger_path, read_json(ledger_path), covered_issue_ids=["I-001"]
        )
        ordered_context = proofcheck.build_context_packet(
            self.audit, "lem:main", "challenge"
        )["context_binding_sha256"]
        self.assertNotEqual(original_context, ordered_context)
        issue_record["issues"][0]["contract_refs"].reverse()
        write_json(issue_path, issue_record)
        self.seal_schema5_challenge(
            ledger_path, read_json(ledger_path), covered_issue_ids=["I-001"]
        )
        reordered_context = proofcheck.build_context_packet(
            self.audit, "lem:main", "challenge"
        )["context_binding_sha256"]
        self.assertEqual(ordered_context, reordered_context)

        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        manifest["notes"].append(
            "This unrelated administrative note must not stale a challenge."
        )
        write_json(manifest_path, manifest)
        self.assertEqual(
            reordered_context,
            proofcheck.build_context_packet(
                self.audit, "lem:main", "challenge"
            )["context_binding_sha256"],
        )

        issue_record = read_json(issue_path)
        issue_record["issues"][0]["severity"] = "S0"
        write_json(issue_path, issue_record)
        self.seal_schema5_challenge(
            ledger_path, read_json(ledger_path), covered_issue_ids=["I-001"]
        )
        # Authored severity is not a blinded mathematical target input.
        self.assertEqual(
            reordered_context,
            proofcheck.build_context_packet(
                self.audit, "lem:main", "challenge"
            )["context_binding_sha256"],
        )

    def test_premise_dependency_origin_is_resolved_within_its_step(self) -> None:
        dependency = {
            "id": "lem:prior",
            "use_id": "D001",
            "kind": "internal_result",
            "conclusion_id": "C001",
            "status": "verified",
            "needed_form": "The prior conclusion in the needed form.",
            "compatibility_check": "The result has the exact needed form.",
        }
        first_step = {"id": "S001", "dependencies": [dict(dependency)]}
        colliding_dependency = {
            **dependency,
            "id": "D001",
            "use_id": "D002",
        }
        second_step = {
            "id": "S002",
            "dependencies": [dict(dependency), colliding_dependency],
        }
        ledger = {"steps": [first_step, second_step]}
        premise = {
            "origin": {"kind": "internal_result", "reference": "D001"}
        }

        projected = proofcheck.packet_issue_premise_origin(
            self.audit,
            self.audit / "audit" / "04_local_checks" / "unit.ledger.json",
            ledger,
            second_step,
            premise,
            [],
        )

        self.assertEqual("D001", projected["use_id"])
        self.assertEqual("lem:prior", projected["dependency_id"])
        self.assertEqual("C001", projected["dependency_conclusion_id"])

    def test_primary_issue_propagation_defers_only_current_unit_anchor(
        self,
    ) -> None:
        issue = {
            "affected_result": "lem:root",
            "affected_results": ["lem:root", "lem:target"],
        }
        edge = {
            "use_id": "D001",
            "dependency_id": "lem:root",
            "dependency_conclusion_id": "C001",
            "dependent_unit": "lem:target",
            "needed_form": "The root conclusion in the exact needed form.",
            "dependency_conclusion": "The root conclusion.",
            "dependency_contract_sha256": "a" * 64,
            "step_ids": ["S002"],
        }
        registry = {"internal_uses": [edge], "external_results": []}
        with mock.patch.object(
            proofcheck,
            "packet_issue_ledger",
            side_effect=AssertionError("current ledger must not be read"),
        ) as ledger_reader:
            propagation = proofcheck.packet_issue_propagation(
                self.audit,
                issue,
                registry,
                [],
                "lem:target",
                pending_step_anchor_unit="lem:target",
            )
        ledger_reader.assert_not_called()
        self.assertEqual([], propagation["uses"][0]["source_anchors"])

        with mock.patch.object(
            proofcheck,
            "packet_issue_ledger",
            side_effect=ValueError("missing current ledger"),
        ):
            with self.assertRaisesRegex(ValueError, "missing current ledger"):
                proofcheck.packet_issue_propagation(
                    self.audit, issue, registry, [], "lem:target"
                )

        issue["affected_results"].insert(1, "lem:middle")
        registry["internal_uses"] = [
            {**edge, "dependent_unit": "lem:middle"},
            {
                **edge,
                "use_id": "D002",
                "dependency_id": "lem:middle",
            },
        ]
        with mock.patch.object(
            proofcheck,
            "packet_issue_ledger",
            side_effect=ValueError("missing intermediate ledger"),
        ):
            with self.assertRaisesRegex(ValueError, "missing intermediate ledger"):
                proofcheck.packet_issue_propagation(
                    self.audit,
                    issue,
                    registry,
                    [],
                    "lem:target",
                    pending_step_anchor_unit="lem:target",
                )

    def test_primary_packet_defers_current_unit_issue_contract(self) -> None:
        ledger_path = self.make_complete_audit()
        prior_path, _ = self.install_internal_dependency(ledger_path)
        ledger_path.unlink()
        issue = self.make_global_issue(
            finding_status="defect",
            load_bearing=True,
            severity="S1",
            summary=(
                "The upstream result is defective at the exact inference "
                "used by the downstream unit."
            ),
        )
        issue.update(
            {
                "origin_ref": {
                    "kind": "ledger_move",
                    "unit_id": "lem:prior",
                    "step_id": "S001",
                    "move_id": "M001",
                },
                "contract_refs": [
                    {
                        "kind": "conclusion",
                        "unit_id": "lem:prior",
                        "conclusion_id": "C001",
                    },
                    {
                        "kind": "dependency_use",
                        "unit_id": "lem:main",
                        "use_id": "D001",
                    },
                ],
                "affected_result": "lem:prior",
                "affected_results": ["lem:prior", "lem:main"],
                "invalidation_kind": "proof_invalid",
            }
        )
        issue_path = self.audit / "audit" / "06_reports" / "ISSUE_LOG.json"
        write_json(
            issue_path,
            {"schema_version": proofcheck.SCHEMA_VERSION, "issues": [issue]},
        )

        packet = proofcheck.build_context_packet(
            self.audit, "lem:main", "primary"
        )

        self.assertTrue(prior_path.is_file())
        trigger = packet["issue_triggers"][0]
        contracts = trigger["target_contract"]["contracts"]
        pending = next(
            row
            for row in contracts
            if row["reference"].get("unit_id") == "lem:main"
        )
        self.assertEqual("pending_current_unit", pending["status"])
        self.assertEqual("dependency_use", pending["reference"]["kind"])
        self.assertEqual(
            [], trigger["target_contract"]["propagation"]["uses"][0]["source_anchors"]
        )

    def test_current_unit_issue_output_does_not_stale_work_context(self) -> None:
        ledger_path, _, _ = self.make_ledger_move_defect_audit()
        baseline = read_json(ledger_path)["work_context_sha256"]
        issue_path = self.audit / "audit" / "06_reports" / "ISSUE_LOG.json"
        before = proofcheck.build_context_packet(
            self.audit, "lem:main", "primary"
        )
        issue_log = read_json(issue_path)
        issue_log["issues"][0]["summary"] = (
            "The same recorded inference defect, stated more concisely."
        )
        issue_log["issues"][0]["severity"] = "S1"
        issue_log["issues"][0]["repair_search"] = make_repair_search("S1")
        write_json(issue_path, issue_log)

        primary = proofcheck.build_context_packet(
            self.audit, "lem:main", "primary"
        )
        challenge = proofcheck.build_context_packet(
            self.audit, "lem:main", "challenge"
        )

        self.assertEqual(baseline, primary["work_context_sha256"])
        self.assertNotEqual(
            before["context_binding_sha256"],
            primary["context_binding_sha256"],
        )
        self.assertEqual("I-001", primary["issue_triggers"][0]["id"])
        self.assertEqual("S1", primary["issue_triggers"][0]["severity"])
        self.assertEqual(
            issue_log["issues"][0]["summary"],
            primary["issue_triggers"][0]["summary"],
        )
        self.assertEqual("I-001", challenge["issue_triggers"][0]["id"])

    def test_work_context_keeps_global_and_interface_issue_inputs(self) -> None:
        common = {
            "severity": "S2",
            "status": "open",
            "load_bearing": True,
            "affected_result": "lem:main",
            "affected_results": ["lem:main"],
            "contract_refs": [],
        }
        issues = [
            {
                **common,
                "id": "I-001",
                "origin_ref": {
                    "kind": "ledger_move",
                    "unit_id": "lem:main",
                },
            },
            {
                **common,
                "id": "I-002",
                "origin_ref": {"kind": "global_check", "aspect": "scope"},
            },
            {
                **common,
                "id": "I-003",
                "origin_ref": {
                    "kind": "interface_record",
                    "interface_id": "IF-001",
                },
            },
        ]
        with (
            mock.patch.object(
                proofcheck,
                "load_issue_log",
                return_value=(None, issues, proofcheck.SCHEMA_VERSION, []),
            ),
            mock.patch.object(
                proofcheck,
                "packet_issue_origin_target",
                return_value={"kind": "resolved"},
            ),
            mock.patch.object(
                proofcheck,
                "packet_issue_propagation",
                return_value={"uses": []},
            ),
        ):
            projected = proofcheck.packet_issue_triggers(
                self.audit,
                {},
                "lem:main",
                "primary",
                records={"dependency_registry": {}},
                members=[],
                work_context_inputs_only=True,
            )

        self.assertEqual(["I-002", "I-003"], [row["id"] for row in projected])

    def test_historical_challenges_receive_only_their_exact_retired_path_cut(
        self,
    ) -> None:
        manifest = read_json(self.audit / "AUDIT_MANIFEST.json")
        members = proofcheck.packet_source_members(self.audit, manifest)
        evidence_span = proofcheck.locked_span(
            self.paper,
            6,
            6,
            self.audit,
            role="retirement_verification",
        )
        common = {
            "dependency_conclusion_id": "C001",
            "needed_form": "The dependency supplies the exact needed result.",
            "dependency_conclusion": "The dependency result holds.",
            "dependency_contract_sha256": "a" * 64,
            "step_ids": ["S001"],
            "status": "verified",
            "compatibility_check": "The prior edge was applicable.",
            "compatibility_checks": [],
            "issue_ids": ["I-001"],
        }
        shared = {
            **common,
            "use_id": "D001",
            "dependency_id": "lem:root",
            "dependent_unit": "lem:middle",
        }
        cut_a = {
            **common,
            "use_id": "D002",
            "dependency_id": "lem:middle",
            "dependent_unit": "lem:a",
        }
        cut_b = {
            **common,
            "use_id": "D003",
            "dependency_id": "lem:middle",
            "dependent_unit": "lem:b",
        }
        route_a_1 = {
            **common,
            "use_id": "D004",
            "dependency_id": "lem:root",
            "dependent_unit": "lem:x",
        }
        route_a_2 = {
            **common,
            "use_id": "D005",
            "dependency_id": "lem:x",
            "dependent_unit": "lem:a",
        }
        route_b_1 = {
            **common,
            "use_id": "D006",
            "dependency_id": "lem:root",
            "dependent_unit": "lem:y",
        }
        route_b_2 = {
            **common,
            "use_id": "D007",
            "dependency_id": "lem:y",
            "dependent_unit": "lem:b",
        }
        archived_hashes = {
            "D001": "1" * 64,
            "D002": "2" * 64,
            "D003": "3" * 64,
        }
        issue = {
            "id": "I-001",
            "status": "resolved",
            "affected_result": "lem:root",
            "affected_results": ["lem:root", "lem:middle"],
            "origin_ref": {
                "kind": "ledger_move",
                "unit_id": "lem:root",
                "step_id": "S001",
                "move_id": "M001",
            },
            "historical_origin": {
                "required_challenges": ["lem:a", "lem:b"]
            },
            "current_resolution": {
                "evidence_spans": [evidence_span],
                "retired_dependency_uses": [
                    {
                        "use_id": "D002",
                        "prior_edge_sha256": archived_hashes["D002"],
                    },
                    {
                        "use_id": "D003",
                        "prior_edge_sha256": archived_hashes["D003"],
                    },
                ],
            },
        }
        prior_registry = {"internal_uses": [shared, cut_a, cut_b]}
        archive = {
            "issue_record": {
                "origin_ref": issue["origin_ref"],
                "affected_results": [
                    "lem:root",
                    "lem:middle",
                    "lem:a",
                    "lem:b",
                ],
            },
            "prior_artifacts": {"dependency_registry": {}},
            "required_closure": {
                "dependency_uses": [
                    {"use_id": use_id, "edge_sha256": digest}
                    for use_id, digest in archived_hashes.items()
                ]
            },
        }
        current_registry = {
            "internal_uses": [route_a_1, route_a_2, route_b_1, route_b_2],
            "external_results": [],
        }

        with mock.patch.object(
            proofcheck, "load_resolution_archive", return_value=archive
        ), mock.patch.object(
            proofcheck,
            "sealed_json_object",
            return_value=("prior-registry.json", "f" * 64, prior_registry),
        ), mock.patch.object(
            proofcheck,
            "packet_issue_ledger",
            side_effect=lambda _root, unit_id: (
                self.audit / f"{unit_id}.ledger.json",
                {"steps": [{"id": "S001"}]},
            ),
        ), mock.patch.object(
            proofcheck,
            "packet_issue_step_anchor",
            return_value={
                "file": "paper.tex",
                "start_line": 1,
                "end_line": 1,
                "sha256": "f" * 64,
            },
        ):
            propagation_a = proofcheck.packet_issue_propagation(
                self.audit,
                issue,
                current_registry,
                members,
                "lem:a",
            )
            propagation_b = proofcheck.packet_issue_propagation(
                self.audit,
                issue,
                current_registry,
                members,
                "lem:b",
            )

        cuts_a = propagation_a["retirement"]["retired_path_edges"]
        cuts_b = propagation_b["retirement"]["retired_path_edges"]
        self.assertEqual(["D002"], [row["use_id"] for row in cuts_a])
        self.assertEqual(["D003"], [row["use_id"] for row in cuts_b])
        self.assertEqual("lem:a", cuts_a[0]["dependent_unit"])
        self.assertEqual("lem:middle", cuts_a[0]["dependency_id"])
        self.assertEqual(
            ["D002"],
            propagation_a["retirement"][
                "current_issue_closure_absent_use_ids"
            ],
        )
        self.assertTrue(propagation_a["current_route"]["path_present"])
        self.assertTrue(propagation_b["current_route"]["path_present"])
        self.assertEqual(
            ["D004", "D005"],
            sorted(
                row["use_id"]
                for row in propagation_a["current_route"]["uses"]
            ),
        )
        self.assertEqual(
            ["D006", "D007"],
            sorted(
                row["use_id"]
                for row in propagation_b["current_route"]["uses"]
            ),
        )
        serialized = json.dumps(
            [
                cuts_a,
                cuts_b,
                propagation_a["current_route"]["uses"],
                propagation_b["current_route"]["uses"],
            ],
            ensure_ascii=False,
        )
        for forbidden in ("status", "compatibility_check", "issue_ids"):
            self.assertNotIn(f'"{forbidden}"', serialized)

    def test_progress_gate_rejects_semantically_stale_challenge_target(
        self,
    ) -> None:
        ledger_path, _, _ = self.make_ledger_move_defect_audit()
        issue_path = self.audit / "audit" / "06_reports" / "ISSUE_LOG.json"
        issue_log = read_json(issue_path)
        issue_log["issues"][0]["severity"] = "S1"
        issue_log["issues"][0]["repair_search"] = make_repair_search("S1")
        write_json(issue_path, issue_log)
        self.seal_schema5_challenge(
            ledger_path,
            read_json(ledger_path),
            covered_issue_ids=["I-001"],
        )
        manifest = read_json(self.audit / "AUDIT_MANIFEST.json")
        _, summaries, _ = proofcheck.audit_ledgers(self.audit, True)
        summaries_by_id = {row["unit_id"]: row for row in summaries}
        current_issues = read_json(issue_path)["issues"]
        self.assertTrue(
            proofcheck.independent_checks_complete(
                self.audit, manifest, summaries_by_id, current_issues
            )
        )

        issue_log = read_json(issue_path)
        issue_log["issues"][0]["contract_refs"].append({
            "kind": "obligation_pointer", "unit_id": "lem:main", "pointer": "/quantifier_scope"
        })
        write_json(issue_path, issue_log)
        self.assertFalse(
            proofcheck.independent_checks_complete(
                self.audit,
                manifest,
                summaries_by_id,
                issue_log["issues"],
            )
        )

    def test_validator_identity_normalizes_platform_newlines(self) -> None:
        lf = self.base / "validator-lf.py"
        crlf = self.base / "validator-crlf.py"
        lf.write_bytes(b"first line\nsecond line\n")
        crlf.write_bytes(b"first line\r\nsecond line\r\n")

        self.assertNotEqual(
            proofcheck.sha256_file(lf), proofcheck.sha256_file(crlf)
        )
        self.assertEqual(
            proofcheck.sha256_portable_text_file(lf),
            proofcheck.sha256_portable_text_file(crlf),
        )

    def test_issue_packet_projects_locked_external_evidence_portably(
        self,
    ) -> None:
        external = self.base / "estimator.py"
        external.write_text(
            "def estimate(x):\n    return x\n",
            encoding="utf-8",
            newline="\n",
        )
        span = proofcheck.locked_span(
            external,
            1,
            2,
            self.audit,
            role="implementation_snapshot",
        )
        manifest = read_json(self.audit / "AUDIT_MANIFEST.json")
        members = proofcheck.packet_source_members(self.audit, manifest)

        anchors = proofcheck.packet_issue_evidence_anchors(
            self.audit, [span], members
        )

        self.assertEqual(1, len(anchors))
        member = anchors[0]["source_member"]
        self.assertEqual("locked_external_evidence", member["membership"])
        self.assertIsNone(member["audit_relative_file"])
        self.assertEqual("estimator.py", member["name"])
        self.assertEqual(proofcheck.sha256_file(external), member["file_sha256"])
        self.assertNotIn(str(self.base), json.dumps(anchors, ensure_ascii=False))

    def test_required_challenge_artifact_rejects_nonportable_paths(self) -> None:
        ledger_path = self.make_complete_audit()
        baseline = read_json(ledger_path)
        outside = self.base / "outside challenge.md"
        outside.write_text(
            "# External challenge\n\nThis file is outside the audit root.\n",
            encoding="utf-8",
            newline="\n",
        )
        cases = (
            outside.resolve().as_posix(),
            "audit/05_adversarial/../06_reports/FINAL_REPORT.md",
            "audit\\05_adversarial\\lem-main-challenge.md",
            "audit/05_adversarial/CON.md",
            "audit/05_adversarial/challenge.",
        )
        for artifact in cases:
            with self.subTest(artifact=artifact):
                ledger = json.loads(json.dumps(baseline))
                ledger["independent_check"]["artifact"] = artifact
                write_json(ledger_path, ledger)

                errors, _ = proofcheck.check_ledger_data(ledger_path, True)

                self.assertTrue(
                    any(
                        "portable audit-relative path under "
                        "audit/05_adversarial" in error
                        for error in errors
                    ),
                    errors,
                )

    def test_finalization_rejects_redirected_challenge_artifact(self) -> None:
        ledger_path = self.make_complete_audit()
        target = self.base / "redirected challenge.md"
        target.write_text(
            "# Redirected challenge\n\nThis target is outside audit state.\n",
            encoding="utf-8",
            newline="\n",
        )
        link = (
            self.audit
            / "audit"
            / "05_adversarial"
            / "redirected-challenge.md"
        )
        try:
            link.symlink_to(target)
        except (NotImplementedError, OSError) as exc:
            self.skipTest(f"Symlink creation is unavailable: {exc}")
        ledger = read_json(ledger_path)
        ledger["independent_check"]["artifact"] = (
            "audit/05_adversarial/redirected-challenge.md"
        )
        ledger["independent_check"]["challenge_artifact_sha256"] = (
            proofcheck.sha256_file(target)
        )
        write_json(ledger_path, ledger)

        errors, _ = proofcheck.check_audit_finalization(self.audit)

        self.assertTrue(
            any(
                "challenge artifact" in error.lower()
                and "symlink" in error.lower()
                for error in errors
            ),
            errors,
        )

    def test_finalization_rejects_unbound_challenge_artifact(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        artifact = self.audit / ledger["independent_check"]["artifact"]
        artifact.write_text(
            "This file contains no structured challenge binding.\n",
            encoding="utf-8",
            newline="\n",
        )
        ledger["independent_check"]["challenge_artifact_sha256"] = (
            proofcheck.sha256_file(artifact)
        )
        write_json(ledger_path, ledger)

        errors, _ = proofcheck.check_audit_finalization(self.audit)

        self.assertTrue(
            any("challenge binding block" in error for error in errors),
            errors,
        )

    def test_finalization_rejects_challenge_judgment_tampering(self) -> None:
        ledger_path = self.make_complete_audit()
        original = read_json(ledger_path)
        cases = {
            "independence_level": "different_model",
            "reconciled_verdict": "invalid",
            "disagreements": ["The challenger now disputes the final verdict."],
            "resolution": "The primary verdict was retained after reconciliation.",
            "artifact": "audit/05_adversarial/copied-challenge.md",
            "generated_utc": "2099-01-01T00:00:00Z",
        }
        for field, value in cases.items():
            with self.subTest(field=field):
                ledger = json.loads(json.dumps(original))
                ledger["independent_check"][field] = value
                if field == "artifact":
                    original_artifact = (
                        self.audit
                        / original["independent_check"]["artifact"]
                    )
                    copied_artifact = self.audit / str(value)
                    shutil.copyfile(original_artifact, copied_artifact)
                write_json(ledger_path, ledger)

                errors, _ = proofcheck.check_audit_finalization(self.audit)

                self.assertTrue(
                    any(
                        "challenge binding block disagrees" in error
                        for error in errors
                    ),
                    errors,
                )

    def test_bind_challenge_derives_bookkeeping_and_writes_exact_binding(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        challenge = ledger["independent_check"]
        artifact = self.audit / challenge["artifact"]
        challenge.update(
            {
                "required": False,
                "status": "not_required",
                "reconciled_verdict": "verified",
                "covered_issue_ids": [],
                "source_snapshot_sha256": "",
                "challenged_ledger_sha256": "",
                "challenge_context_sha256": "",
                "challenge_artifact_sha256": "",
                "generated_utc": "",
            }
        )
        write_json(ledger_path, ledger)
        artifact.write_text(
            "# Independent challenge\n\nThe exact packet was checked.\n",
            encoding="utf-8",
            newline="\n",
        )

        with contextlib.redirect_stdout(io.StringIO()):
            status = proofcheck.cmd_bind_challenge(
                argparse.Namespace(root=self.audit, unit_id="lem:main")
            )

        self.assertEqual(0, status)
        ledger = read_json(ledger_path)
        challenge = ledger["independent_check"]
        manifest = read_json(self.audit / "AUDIT_MANIFEST.json")
        packet = proofcheck.build_context_packet(
            self.audit, "lem:main", "challenge"
        )
        self.assertTrue(challenge["required"])
        self.assertEqual("agreed", challenge["status"])
        self.assertEqual("verified", challenge["reconciled_verdict"])
        self.assertEqual([], challenge["covered_issue_ids"])
        self.assertEqual(
            manifest["source_snapshot"]["sha256"],
            challenge["source_snapshot_sha256"],
        )
        self.assertEqual(
            packet["context_binding_sha256"],
            challenge["challenge_context_sha256"],
        )
        self.assertTrue(proofcheck.is_utc_timestamp(challenge["generated_utc"]))
        self.assertEqual(
            proofcheck.sha256_file(artifact),
            challenge["challenge_artifact_sha256"],
        )
        self.assertEqual(
            [],
            proofcheck.challenge_artifact_binding_errors(
                artifact, "lem:main", challenge
            ),
        )

    def test_bind_challenge_rejects_malformed_blocks_without_mutation(
        self,
    ) -> None:
        ledger_path = self.make_complete_audit()
        baseline_ledger = ledger_path.read_bytes()
        ledger = read_json(ledger_path)
        artifact = self.audit / ledger["independent_check"]["artifact"]
        valid_block = proofcheck.render_challenge_artifact_binding(
            "lem:main", ledger["independent_check"]
        )
        challenge_template = (
            SCRIPT.parents[1]
            / "assets"
            / "templates"
            / "CHALLENGE_ARTIFACT.md"
        ).read_text(encoding="utf-8")
        cases = (
            (
                "unterminated",
                "# Challenge\n\n<!-- proofcheck-challenge-binding-v1\n{}\n",
                "unterminated",
            ),
            (
                "duplicate",
                f"# Challenge\n\n{valid_block}\n\n{valid_block}\n",
                "duplicate",
            ),
            (
                "binding_only",
                f"{valid_block}\n",
                "substantive checking narrative",
            ),
            (
                "heading_only",
                f"# Challenge\n\n{valid_block}\n",
                "substantive checking narrative",
            ),
            (
                "untouched_scaffold",
                challenge_template,
                "NONFINAL challenge scaffold",
            ),
            (
                "scaffold_marker_deleted",
                challenge_template.replace(
                    proofcheck.CHALLENGE_ARTIFACT_SCAFFOLD_MARKER,
                    "",
                ),
                "substantive checking narrative",
            ),
            (
                "scaffold_marker_case_changed",
                challenge_template.replace(
                    proofcheck.CHALLENGE_ARTIFACT_SCAFFOLD_MARKER,
                    proofcheck.CHALLENGE_ARTIFACT_SCAFFOLD_MARKER.lower(),
                ),
                "substantive checking narrative",
            ),
        )
        for name, artifact_text, message in cases:
            with self.subTest(case=name):
                artifact.write_text(
                    artifact_text, encoding="utf-8", newline="\n"
                )
                baseline_artifact = artifact.read_bytes()

                with self.assertRaisesRegex(ValueError, message):
                    proofcheck.cmd_bind_challenge(
                        argparse.Namespace(
                            root=self.audit, unit_id="lem:main"
                        )
                    )

                self.assertEqual(baseline_artifact, artifact.read_bytes())
                self.assertEqual(baseline_ledger, ledger_path.read_bytes())

    def test_bind_challenge_rejects_interleaved_edits(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        artifact = self.audit / ledger["independent_check"]["artifact"]
        ledger_baseline = ledger_path.read_bytes()
        artifact_baseline = artifact.read_bytes()
        for selected in ("ledger", "artifact"):
            with self.subTest(selected=selected):
                ledger_path.write_bytes(ledger_baseline)
                artifact.write_bytes(artifact_baseline)
                ledger_bytes = ledger_path.read_bytes()
                artifact_bytes = artifact.read_bytes()
                selected_path = (
                    ledger_path if selected == "ledger" else artifact
                )
                interleaved_bytes = selected_path.read_bytes() + b" "
                original_transaction = proofcheck.transactional_write_texts

                def edit_before_commit(
                    writes: list, **kwargs: object
                ) -> None:
                    self.assertTrue(
                        proofcheck.migration_update_lock_path(
                            self.audit
                        ).is_file()
                    )
                    selected_path.write_bytes(interleaved_bytes)
                    original_transaction(writes, **kwargs)

                with mock.patch.object(
                    proofcheck,
                    "transactional_write_texts",
                    side_effect=edit_before_commit,
                ):
                    with self.assertRaisesRegex(
                        ValueError,
                        "Transactional baseline changed before commit",
                    ):
                        proofcheck.cmd_bind_challenge(
                            argparse.Namespace(
                                root=self.audit, unit_id="lem:main"
                            )
                        )

                self.assertEqual(
                    interleaved_bytes, selected_path.read_bytes()
                )
                other_path = artifact if selected == "ledger" else ledger_path
                other_bytes = (
                    artifact_bytes if selected == "ledger" else ledger_bytes
                )
                self.assertEqual(other_bytes, other_path.read_bytes())
                self.assertFalse(
                    proofcheck.migration_update_lock_path(
                        self.audit
                    ).exists()
                )

    def test_bind_challenge_rejects_a_concurrent_proofcheck_update(
        self,
    ) -> None:
        ledger_path = self.make_complete_audit()
        ledger_bytes = ledger_path.read_bytes()
        ledger = read_json(ledger_path)
        artifact = self.audit / ledger["independent_check"]["artifact"]
        artifact_bytes = artifact.read_bytes()
        lock, lock_payload = proofcheck.acquire_migration_update_lock(
            self.audit, "concurrent-proofcheck-update"
        )
        try:
            with self.assertRaisesRegex(
                ValueError, "audit migration is in progress"
            ):
                proofcheck.cmd_bind_challenge(
                    argparse.Namespace(
                        root=self.audit, unit_id="lem:main"
                    )
                )
            self.assertEqual(ledger_bytes, ledger_path.read_bytes())
            self.assertEqual(artifact_bytes, artifact.read_bytes())
        finally:
            proofcheck.release_migration_update_lock(lock, lock_payload)

    def test_simultaneous_bind_challenge_keeps_one_consistent_commit(
        self,
    ) -> None:
        self.make_complete_audit()
        barrier = threading.Barrier(2)
        original_acquire = proofcheck.acquire_migration_update_lock

        def synchronized_acquire(
            root: Path, command: str
        ) -> tuple[Path, bytes]:
            barrier.wait(timeout=10)
            return original_acquire(root, command)

        def run_bind() -> tuple[str, str]:
            try:
                status = proofcheck.cmd_bind_challenge(
                    argparse.Namespace(
                        root=self.audit, unit_id="lem:main"
                    )
                )
                return "written", str(status)
            except ValueError as exc:
                return "rejected", str(exc)

        with mock.patch.object(
            proofcheck,
            "acquire_migration_update_lock",
            side_effect=synchronized_acquire,
        ), mock.patch("builtins.print"):
            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(lambda _: run_bind(), range(2)))

        self.assertEqual(
            ["rejected", "written"],
            sorted(status for status, _ in results),
        )
        self.assertFalse(
            proofcheck.migration_update_lock_path(self.audit).exists()
        )
        errors, _ = proofcheck.check_audit_finalization(self.audit)
        self.assertEqual([], errors)

    def test_challenge_narrative_requires_a_concise_rationale(self) -> None:
        for text in (
            "Checked",
            "Verified",
            "Challenge\n=========",
            "<br>",
        ):
            with self.subTest(text=text):
                self.assertFalse(
                    proofcheck.has_substantive_challenge_narrative(text)
                )
        self.assertTrue(
            proofcheck.has_substantive_challenge_narrative(
                "Every inferential step was independently checked."
            )
        )

    def test_finalization_gives_rebind_action_for_v1_challenge_binding(
        self,
    ) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        challenge = ledger["independent_check"]
        artifact = self.audit / challenge["artifact"]
        old_payload = {
            "schema_version": 1,
            "unit_id": "lem:main",
            "challenge_context_sha256": challenge[
                "challenge_context_sha256"
            ],
            "challenger_verdict": challenge["challenger_verdict"],
            "issue_assessments": [],
        }
        artifact.write_text(
            "# Independent challenge\n\n"
            "The exact packet was checked independently.\n\n"
            f"{proofcheck.LEGACY_CHALLENGE_BINDING_BEGIN}\n"
            f"{json.dumps(old_payload, indent=2)}\n"
            f"{proofcheck.CHALLENGE_BINDING_END}\n",
            encoding="utf-8",
            newline="\n",
        )
        challenge["challenge_artifact_sha256"] = proofcheck.sha256_file(
            artifact
        )
        write_json(ledger_path, ledger)

        errors, _ = proofcheck.check_audit_finalization(self.audit)

        self.assertTrue(
            any(
                "obsolete v1 challenge binding" in error
                and "bind-challenge" in error
                for error in errors
            ),
            errors,
        )

    def test_bind_challenge_escapes_comment_delimiter_in_assessment(
        self,
    ) -> None:
        ledger_path, _, _ = self.make_ledger_move_defect_audit()
        issue_path = self.audit / "audit" / "06_reports" / "ISSUE_LOG.json"
        issue_log = read_json(issue_path)
        issue_log["issues"][0]["severity"] = "S1"
        issue_log["issues"][0]["repair_search"] = make_repair_search("S1")
        write_json(issue_path, issue_log)
        progress_path = self.audit / "PROGRESS.json"
        progress = read_json(progress_path)
        progress["open_high_priority_issues"] = ["I-001"]
        write_json(progress_path, progress)
        self.seal_schema5_challenge(
            ledger_path,
            read_json(ledger_path),
            covered_issue_ids=["I-001"],
        )
        ledger = read_json(ledger_path)
        assessment = ledger["independent_check"]["issue_assessments"][0]
        assessment["target_assessment"] = (
            "The implication A --> B was independently checked."
        )
        write_json(ledger_path, ledger)

        with contextlib.redirect_stdout(io.StringIO()):
            status = proofcheck.cmd_bind_challenge(
                argparse.Namespace(root=self.audit, unit_id="lem:main")
            )

        self.assertEqual(0, status)
        ledger = read_json(ledger_path)
        challenge = ledger["independent_check"]
        artifact = self.audit / challenge["artifact"]
        artifact_text = artifact.read_text(encoding="utf-8")
        self.assertIn("--\\u003e", artifact_text)
        self.assertEqual(1, artifact_text.count("-->"))
        self.assertEqual(
            [],
            proofcheck.challenge_artifact_binding_errors(
                artifact, "lem:main", challenge
            ),
        )
        self.sync_incorrect_main_report(ledger_path)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(
            io.StringIO()
        ):
            issue_status = proofcheck.cmd_issues(
                argparse.Namespace(
                    root=self.audit,
                    write_summary=True,
                    write_report_views=True,
                    final=True,
                )
            )
        self.assertEqual(0, issue_status)
        errors, _ = proofcheck.check_audit_finalization(self.audit)
        self.assertEqual([], errors)

    def test_progress_gate_rejects_empty_challenge_artifact(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        artifact = self.audit / ledger["independent_check"]["artifact"]
        artifact.write_bytes(b"")
        ledger["independent_check"]["challenge_artifact_sha256"] = (
            proofcheck.sha256_file(artifact)
        )
        write_json(ledger_path, ledger)
        manifest = read_json(self.audit / "AUDIT_MANIFEST.json")
        _, summaries, _ = proofcheck.audit_ledgers(self.audit, True)
        summaries_by_id = {row["unit_id"]: row for row in summaries}
        issues = read_json(
            self.audit / "audit" / "06_reports" / "ISSUE_LOG.json"
        )["issues"]

        self.assertFalse(
            proofcheck.independent_checks_complete(
                self.audit, manifest, summaries_by_id, issues
            )
        )

    def test_progress_gate_rejects_binding_only_challenge_artifact(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        challenge = ledger["independent_check"]
        artifact = self.audit / challenge["artifact"]
        artifact.write_text(
            proofcheck.render_challenge_artifact_binding(
                "lem:main", challenge
            )
            + "\n",
            encoding="utf-8",
            newline="\n",
        )
        challenge["challenge_artifact_sha256"] = proofcheck.sha256_file(
            artifact
        )
        write_json(ledger_path, ledger)
        manifest = read_json(self.audit / "AUDIT_MANIFEST.json")
        _, summaries, _ = proofcheck.audit_ledgers(self.audit, True)
        summaries_by_id = {row["unit_id"]: row for row in summaries}
        issues = read_json(
            self.audit / "audit" / "06_reports" / "ISSUE_LOG.json"
        )["issues"]

        self.assertFalse(
            proofcheck.independent_checks_complete(
                self.audit, manifest, summaries_by_id, issues
            )
        )

    def test_challenge_dependency_projection_excludes_primary_verdicts(
        self,
    ) -> None:
        ledger_path = self.make_complete_audit()
        self.install_internal_dependency(ledger_path)

        challenge = proofcheck.build_context_packet(
            self.audit, "lem:main", "challenge"
        )
        primary = proofcheck.build_context_packet(
            self.audit, "lem:main", "primary"
        )
        challenge_dependencies = json.dumps(
            challenge["dependencies"], ensure_ascii=False
        )
        primary_dependencies = json.dumps(
            primary["dependencies"], ensure_ascii=False
        )
        for forbidden in (
            "source_status",
            "status",
            "compatibility_check",
            "compatibility_checks",
            "issue_ids",
        ):
            self.assertNotIn(f'"{forbidden}"', challenge_dependencies)
        self.assertIn('"source_status"', primary_dependencies)
        self.assertIn('"compatibility_checks"', primary_dependencies)

    def test_dependency_finding_uses_plain_derived_final_closure(
        self,
    ) -> None:
        self.make_dependency_mismatch_audit()
        output = io.StringIO()
        errors = io.StringIO()

        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            status = proofcheck.cmd_issues(
                argparse.Namespace(
                    root=self.audit,
                    write_summary=True,
                    write_report_views=True,
                    final=True,
                )
            )
        payload = json.loads(output.getvalue())
        self.assertEqual(0, status, errors.getvalue())
        self.assertEqual("", errors.getvalue())
        self.assertTrue(payload["report_views_written"])

        report = (
            self.audit / "audit" / "06_reports" / "FINAL_REPORT.md"
        ).read_text(encoding="utf-8")
        details = proofcheck.report_section(
            report, "## Findings and repairs"
        ) or ""
        self.assertIn("dependency use D001", details)
        self.assertIn("dependency source status is verified", details)
        self.assertIn("use-site applicability is incorrect", details)
        self.assertIn("effective dependency status is incorrect", details)
        self.assertIn(
            "quantifiers_and_domains is incorrect: The dependency conclusion "
            "has the wrong quantified domain at this use site.",
            details,
        )
        self.assertNotIn('"source_status"', details)
        self.assertNotIn('"nonpassing_compatibility_checks"', details)

        final_errors, _ = proofcheck.check_audit_finalization(self.audit)
        self.assertEqual([], final_errors)

    def test_external_dependency_finding_preserves_exact_failure_evidence(
        self,
    ) -> None:
        compatibility_failure = {
            "aspect": "quantifiers_and_domains",
            "status": "incorrect",
            "evidence": "The cited result quantifies only over bounded x.",
            "issue_ids": ["I-001"],
        }
        prerequisite_failure = {
            "prerequisite": "The manuscript variable x is bounded.",
            "status": "incorrect",
            "manuscript_evidence": (
                "The theorem statement instead permits every real x."
            ),
            "evidence_spans": [
                {
                    "file": "paper.tex",
                    "start_line": 2,
                    "end_line": 4,
                    "sha256": "1" * 64,
                    "role": "manuscript_prerequisite",
                }
            ],
            "issue_ids": ["I-001"],
        }
        source_evidence = [
            {
                "file": "external-result.txt",
                "sha256": "2" * 64,
                "locator": "Theorem 2, page 7",
                "role": "authoritative_theorem_source",
            }
        ]
        issue = {
            "id": "I-001",
            "affected_result": "lem:main",
            "affected_results": ["lem:main"],
            "status": "open",
            "severity": "S1",
            "confidence": "high",
            "load_bearing": True,
            "invalidation_kind": "dependency_mismatch",
            "origin_ref": {
                "kind": "dependency_use",
                "unit_id": "lem:main",
                "use_id": "D001",
            },
            "contract_refs": [],
            "suggested_changes": [],
        }
        summaries = {
            "lem:main": {
                "result_dependency_claims": [{"use_id": "D001"}],
                "direct_dependencies": [
                    {
                        "id": "ext:bounded",
                        "use_id": "D001",
                        "needed_form": "The claim holds for every real x.",
                        "compatibility_check": (
                            "The cited and needed domains must agree."
                        ),
                        "status": "incorrect",
                    }
                ],
                "review_components": {},
                "conclusion_results": [],
            }
        }
        dependency_edges = [
            {
                "dependent_unit": "lem:main",
                "use_id": "D001",
                "dependency_id": "ext:bounded",
                "dependency_conclusion_id": None,
                "kind": "external_result",
                "source_status": "incorrect",
                "applicability_status": "incorrect",
                "effective_status": "incorrect",
                "issue_ids": ["I-001"],
                "compatibility_checks": [
                    {
                        "aspect": "object_identity",
                        "status": "passed",
                        "evidence": "The same variable x is used.",
                        "issue_ids": [],
                    },
                    compatibility_failure,
                ],
                "prerequisite_map": [
                    {
                        "prerequisite": "The object is real-valued.",
                        "status": "satisfied",
                        "manuscript_evidence": "The statement declares x real.",
                        "evidence_spans": [],
                        "issue_ids": [],
                    },
                    prerequisite_failure,
                ],
                "source_evidence": source_evidence,
            }
        ]

        projection = proofcheck.canonical_issue_detail_projection(
            issue,
            summaries,
            dependency_edges,
            [],
            [],
            "defects_found",
        )

        self.assertEqual(
            json.dumps(
                {
                    "source_status": "incorrect",
                    "applicability_status": "incorrect",
                    "effective_status": "incorrect",
                    "issue_ids": ["I-001"],
                    "nonpassing_compatibility_checks": [
                        compatibility_failure
                    ],
                    "nonpassing_prerequisites": [prerequisite_failure],
                    "source_evidence": source_evidence,
                },
                ensure_ascii=False,
            ),
            projection["failure"][0][8],
        )

    def test_finding_heading_preserves_vertical_bar(self) -> None:
        self.make_complete_audit()
        summary = "The first and second | clauses form one summary."
        issue = self.make_global_issue(
            load_bearing=False,
            severity="S3",
            summary=summary,
        )
        self.install_canonical_issue(issue)

        errors, _ = proofcheck.check_audit_finalization(self.audit)
        report_path = self.audit / "audit" / "06_reports" / "FINAL_REPORT.md"
        section = proofcheck.report_section(
            report_path.read_text(encoding="utf-8"),
            "## Findings and repairs",
        )

        self.assertEqual([], errors)
        self.assertIn(f"### I-001 [S3] {summary}", section or "")

    def test_global_check_finding_projects_exact_canonical_status_evidence(
        self,
    ) -> None:
        self.make_complete_audit()
        _, summaries, _ = proofcheck.audit_ledgers(self.audit, True)
        summaries_by_id = {
            summary["unit_id"]: summary for summary in summaries
        }
        aspect = "constants_and_rates"
        check = {
            "aspect": aspect,
            "status": "defect",
            "evidence": (
                "Distinctive global evidence: the n^-1 rate was substituted "
                "for the required n^-1/2 rate."
            ),
            "affected_units": ["lem:main"],
            "issue_ids": ["I-001"],
        }
        issue = self.make_global_issue(
            finding_status="defect",
            summary="The global rate check records a canonical mismatch.",
        )
        issue["origin_ref"] = {
            "kind": "global_check",
            "aspect": aspect,
            "evidence_spans": [
                proofcheck.locked_span(
                    self.paper,
                    3,
                    3,
                    self.audit,
                    role="global_consistency_evidence",
                )
            ],
        }

        projection = proofcheck.canonical_issue_detail_projection(
            issue,
            summaries_by_id,
            [],
            ["lem:main"],
            [],
            "defects_found",
            global_checks={aspect: check},
        )
        failure_row = projection["failure"][0]

        self.assertEqual(
            {
                "affected_units": ["lem:main"],
                "aspect": aspect,
                "evidence": check["evidence"],
                "issue_ids": ["I-001"],
                "status": "defect",
            },
            json.loads(failure_row[8]),
        )
        self.assertEqual("defect", failure_row[9])
        self.assertEqual(
            {"affected_units": ["lem:main"]},
            json.loads(failure_row[7]),
        )

    def test_interface_finding_projects_exact_mismatch_statuses(self) -> None:
        self.make_complete_audit()
        _, summaries, _ = proofcheck.audit_ledgers(self.audit, True)
        summaries_by_id = {
            summary["unit_id"]: summary for summary in summaries
        }
        interface = self.make_interface_record(
            target_verdict="mismatch",
            code_to_documented="inconsistent",
            code_to_target="inconsistent",
            execution_provenance="not_matched",
            load_bearing=True,
            implementation_required=True,
            execution_required=True,
        )
        interface["issue_ids"] = ["I-001"]
        issue = self.make_global_issue(
            finding_status="defect",
            load_bearing=True,
            severity="S1",
            summary="The estimator implementation targets the wrong object.",
        )
        issue.update(
            {
                "interface_id": interface["id"],
                "finding_class": "implementation_mismatch",
                "affected_layer": "implementation_to_target",
                "origin_ref": {
                    "kind": "interface_record",
                    "interface_id": interface["id"],
                    "evidence_spans": interface[
                        "implementation_relation"
                    ]["evidence_spans"],
                },
            }
        )

        projection = proofcheck.canonical_issue_detail_projection(
            issue,
            summaries_by_id,
            [],
            ["lem:main"],
            [],
            "defects_found",
            interfaces={interface["id"]: interface},
        )
        failure_row = projection["failure"][0]
        evidence = json.loads(failure_row[8])

        self.assertEqual(
            interface["target_relation"], evidence["target_relation"]
        )
        self.assertEqual(
            interface["implementation_relation"],
            evidence["implementation_relation"],
        )
        self.assertEqual(["I-001"], evidence["issue_ids"])
        self.assertEqual(
            "mismatch", evidence["target_relation"]["verdict"]
        )
        comparisons = {
            row["to"]: row["verdict"]
            for row in evidence["implementation_relation"]["comparisons"]
        }
        self.assertEqual("inconsistent", comparisons["documented_estimator"])
        self.assertEqual("inconsistent", comparisons["required_target"])
        self.assertEqual(
            "not_matched",
            evidence["implementation_relation"]["execution_provenance"][
                "status"
            ],
        )
        self.assertEqual("implementation_mismatch", failure_row[9])

    def test_stored_cross_reference_json_must_match_fresh_scan(self) -> None:
        self.make_complete_audit()
        crossref_path = (
            self.audit / "audit" / "01_index" / "cross_reference_audit.json"
        )
        crossref = read_json(crossref_path)
        crossref["references"] = {}
        write_json(crossref_path, crossref)

        errors, _ = proofcheck.check_audit_finalization(self.audit)

        self.assertTrue(
            any("cross_reference_audit.json" in error for error in errors),
            errors,
        )

    def test_stored_cross_reference_markdown_must_match_json(self) -> None:
        self.make_complete_audit()
        crossref_path = (
            self.audit / "audit" / "01_index" / "cross_reference_audit.md"
        )
        crossref_path.write_text(
            "# Invented Cross-Reference Audit\n\nNo references.\n",
            encoding="utf-8",
            newline="\n",
        )

        errors, _ = proofcheck.check_audit_finalization(self.audit)

        self.assertTrue(
            any("cross_reference_audit.md" in error for error in errors),
            errors,
        )

    def test_final_report_rejects_certification_overclaim(self) -> None:
        self.make_complete_audit()
        report_path = self.audit / "audit" / "06_reports" / "FINAL_REPORT.md"
        report = report_path.read_text(encoding="utf-8").replace(
            "\n### Independent verification\n",
            "\nThis certifies the proof as correct.\n\n"
            "### Independent verification\n",
            1,
        )
        report_path.write_text(report, encoding="utf-8", newline="\n")
        errors, _ = proofcheck.check_audit_finalization(self.audit)
        self.assertTrue(
            any("unsupported proof-certification language" in error for error in errors),
            errors,
        )

    def test_final_report_rejects_formal_verification_overclaim(self) -> None:
        self.make_complete_audit()
        report_path = self.audit / "audit" / "06_reports" / "FINAL_REPORT.md"
        report = report_path.read_text(encoding="utf-8").replace(
            "\n### Independent verification\n",
            "\nThis is a formally verified proof.\n\n"
            "### Independent verification\n",
            1,
        )
        report_path.write_text(report, encoding="utf-8", newline="\n")
        errors, _ = proofcheck.check_audit_finalization(self.audit)
        self.assertTrue(
            any("unsupported formal-verification language" in error for error in errors),
            errors,
        )

    def test_multi_conclusion_support_is_ordered_and_complete(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        second = json.loads(
            json.dumps(ledger["obligation"]["conclusions"][0])
        )
        second["id"] = "C002"
        second["claim"] = "Every real x is identical to itself"
        ledger["obligation"]["conclusions"].append(second)

        first_step = ledger["steps"][2]
        second_step = json.loads(json.dumps(first_step))
        second_step["id"] = "S004"
        second_step["restatement"] = second["claim"]
        second_step["goal"] = "Record the equivalent verbal conclusion."
        second_step["dependencies"] = [
            {
                "id": "S003",
                "kind": "step",
                "status": "verified",
                "needed_form": first_step["restatement"],
                "compatibility_check": (
                    "The verbal conclusion restates the same reflexive equality."
                ),
            }
        ]
        second_step["premise_uses"] = [
            {
                "id": "P001",
                "role": "fact",
                "claim": first_step["restatement"],
                "origin": {"kind": "prior_step", "reference": "S003"},
                "evidence": (
                    "S003 establishes the symbolic reflexive equality first."
                ),
            }
        ]
        second_step["inference"] = {
            "moves": [
                {
                    "id": "M001",
                    "claim": second["claim"],
                    "rule": "Equivalent verbal restatement",
                    "premise_ids": ["P001"],
                    "prior_move_ids": [],
                    "justification": (
                        "Identity with itself is the verbal form of reflexivity."
                    ),
                }
            ],
            "conclusion_move": "M001",
        }
        second_step["checks"]["literal"] = (
            "The shared source line states the same reflexive equality."
        )
        ledger["steps"][3]["id"] = "S005"
        ledger["steps"].insert(3, second_step)
        second_result = json.loads(
            json.dumps(ledger["review"]["conclusion_results"][0])
        )
        second_result["conclusion_id"] = "C002"
        second_result["support"] = {"step_id": "S004", "move_id": "M001"}
        ledger["review"]["conclusion_results"].append(second_result)
        ledger["review"]["conclusion_step_id"] = ""
        write_json(ledger_path, ledger)
        self.seal_schema5_challenge(ledger_path, read_json(ledger_path))

        errors, _ = proofcheck.check_ledger_data(ledger_path, True)
        self.assertEqual([], errors)

        ledger["review"]["conclusion_results"].pop()
        write_json(ledger_path, ledger)
        errors, _ = proofcheck.check_ledger_data(ledger_path, True)
        self.assertTrue(
            any("omits conclusions: C002" in error for error in errors),
            errors,
        )

    def test_joint_side_condition_discharge_uses_all_sources(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        conclusion_step = ledger["steps"][2]
        domain_step = json.loads(json.dumps(conclusion_step))
        domain_step["restatement"] = (
            "x lies in the real-number equality domain"
        )
        domain_step["goal"] = "Establish the domain fact used by reflexivity."
        domain_step["inference"] = {
            "moves": [
                {
                    "id": "M001",
                    "claim": "x lies in the real-number equality domain",
                    "rule": "Domain extraction",
                    "premise_ids": ["P001"],
                    "prior_move_ids": [],
                    "justification": "P001 quantifies x over the real numbers.",
                }
            ],
            "conclusion_move": "M001",
        }
        domain_step["side_conditions"] = []

        conclusion_step = json.loads(json.dumps(conclusion_step))
        conclusion_step["id"] = "S004"
        conclusion_step["dependencies"] = [
            {
                "id": "S003",
                "kind": "step",
                "status": "verified",
                "needed_form": domain_step["restatement"],
                "compatibility_check": (
                    "The established domain is exactly the domain of equality."
                ),
            }
        ]
        conclusion_step["premise_uses"].append(
            {
                "id": "P002",
                "role": "fact",
                "claim": domain_step["restatement"],
                "origin": {"kind": "prior_step", "reference": "S003"},
                "evidence": "S003 supplies the exact real-domain fact.",
            }
        )
        conclusion_step["inference"] = {
            "moves": [
                {
                    "id": "M001",
                    "claim": conclusion_step["restatement"],
                    "rule": "Reflexivity of equality",
                    "premise_ids": ["P001", "P002"],
                    "prior_move_ids": [],
                    "justification": (
                        "The quantified real variable and established domain "
                        "jointly permit reflexivity."
                    ),
                },
            ],
            "conclusion_move": "M001",
        }
        conclusion_step["side_conditions"] = [
            {
                "id": "SC001",
                "generated_by": "M001",
                "condition": "The equality operation is defined for x.",
                "status": "discharged",
                "discharge": {
                    "sources": [
                        {
                            "kind": "premise",
                            "reference": "P001",
                            "contribution": "P001 supplies the real-number domain.",
                        },
                        {
                            "kind": "premise",
                            "reference": "P002",
                            "contribution": (
                                "P002 supplies the specialized domain fact."
                            ),
                        },
                    ],
                    "rule": (
                        "The quantified domain and its specialization jointly "
                        "establish definedness."
                    ),
                    "evidence": (
                        "Both recorded sources are needed for the explicit "
                        "domain discharge."
                    ),
                },
            }
        ]
        ledger["steps"][2] = domain_step
        ledger["steps"][3]["id"] = "S005"
        ledger["steps"].insert(3, conclusion_step)
        ledger["review"]["conclusion_step_id"] = "S004"
        ledger["review"]["conclusion_results"][0]["support"] = {
            "step_id": "S004",
            "move_id": "M001",
        }
        write_json(ledger_path, ledger)
        self.seal_schema5_challenge(ledger_path, read_json(ledger_path))

        errors, _ = proofcheck.check_ledger_data(ledger_path, True)
        self.assertEqual([], errors)

    def test_controlled_multiline_atomicity_requires_full_source_partition(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = self.downgrade_ledger_fixture_to_schema4(
            read_json(ledger_path)
        )
        del ledger["steps"][1]
        step = ledger["steps"][1]
        step["lines"] = [5, 6]
        step["checks"]["atomicity"] = {
            "status": "source_indivisible_chain",
            "source_unit_kind": "continued_sentence",
            "partition_evidence": (
                "The two adjacent source lines are treated as one continued unit."
            ),
            "evidence": "Each physical line is assigned to an atomic move.",
        }
        step["inference"] = {
            "moves": [
                {
                    "id": "M001",
                    "claim": "The proof environment opens the argument.",
                    "rule": "Proof setup",
                    "premise_ids": ["P001"],
                    "prior_move_ids": [],
                    "source_line_range": [5, 5],
                    "justification": "The first line establishes the proof context.",
                },
                {
                    "id": "M002",
                    "claim": step["restatement"],
                    "rule": "Reflexivity of equality",
                    "premise_ids": [],
                    "prior_move_ids": ["M001"],
                    "source_line_range": [6, 6],
                    "justification": "The second line states the reflexive conclusion.",
                },
            ],
            "conclusion_move": "M002",
        }
        ledger["review"]["conclusion_results"][0]["support"]["move_id"] = "M002"
        write_json(ledger_path, ledger)

        errors, _ = proofcheck.check_ledger_data(ledger_path, False)
        self.assertEqual([], errors)

        step["inference"]["moves"][1]["source_line_range"] = [5, 5]
        write_json(ledger_path, ledger)
        errors, _ = proofcheck.check_ledger_data(ledger_path, True)
        self.assertTrue(
            any(
                "do not represent every covered source line" in error
                for error in errors
            ),
            errors,
        )

    def test_prior_step_source_anchor_binds_exact_occurrence(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        prior = ledger["steps"][0]
        self.record_domain_introduction(ledger, prior)
        dependency = {
            "id": "S001",
            "kind": "step",
            "status": "verified",
            "needed_form": prior["restatement"],
            "compatibility_check": (
                "The prior setup is used in exactly its recorded form."
            ),
        }
        step = ledger["steps"][2]
        step["dependencies"] = [dependency]
        premise = step["premise_uses"][0]
        premise["claim"] = prior["restatement"]
        premise["origin"] = {"kind": "prior_step", "reference": "S001"}
        disposition = ledger["review"]["source_reference_dispositions"][0]
        premise["source_reference_id"] = disposition["target"]
        premise["source_reference_occurrence_id"] = disposition["occurrence_id"]
        disposition["disposition"] = "local_step"
        disposition["premise_links"] = [
            {"step_id": "S003", "premise_id": "P001"}
        ]
        disposition["evidence"] = (
            "The exact proof occurrence names the label inside the earlier setup."
        )
        write_json(ledger_path, ledger)
        self.seal_schema5_challenge(ledger_path, read_json(ledger_path))

        errors, _ = proofcheck.check_ledger_data(ledger_path, True)
        self.assertEqual([], errors)

    def test_occurrence_disposition_cannot_be_reused_for_another_occurrence(self) -> None:
        ledger_path = self.make_complete_audit()
        ledger = read_json(ledger_path)
        ledger["review"]["source_reference_dispositions"][0][
            "occurrence_id"
        ] = "R-deadbeefdeadbeef"
        write_json(ledger_path, ledger)

        errors, _ = proofcheck.check_audit_finalization(self.audit)
        self.assertTrue(
            any(
                "source occurrences lack reviewed dispositions" in error
                for error in errors
            ),
            errors,
        )
        self.assertTrue(
            any(
                "source-reference dispositions are not present" in error
                for error in errors
            ),
            errors,
        )

    def test_reviewed_proof_evidence_must_match_canonical_rescan(self) -> None:
        self.make_complete_audit()
        inventory_path = (
            self.audit / "audit" / "01_index" / "theorem_inventory.json"
        )
        inventory = read_json(inventory_path)
        inventory["units"][0]["reference_occurrences"] = []
        write_json(inventory_path, inventory)
        self.refresh_dependency_review()

        errors, _ = proofcheck.check_audit_finalization(self.audit)
        self.assertTrue(
            any(
                "reference_occurrences disagrees with the canonical rescan"
                in error
                for error in errors
            ),
            errors,
        )

    def test_explicit_proof_rejection_requires_exact_overrides(self) -> None:
        ledger_path = self.make_complete_audit()
        inventory_path = (
            self.audit / "audit" / "01_index" / "theorem_inventory.json"
        )
        inventory = read_json(inventory_path)
        unit = inventory["units"][0]
        parser_proof = proofcheck.canonical_location(unit["proof"])
        parser_association = json.loads(
            json.dumps(unit["proof_association"])
        )
        reviewed_association = {
            "status": "rejected",
            "method": "reviewed_rejection",
            "target": "lem:main",
            "evidence_occurrence_ids": [],
        }
        unit["proof"] = None
        unit["proof_redirects"] = []
        unit["proof_association"] = reviewed_association
        unit["reference_occurrences"] = []
        unit["dependencies"] = []
        unit["candidate_internal_dependencies"] = []
        unit["citations"] = []
        write_json(inventory_path, inventory)

        ledger = read_json(ledger_path)
        ledger["review"]["source_reference_dispositions"] = []
        ledger["review"]["citation_dispositions"] = []
        write_json(ledger_path, ledger)
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        manifest["audit_scope"]["inventory_overrides"] = [
            {
                "unit_id": "lem:main",
                "kind": "proof_location",
                "parser_proof": parser_proof,
                "reviewed_proof": None,
                "reviewed_proof_sha256": None,
                "association_method": "reviewed_rejection",
                "reason": "Rendered review rejects the parser-associated proof.",
                "evidence": "The reviewed unit intentionally has no accepted proof.",
            },
            {
                "unit_id": "lem:main",
                "kind": "proof_association",
                "parser_association": parser_association,
                "reviewed_association": reviewed_association,
                "rendered_source_evidence": (
                    "Rendered source confirms that the associated span is rejected."
                ),
                "reason": "The parser candidate is not accepted as this proof.",
                "evidence": "The rejection is explicit and source reviewed.",
            },
        ]
        write_json(manifest_path, manifest)
        self.refresh_dependency_review()

        errors, _ = proofcheck.check_audit_finalization(self.audit)
        self.assertTrue(
            any(
                "proof-required result has no inventoried proof range" in error
                for error in errors
            ),
            errors,
        )
        self.assertFalse(
            any("lack explicit overrides" in error for error in errors),
            errors,
        )

    def test_manual_unit_override_hash_is_fail_closed(self) -> None:
        ledger_path = self.make_complete_audit()
        self.install_internal_dependency(ledger_path)
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        manifest["audit_scope"]["inventory_overrides"][0][
            "reviewed_unit_sha256"
        ] = "0" * 64
        write_json(manifest_path, manifest)

        errors, _ = proofcheck.check_audit_finalization(self.audit)
        self.assertTrue(
            any("reviewed_unit_sha256 is stale" in error for error in errors),
            errors,
        )

    def test_internal_use_must_name_the_exact_dependency_conclusion(self) -> None:
        ledger_path = self.make_complete_audit()
        self.install_internal_dependency(ledger_path)
        registry_path = (
            self.audit
            / "audit"
            / "03_dependencies"
            / "DEPENDENCY_REGISTRY.json"
        )
        registry = read_json(registry_path)
        registry["internal_uses"][0]["dependency_conclusion_id"] = "C002"
        write_json(registry_path, registry)

        errors, _ = proofcheck.check_audit_finalization(self.audit)
        self.assertTrue(
            any(
                "dependency_conclusion_id disagrees with the invoking ledger"
                in error
                for error in errors
            ),
            errors,
        )
        self.assertTrue(
            any("unknown dependency conclusion C002" in error for error in errors),
            errors,
        )

    def test_focused_scope_must_equal_exact_target_closure(self) -> None:
        ledger_path = self.make_complete_audit()
        self.install_internal_dependency(ledger_path)
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        manifest["audit_scope"]["target_units"] = ["lem:prior"]
        manifest["audit_scope"]["critical_units"] = ["lem:prior"]
        write_json(manifest_path, manifest)
        report_path = self.audit / "audit" / "06_reports" / "FINAL_REPORT.md"
        report = report_path.read_text(encoding="utf-8").replace(
            "- Target results: lem:main",
            "- Target results: lem:prior",
        )
        report_path.write_text(report, encoding="utf-8", newline="\n")

        errors, _ = proofcheck.check_audit_finalization(self.audit)
        self.assertTrue(
            any(
                "includes units outside the exact target closure" in error
                for error in errors
            ),
            errors,
        )

    def test_status_preflight_is_populated_without_a_finalization_record(self) -> None:
        complete_output = io.StringIO()
        self.make_complete_audit()
        with contextlib.redirect_stdout(complete_output):
            complete_status = proofcheck.cmd_status(
                argparse.Namespace(
                    root=self.audit,
                    format="json",
                    output=None,
                    force=False,
                )
            )
        complete = json.loads(complete_output.getvalue())["finalization"]
        self.assertEqual(0, complete_status)
        self.assertEqual("passed", complete["preflight_status"])
        self.assertTrue(complete["finalizable_now"])
        self.assertEqual([], complete["current_gate_errors"])

        incomplete_output = io.StringIO()
        incomplete_root = self.base / "incomplete-audit"
        with contextlib.redirect_stdout(io.StringIO()):
            proofcheck.cmd_scaffold(
                argparse.Namespace(paper=self.paper, output=incomplete_root)
            )
        with contextlib.redirect_stdout(incomplete_output):
            incomplete_status = proofcheck.cmd_status(
                argparse.Namespace(
                    root=incomplete_root,
                    format="json",
                    output=None,
                    force=False,
                )
            )
        incomplete = json.loads(incomplete_output.getvalue())["finalization"]
        self.assertEqual(0, incomplete_status)
        self.assertEqual("failed", incomplete["preflight_status"])
        self.assertFalse(incomplete["finalizable_now"])
        self.assertTrue(incomplete["current_gate_errors"])

    def test_unresolved_named_proof_does_not_fall_through_to_adjacency(self) -> None:
        cases = {
            "ambiguous": (
                "Proof of \\ref{thm:first} and \\ref{thm:second}"
            ),
            "unresolved": "Proof of \\ref{thm:missing}",
        }
        for case, title in cases.items():
            with self.subTest(case=case):
                source = self.base / f"named-{case}.tex"
                source.write_text(
                    "\\newtheorem{theorem}{Theorem}\n"
                    "\\begin{theorem}\\label{thm:first}\nFirst.\n"
                    "\\end{theorem}\n"
                    "\\begin{theorem}\\label{thm:second}\nSecond.\n"
                    "\\end{theorem}\n"
                    f"\\begin{{proof}}[{title}]\n"
                    "A proof body.\n"
                    "\\end{proof}\n",
                    encoding="utf-8",
                    newline="\n",
                )

                inventory = proofcheck.scan_formal_units(source)
                units = {unit["id"]: unit for unit in inventory["units"]}

                self.assertIsNone(units["thm:first"]["proof"])
                self.assertIsNone(units["thm:second"]["proof"])
                self.assertTrue(
                    any(
                        "Named proof header does not resolve to exactly one"
                        in warning
                        for warning in inventory["warnings"]
                    ),
                    inventory,
                )
                self.assertFalse(
                    any(
                        unit["proof_association"]["method"]
                        == "adjacent_environment"
                        for unit in units.values()
                    ),
                    inventory,
                )

    def test_multiline_proof_title_uses_exact_header_location(self) -> None:
        source = self.base / "multiline-proof-title.tex"
        source.write_text(
            "\\newtheorem{theorem}{Theorem}\n"
            "\\begin{theorem}\\label{thm:first}\nFirst.\n"
            "\\end{theorem}\n"
            "\\begin{theorem}\\label{thm:second}\nSecond.\n"
            "\\end{theorem}\n"
            "\\begin{proof}[\n"
            "Proof of \\ref{thm:first}] Body uses \\ref{thm:second}.\n"
            "\\end{proof}\n",
            encoding="utf-8",
            newline="\n",
        )

        inventory = proofcheck.scan_formal_units(source)
        first = next(
            unit for unit in inventory["units"] if unit["id"] == "thm:first"
        )
        occurrences = {
            occurrence["target"]: occurrence
            for occurrence in first["reference_occurrences"]
        }

        self.assertEqual("named_environment", first["proof_association"]["method"])
        self.assertEqual("proof_header", occurrences["thm:first"]["structural_context"])
        self.assertEqual("proof_body", occurrences["thm:second"]["structural_context"])
        self.assertEqual(["thm:second"], first["candidate_internal_dependencies"])

    def test_named_proof_heading_resolves_balanced_hyperref_target(self) -> None:
        source = self.base / "named-proof-hyperref.tex"
        source.write_text(
            "\\newtheorem{theorem}{Theorem}\n"
            "\\begin{theorem}\\label{thm:x}\n"
            "Claim.\n"
            "\\end{theorem}\n"
            "\\begin{proof}[Proof of \\hyperref[thm:x]{Theorem 1}]\n"
            "Proof body.\n"
            "\\end{proof}\n",
            encoding="utf-8",
            newline="\n",
        )

        inventory = proofcheck.scan_formal_units(source)
        unit = inventory["units"][0]

        self.assertEqual("thm:x", unit["id"])
        self.assertEqual(
            {
                "file": source.name,
                "start_line": 5,
                "end_line": 7,
            },
            unit["proof"],
        )
        self.assertEqual("associated", unit["proof_association"]["status"])
        self.assertEqual(
            "named_environment", unit["proof_association"]["method"]
        )
        self.assertEqual("thm:x", unit["proof_association"]["target"])
        occurrence = next(
            row
            for row in unit["reference_occurrences"]
            if row["command"] == "hyperref"
        )
        self.assertEqual("proof_header", occurrence["structural_context"])
        self.assertEqual([], inventory["warnings"], inventory)

    def test_named_proof_section_accepts_optional_short_title(self) -> None:
        source = self.base / "named-proof-short-title.tex"
        source.write_text(
            "\\newtheorem{theorem}{Theorem}\n"
            "\\begin{theorem}\\label{thm:x}\n"
            "Claim.\n"
            "\\end{theorem}\n"
            "\\subsection[Short proof title]{Proof of Theorem \\ref{thm:x}}\n"
            "\\begin{proof}\n"
            "Proof body.\n"
            "\\end{proof}\n",
            encoding="utf-8",
            newline="\n",
        )

        inventory = proofcheck.scan_formal_units(source)
        unit = inventory["units"][0]

        self.assertEqual(
            {"file": source.name, "start_line": 6, "end_line": 8},
            unit["proof"],
        )
        self.assertEqual("named_heading", unit["proof_association"]["method"])
        self.assertTrue(
            unit["proof_association"]["evidence_occurrence_ids"], inventory
        )
        self.assertEqual([], inventory["warnings"], inventory)

    def test_named_section_can_target_one_unnamed_proof_among_named_proofs(
        self,
    ) -> None:
        source = self.base / "named-section-multiple-proof-environments.tex"
        source.write_text(
            "\\newtheorem{theorem}{Theorem}\n"
            "\\newtheorem{corollary}{Corollary}\n"
            "\\begin{theorem}\\label{thm:x}\n"
            "The theorem claim.\n"
            "\\end{theorem}\n"
            "\\begin{corollary}\\label{cor:y}\n"
            "The corollary claim.\n"
            "\\end{corollary}\n"
            "\\subsection{Proof of Theorem \\ref{thm:x}}\n"
            "We first prove the theorem and then its corollary.\n"
            "\\begin{proof}\n"
            "The theorem proof.\n"
            "\\end{proof}\n"
            "\\begin{proof}[Proof of Corollary \\ref{cor:y}]\n"
            "The corollary proof.\n"
            "\\end{proof}\n",
            encoding="utf-8",
            newline="\n",
        )

        inventory = proofcheck.scan_formal_units(source)
        units = {unit["id"]: unit for unit in inventory["units"]}

        self.assertEqual(
            {"file": source.name, "start_line": 11, "end_line": 13},
            units["thm:x"]["proof"],
        )
        self.assertEqual(
            "named_heading", units["thm:x"]["proof_association"]["method"]
        )
        self.assertEqual(
            {"file": source.name, "start_line": 14, "end_line": 16},
            units["cor:y"]["proof"],
        )
        self.assertEqual(
            "named_environment", units["cor:y"]["proof_association"]["method"]
        )
        self.assertFalse(
            any(
                "multiple_terminal_markers" in warning
                for warning in inventory["warnings"]
            ),
            inventory,
        )

    def test_outer_named_heading_does_not_claim_nested_section_proof(
        self,
    ) -> None:
        source = self.base / "nested-named-proof-sections.tex"
        source.write_text(
            "\\newtheorem{theorem}{Theorem}\n"
            "\\begin{theorem}\\label{thm:outer}\n"
            "The outer theorem claim.\n"
            "\\end{theorem}\n"
            "\\begin{theorem}\\label{thm:inner}\n"
            "The inner theorem claim.\n"
            "\\end{theorem}\n"
            "\\section{Proof of Theorem \\ref{thm:outer}}\n"
            "The outer proof is not supplied here.\n"
            "\\subsection{Proof of Theorem \\ref{thm:inner}}\n"
            "\\begin{proof}\n"
            "The inner theorem proof.\n"
            "\\end{proof}\n",
            encoding="utf-8",
            newline="\n",
        )

        inventory = proofcheck.scan_formal_units(source)
        units = {unit["id"]: unit for unit in inventory["units"]}

        self.assertIsNone(units["thm:outer"]["proof"])
        self.assertEqual(
            "unassociated",
            units["thm:outer"]["proof_association"]["status"],
        )
        self.assertEqual(
            {"file": source.name, "start_line": 11, "end_line": 13},
            units["thm:inner"]["proof"],
        )
        self.assertEqual(
            "named_heading",
            units["thm:inner"]["proof_association"]["method"],
        )
        self.assertTrue(
            any(
                "Proof-required result has no associated proof: thm:outer"
                in warning
                for warning in inventory["warnings"]
            ),
            inventory,
        )

    def test_bracket_hyperref_is_recognized_as_an_exact_occurrence(self) -> None:
        source = self.base / "hyperref-occurrence.tex"
        text = "\\hyperref[thm:target]{the target theorem}"
        occurrences, warnings = proofcheck.scan_reference_occurrences(
            text,
            source,
            self.base,
        )

        self.assertEqual([], warnings)
        self.assertEqual(1, len(occurrences))
        self.assertEqual("hyperref", occurrences[0]["command"])
        self.assertEqual("thm:target", occurrences[0]["target"])
        self.assertEqual(1, occurrences[0]["line"])
        self.assertEqual(1, occurrences[0]["column"])

    def test_common_single_target_reference_commands_are_exact(self) -> None:
        source = self.base / "single-target-references.tex"
        commands = (
            "nameref",
            "vref",
            "Vref",
            "cpageref",
            "Cpageref",
            "labelcref",
            "labelcpageref",
        )
        expected = [
            (command, f"target:{index}")
            for index, command in enumerate(commands, 1)
        ]
        text = "\n".join(
            f"\\{command}{{{target}}}"
            for command, target in expected
        )

        occurrences, warnings = proofcheck.scan_reference_occurrences(
            text,
            source,
            self.base,
        )

        self.assertEqual([], warnings)
        self.assertEqual(
            expected,
            [
                (occurrence["command"], occurrence["target"])
                for occurrence in occurrences
            ],
        )
        self.assertEqual(
            list(range(1, len(commands) + 1)),
            [occurrence["line"] for occurrence in occurrences],
        )
        self.assertTrue(
            all(occurrence["column"] == 1 for occurrence in occurrences)
        )

    def test_reference_range_commands_emit_both_exact_targets(self) -> None:
        source = self.base / "range-references.tex"
        commands = (
            "crefrange",
            "Crefrange",
            "cpagerefrange",
            "Cpagerefrange",
            "vrefrange",
            "Vrefrange",
        )
        text = "\n".join(
            f"\\{command}{{range:{index}:first}}{{range:{index}:last}}"
            for index, command in enumerate(commands, 1)
        )
        expected = [
            (command, target)
            for index, command in enumerate(commands, 1)
            for target in (
                f"range:{index}:first",
                f"range:{index}:last",
            )
        ]

        occurrences, warnings = proofcheck.scan_reference_occurrences(
            text,
            source,
            self.base,
        )

        self.assertEqual([], warnings)
        self.assertEqual(
            expected,
            [
                (occurrence["command"], occurrence["target"])
                for occurrence in occurrences
            ],
        )
        self.assertEqual(
            [
                line
                for line in range(1, len(commands) + 1)
                for _ in range(2)
            ],
            [occurrence["line"] for occurrence in occurrences],
        )
        self.assertFalse(
            any(
                occurrence["command"] == "cref"
                for occurrence in occurrences
            ),
            occurrences,
        )

    def test_unsupported_ref_like_command_warns_once_without_config_noise(
        self,
    ) -> None:
        source = self.base / "unsupported-reference-command.tex"
        text = (
            "\\refstepcounter{theorem}\n"
            "\\crefname{theorem}{theorem}{theorems}\n"
            "\\Crefname{theorem}{Theorem}{Theorems}\n"
            "\\crefalias{lemma}{theorem}\n"
            "\\creflabelformat{equation}{(#2#1#3)}\n"
            "\\crefrangeconjunction{to}\n"
            "\\mysteryref{thm:target}\n"
        )

        occurrences, warnings = proofcheck.scan_reference_occurrences(
            text,
            source,
            self.base,
        )

        self.assertEqual([], occurrences)
        self.assertEqual(1, len(warnings), warnings)
        self.assertIn("\\mysteryref", warnings[0])
        self.assertIn("manual review", warnings[0].lower())
        self.assertIn(f"{source.name}:7:1", warnings[0])

    def test_equation_label_owner_promotes_the_formal_result_dependency(self) -> None:
        source = self.base / "equation-owner.tex"
        source.write_text(
            "\\newtheorem{lemma}{Lemma}\n"
            "\\begin{lemma}\\label{lem:prior}\n"
            "\\begin{equation}x=x\\label{eq:prior}\\end{equation}\n"
            "\\end{lemma}\n"
            "\\begin{proof}\nBy reflexivity.\n\\end{proof}\n"
            "\\begin{lemma}\\label{lem:main}\nMain claim.\n"
            "\\end{lemma}\n"
            "\\begin{proof}\nUse \\eqref{eq:prior}.\n\\end{proof}\n",
            encoding="utf-8",
            newline="\n",
        )

        inventory = proofcheck.scan_formal_units(source)
        main = next(
            unit for unit in inventory["units"] if unit["id"] == "lem:main"
        )
        occurrence = next(
            row
            for row in main["reference_occurrences"]
            if row["target"] == "eq:prior"
        )

        self.assertEqual("unique", occurrence["resolution_status"])
        self.assertEqual("lem:prior", occurrence["owner_unit_id"])
        self.assertEqual("statement", occurrence["owner_region"])
        self.assertEqual(["lem:prior"], main["candidate_internal_dependencies"])

    def test_formal_statement_reference_promotes_internal_candidate(self) -> None:
        source = self.base / "statement-dependency.tex"
        source.write_text(
            "\\newtheorem{lemma}{Lemma}\n"
            "\\begin{lemma}\\label{lem:prior}\nPrior claim.\n"
            "\\end{lemma}\n"
            "\\begin{proof}\nPrior proof.\n\\end{proof}\n"
            "\\begin{lemma}\\label{lem:main}\n"
            "Under Lemma~\\ref{lem:prior}, the main claim holds.\n"
            "\\end{lemma}\n"
            "\\begin{proof}\nThe proof repeats no source reference.\n"
            "\\end{proof}\n",
            encoding="utf-8",
            newline="\n",
        )

        inventory = proofcheck.scan_formal_units(source)
        unit_inventory = {
            unit["id"]: unit for unit in inventory["units"]
        }
        main = unit_inventory["lem:main"]

        self.assertEqual([], main["reference_occurrences"])
        self.assertEqual([], main["dependencies"])
        self.assertEqual(
            ["lem:prior"], main["candidate_internal_dependencies"]
        )

        cross_references = proofcheck.scan_cross_references(source)
        label_owners = proofcheck.reviewed_label_owners(
            cross_references, unit_inventory, self.base
        )
        source_lines = {source.resolve(): proofcheck.read_lines(source)}
        support_index = proofcheck.build_unowned_label_support_index(
            source_lines,
            unit_inventory.values(),
            label_owners,
            self.base,
        )
        rescanned = proofcheck.reviewed_span_evidence(
            "lem:main",
            main,
            self.base,
            label_owners,
            support_index,
        )
        self.assertEqual(
            main["candidate_internal_dependencies"],
            rescanned["candidate_internal_dependencies"],
        )

    def test_bounded_unowned_equation_promotes_supporting_result(self) -> None:
        source = self.base / "bounded-unowned-equation.tex"
        source.write_text(
            "\\newtheorem{theorem}{Theorem}\n"
            "\\newtheorem{lemma}{Lemma}\n"
            "\\begin{theorem}\\label{thm:support}\nSupport result.\n"
            "\\end{theorem}\n"
            "\\begin{proof}\nSupport proof.\n\\end{proof}\n"
            "\\begin{theorem}\\label{thm:outside}\nOutside result.\n"
            "\\end{theorem}\n"
            "\\begin{proof}\nOutside proof.\n\\end{proof}\n"
            "Before the proof heading, see \\ref{thm:outside}.\n"
            "\\section*{Proof of a calibration result}\n"
            "Using Theorem~\\ref{thm:support}, derive\n"
            "\\begin{equation}\n"
            "x=x.\n"
            "\\label{eq:bridge}\n"
            "\\end{equation}\n"
            "After the display, see \\ref{thm:outside}.\n"
            "\\begin{lemma}\\label{lem:main}\nMain claim.\n"
            "\\end{lemma}\n"
            "\\begin{proof}\nUse \\eqref{eq:bridge}.\n"
            "\\end{proof}\n",
            encoding="utf-8",
            newline="\n",
        )

        inventory = proofcheck.scan_formal_units(source)
        unit_inventory = {
            unit["id"]: unit for unit in inventory["units"]
        }
        main = unit_inventory["lem:main"]
        occurrence = next(
            row
            for row in main["reference_occurrences"]
            if row["target"] == "eq:bridge"
        )

        self.assertEqual("unowned", occurrence["resolution_status"])
        self.assertIsNone(occurrence["owner_unit_id"])
        self.assertEqual(["eq:bridge"], main["dependencies"])
        self.assertEqual(
            ["thm:support"], main["candidate_internal_dependencies"]
        )

        cross_references = proofcheck.scan_cross_references(source)
        label_owners = proofcheck.reviewed_label_owners(
            cross_references, unit_inventory, self.base
        )
        source_lines = {source.resolve(): proofcheck.read_lines(source)}
        support_index = proofcheck.build_unowned_label_support_index(
            source_lines,
            unit_inventory.values(),
            label_owners,
            self.base,
        )
        rescanned = proofcheck.reviewed_span_evidence(
            "lem:main",
            main,
            self.base,
            label_owners,
            support_index,
        )
        self.assertEqual(
            main["candidate_internal_dependencies"],
            rescanned["candidate_internal_dependencies"],
        )

    def test_bounded_unowned_dependency_uses_source_closure(self) -> None:
        included = self.base / "included-derivation.tex"
        included.write_text(
            "\\newtheorem{theorem}{Theorem}\n"
            "\\begin{theorem}\\label{thm:support}\nSupport result.\n"
            "\\end{theorem}\n"
            "\\begin{proof}\nSupport proof.\n\\end{proof}\n"
            "\\section*{Proof of the bridge identity}\n"
            "By Theorem~\\ref{thm:support},\n"
            "\\begin{align}\n"
            "x &= x.\\label{eq:bridge}\n"
            "\\end{align}\n",
            encoding="utf-8",
            newline="\n",
        )
        source = self.base / "cross-file-dependency.tex"
        source.write_text(
            "\\newtheorem{lemma}{Lemma}\n"
            "\\input{included-derivation}\n"
            "\\begin{lemma}\\label{lem:main}\nMain claim.\n"
            "\\end{lemma}\n"
            "\\begin{proof}\nUse \\eqref{eq:bridge}.\n"
            "\\end{proof}\n",
            encoding="utf-8",
            newline="\n",
        )

        closure = proofcheck.discover_source_closure(source)
        inventory = proofcheck.scan_formal_units(
            source,
            source_files=closure["files"],
            source_warnings=closure["warnings"],
        )
        main = next(
            unit for unit in inventory["units"] if unit["id"] == "lem:main"
        )

        self.assertEqual(
            ["thm:support"], main["candidate_internal_dependencies"]
        )

    def test_candidate_traversal_is_cycle_safe_and_suppresses_self(self) -> None:
        label_owners = {
            "eq:a": {"status": "unowned", "owner_unit_id": None},
            "eq:b": {"status": "unowned", "owner_unit_id": None},
            "eq:unsafe": {"status": "unowned", "owner_unit_id": None},
            "lem:main": {
                "status": "unique",
                "owner_unit_id": "lem:main",
            },
            "thm:prior": {
                "status": "unique",
                "owner_unit_id": "thm:prior",
            },
        }
        support_index = {
            "eq:a": {"reference_occurrences": [{"target": "eq:b"}]},
            "eq:b": {
                "reference_occurrences": [
                    {"target": "eq:a"},
                    {"target": "lem:main"},
                    {"target": "thm:prior"},
                ],
            },
        }

        candidates = proofcheck.resolve_candidate_internal_dependencies(
            "lem:main",
            [{"target": "eq:a"}, {"target": "eq:unsafe"}],
            label_owners,
            support_index,
        )

        self.assertEqual(["thm:prior"], candidates)

    def test_partial_and_stale_hash_proof_location_overrides_fail(self) -> None:
        self.paper.write_text(
            self.paper.read_text(encoding="utf-8")
            + "\\begin{proof}\nAgain by reflexivity.\n\\end{proof}\n",
            encoding="utf-8",
            newline="\n",
        )
        self.audit = self.base / "proof-location-override-audit"
        with contextlib.redirect_stdout(io.StringIO()):
            proofcheck.cmd_scaffold(
                argparse.Namespace(paper=self.paper, output=self.audit)
            )
        ledger_path = self.make_complete_audit()
        inventory_path = (
            self.audit / "audit" / "01_index" / "theorem_inventory.json"
        )
        inventory = read_json(inventory_path)
        unit = inventory["units"][0]
        parser_proof = proofcheck.canonical_location(unit["proof"])
        parser_association = json.loads(
            json.dumps(unit["proof_association"])
        )
        reviewed_proof = {
            "file": "paper.tex",
            "start_line": 8,
            "end_line": 10,
        }
        reviewed_association = {
            "status": "associated",
            "method": "reviewed_manual",
            "target": "lem:main",
            "evidence_occurrence_ids": [],
        }
        unit["proof"] = reviewed_proof
        unit["proof_redirects"] = []
        unit["proof_association"] = reviewed_association
        unit["reference_occurrences"] = []
        unit["dependencies"] = []
        unit["candidate_internal_dependencies"] = []
        unit["citations"] = []
        write_json(inventory_path, inventory)
        ledger = read_json(ledger_path)
        ledger["review"]["source_reference_dispositions"] = []
        ledger["review"]["citation_dispositions"] = []
        write_json(ledger_path, ledger)

        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        proof_location_override = {
            "unit_id": "lem:main",
            "kind": "proof_location",
            "parser_proof": parser_proof,
            "reviewed_proof": reviewed_proof,
            "reviewed_proof_sha256": "0" * 64,
            "association_method": "reviewed_manual",
            "reason": "Rendered review selects the alternate complete proof.",
            "evidence": "The alternate proof span is inspected directly.",
        }
        association_override = {
            "unit_id": "lem:main",
            "kind": "proof_association",
            "parser_association": parser_association,
            "reviewed_association": reviewed_association,
            "rendered_source_evidence": (
                "Rendered source shows the complete alternate proof span."
            ),
            "reason": "The alternate proof is associated manually.",
            "evidence": "The association is recorded with exact source bounds.",
        }
        manifest["audit_scope"]["inventory_overrides"] = [
            proof_location_override,
            association_override,
        ]
        for review in manifest["parser_warning_reviews"]:
            review.update(
                {
                    "disposition": "confirmed_non_load_bearing",
                    "affected_units": [],
                    "evidence": (
                        "The additional orphan proof is a controlled test fixture."
                    ),
                }
            )
        write_json(manifest_path, manifest)
        self.refresh_dependency_review()

        errors, _ = proofcheck.check_audit_finalization(self.audit)
        self.assertTrue(
            any("reviewed_proof_sha256 is stale" in error for error in errors),
            errors,
        )

        partial_manifest = read_json(manifest_path)
        del partial_manifest["audit_scope"]["inventory_overrides"][0][
            "parser_proof"
        ]
        partial_manifest["audit_scope"]["inventory_overrides"][0][
            "reviewed_proof_sha256"
        ] = proofcheck.source_span_sha256(self.paper, 8, 10)
        write_json(manifest_path, partial_manifest)
        errors, _ = proofcheck.check_audit_finalization(self.audit)
        self.assertTrue(
            any("parser_proof is stale" in error for error in errors),
            errors,
        )

    def schema5_risk_checks(self, step_id: str) -> list[dict[str, str]]:
        rows = json.loads(json.dumps(make_risk_checks()))
        for row in rows:
            row["evidence"] = f"{row['evidence']} This disposition is specific to {step_id}."
        return rows

    def seal_schema5_challenge(
        self,
        ledger_path: Path,
        ledger: dict,
        *,
        covered_issue_ids: list[str] | None = None,
        artifact_text: str | None = None,
    ) -> None:
        write_json(ledger_path, ledger)
        try:
            primary_packet = proofcheck.build_context_packet(
                self.audit, ledger["unit_id"], "primary"
            )
        except ValueError:
            # Standalone schema fixtures can intentionally disagree with the
            # canonical inventory and therefore cannot have a current packet.
            primary_packet = None
        if primary_packet is not None:
            ledger["work_context_sha256"] = primary_packet[
                "work_context_sha256"
            ]
            write_json(ledger_path, ledger)
        independent = ledger["independent_check"]
        if independent.get("required") is not True:
            independent.update(
                {
                    "covered_issue_ids": [],
                    "source_snapshot_sha256": "",
                    "challenged_ledger_sha256": "",
                    "challenge_context_sha256": "",
                    "challenge_artifact_sha256": "",
                    "issue_assessments": [],
                    "generated_utc": "",
                }
            )
            write_json(ledger_path, ledger)
            return

        artifact = self.audit / independent["artifact"]
        if artifact_text is not None:
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_text(artifact_text, encoding="utf-8", newline="\n")
        manifest = read_json(self.audit / "AUDIT_MANIFEST.json")
        issue_ids = sorted(covered_issue_ids or [])
        independent.update(
            {
                "covered_issue_ids": issue_ids,
                "source_snapshot_sha256": manifest["source_snapshot"]["sha256"],
                "challenged_ledger_sha256": (
                    proofcheck.canonical_primary_ledger_sha256(ledger)
                ),
                "challenge_context_sha256": "0" * 64,
                "challenge_artifact_sha256": "0" * 64,
                "issue_assessments": [
                    {
                        "issue_id": issue_id,
                        "target_contract_sha256": "0" * 64,
                        "assessment": "confirmed",
                        "target_assessment": (
                            "The challenger independently checked the exact target "
                            "contract associated with this issue."
                        ),
                        "downstream_assessment": (
                            "The challenger independently traced the stated "
                            "downstream consequences of this issue."
                        ),
                    }
                    for issue_id in issue_ids
                ],
                "generated_utc": "2026-08-09T00:00:00+00:00",
            }
        )
        write_json(ledger_path, ledger)
        try:
            challenge_packet = proofcheck.build_context_packet(
                self.audit, ledger["unit_id"], "challenge"
            )
        except ValueError:
            # Some unit-level schema tests intentionally use a standalone ledger
            # whose source binding disagrees with the canonical audit inventory.
            # The placeholder remains structurally valid for those local checks.
            challenge_packet = None
        if challenge_packet is None:
            artifact.parent.mkdir(parents=True, exist_ok=True)
            narrative = (
                artifact.read_text(encoding="utf-8")
                if artifact.is_file()
                else (
                    "# Independent challenge\n\n"
                    "Every inferential step was independently checked."
                )
            )
            artifact.write_text(
                proofcheck.upsert_challenge_artifact_binding(
                    narrative, ledger["unit_id"], independent
                ),
                encoding="utf-8",
                newline="\n",
            )
            independent["challenge_artifact_sha256"] = (
                proofcheck.sha256_file(artifact)
            )
            write_json(ledger_path, ledger)
            return
        triggers = {
            row["id"]: row
            for row in challenge_packet.get("issue_triggers", [])
            if isinstance(row, dict)
            and isinstance(row.get("id"), str)
        }
        independent["challenge_context_sha256"] = challenge_packet[
            "context_binding_sha256"
        ]
        for assessment in independent["issue_assessments"]:
            trigger = triggers.get(assessment["issue_id"])
            if isinstance(trigger, dict):
                assessment["target_contract_sha256"] = trigger[
                    "target_contract_sha256"
                ]
        artifact.parent.mkdir(parents=True, exist_ok=True)
        narrative = (
            artifact.read_text(encoding="utf-8")
            if artifact.is_file()
            else (
                "# Independent challenge\n\n"
                "Every inferential step was independently checked."
            )
        )
        artifact.write_text(
            proofcheck.upsert_challenge_artifact_binding(
                narrative, ledger["unit_id"], independent
            ),
            encoding="utf-8",
            newline="\n",
        )
        independent["challenge_artifact_sha256"] = proofcheck.sha256_file(
            artifact
        )
        write_json(ledger_path, ledger)
        report_path = self.audit / "audit" / "06_reports" / "FINAL_REPORT.md"
        if report_path.is_file():
            report = report_path.read_text(encoding="utf-8")
            heading = "### Independent verification"
            section_start = report.find(heading)
            if section_start >= 0:
                next_heading = report.find("\n### ", section_start + len(heading))
                section_end = len(report) if next_heading < 0 else next_heading
                section = report[section_start:section_end]
                unit_id = ledger["unit_id"]
                row = (
                    f"| {unit_id} | {independent['status']} | "
                    f"{independent['independence_level']} | "
                    f"{independent['challenger_verdict']} | "
                    f"{independent['reconciled_verdict']} | "
                    f"{independent.get('resolution') if independent['status'] == 'resolved' else 'agreed'} |"
                )
                section = re.sub(
                    rf"^\| {re.escape(unit_id)} \|.*$",
                    lambda _: row,
                    section,
                    count=1,
                    flags=re.MULTILINE,
                )
                report_path.write_text(
                    report[:section_start] + section + report[section_end:],
                    encoding="utf-8",
                    newline="\n",
                )

    def seal_live_challenges(self) -> None:
        for ledger_path in reversed(
            proofcheck.live_local_check_artifacts(
                self.audit, ".ledger.json"
            )
        ):
            ledger = read_json(ledger_path)
            covered = ledger.get("independent_check", {}).get(
                "covered_issue_ids"
            )
            self.seal_schema5_challenge(
                ledger_path,
                ledger,
                covered_issue_ids=(covered if isinstance(covered, list) else None),
            )

    def downgrade_ledger_fixture_to_schema4(self, ledger: dict) -> dict:
        source_units = {
            unit["id"]: unit
            for unit in ledger.get("source_units", [])
            if isinstance(unit, dict) and isinstance(unit.get("id"), str)
        }
        for step in ledger.get("steps", []):
            source_unit = source_units.get(step.pop("source_unit_id", None))
            if source_unit is not None:
                step["lines"] = list(source_unit["lines"])
            step.pop("support_role", None)
        ledger["schema_version"] = 4
        ledger["evidence_contract_version"] = 3
        ledger.pop("source_units", None)
        return ledger

    def downgrade_complete_audit_to_schema4(self) -> Path:
        ledger_path = self.make_complete_audit()
        ledger = self.downgrade_ledger_fixture_to_schema4(
            read_json(ledger_path)
        )
        for field in (
            "covered_issue_ids",
            "source_snapshot_sha256",
            "challenged_ledger_sha256",
            "challenge_context_sha256",
            "challenge_artifact_sha256",
            "issue_assessments",
            "generated_utc",
        ):
            ledger["independent_check"].pop(field, None)
        write_json(ledger_path, ledger)

        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        manifest["schema_version"] = 4
        manifest["protocol"].update(
            {
                "artifact_schema_version": 4,
                "evidence_contract_version": 3,
                "closure_contract_version": 2,
                "validator_sha256": proofcheck.sha256_text(
                    "legacy validator fixture"
                ),
            }
        )
        write_json(manifest_path, manifest)

        versioned_paths = (
            self.audit / "PROGRESS.json",
            self.audit / "audit" / "01_index" / "theorem_inventory.json",
            self.audit
            / "audit"
            / "01_index"
            / "cross_reference_audit.json",
            self.audit / "audit" / "06_reports" / "ISSUE_LOG.json",
        )
        for path in versioned_paths:
            record = read_json(path)
            record["schema_version"] = 4
            write_json(path, record)

        registry_path = (
            self.audit
            / "audit"
            / "03_dependencies"
            / "DEPENDENCY_REGISTRY.json"
        )
        registry = read_json(registry_path)
        registry["schema_version"] = 4
        registry["closure_contract_version"] = 2
        registry["review"]["inventory_sha256"] = proofcheck.sha256_file(
            self.audit
            / "audit"
            / "01_index"
            / "theorem_inventory.json"
        )
        write_json(registry_path, registry)

        report_path = self.audit / "audit" / "06_reports" / "FINAL_REPORT.md"
        report = report_path.read_text(encoding="utf-8")
        report = report.replace(
            "- Artifact schema version: 5",
            "- Artifact schema version: 4",
        )
        report = report.replace(
            "- Evidence contract version: 4",
            "- Evidence contract version: 3",
        )
        report = report.replace(
            "- Closure contract version: 4",
            "- Closure contract version: 2",
        )
        report_path.write_text(report, encoding="utf-8", newline="\n")
        return ledger_path

    def upgrade_ledger_to_schema5(self, ledger_path: Path) -> dict:
        ledger = read_json(ledger_path)
        source_path = proofcheck.resolve_stored_path(
            ledger["source"]["file"], ledger_path.parent
        )
        source_units = []
        for index, step in enumerate(ledger["steps"], 1):
            unit_id = f"U{index:03d}"
            lines = step.pop("lines", None)
            if not (
                isinstance(lines, list)
                and len(lines) == 2
                and all(isinstance(value, int) for value in lines)
            ):
                existing = next(
                    (
                        row
                        for row in ledger.get("source_units", [])
                        if row.get("id") == step.get("source_unit_id")
                    ),
                    None,
                )
                if existing is None:
                    raise AssertionError(f"Cannot recover source unit for {step['id']}")
                lines = list(existing["lines"])
            if step.get("status") == "non_substantive":
                kind = "non_substantive"
            elif lines[0] == lines[1]:
                kind = "one_line"
            else:
                kind = "continued_sentence"
            source_units.append(
                {
                    "id": unit_id,
                    "lines": lines,
                    "kind": kind,
                    "source_sha256": proofcheck.source_span_sha256(
                        source_path, lines[0], lines[1]
                    ),
                    "partition_evidence": (
                        f"{unit_id} is the exact physical source unit assigned to "
                        f"{step['id']}."
                    ),
                }
            )
            step["source_unit_id"] = unit_id
            if step.get("inference", {}).get("moves"):
                step["support_role"] = "derivation"
        ledger["schema_version"] = 5
        ledger["evidence_contract_version"] = proofcheck.EVIDENCE_CONTRACT_VERSION
        ledger["source_units"] = source_units
        self.seal_schema5_challenge(ledger_path, ledger)
        return read_json(ledger_path)

    def upgrade_complete_audit_to_schema5(self) -> list[Path]:
        ledger_paths = sorted(
            (self.audit / "audit" / "04_local_checks").glob("*.ledger.json")
        )
        for ledger_path in ledger_paths:
            self.upgrade_ledger_to_schema5(ledger_path)

        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        manifest["schema_version"] = 5
        manifest["protocol"].update(
            {
                "skill_name": "stat-paper-proofcheck",
                "skill_version": proofcheck.SKILL_VERSION,
                "artifact_schema_version": 5,
                "evidence_contract_version": proofcheck.EVIDENCE_CONTRACT_VERSION,
                "method_interface_schema_version": 1,
                "closure_contract_version": proofcheck.CLOSURE_CONTRACT_VERSION,
                "validator_sha256": proofcheck.protocol_identity()[
                    "validator_sha256"
                ],
            }
        )
        write_json(manifest_path, manifest)

        inventory_path = (
            self.audit / "audit" / "01_index" / "theorem_inventory.json"
        )
        inventory = read_json(inventory_path)
        inventory["schema_version"] = 5
        write_json(inventory_path, inventory)

        crossref_path = (
            self.audit / "audit" / "01_index" / "cross_reference_audit.json"
        )
        crossref = read_json(crossref_path)
        crossref["schema_version"] = 5
        write_json(crossref_path, crossref)

        issue_path = self.audit / "audit" / "06_reports" / "ISSUE_LOG.json"
        issue_log = read_json(issue_path)
        issue_log["schema_version"] = 5
        write_json(issue_path, issue_log)

        progress_path = self.audit / "PROGRESS.json"
        progress = read_json(progress_path)
        progress["schema_version"] = 5
        write_json(progress_path, progress)

        registry_path = (
            self.audit
            / "audit"
            / "03_dependencies"
            / "DEPENDENCY_REGISTRY.json"
        )
        registry = read_json(registry_path)
        registry["schema_version"] = 5
        registry["closure_contract_version"] = proofcheck.CLOSURE_CONTRACT_VERSION
        registry["review"]["inventory_sha256"] = proofcheck.sha256_file(
            inventory_path
        )
        write_json(registry_path, registry)

        report_path = self.audit / "audit" / "06_reports" / "FINAL_REPORT.md"
        report_lines = report_path.read_text(encoding="utf-8").splitlines()
        replacements = {
            "Skill version": proofcheck.SKILL_VERSION,
            "Artifact schema version": "5",
            "Evidence contract version": "4",
            "Closure contract version": str(proofcheck.CLOSURE_CONTRACT_VERSION),
        }
        for index, line in enumerate(report_lines):
            for label, value in replacements.items():
                if line.startswith(f"- {label}:"):
                    report_lines[index] = f"- {label}: {value}"
        report_path.write_text(
            "\n".join(report_lines) + "\n", encoding="utf-8", newline="\n"
        )

        self.assertEqual(
            proofcheck.SKILL_VERSION, manifest["protocol"]["skill_version"]
        )
        return ledger_paths

    def replace_ledger_source(
        self,
        ledger_path: Path,
        source: Path,
        *,
        statement_start: int,
        statement_end: int,
        source_end: int,
    ) -> tuple[dict, dict]:
        ledger = read_json(ledger_path)
        with contextlib.redirect_stdout(io.StringIO()):
            proofcheck.cmd_extract(
                argparse.Namespace(
                    file=source,
                    start=1,
                    end=source_end,
                    statement_file=source,
                    statement_start=statement_start,
                    statement_end=statement_end,
                    separate_statement_reason=None,
                    unit_id="lem:main",
                    output=ledger_path,
                    force=True,
                )
            )
        extracted = read_json(ledger_path)
        ledger["source"] = extracted["source"]
        ledger["source_lines"] = extracted["source_lines"]
        statement_span = extracted["obligation"]["statement_spans"][0]
        ledger["obligation"]["statement_spans"] = [statement_span]
        ledger["obligation"]["conclusions"][0]["source_spans"] = [
            dict(statement_span)
        ]
        ledger["review"]["source_reference_dispositions"] = []
        ledger["review"]["citation_dispositions"] = []
        return ledger, extracted

    def make_schema5_long_display_ledger(self) -> Path:
        ledger_path = self.make_complete_audit()
        source = self.base / "long-indivisible-display.tex"
        source.write_text(
            "\\begin{lemma}\\label{lem:main}For every real $x$, $x=x$.\\end{lemma}\n"
            "\\begin{proof}\n"
            "\\begin{equation*}\n"
            "\\underbrace{\n"
            "\\left(\n"
            "x\n"
            "\\right)\n"
            "}_{\\text{the arbitrary real number}}\n"
            "=\n"
            "x.\n"
            "\\end{equation*}\n"
            "\\end{proof}\n",
            encoding="utf-8",
            newline="\n",
        )
        ledger, _ = self.replace_ledger_source(
            ledger_path,
            source,
            statement_start=1,
            statement_end=1,
            source_end=12,
        )
        statement_step = json.loads(json.dumps(ledger["steps"][0]))
        statement_step.pop("lines", None)
        statement_step["source_unit_id"] = "U001"
        open_step = {
            "id": "S002",
            "source_unit_id": "U002",
            "kind": "other",
            "status": "non_substantive",
            "issue_ids": [],
        }
        conclusion_step = json.loads(json.dumps(ledger["steps"][2]))
        conclusion_step.pop("lines", None)
        conclusion_step["source_unit_id"] = "U003"
        conclusion_step["support_role"] = "derivation"
        conclusion_step["checks"]["literal"] = (
            "Lines 3-11 form one displayed reflexive equality for the fixed x."
        )
        conclusion_step["checks"]["atomicity"] = {
            "status": "single_move",
            "evidence": (
                "The long display is one syntactic equality split only for layout."
            ),
        }
        conclusion_step["checks"]["adversarial"] = [
            "Removing the layout commands leaves the single equality x equals x."
        ]
        conclusion_step["risk_checks"] = self.schema5_risk_checks("S003")
        close_step = {
            "id": "S004",
            "source_unit_id": "U004",
            "kind": "other",
            "status": "non_substantive",
            "issue_ids": [],
        }
        ledger["steps"] = [statement_step, open_step, conclusion_step, close_step]
        ledger["source_units"] = [
            {
                "id": "U001",
                "lines": [1, 1],
                "kind": "one_line",
                "source_sha256": proofcheck.source_span_sha256(source, 1, 1),
                "partition_evidence": "The complete theorem statement is on line 1.",
            },
            {
                "id": "U002",
                "lines": [2, 2],
                "kind": "non_substantive",
                "source_sha256": proofcheck.source_span_sha256(source, 2, 2),
                "partition_evidence": "Line 2 is only the proof delimiter.",
            },
            {
                "id": "U003",
                "lines": [3, 11],
                "kind": "continued_display",
                "source_sha256": proofcheck.source_span_sha256(source, 3, 11),
                "partition_evidence": (
                    "Lines 3-11 are one uninterrupted display of x equals x."
                ),
            },
            {
                "id": "U004",
                "lines": [12, 12],
                "kind": "non_substantive",
                "source_sha256": proofcheck.source_span_sha256(source, 12, 12),
                "partition_evidence": "Line 12 is only the proof delimiter.",
            },
        ]
        ledger["schema_version"] = 5
        ledger["evidence_contract_version"] = proofcheck.EVIDENCE_CONTRACT_VERSION
        self.seal_schema5_challenge(ledger_path, ledger)
        return ledger_path

    def make_schema5_parallel_steps_ledger(self) -> Path:
        ledger_path = self.make_complete_audit()
        source = self.base / "parallel-atomic-steps.tex"
        source.write_text(
            "\\begin{lemma}\\label{lem:main}For every real $x$, $x=x$.\\end{lemma}\n"
            "\\begin{proof}\n"
            "The element $x$ lies in the real-number domain.\n"
            "Equality is defined on pairs of real numbers.\n"
            "Reflexivity applies to every real number.\n"
            "Both coordinates of the current pair are the same $x$.\n"
            "Therefore $x=x$.\n"
            "\\end{proof}\n",
            encoding="utf-8",
            newline="\n",
        )
        ledger, _ = self.replace_ledger_source(
            ledger_path,
            source,
            statement_start=1,
            statement_end=1,
            source_end=8,
        )

        def obligation_premise(
            premise_id: str, claim: str, reference: str, evidence: str
        ) -> dict:
            return {
                "id": premise_id,
                "role": "fact",
                "claim": claim,
                "origin": {
                    "kind": "obligation",
                    "reference": reference,
                    "anchor": {"kind": "statement_span", "index": 1},
                },
                "evidence": evidence,
            }

        def derivation_step(
            step_id: str,
            source_unit_id: str,
            claim: str,
            used_premises: list[dict],
            dependencies: list[dict],
            rule: str,
        ) -> dict:
            return {
                "id": step_id,
                "source_unit_id": source_unit_id,
                "support_role": "derivation",
                "kind": "conclusion" if step_id == "S007" else "setup",
                "goal": f"Establish the atomic claim recorded in {step_id}.",
                "restatement": claim,
                "premise_uses": used_premises,
                "dependencies": dependencies,
                "inference": {
                    "moves": [
                        {
                            "id": "M001",
                            "claim": claim,
                            "rule": rule,
                            "premise_ids": [row["id"] for row in used_premises],
                            "prior_move_ids": [],
                            "justification": (
                                f"The recorded premises justify only the {step_id} claim."
                            ),
                        }
                    ],
                    "conclusion_move": "M001",
                },
                "checks": {
                    "literal": f"The source line for {step_id} states this exact claim.",
                    "atomicity": {
                        "status": "single_move",
                        "evidence": f"{step_id} contains one independently checkable move.",
                    },
                    "adversarial": [
                        f"The weakest real-domain case was checked specifically for {step_id}."
                    ],
                },
                "side_conditions": [],
                "risk_checks": self.schema5_risk_checks(step_id),
                "status": "verified",
                "issue_ids": [],
            }

        statement = json.loads(json.dumps(ledger["steps"][0]))
        statement.pop("lines", None)
        statement["source_unit_id"] = "U001"
        proof_open = {
            "id": "S002",
            "source_unit_id": "U002",
            "kind": "other",
            "status": "non_substantive",
            "issue_ids": [],
        }
        parallel_claims = [
            "x lies in the real-number domain.",
            "Equality is defined on pairs of real numbers.",
            "Reflexivity applies to every real number.",
            "Both coordinates of the current pair are the same x.",
        ]
        parallel_steps = []
        for offset, claim in enumerate(parallel_claims, 3):
            reference = "/definitions/0" if offset in {4, 5} else "/quantifier_scope"
            source_claim = (
                ledger["obligation"]["definitions"][0]
                if reference == "/definitions/0"
                else ledger["obligation"]["quantifier_scope"]
            )
            parallel_steps.append(
                derivation_step(
                    f"S{offset:03d}",
                    f"U{offset:03d}",
                    claim,
                    [
                        obligation_premise(
                            "P001",
                            source_claim,
                            reference,
                            f"The locked statement supplies the input for S{offset:03d}.",
                        )
                    ],
                    [],
                    "Direct specialization of the locked theorem contract",
                )
            )
        final_dependencies = []
        final_premises = []
        for offset, claim in enumerate(parallel_claims, 3):
            step_id = f"S{offset:03d}"
            final_dependencies.append(
                {
                    "id": step_id,
                    "kind": "step",
                    "status": "verified",
                    "needed_form": claim,
                    "compatibility_check": (
                        f"{step_id} concerns the same real number x as the conclusion."
                    ),
                }
            )
            final_premises.append(
                {
                    "id": f"P{offset - 2:03d}",
                    "role": "fact",
                    "claim": claim,
                    "origin": {"kind": "prior_step", "reference": step_id},
                    "evidence": f"{step_id} supplies this exact prerequisite.",
                }
            )
        final_step = derivation_step(
            "S007",
            "U007",
            "x equals x",
            final_premises,
            final_dependencies,
            "Definition of equality and reflexivity",
        )
        proof_close = {
            "id": "S008",
            "source_unit_id": "U008",
            "kind": "other",
            "status": "non_substantive",
            "issue_ids": [],
        }
        ledger["steps"] = [
            statement,
            proof_open,
            *parallel_steps,
            final_step,
            proof_close,
        ]
        ledger["review"]["conclusion_step_id"] = "S007"
        ledger["review"]["conclusion_results"][0]["support"] = {
            "step_id": "S007",
            "move_id": "M001",
        }
        ledger["source_units"] = [
            {
                "id": f"U{line:03d}",
                "lines": [line, line],
                "kind": "non_substantive" if line in {2, 8} else "one_line",
                "source_sha256": proofcheck.source_span_sha256(source, line, line),
                "partition_evidence": (
                    f"Line {line} is the complete physical source unit U{line:03d}."
                ),
            }
            for line in range(1, 9)
        ]
        ledger["schema_version"] = 5
        ledger["evidence_contract_version"] = proofcheck.EVIDENCE_CONTRACT_VERSION
        self.seal_schema5_challenge(ledger_path, ledger)
        return ledger_path

    def test_nonexecuting_tex_cannot_create_formal_units_or_proof_spans(
        self,
    ) -> None:
        cases = {
            "newcommand": (
                "\\newcommand{\\ghost}{"
                "\\newtheorem{ghost}{Ghost}"
                "\\begin{ghost}\\label{thm:ghost}Ghost.\\end{ghost}"
                "\\begin{proof}Ghost.\\end{proof}}\n"
            ),
            "verbatim": (
                "\\begin{verbatim}\n"
                "\\begin{theorem}\\label{thm:ghost}Ghost.\\end{theorem}\n"
                "\\begin{proof}Ghost.\\end{proof}\n"
                "\\end{verbatim}\n"
            ),
            "lstlisting": (
                "\\begin{lstlisting}\n"
                "\\begin{theorem}\\label{thm:ghost}Ghost.\\end{theorem}\n"
                "\\begin{proof}Ghost.\\end{proof}\n"
                "\\end{lstlisting}\n"
            ),
            "minted": (
                "\\begin{minted}{latex}\n"
                "\\begin{theorem}\\label{thm:ghost}Ghost.\\end{theorem}\n"
                "\\begin{proof}Ghost.\\end{proof}\n"
                "\\end{minted}\n"
            ),
            "iffalse": (
                "\\iffalse\n"
                "\\begin{theorem}\\label{thm:ghost}Ghost.\\end{theorem}\n"
                "\\begin{proof}Ghost.\\end{proof}\n"
                "\\fi\n"
            ),
        }

        for case, text in cases.items():
            with self.subTest(case=case):
                source = self.base / f"masked-{case}.tex"
                source.write_text(text, encoding="utf-8", newline="\n")

                inventory = proofcheck.scan_formal_units(source)

                self.assertEqual([], inventory["units"], inventory)
                self.assertEqual(
                    set(),
                    proofcheck.proof_environment_spans(source),
                    inventory,
                )
                self.assertEqual([], inventory["warnings"], inventory)
                if case == "newcommand":
                    self.assertNotIn(
                        "ghost",
                        inventory["formal_environments"],
                        inventory,
                    )

    def test_inline_verb_delimiter_inside_multiline_macro_stays_masked(
        self,
    ) -> None:
        source = self.base / "multiline-macro-inline-verb.tex"
        source.write_text(
            "\\newtheorem{theorem}{Theorem}\n"
            "\\newcommand{\\ghost}{%\n"
            "  \\verb|}|%\n"
            "  \\begin{theorem}\\label{thm:ghost}Ghost.\\end{theorem}\n"
            "  \\begin{proof}Ghost proof.\\end{proof}\n"
            "}\n"
            "\\begin{theorem}\\label{thm:real}\n"
            "Real claim.\n"
            "\\end{theorem}\n"
            "\\begin{proof}\n"
            "Real proof.\n"
            "\\end{proof}\n",
            encoding="utf-8",
            newline="\n",
        )

        inventory = proofcheck.scan_formal_units(source)

        self.assertEqual(
            ["thm:real"],
            [unit["id"] for unit in inventory["units"]],
            inventory,
        )
        self.assertEqual(
            {(10, 12)}, proofcheck.proof_environment_spans(source)
        )
        self.assertEqual([], inventory["warnings"], inventory)

    def test_inline_verb_delimiters_inside_multiline_environment_stay_masked(
        self,
    ) -> None:
        source = self.base / "multiline-environment-inline-verb.tex"
        source.write_text(
            "\\newtheorem{theorem}{Theorem}\n"
            "\\NewDocumentEnvironment{ghost}{}{%\n"
            "  \\verb|}|%\n"
            "  \\begin{theorem}\\label{thm:ghost}Ghost.\\end{theorem}\n"
            "  \\begin{proof}Ghost proof.\\end{proof}\n"
            "}{%\n"
            "  \\verb|{|%\n"
            "}\n"
            "\\begin{theorem}\\label{thm:real}\n"
            "Real claim.\n"
            "\\end{theorem}\n"
            "\\begin{proof}\n"
            "Real proof.\n"
            "\\end{proof}\n",
            encoding="utf-8",
            newline="\n",
        )

        inventory = proofcheck.scan_formal_units(source)

        self.assertEqual(
            ["thm:real"],
            [unit["id"] for unit in inventory["units"]],
            inventory,
        )
        self.assertEqual(
            {(12, 14)}, proofcheck.proof_environment_spans(source)
        )
        self.assertEqual([], inventory["warnings"], inventory)

    def test_robust_command_definitions_mask_ghost_proof_structure(self) -> None:
        for command in (
            "newrobustcmd",
            "renewrobustcmd",
            "providerobustcmd",
        ):
            with self.subTest(command=command):
                source = self.base / f"{command}-masked.tex"
                source.write_text(
                    "\\newtheorem{theorem}{Theorem}\n"
                    f"\\{command}{{\\ghost}}{{%\n"
                    "\\begin{theorem}\\label{thm:ghost}Ghost."
                    "\\end{theorem}\n"
                    "\\begin{proof}Ghost proof.\\end{proof}\n"
                    "}\n"
                    "\\begin{theorem}\\label{thm:real}\n"
                    "Real claim.\n"
                    "\\end{theorem}\n"
                    "\\begin{proof}\n"
                    "Real proof.\n"
                    "\\end{proof}\n",
                    encoding="utf-8",
                    newline="\n",
                )

                inventory = proofcheck.scan_formal_units(source)

                self.assertEqual(
                    ["thm:real"],
                    [unit["id"] for unit in inventory["units"]],
                    inventory,
                )
                self.assertEqual(
                    {(9, 11)}, proofcheck.proof_environment_spans(source)
                )
                self.assertEqual([], inventory["warnings"], inventory)

    def test_named_and_protected_definitions_mask_ghost_proof_structure(
        self,
    ) -> None:
        definitions = {
            "@namedef": "\\@namedef{ghost}#1",
            "csdef": "\\csdef{ghost}#1",
            "csedef": "\\csedef{ghost}#1",
            "csgdef": "\\csgdef{ghost}#1",
            "csxdef": "\\csxdef{ghost}#1",
            "protected@edef": "\\protected@edef\\ghost#1",
            "protected@xdef": "\\protected@xdef\\ghost#1",
        }
        for command, definition in definitions.items():
            with self.subTest(command=command):
                source = self.base / f"{command.replace('@', '-')}-masked.tex"
                source.write_text(
                    "\\newtheorem{theorem}{Theorem}\n"
                    f"{definition}{{%\n"
                    "\\begin{theorem}\\label{thm:ghost}Ghost."
                    "\\end{theorem}\n"
                    "\\begin{proof}Ghost proof.\\end{proof}\n"
                    "}\n"
                    "\\begin{theorem}\\label{thm:real}\n"
                    "Real claim.\n"
                    "\\end{theorem}\n"
                    "\\begin{proof}\n"
                    "Real proof.\n"
                    "\\end{proof}\n",
                    encoding="utf-8",
                    newline="\n",
                )

                inventory = proofcheck.scan_formal_units(source)

                self.assertEqual(
                    ["thm:real"],
                    [unit["id"] for unit in inventory["units"]],
                    inventory,
                )
                self.assertEqual(
                    {(9, 11)},
                    proofcheck.proof_environment_spans(source),
                )
                self.assertEqual([], inventory["warnings"], inventory)

    def test_extended_inline_verbatim_forms_mask_ghost_proof_structure(
        self,
    ) -> None:
        inline_forms = {
            "lstinline": (
                "\\lstinline|\\begin{theorem}\\label{thm:ghost}Ghost."
                "\\end{theorem}\\begin{proof}Ghost.\\end{proof}|"
            ),
            "mintinline": (
                "\\mintinline{latex}|\\begin{theorem}"
                "\\label{thm:ghost}Ghost.\\end{theorem}"
                "\\begin{proof}Ghost.\\end{proof}|"
            ),
            "Verb-options": (
                "\\Verb[formatcom=\\bfseries]|\\begin{theorem}"
                "\\label{thm:ghost}Ghost.\\end{theorem}"
                "\\begin{proof}Ghost.\\end{proof}|"
            ),
        }
        for case, inline_form in inline_forms.items():
            with self.subTest(case=case):
                source = self.base / f"{case}-masked.tex"
                source.write_text(
                    "\\newtheorem{theorem}{Theorem}\n"
                    f"{inline_form}\n"
                    "\\begin{theorem}\\label{thm:real}\n"
                    "Real claim.\n"
                    "\\end{theorem}\n"
                    "\\begin{proof}\n"
                    "Real proof.\n"
                    "\\end{proof}\n",
                    encoding="utf-8",
                    newline="\n",
                )

                inventory = proofcheck.scan_formal_units(source)

                self.assertEqual(
                    ["thm:real"],
                    [unit["id"] for unit in inventory["units"]],
                    inventory,
                )
                self.assertEqual(
                    {(6, 8)}, proofcheck.proof_environment_spans(source)
                )
                self.assertEqual([], inventory["warnings"], inventory)

    def test_real_theorem_and_manual_proof_survive_preceding_masked_tex(
        self,
    ) -> None:
        source = self.base / "masked-positive-control.tex"
        source.write_text(
            "\\newcommand{\\ghost}{\\newtheorem{ghost}{Ghost}"
            "\\begin{ghost}\\label{thm:macro}Ghost.\\end{ghost}"
            "\\begin{proof}Ghost.\\end{proof}}\n"
            "\\begin{verbatim}\n"
            "\\begin{theorem}\\label{thm:verbatim}Ghost.\\end{theorem}"
            "\\begin{proof}Ghost.\\end{proof}\n"
            "\\end{verbatim}\n"
            "\\begin{lstlisting}\n"
            "\\begin{theorem}\\label{thm:listing}Ghost.\\end{theorem}"
            "\\begin{proof}Ghost.\\end{proof}\n"
            "\\end{lstlisting}\n"
            "\\begin{minted}{latex}\n"
            "\\begin{theorem}\\label{thm:minted}Ghost.\\end{theorem}"
            "\\begin{proof}Ghost.\\end{proof}\n"
            "\\end{minted}\n"
            "\\iffalse\n"
            "\\begin{theorem}\\label{thm:disabled}Ghost.\\end{theorem}"
            "\\begin{proof}Ghost.\\end{proof}\n"
            "\\fi\n"
            "\\begin{theorem}\\label{thm:real}\n"
            "Real claim.\n"
            "\\end{theorem}\n"
            "\\subsection{Proof of Theorem \\ref{thm:real}}\n"
            "Real argument.\n"
            "\\qed\n",
            encoding="utf-8",
            newline="\n",
        )

        inventory = proofcheck.scan_formal_units(source)

        self.assertEqual(
            ["thm:real"],
            [unit["id"] for unit in inventory["units"]],
            inventory,
        )
        self.assertNotIn("ghost", inventory["formal_environments"], inventory)
        self.assertEqual(
            set(),
            proofcheck.proof_environment_spans(source),
            inventory,
        )
        unit = inventory["units"][0]
        self.assertEqual(
            {
                "file": source.name,
                "start_line": 14,
                "end_line": 16,
            },
            unit["statement"],
        )
        self.assertEqual(
            {
                "file": source.name,
                "start_line": 17,
                "end_line": 19,
            },
            unit["proof"],
        )
        self.assertEqual("associated", unit["proof_association"]["status"])
        self.assertEqual(
            "named_heading", unit["proof_association"]["method"]
        )
        self.assertEqual(
            "thm:real", unit["proof_association"]["target"]
        )
        self.assertEqual([], inventory["warnings"], inventory)

    def test_primitive_definition_ignores_comment_brace_before_body(
        self,
    ) -> None:
        source = self.base / "primitive-definition-comment-brace.tex"
        source.write_text(
            "\\newtheorem{theorem}{Theorem}\n"
            "\\def\\ghost% comment with {decoy}\n"
            "{\\begin{theorem}\\label{thm:ghost}Ghost.\\end{theorem}}\n"
            "\\begin{theorem}\\label{thm:real}\n"
            "Real claim.\n"
            "\\end{theorem}\n"
            "\\begin{proof}\n"
            "Real proof.\n"
            "\\end{proof}\n",
            encoding="utf-8",
            newline="\n",
        )

        inventory = proofcheck.scan_formal_units(source)

        self.assertEqual(
            ["thm:real"],
            [unit["id"] for unit in inventory["units"]],
            inventory,
        )
        unit = inventory["units"][0]
        self.assertEqual(
            {
                "file": source.name,
                "start_line": 4,
                "end_line": 6,
            },
            unit["statement"],
        )
        self.assertEqual(
            {
                "file": source.name,
                "start_line": 7,
                "end_line": 9,
            },
            unit["proof"],
        )
        self.assertEqual(
            {(7, 9)}, proofcheck.proof_environment_spans(source)
        )
        self.assertEqual([], inventory["warnings"], inventory)

    def test_newif_declaration_does_not_poison_later_unconditional_unit(
        self,
    ) -> None:
        source = self.base / "newif-unconditional-unit.tex"
        source.write_text(
            "\\newtheorem{theorem}{Theorem}\n"
            "\\newif\\ifdraft\n"
            "\\begin{theorem}\\label{thm:real}\n"
            "Real claim.\n"
            "\\end{theorem}\n"
            "\\begin{proof}\n"
            "Real proof.\n"
            "\\end{proof}\n",
            encoding="utf-8",
            newline="\n",
        )

        inventory = proofcheck.scan_formal_units(source)

        self.assertEqual(
            ["thm:real"],
            [unit["id"] for unit in inventory["units"]],
            inventory,
        )
        unit = inventory["units"][0]
        self.assertEqual("associated", unit["proof_association"]["status"])
        self.assertEqual(
            "adjacent_environment", unit["proof_association"]["method"]
        )
        self.assertTrue(
            proofcheck.locked_span_contains_label(
                {
                    "file": source.name,
                    "start_line": 3,
                    "end_line": 5,
                },
                self.base,
                "thm:real",
            )
        )
        self.assertEqual([], inventory["warnings"], inventory)

    def test_newif_custom_conditional_is_reviewed_without_losing_candidates(
        self,
    ) -> None:
        source = self.base / "newif-custom-conditional.tex"
        source.write_text(
            "\\newtheorem{theorem}{Theorem}\n"
            "\\newif\\ifdraft\n"
            "\\ifdraft\n"
            "\\begin{theorem}\\label{thm:conditional}\n"
            "Conditional claim.\n"
            "\\end{theorem}\n"
            "\\begin{proof}\n"
            "Conditional proof.\n"
            "\\end{proof}\n"
            "\\fi\n"
            "\\begin{theorem}\\label{thm:real}\n"
            "Unconditional claim.\n"
            "\\end{theorem}\n"
            "\\begin{proof}\n"
            "Unconditional proof.\n"
            "\\end{proof}\n",
            encoding="utf-8",
            newline="\n",
        )

        inventory = proofcheck.scan_formal_units(source)

        self.assertEqual(
            ["thm:conditional", "thm:real"],
            [unit["id"] for unit in inventory["units"]],
            inventory,
        )
        self.assertTrue(
            all(
                unit["proof_association"]["status"] == "associated"
                for unit in inventory["units"]
            ),
            inventory,
        )
        conditional_warnings = [
            warning
            for warning in inventory["warnings"]
            if "\\ifdraft" in warning
            and "review" in warning.lower()
        ]
        self.assertEqual(1, len(conditional_warnings), inventory)
        self.assertIn(f"{source.name}:3", conditional_warnings[0])
        self.assertFalse(
            proofcheck.locked_span_contains_label(
                {
                    "file": source.name,
                    "start_line": 4,
                    "end_line": 6,
                },
                self.base,
                "thm:conditional",
            )
        )
        self.assertTrue(
            proofcheck.locked_span_contains_label(
                {
                    "file": source.name,
                    "start_line": 11,
                    "end_line": 13,
                },
                self.base,
                "thm:real",
            )
        )

    def test_let_assignments_do_not_poison_later_unconditional_labels(
        self,
    ) -> None:
        assignments = {
            "let": "\\let\\ifdraft\\iffalse",
            "global-let": "\\global\\let\\ifdraft\\iftrue",
        }
        for case, assignment in assignments.items():
            with self.subTest(case=case):
                source = self.base / f"{case}-unconditional-label.tex"
                source.write_text(
                    "\\newtheorem{theorem}{Theorem}\n"
                    f"{assignment}\n"
                    "\\begin{theorem}\\label{thm:real}\n"
                    "Real claim.\n"
                    "\\end{theorem}\n"
                    "\\begin{proof}\n"
                    "Real proof.\n"
                    "\\end{proof}\n",
                    encoding="utf-8",
                    newline="\n",
                )

                inventory = proofcheck.scan_formal_units(source)

                self.assertEqual(
                    ["thm:real"],
                    [unit["id"] for unit in inventory["units"]],
                    inventory,
                )
                self.assertTrue(
                    proofcheck.locked_span_contains_label(
                        {
                            "file": source.name,
                            "start_line": 3,
                            "end_line": 5,
                        },
                        self.base,
                        "thm:real",
                    )
                )
                self.assertEqual([], inventory["warnings"], inventory)

    def test_expl3_definitions_mask_fake_structure_for_N_and_c_targets(
        self,
    ) -> None:
        definitions = {
            "N-type": "\\cs_new:Npn \\ghost #1",
            "c-type": "\\cs_new:cpn { ghost } #1",
        }
        for case, definition in definitions.items():
            with self.subTest(case=case):
                source = self.base / f"expl3-{case}.tex"
                source.write_text(
                    "\\newtheorem{theorem}{Theorem}\n"
                    f"{definition} {{\n"
                    "\\begin{theorem}\\label{thm:ghost}Ghost."
                    "\\end{theorem}\n"
                    "\\begin{proof}Ghost proof.\\end{proof}}\n"
                    "\\begin{theorem}\\label{thm:real}\n"
                    "Real claim.\n"
                    "\\end{theorem}\n"
                    "\\begin{proof}\n"
                    "Real proof.\n"
                    "\\end{proof}\n",
                    encoding="utf-8",
                    newline="\n",
                )

                inventory = proofcheck.scan_formal_units(source)

                self.assertEqual(
                    ["thm:real"],
                    [unit["id"] for unit in inventory["units"]],
                    inventory,
                )
                unit = inventory["units"][0]
                proof = unit["proof"]
                self.assertIsInstance(proof, dict, inventory)
                self.assertEqual(
                    {(proof["start_line"], proof["end_line"])},
                    proofcheck.proof_environment_spans(source),
                )
                self.assertEqual([], inventory["warnings"], inventory)

    def test_named_proof_heading_inside_iffalse_cannot_associate(self) -> None:
        source = self.base / "inactive-named-proof-heading.tex"
        text = (
            "\\newtheorem{theorem}{Theorem}\n"
            "\\begin{theorem}\\label{thm:real}\n"
            "Real claim.\n"
            "\\end{theorem}\n"
            "\\iffalse\n"
            "\\subsection{Proof of Theorem \\ref{thm:real}}\n"
            "\\fi\n"
            "Detached text must not acquire proof status.\n"
            "\\qed\n"
        )
        source.write_text(text, encoding="utf-8", newline="\n")

        inventory = proofcheck.scan_formal_units(source)
        unit = next(
            row for row in inventory["units"] if row["id"] == "thm:real"
        )

        self.assertIsNone(unit["proof"], inventory)
        self.assertEqual("unassociated", unit["proof_association"]["status"])
        self.assertEqual("none", unit["proof_association"]["method"])
        self.assertEqual([], unit["reference_occurrences"])
        self.assertTrue(
            any(
                "Proof-required result has no associated proof: thm:real"
                in warning
                for warning in inventory["warnings"]
            ),
            inventory,
        )

    def test_inactive_labels_and_references_are_excluded(self) -> None:
        source = self.base / "inactive-cross-references.tex"
        source.write_text(
            "\\iffalse\n"
            "\\label{eq:ghost}\n"
            "See \\ref{eq:ghost}.\n"
            "\\fi\n"
            "\\label{eq:real}\n"
            "See \\eqref{eq:real}.\n",
            encoding="utf-8",
            newline="\n",
        )

        cross_references = proofcheck.scan_cross_references(source)

        self.assertEqual(["eq:real"], list(cross_references["labels"]))
        self.assertEqual(["eq:real"], list(cross_references["references"]))
        self.assertEqual(
            ["eq:real"],
            [row["target"] for row in cross_references["occurrences"]],
        )
        self.assertEqual(
            {
                "unique_labels": 1,
                "unique_references": 1,
                "broken_references": 0,
                "orphan_labels": 0,
                "duplicate_labels": 0,
            },
            cross_references["counts"],
        )
        self.assertEqual([], cross_references["warnings"])

    def test_inactive_unless_does_not_leak_into_later_theorem_discovery(
        self,
    ) -> None:
        source = self.base / "inactive-unless-structure.tex"
        source.write_text(
            "\\newtheorem{theorem}{Theorem}\n"
            "\\iffalse\n"
            "\\unless\\iftrue\n"
            "\\begin{theorem}\\label{thm:ghost}\n"
            "Ghost claim.\n"
            "\\end{theorem}\n"
            "\\fi\n"
            "\\fi\n"
            "\\begin{theorem}\\label{thm:real}\n"
            "Real claim.\n"
            "\\end{theorem}\n"
            "\\begin{proof}\n"
            "Real proof.\n"
            "\\end{proof}\n",
            encoding="utf-8",
            newline="\n",
        )

        inventory = proofcheck.scan_formal_units(source)

        self.assertEqual(
            ["thm:real"],
            [unit["id"] for unit in inventory["units"]],
            inventory,
        )
        self.assertEqual(
            "associated",
            inventory["units"][0]["proof_association"]["status"],
        )
        self.assertEqual([], inventory["warnings"], inventory)

    def test_inactive_unless_does_not_leak_into_locked_label_recognition(
        self,
    ) -> None:
        source = self.base / "inactive-unless-labels.tex"
        source.write_text(
            "\\iffalse\n"
            "\\unless\\iftrue\n"
            "\\label{eq:ghost}\n"
            "See \\ref{eq:ghost}.\n"
            "\\fi\n"
            "\\fi\n"
            "\\label{eq:real}\n"
            "See \\ref{eq:real}.\n",
            encoding="utf-8",
            newline="\n",
        )
        span = {
            "file": source.name,
            "start_line": 1,
            "end_line": 8,
        }

        cross_references = proofcheck.scan_cross_references(source)

        self.assertFalse(
            proofcheck.locked_span_contains_label(
                span,
                self.base,
                "eq:ghost",
            )
        )
        self.assertTrue(
            proofcheck.locked_span_contains_label(
                span,
                self.base,
                "eq:real",
            )
        )
        self.assertEqual(["eq:real"], list(cross_references["labels"]))
        self.assertEqual(["eq:real"], list(cross_references["references"]))
        self.assertEqual([], cross_references["warnings"])

    def test_unknown_conditional_preserves_candidates_and_warns(self) -> None:
        source = self.base / "unknown-conditional.tex"
        source.write_text(
            "\\newtheorem{theorem}{Theorem}\n"
            "\\ifdefined\\pdfoutput\n"
            "\\begin{theorem}\\label{thm:conditional}\n"
            "Conditional claim.\n"
            "\\end{theorem}\n"
            "\\begin{proof}\n"
            "Conditional proof.\n"
            "\\end{proof}\n"
            "\\fi\n",
            encoding="utf-8",
            newline="\n",
        )

        inventory = proofcheck.scan_formal_units(source)
        self.assertEqual(
            ["thm:conditional"],
            [row["id"] for row in inventory["units"]],
            inventory,
        )
        unit = inventory["units"][0]
        self.assertEqual(
            {
                "file": source.name,
                "start_line": 3,
                "end_line": 5,
            },
            unit["statement"],
        )
        self.assertEqual(
            {
                "file": source.name,
                "start_line": 6,
                "end_line": 8,
            },
            unit["proof"],
        )
        self.assertEqual(
            "adjacent_environment", unit["proof_association"]["method"]
        )
        self.assertEqual(
            "thm:conditional", unit["proof_association"]["target"]
        )
        self.assertEqual(
            {(6, 8)}, proofcheck.proof_environment_spans(source)
        )
        conditional_warnings = [
            warning
            for warning in inventory["warnings"]
            if "\\ifdefined" in warning
            and "conditional" in warning.lower()
            and "review" in warning.lower()
        ]
        self.assertEqual(1, len(conditional_warnings), inventory)
        self.assertIn(f"{source.name}:2", conditional_warnings[0])

    def test_argument_style_conditionals_warn_without_poisoning_later_labels(
        self,
    ) -> None:
        conditionals = {
            "ifthenelse": (
                "\\ifthenelse{\\boolean{draft}}{Draft text.}{Final text.}"
            ),
            "ifdef": "\\ifdef{\\draftmode}{Draft text.}{Final text.}",
        }
        for command, conditional in conditionals.items():
            with self.subTest(command=command):
                source = self.base / f"argument-{command}.tex"
                source.write_text(
                    "\\newtheorem{theorem}{Theorem}\n"
                    f"{conditional}\n"
                    "\\begin{theorem}\\label{thm:real}\n"
                    "Real claim.\n"
                    "\\end{theorem}\n"
                    "\\begin{proof}\n"
                    "Real proof.\n"
                    "\\end{proof}\n",
                    encoding="utf-8",
                    newline="\n",
                )

                inventory = proofcheck.scan_formal_units(source)

                self.assertEqual(
                    ["thm:real"],
                    [unit["id"] for unit in inventory["units"]],
                    inventory,
                )
                self.assertEqual(
                    "associated",
                    inventory["units"][0]["proof_association"]["status"],
                )
                self.assertTrue(
                    proofcheck.locked_span_contains_label(
                        {
                            "file": source.name,
                            "start_line": 3,
                            "end_line": 5,
                        },
                        self.base,
                        "thm:real",
                    )
                )
                conditional_warnings = [
                    warning
                    for warning in inventory["warnings"]
                    if f"\\{command}" in warning
                    and "review" in warning.lower()
                ]
                self.assertEqual(1, len(conditional_warnings), inventory)
                self.assertIn(f"{source.name}:2", conditional_warnings[0])

    def test_argument_conditional_inside_iffalse_does_not_steal_outer_fi(
        self,
    ) -> None:
        source = self.base / "argument-conditional-inside-iffalse.tex"
        source.write_text(
            "\\newtheorem{theorem}{Theorem}\n"
            "\\iffalse\n"
            "\\ifthenelse{\\boolean{draft}}{%\n"
            "\\begin{theorem}\\label{thm:ghost}Ghost.\\end{theorem}\n"
            "}{Final text.}\n"
            "\\fi\n"
            "\\begin{theorem}\\label{thm:real}\n"
            "Real claim.\n"
            "\\end{theorem}\n"
            "\\begin{proof}\n"
            "Real proof.\n"
            "\\end{proof}\n",
            encoding="utf-8",
            newline="\n",
        )

        inventory = proofcheck.scan_formal_units(source)

        self.assertEqual(
            ["thm:real"],
            [unit["id"] for unit in inventory["units"]],
            inventory,
        )
        self.assertTrue(
            proofcheck.locked_span_contains_label(
                {
                    "file": source.name,
                    "start_line": 7,
                    "end_line": 9,
                },
                self.base,
                "thm:real",
            )
        )

    def test_argument_conditional_inside_unknown_primitive_preserves_outer_fi(
        self,
    ) -> None:
        source = self.base / "argument-conditional-inside-ifdraft.tex"
        source.write_text(
            "\\newtheorem{theorem}{Theorem}\n"
            "\\newif\\ifdraft\n"
            "\\ifdraft\n"
            "\\ifthenelse{\\boolean{nested}}{%\n"
            "\\begin{theorem}\\label{thm:conditional}\n"
            "Conditional claim.\n"
            "\\end{theorem}\n"
            "}{Final text.}\n"
            "\\fi\n"
            "\\begin{theorem}\\label{thm:real}\n"
            "Real claim.\n"
            "\\end{theorem}\n"
            "\\begin{proof}\n"
            "Real proof.\n"
            "\\end{proof}\n",
            encoding="utf-8",
            newline="\n",
        )

        inventory = proofcheck.scan_formal_units(source)

        self.assertEqual(
            ["thm:conditional", "thm:real"],
            [unit["id"] for unit in inventory["units"]],
            inventory,
        )
        self.assertFalse(
            proofcheck.locked_span_contains_label(
                {
                    "file": source.name,
                    "start_line": 5,
                    "end_line": 7,
                },
                self.base,
                "thm:conditional",
            )
        )
        self.assertTrue(
            proofcheck.locked_span_contains_label(
                {
                    "file": source.name,
                    "start_line": 10,
                    "end_line": 12,
                },
                self.base,
                "thm:real",
            )
        )
        self.assertEqual(
            1,
            sum(
                "\\ifdraft" in warning and "review" in warning.lower()
                for warning in inventory["warnings"]
            ),
            inventory,
        )

    def test_lowercase_argument_conditionals_inside_iffalse_preserve_outer_fi(
        self,
    ) -> None:
        openings = {
            "ifbool": "\\ifbool{draft}{%",
            "ifnumgreater": "\\ifnumgreater{2}{1}{%",
            "ifdimgreater": "\\ifdimgreater{2pt}{1pt}{%",
        }
        for command, opening in openings.items():
            with self.subTest(command=command):
                source = self.base / f"{command}-inside-iffalse.tex"
                source.write_text(
                    "\\newtheorem{theorem}{Theorem}\n"
                    "\\iffalse\n"
                    f"{opening}\n"
                    "\\begin{theorem}\\label{thm:ghost}\n"
                    "Ghost claim.\n"
                    "\\end{theorem}\n"
                    "}{Final text.}\n"
                    "\\fi\n"
                    "\\begin{theorem}\\label{thm:real}\n"
                    "Real claim.\n"
                    "\\end{theorem}\n"
                    "\\begin{proof}\n"
                    "Real proof.\n"
                    "\\end{proof}\n",
                    encoding="utf-8",
                    newline="\n",
                )

                inventory = proofcheck.scan_formal_units(source)

                self.assertEqual(
                    ["thm:real"],
                    [unit["id"] for unit in inventory["units"]],
                    inventory,
                )
                self.assertTrue(
                    proofcheck.locked_span_contains_label(
                        {
                            "file": source.name,
                            "start_line": 9,
                            "end_line": 11,
                        },
                        self.base,
                        "thm:real",
                    )
                )

    def test_lowercase_argument_conditionals_inside_unknown_primitive_preserve_fi(
        self,
    ) -> None:
        openings = {
            "ifbool": "\\ifbool{draft}{%",
            "ifnumgreater": "\\ifnumgreater{2}{1}{%",
            "ifdimgreater": "\\ifdimgreater{2pt}{1pt}{%",
        }
        for command, opening in openings.items():
            with self.subTest(command=command):
                source = self.base / f"{command}-inside-ifdraft.tex"
                source.write_text(
                    "\\newtheorem{theorem}{Theorem}\n"
                    "\\newif\\ifdraft\n"
                    "\\ifdraft\n"
                    f"{opening}\n"
                    "\\begin{theorem}\\label{thm:conditional}\n"
                    "Conditional claim.\n"
                    "\\end{theorem}\n"
                    "}{Final text.}\n"
                    "\\fi\n"
                    "\\begin{theorem}\\label{thm:real}\n"
                    "Real claim.\n"
                    "\\end{theorem}\n"
                    "\\begin{proof}\n"
                    "Real proof.\n"
                    "\\end{proof}\n",
                    encoding="utf-8",
                    newline="\n",
                )

                inventory = proofcheck.scan_formal_units(source)

                self.assertEqual(
                    ["thm:conditional", "thm:real"],
                    [unit["id"] for unit in inventory["units"]],
                    inventory,
                )
                self.assertFalse(
                    proofcheck.locked_span_contains_label(
                        {
                            "file": source.name,
                            "start_line": 5,
                            "end_line": 7,
                        },
                        self.base,
                        "thm:conditional",
                    )
                )
                self.assertTrue(
                    proofcheck.locked_span_contains_label(
                        {
                            "file": source.name,
                            "start_line": 10,
                            "end_line": 12,
                        },
                        self.base,
                        "thm:real",
                    )
                )

    def test_uppercase_and_expl3_argument_conditionals_are_review_bounded(
        self,
    ) -> None:
        conditionals = {
            "IfFileExists": (
                "\\IfFileExists{draft.tex}{\n",
                "}{Fallback text.}\n",
            ),
            "bool_if:NTF": (
                "\\bool_if:NTF \\l_tmpa_bool {\n",
                "}{Fallback text.}\n",
            ),
        }
        for command, (opening, closing) in conditionals.items():
            with self.subTest(command=command):
                source = self.base / f"argument-{command.replace(':', '-')}.tex"
                source.write_text(
                    "\\newtheorem{theorem}{Theorem}\n"
                    f"{opening}"
                    "\\begin{theorem}\\label{thm:conditional}\n"
                    "Conditional claim.\n"
                    "\\end{theorem}\n"
                    "\\begin{proof}\n"
                    "Conditional proof.\n"
                    "\\end{proof}\n"
                    f"{closing}"
                    "\\begin{theorem}\\label{thm:real}\n"
                    "Unconditional claim.\n"
                    "\\end{theorem}\n"
                    "\\begin{proof}\n"
                    "Unconditional proof.\n"
                    "\\end{proof}\n",
                    encoding="utf-8",
                    newline="\n",
                )

                inventory = proofcheck.scan_formal_units(source)

                self.assertEqual(
                    ["thm:conditional", "thm:real"],
                    [unit["id"] for unit in inventory["units"]],
                    inventory,
                )
                self.assertTrue(
                    all(
                        unit["proof_association"]["status"] == "associated"
                        for unit in inventory["units"]
                    ),
                    inventory,
                )
                conditional_warnings = [
                    warning
                    for warning in inventory["warnings"]
                    if f"\\{command}" in warning
                    and "review" in warning.lower()
                ]
                self.assertEqual(1, len(conditional_warnings), inventory)
                self.assertIn(f"{source.name}:2", conditional_warnings[0])
                self.assertFalse(
                    proofcheck.locked_span_contains_label(
                        {
                            "file": source.name,
                            "start_line": 3,
                            "end_line": 5,
                        },
                        self.base,
                        "thm:conditional",
                    )
                )
                self.assertTrue(
                    proofcheck.locked_span_contains_label(
                        {
                            "file": source.name,
                            "start_line": 10,
                            "end_line": 12,
                        },
                        self.base,
                        "thm:real",
                    )
                )

    def test_multiline_expl3_n_type_conditional_is_review_bounded(
        self,
    ) -> None:
        source = self.base / "argument-bool-if-ntf-multiline.tex"
        source.write_text(
            "\\newtheorem{theorem}{Theorem}\n"
            "\\bool_if:NTF\n"
            "  \\l_tmpa_bool\n"
            "  {\n"
            "\\begin{theorem}\\label{thm:conditional}\n"
            "Conditional claim.\n"
            "\\end{theorem}\n"
            "\\begin{proof}\n"
            "Conditional proof.\n"
            "\\end{proof}\n"
            "  }\n"
            "  {Fallback text.}\n"
            "\\begin{theorem}\\label{thm:real}\n"
            "Unconditional claim.\n"
            "\\end{theorem}\n"
            "\\begin{proof}\n"
            "Unconditional proof.\n"
            "\\end{proof}\n",
            encoding="utf-8",
            newline="\n",
        )

        inventory = proofcheck.scan_formal_units(source)

        self.assertEqual(
            ["thm:conditional", "thm:real"],
            [unit["id"] for unit in inventory["units"]],
            inventory,
        )
        self.assertTrue(
            all(
                unit["proof_association"]["status"] == "associated"
                for unit in inventory["units"]
            ),
            inventory,
        )
        warnings = [
            warning
            for warning in inventory["warnings"]
            if "\\bool_if:NTF" in warning and "review" in warning.lower()
        ]
        self.assertEqual(1, len(warnings), inventory)
        self.assertIn(f"{source.name}:2", warnings[0])
        self.assertFalse(
            proofcheck.locked_span_contains_label(
                {
                    "file": source.name,
                    "start_line": 5,
                    "end_line": 7,
                },
                self.base,
                "thm:conditional",
            )
        )
        self.assertTrue(
            proofcheck.locked_span_contains_label(
                {
                    "file": source.name,
                    "start_line": 13,
                    "end_line": 15,
                },
                self.base,
                "thm:real",
            )
        )

    def test_multiline_expl3_nn_type_conditional_is_review_bounded(
        self,
    ) -> None:
        source = self.base / "argument-cs-if-eq-nntf-multiline.tex"
        source.write_text(
            "\\newtheorem{theorem}{Theorem}\n"
            "\\cs_if_eq:NNTF\n"
            "  \\l_tmpa_tl\n"
            "  \\l_tmpb_tl\n"
            "  {\n"
            "\\begin{theorem}\\label{thm:conditional}\n"
            "Conditional claim.\n"
            "\\end{theorem}\n"
            "\\begin{proof}\n"
            "Conditional proof.\n"
            "\\end{proof}\n"
            "  }\n"
            "  {Fallback text.}\n"
            "\\begin{theorem}\\label{thm:real}\n"
            "Unconditional claim.\n"
            "\\end{theorem}\n"
            "\\begin{proof}\n"
            "Unconditional proof.\n"
            "\\end{proof}\n",
            encoding="utf-8",
            newline="\n",
        )

        inventory = proofcheck.scan_formal_units(source)

        self.assertEqual(
            ["thm:conditional", "thm:real"],
            [unit["id"] for unit in inventory["units"]],
            inventory,
        )
        warnings = [
            warning
            for warning in inventory["warnings"]
            if "\\cs_if_eq:NNTF" in warning and "review" in warning.lower()
        ]
        self.assertEqual(1, len(warnings), inventory)
        self.assertIn(f"{source.name}:2", warnings[0])
        self.assertFalse(
            proofcheck.locked_span_contains_label(
                {
                    "file": source.name,
                    "start_line": 6,
                    "end_line": 8,
                },
                self.base,
                "thm:conditional",
            )
        )
        self.assertTrue(
            proofcheck.locked_span_contains_label(
                {
                    "file": source.name,
                    "start_line": 14,
                    "end_line": 16,
                },
                self.base,
                "thm:real",
            )
        )

    def test_ifnextchar_token_argument_is_review_bounded(self) -> None:
        source = self.base / "argument-ifnextchar-token.tex"
        source.write_text(
            "\\newtheorem{theorem}{Theorem}\n"
            "\\makeatletter\n"
            "\\@ifnextchar\n"
            "  [\n"
            "  {\n"
            "\\begin{theorem}\\label{thm:conditional}\n"
            "Conditional claim.\n"
            "\\end{theorem}\n"
            "\\begin{proof}\n"
            "Conditional proof.\n"
            "\\end{proof}\n"
            "  }\n"
            "  {Fallback text.}\n"
            "\\makeatother\n"
            "\\begin{theorem}\\label{thm:real}\n"
            "Unconditional claim.\n"
            "\\end{theorem}\n"
            "\\begin{proof}\n"
            "Unconditional proof.\n"
            "\\end{proof}\n",
            encoding="utf-8",
            newline="\n",
        )

        inventory = proofcheck.scan_formal_units(source)

        self.assertEqual(
            ["thm:conditional", "thm:real"],
            [unit["id"] for unit in inventory["units"]],
            inventory,
        )
        warnings = [
            warning
            for warning in inventory["warnings"]
            if "\\@ifnextchar" in warning and "review" in warning.lower()
        ]
        self.assertEqual(1, len(warnings), inventory)
        self.assertIn(f"{source.name}:3", warnings[0])
        self.assertFalse(
            proofcheck.locked_span_contains_label(
                {
                    "file": source.name,
                    "start_line": 6,
                    "end_line": 8,
                },
                self.base,
                "thm:conditional",
            )
        )
        self.assertTrue(
            proofcheck.locked_span_contains_label(
                {
                    "file": source.name,
                    "start_line": 15,
                    "end_line": 17,
                },
                self.base,
                "thm:real",
            )
        )

    def test_thmtools_declaretheorem_registers_the_formal_environment(
        self,
    ) -> None:
        source = self.base / "thmtools-declaretheorem.tex"
        source.write_text(
            "\\usepackage{thmtools}\n"
            "\\declaretheorem[name=Proposition]{proposition}\n"
            "\\begin{proposition}\\label{prop:real}\n"
            "The declared proposition holds.\n"
            "\\end{proposition}\n"
            "\\begin{proof}\n"
            "The claim follows directly.\n"
            "\\end{proof}\n",
            encoding="utf-8",
            newline="\n",
        )

        inventory = proofcheck.scan_formal_units(source)

        self.assertIn("proposition", inventory["formal_environments"])
        self.assertEqual(
            ["prop:real"],
            [unit["id"] for unit in inventory["units"]],
            inventory,
        )
        self.assertEqual(
            "associated",
            inventory["units"][0]["proof_association"]["status"],
        )
        self.assertEqual([], inventory["warnings"], inventory)

    def test_adversarial_masking_order_preserves_real_structure(self) -> None:
        source = self.base / "adversarial-masking-order.tex"
        source.write_text(
            "\\newtheorem{result}{Result}\n"
            "\\newcommand{\\ghost}{\\begin{verbatim}}\n"
            "\\verb|%| \\begin{result}\\label{res:real}\n"
            "Real claim.\n"
            "\\end{result}\n"
            "\\begin{proof}\n"
            "Real proof.\n"
            "\\end{proof}\n",
            encoding="utf-8",
            newline="\n",
        )

        inventory = proofcheck.scan_formal_units(source)

        self.assertIn("result", inventory["formal_environments"])
        self.assertEqual(
            ["res:real"],
            [row["id"] for row in inventory["units"]],
            inventory,
        )
        unit = inventory["units"][0]
        self.assertEqual(
            {
                "file": source.name,
                "start_line": 3,
                "end_line": 5,
            },
            unit["statement"],
        )
        self.assertEqual(
            {
                "file": source.name,
                "start_line": 6,
                "end_line": 8,
            },
            unit["proof"],
        )
        self.assertEqual(
            {(6, 8)}, proofcheck.proof_environment_spans(source)
        )
        self.assertEqual("associated", unit["proof_association"]["status"])
        self.assertEqual(
            "adjacent_environment", unit["proof_association"]["method"]
        )
        self.assertEqual("res:real", unit["proof_association"]["target"])
        self.assertEqual([], inventory["warnings"], inventory)

    def test_named_proof_accepts_terminal_marker_after_substantive_text(
        self,
    ) -> None:
        cases = {
            "qed-suffix": (
                "Thus the claim follows. \\qed\n",
                6,
                "\\qed",
                "qed_marker",
            ),
            "black-box-suffix": (
                "Thus the claim follows. \\hfill\\BlackBox\n",
                6,
                "\\BlackBox",
                "qed_marker",
            ),
            "display-qedhere-suffix": (
                "\\begin{align*}\n"
                "x_n\n"
                "&=0. \\qedhere\n"
                "\\end{align*}\n",
                8,
                "\\qedhere",
                "qed_here_marker",
            ),
            "display-qedhere-bracket-close": (
                "\\[\n"
                "x_n=0. \\qedhere\n"
                "\\]\n",
                7,
                "\\qedhere",
                "qed_here_marker",
            ),
            "display-qedhere-same-line-align-close": (
                "\\begin{align*}\n"
                "x_n&=0. \\qedhere\\end{align*}\n",
                7,
                "\\qedhere",
                "qed_here_marker",
            ),
            "dollar-square-suffix": (
                "Thus the claim follows. $\\square$\n",
                6,
                "\\square",
                "qed_marker",
            ),
            "dollar-blacksquare-suffix": (
                "Thus the claim follows. $\\blacksquare$\n",
                6,
                "\\blacksquare",
                "qed_marker",
            ),
        }
        for case, (
            body,
            marker_line,
            marker,
            boundary_kind,
        ) in cases.items():
            with self.subTest(case=case):
                source = self.base / f"named-{case}.tex"
                source.write_text(
                    "\\newtheorem{theorem}{Theorem}\n"
                    "\\begin{theorem}\\label{thm:manual}\n"
                    "The claim holds.\n"
                    "\\end{theorem}\n"
                    "\\subsection{Proof of Theorem \\ref{thm:manual}}\n"
                    f"{body}",
                    encoding="utf-8",
                    newline="\n",
                )

                region = proofcheck.analyze_proof_region(
                    source,
                    5,
                    target_unit_id="thm:manual",
                )

                self.assertEqual("accepted", region["status"], region)
                self.assertEqual("named_heading", region["method"], region)
                self.assertEqual(
                    boundary_kind,
                    region["boundary"]["kind"],
                )
                self.assertEqual(
                    region["end_line"],
                    region["boundary"]["line"],
                )
                self.assertEqual(
                    marker_line,
                    region["boundary"]["marker_line"],
                )
                self.assertIn(
                    marker,
                    proofcheck.read_lines(source)[marker_line - 1],
                )
                self.assertTrue(
                    proofcheck.proof_span_has_safe_boundary(
                        source,
                        5,
                        region["end_line"],
                        target_unit_id="thm:manual",
                    )
                )
                inventory = proofcheck.scan_formal_units(source)
                unit = next(
                    row
                    for row in inventory["units"]
                    if row["id"] == "thm:manual"
                )
                self.assertIsNotNone(unit["proof"], inventory)
                self.assertEqual(
                    "named_heading",
                    unit["proof_association"]["method"],
                )

    def test_suffix_terminal_markers_remain_strict_about_proof_tails(
        self,
    ) -> None:
        cases = {
            "substantive-tail": (
                "\\subsection{Proof of Theorem \\ref{thm:manual}}\n"
                "First argument. \\qed\n"
                "A second substantive derivation continues here.\n"
                "\\end{document}\n",
                "terminator_followed_by_substantive_or_ambiguous_tail",
            ),
            "competing-markers": (
                "\\subsection{Proof of Theorem \\ref{thm:manual}}\n"
                "First argument. \\qed\n"
                "Second argument. \\hfill\\BlackBox\n"
                "\\end{document}\n",
                "multiple_terminal_markers",
            ),
        }
        for case, (text, expected_reason) in cases.items():
            with self.subTest(case=case):
                source = self.base / f"named-{case}.tex"
                source.write_text(text, encoding="utf-8", newline="\n")

                region = proofcheck.analyze_proof_region(
                    source,
                    1,
                    target_unit_id="thm:manual",
                )

                self.assertEqual("ambiguous", region["status"], region)
                self.assertEqual(expected_reason, region["reason"], region)
                self.assertIsNone(
                    proofcheck.bounded_proof_region(
                        source,
                        1,
                        target_unit_id="thm:manual",
                    )
                )

    def test_manual_heading_with_nested_ref_and_terminal_marker_is_bounded(
        self,
    ) -> None:
        source = self.base / "manual-terminal-proof.tex"
        source.write_text(
            "\\newtheorem{theorem}{Theorem}\n"
            "\\begin{theorem}\\label{thm:manual}\n"
            "The claim holds.\n"
            "\\end{theorem}\n"
            "\\subsection{Proof of Theorem \\ref{thm:manual}}\n"
            "The proof checks the claim directly.\n"
            "\\hfill\\BlackBox\n"
            "% The remaining lines are document epilogue only.\n"
            "\\vskip 0.15in\n"
            "\\bibliography{refs}\n"
            "\\end{document}\n",
            encoding="utf-8",
            newline="\n",
        )

        region = proofcheck.bounded_proof_region(source, 5)

        self.assertIsNotNone(region)
        self.assertEqual(5, region["start_line"])
        self.assertEqual(7, region["end_line"])
        self.assertEqual(
            "Proof of Theorem \\ref{thm:manual}",
            region["header_span"]["text"],
        )
        self.assertEqual(
            {
                "kind": "qed_marker",
                "line": 7,
                "marker_line": 7,
                "evidence": "\\hfill\\BlackBox",
            },
            region["boundary"],
        )
        self.assertTrue(proofcheck.proof_span_has_safe_boundary(source, 5, 7))

        inventory = proofcheck.scan_formal_units(source)
        unit = next(row for row in inventory["units"] if row["id"] == "thm:manual")
        unit["proof"] = {
            "file": proofcheck.relative_or_absolute(source, self.base),
            "start_line": 5,
            "end_line": 7,
        }
        units = {"thm:manual": unit}
        cross_references = proofcheck.scan_cross_references(source)
        owners = proofcheck.reviewed_label_owners(
            cross_references, units, self.base
        )
        evidence = proofcheck.reviewed_span_evidence(
            "thm:manual", unit, self.base, owners
        )
        heading_occurrence = next(
            row
            for row in evidence["reference_occurrences"]
            if row["target"] == "thm:manual"
        )
        self.assertEqual("proof_header", heading_occurrence["structural_context"])

    def test_terminal_manual_proof_rejects_ambiguous_or_substantive_tail(
        self,
    ) -> None:
        cases = {
            "substantive_tail": (
                "\\subsection{Proof of Theorem \\ref{thm:manual}}\n"
                "First argument.\n"
                "\\hfill\\BlackBox\n"
                "A second substantive derivation continues here.\n"
                "\\end{document}\n",
                [3],
            ),
            "ambiguous_closures": (
                "\\subsection{Proof of Theorem \\ref{thm:manual}}\n"
                "First argument.\n"
                "\\hfill\\BlackBox\n"
                "Second argument.\n"
                "\\hfill\\BlackBox\n"
                "\\end{document}\n",
                [3, 5],
            ),
        }
        for name, (text, candidate_ends) in cases.items():
            with self.subTest(case=name):
                source = self.base / f"manual-{name}.tex"
                source.write_text(text, encoding="utf-8", newline="\n")
                for end_line in candidate_ends:
                    self.assertFalse(
                        proofcheck.proof_span_has_safe_boundary(
                            source, 1, end_line
                        )
                    )

    def test_schema5_accepts_a_long_indivisible_display(self) -> None:
        ledger_path = self.make_schema5_long_display_ledger()

        errors, _ = proofcheck.check_ledger_data(ledger_path, True)

        self.assertEqual([], errors)

    def test_schema5_rejects_a_coarse_multi_transition_step(self) -> None:
        ledger_path = self.make_schema5_long_display_ledger()
        ledger = read_json(ledger_path)
        step = next(row for row in ledger["steps"] if row["id"] == "S003")
        step["inference"]["moves"].append(
            {
                "id": "M002",
                "claim": step["restatement"],
                "rule": "A second transition hidden in the same ledger step",
                "premise_ids": [],
                "prior_move_ids": ["M001"],
                "justification": (
                    "This deliberately records a second logical transition in S003."
                ),
            }
        )
        step["inference"]["conclusion_move"] = "M002"
        ledger["review"]["conclusion_results"][0]["support"]["move_id"] = "M002"
        self.seal_schema5_challenge(ledger_path, ledger)

        errors, _ = proofcheck.check_ledger_data(ledger_path, True)

        self.assertTrue(
            any(
                "schema-5" in error.lower()
                and "exactly one" in error.lower()
                and "move" in error.lower()
                for error in errors
            ),
            errors,
        )

    def test_schema5_derivation_rejects_duplicate_exact_conclusion_premises(
        self,
    ) -> None:
        ledger_path = self.make_complete_audit()
        ledger = self.upgrade_ledger_to_schema5(ledger_path)
        prior = ledger["steps"][0]
        prior["kind"] = "setup"
        prior["restatement"] = "x equals x"
        step = next(row for row in ledger["steps"] if row["id"] == "S003")
        dependency = {
            "id": "S001",
            "kind": "step",
            "status": "verified",
            "needed_form": step["restatement"],
            "compatibility_check": "The imported claim exactly repeats the goal.",
        }
        step["dependencies"] = [dependency]
        for premise_id in ("P002", "P003"):
            step["premise_uses"].append(
                {
                    "id": premise_id,
                    "role": "fact",
                    "claim": step["restatement"],
                    "origin": {"kind": "prior_step", "reference": "S001"},
                    "evidence": (
                        "The prior row is cited verbatim as the conclusion under review."
                    ),
                }
            )
            step["inference"]["moves"][0]["premise_ids"].append(premise_id)
        self.seal_schema5_challenge(ledger_path, ledger)

        errors, _ = proofcheck.check_ledger_data(ledger_path, True)

        self.assertTrue(
            any(
                "derivation" in error.lower()
                and "restatement" in error.lower()
                and ("premise" in error.lower() or "circular" in error.lower())
                for error in errors
            ),
            errors,
        )

    def test_schema5_evidence_specificity_is_conservative_and_bounded(self) -> None:
        ledger_path = self.make_schema5_parallel_steps_ledger()
        baseline = read_json(ledger_path)
        repeated = (
            "The exact same evidence sentence is reused without identifying "
            "the claim checked in this step."
        )

        cross_step = json.loads(json.dumps(baseline))
        for step_id in ("S003", "S004", "S005", "S006"):
            step = next(row for row in cross_step["steps"] if row["id"] == step_id)
            step["checks"]["literal"] = repeated
        self.seal_schema5_challenge(ledger_path, cross_step)
        errors, _ = proofcheck.check_ledger_data(ledger_path, True)
        repetition_errors = [
            error
            for error in errors
            if "evidence" in error.lower()
            and ("repeated" in error.lower() or "specificity" in error.lower())
        ]
        self.assertEqual(1, len(repetition_errors), errors)
        self.assertIn("4", repetition_errors[0])
        self.assertIn("S003", repetition_errors[0])

        cross_aspect = json.loads(json.dumps(baseline))
        step = next(row for row in cross_aspect["steps"] if row["id"] == "S003")
        for aspect in ("domain", "dimension", "sign"):
            row = next(
                item for item in step["risk_checks"] if item["aspect"] == aspect
            )
            row["status"] = "passed"
            row["evidence"] = repeated
        self.seal_schema5_challenge(ledger_path, cross_aspect)
        errors, _ = proofcheck.check_ledger_data(ledger_path, True)
        aspect_errors = [
            error
            for error in errors
            if "risk" in error.lower()
            and "evidence" in error.lower()
            and ("aspect" in error.lower() or "specificity" in error.lower())
        ]
        self.assertEqual(1, len(aspect_errors), errors)
        self.assertIn("3", aspect_errors[0])
        self.assertIn("S003", aspect_errors[0])

    def test_dependency_issue_origin_enters_propagation_and_recheck_closure(
        self,
    ) -> None:
        ledger_path = self.make_complete_audit()
        self.install_internal_dependency(ledger_path)
        self.seal_schema5_challenge(
            ledger_path,
            read_json(ledger_path),
            covered_issue_ids=["I-001"],
        )
        _, summaries, _ = proofcheck.audit_ledgers(self.audit, True)
        summaries_by_id = {
            summary["unit_id"]: summary for summary in summaries
        }
        registry = read_json(
            self.audit
            / "audit"
            / "03_dependencies"
            / "DEPENDENCY_REGISTRY.json"
        )
        issue = {
            "id": "I-001",
            "severity": "S1",
            "confidence": "high",
            "status": "resolved",
            "finding_status": "resolved",
            "scope": "unit",
            "load_bearing": True,
            "affected_result": "lem:main",
            "affected_results": ["lem:main"],
            "summary": "The dependency use required an explicit compatibility repair.",
            "origin_ref": {
                "kind": "dependency_use",
                "unit_id": "lem:main",
                "use_id": "D001",
            },
            "contract_refs": [
                {
                    "kind": "dependency_use",
                    "unit_id": "lem:main",
                    "use_id": "D001",
                },
                {
                    "kind": "conclusion",
                    "unit_id": "lem:main",
                    "conclusion_id": "C001",
                },
            ],
            "invalidation_kind": "dependency_mismatch",
            "suggested_changes": [],
            "rechecked_units": ["lem:main"],
            "rechecked_dependency_uses": ["D001"],
            "reconciled_deliverables": [],
        }

        projection = proofcheck.canonical_issue_detail_projection(
            issue,
            summaries_by_id,
            registry["internal_uses"],
            ["lem:main"],
            [],
            "defects_found",
        )

        self.assertTrue(
            any(row[2] == "D001" for row in projection["propagation"]),
            projection,
        )
        closure = projection["closure"][0]
        self.assertEqual("D001", closure[2])
        self.assertEqual("D001", closure[3])
        self.assertEqual("complete", closure[-1])

        issue["rechecked_dependency_uses"] = []
        projection = proofcheck.canonical_issue_detail_projection(
            issue,
            summaries_by_id,
            registry["internal_uses"],
            ["lem:main"],
            [],
            "defects_found",
        )
        self.assertEqual("open", projection["closure"][0][-1])

    def test_dependency_mismatch_requires_nonclean_backlinked_origin_use(
        self,
    ) -> None:
        ledger_path = self.make_complete_audit()
        self.install_internal_dependency(ledger_path)
        issue = self.make_global_issue(
            finding_status="defect",
            load_bearing=True,
            severity="S1",
            summary="The recorded dependency use is incompatible with the needed form.",
        )
        issue.update(
            {
                "origin_ref": {
                    "kind": "dependency_use",
                    "unit_id": "lem:main",
                    "use_id": "D001",
                },
                "contract_refs": [
                    {
                        "kind": "dependency_use",
                        "unit_id": "lem:main",
                        "use_id": "D001",
                    },
                    {
                        "kind": "conclusion",
                        "unit_id": "lem:main",
                        "conclusion_id": "C001",
                    },
                ],
                "invalidation_kind": "dependency_mismatch",
            }
        )
        issue["suggested_changes"][0]["action"] = "repair_dependency"
        manifest = read_json(self.audit / "AUDIT_MANIFEST.json")
        registry = read_json(
            self.audit
            / "audit"
            / "03_dependencies"
            / "DEPENDENCY_REGISTRY.json"
        )
        dependency_edges = registry["internal_uses"]

        def validate(summaries: list[dict]) -> list[str]:
            errors, _ = proofcheck.validate_issues(
                [issue],
                set(),
                True,
                evidence_base=self.audit,
                source_snapshot_id=manifest["source_snapshot"]["sha256"],
                in_scope=["lem:main", "lem:prior"],
                ledger_summaries=summaries,
                dependency_edges=dependency_edges,
            )
            return errors

        _, clean_summaries, _ = proofcheck.audit_ledgers(self.audit, True)
        clean_errors = validate(clean_summaries)
        self.assertTrue(
            any(
                "dependency_mismatch" in error
                and "origin_ref" in error
                and (
                    "nonclean" in error.lower()
                    or "backlink" in error.lower()
                    or "verified" in error.lower()
                )
                for error in clean_errors
            ),
            clean_errors,
        )

        ledger = read_json(ledger_path)
        step_dependency = ledger["steps"][2]["dependencies"][0]
        review_dependency = ledger["review"]["direct_dependencies"][0]
        for dependency in (step_dependency, review_dependency):
            dependency["status"] = "incorrect"
            dependency["issue_ids"] = ["I-001"]
        write_json(ledger_path, ledger)
        dependency_edges[0]["status"] = "incorrect"
        dependency_edges[0]["issue_ids"] = ["I-001"]
        nonclean_summaries = json.loads(json.dumps(clean_summaries))
        main_summary = next(
            summary
            for summary in nonclean_summaries
            if summary["unit_id"] == "lem:main"
        )
        main_summary["review_components"]["dependency_closure"] = "incorrect"

        self.assertEqual([], validate(nonclean_summaries))

        ledger = read_json(ledger_path)
        for dependency in (
            ledger["steps"][2]["dependencies"][0],
            ledger["review"]["direct_dependencies"][0],
        ):
            dependency["status"] = "unclear"
        write_json(ledger_path, ledger)
        dependency_edges[0]["status"] = "unclear"
        main_summary["review_components"]["dependency_closure"] = "unclear"

        definite_errors = validate(nonclean_summaries)
        self.assertTrue(
            any(
                "status 'unclear'" in error
                and "finding_status 'defect'" in error
                for error in definite_errors
            ),
            definite_errors,
        )
        issue["finding_status"] = "inconclusive"
        self.assertEqual([], validate(nonclean_summaries))

        ledger = read_json(ledger_path)
        for dependency in (
            ledger["steps"][2]["dependencies"][0],
            ledger["review"]["direct_dependencies"][0],
        ):
            dependency["status"] = "incorrect"
        write_json(ledger_path, ledger)
        dependency_edges[0]["status"] = "incorrect"
        main_summary["review_components"]["dependency_closure"] = "incorrect"
        inconclusive_errors = validate(nonclean_summaries)
        self.assertTrue(
            any(
                "status 'incorrect'" in error
                and "finding_status 'inconclusive'" in error
                for error in inconclusive_errors
            ),
            inconclusive_errors,
        )
        issue["finding_status"] = "defect"

        ledger = read_json(ledger_path)
        for dependency in (
            ledger["steps"][2]["dependencies"][0],
            ledger["review"]["direct_dependencies"][0],
        ):
            dependency["issue_ids"] = []
        write_json(ledger_path, ledger)
        dependency_edges[0]["issue_ids"] = []
        backlink_errors = validate(nonclean_summaries)
        self.assertTrue(
            any(
                "origin_ref dependency use" in error
                and (
                    "backlink" in error.lower()
                    or "link back" in error.lower()
                )
                for error in backlink_errors
            ),
            backlink_errors,
        )

    def install_declared_user_report_with_orientation(
        self,
        orientation: str,
    ) -> tuple[Path, Path]:
        self.make_complete_audit()
        self.upgrade_complete_audit_to_schema5()
        canonical_report = (
            self.audit / "audit" / "06_reports" / "FINAL_REPORT.md"
        )
        user_report = self.audit / "audit" / "06_reports" / "USER_REPORT.md"
        canonical_text = canonical_report.read_text(encoding="utf-8")
        deliverable_table = proofcheck.render_markdown_table(
            [
                "Deliverable ID",
                "Role",
                "Path",
                "Issue IDs",
                "Overall verdict",
            ],
            [
                [
                    "R001",
                    "user_facing_report",
                    "audit/06_reports/USER_REPORT.md",
                    "none",
                    "no_defect_found",
                ]
            ],
        )
        canonical_text = canonical_text.replace(
            "- Declared external deliverables: none",
            "- Declared external deliverables: R001",
            1,
        ).replace(
            "### Declared external deliverables\n\nNone.",
            "### Declared external deliverables\n\n" + deliverable_table,
            1,
        )
        user_text = canonical_text.replace(
            "# Final Proof-Check Report",
            f"# Reader-Facing Proof Audit\n\n{orientation}",
            1,
        )
        user_report.write_text(
            user_text,
            encoding="utf-8",
            newline="\n",
        )
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        manifest["report_deliverables"] = [
            {
                "id": "R001",
                "role": "user_facing_report",
                "path": "audit/06_reports/USER_REPORT.md",
                "sha256": proofcheck.sha256_file(user_report),
                "issue_ids": [],
                "overall_verdict": "no_defect_found",
            }
        ]
        write_json(manifest_path, manifest)
        canonical_report.write_text(
            canonical_text,
            encoding="utf-8",
            newline="\n",
        )
        return canonical_report, user_report

    def test_declared_user_report_rejects_active_correctness_overclaim(
        self,
    ) -> None:
        self.install_declared_user_report_with_orientation(
            "The theorem and its proof are correct."
        )

        errors, _ = proofcheck.check_audit_finalization(self.audit)

        self.assertTrue(
            any(
                "report_deliverables[1]" in error
                and "correctness overclaim" in error
                for error in errors
            ),
            errors,
        )

    def test_declared_user_report_rejects_nonfinal_scaffold_marker(
        self,
    ) -> None:
        _, user_report = (
            self.install_declared_user_report_with_orientation(
                "This orientation paragraph is reader-facing only."
            )
        )
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        user_report.write_text(
            f"> **{proofcheck.REPORT_SCAFFOLD_MARKER}:** Working report.\n\n"
            + user_report.read_text(encoding="utf-8"),
            encoding="utf-8",
            newline="\n",
        )
        new_digest = proofcheck.sha256_file(user_report)
        manifest["report_deliverables"][0]["sha256"] = new_digest
        write_json(manifest_path, manifest)

        errors, _ = proofcheck.check_audit_finalization(self.audit)

        self.assertIn(
            "report_deliverables[1]: user-facing report still contains the "
            "NONFINAL scaffold marker",
            errors,
        )

    def test_declared_user_report_requires_exact_metadata_and_core_sections(
        self,
    ) -> None:
        canonical_report, user_report = (
            self.install_declared_user_report_with_orientation(
                "This orientation paragraph is reader-facing only."
            )
        )
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        baseline_canonical = canonical_report.read_text(encoding="utf-8")
        baseline_user = user_report.read_text(encoding="utf-8")
        baseline_manifest = read_json(manifest_path)
        source_snapshot = baseline_manifest["source_snapshot"]["sha256"]
        cases = {
            "not-answer-first": (
                baseline_user.replace(
                    "## Summary",
                    "## Orientation\n\nReader context only.\n\n## Summary",
                    1,
                ),
                "must begin its substantive content with ## Summary",
            ),
            "changed-skill-version": (
                baseline_user.replace(
                    f"- Skill version: {proofcheck.SKILL_VERSION}",
                    "- Skill version: 9.9",
                    1,
                ),
                "user-facing report field Skill version disagrees",
            ),
            "changed-source-snapshot": (
                baseline_user.replace(
                    f"- Source snapshot ID: {source_snapshot}",
                    f"- Source snapshot ID: {'0' * 64}",
                    1,
                ),
                "user-facing report field Source snapshot ID disagrees",
            ),
            "removed-top-metadata": (
                re.sub(
                    r"(?ms)^- Overall assessment code:.*?"
                    r"^- Final confidence:.*?\n+",
                    "",
                    baseline_user,
                    count=1,
                ),
                "rendered report needs exactly one canonical overall verdict",
            ),
            "missing-results-and-impact": (
                re.sub(
                    r"(?ms)^## Results and impact\s*$.*?(?=^## |\Z)",
                    "",
                    baseline_user,
                    count=1,
                ),
                "user-facing Results and impact section is missing or duplicated",
            ),
        }
        for case, (mutated_user, expected) in cases.items():
            with self.subTest(case=case):
                user_report.write_text(
                    mutated_user,
                    encoding="utf-8",
                    newline="\n",
                )
                changed_manifest = json.loads(json.dumps(baseline_manifest))
                changed_digest = proofcheck.sha256_file(user_report)
                changed_manifest["report_deliverables"][0]["sha256"] = (
                    changed_digest
                )
                write_json(manifest_path, changed_manifest)

                errors, _ = proofcheck.check_audit_finalization(self.audit)

                self.assertTrue(
                    any(
                        "report_deliverables[1]" in error
                        and expected in error
                        for error in errors
                    ),
                    errors,
                )
        user_report.write_text(
            baseline_user,
            encoding="utf-8",
            newline="\n",
        )
        write_json(manifest_path, baseline_manifest)
        canonical_report.write_text(
            baseline_canonical,
            encoding="utf-8",
            newline="\n",
        )

    def test_declared_user_report_rejects_issue_and_verdict_drift(self) -> None:
        self.install_declared_user_report_with_orientation(
            "This orientation paragraph is reader-facing only."
        )
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)

        errors, _ = proofcheck.check_audit_finalization(self.audit)
        self.assertFalse(
            any("report_deliverables" in error for error in errors), errors
        )

        cases = {
            "issue_ids": ("issue_ids", ["I-999"]),
            "overall_verdict": ("overall_verdict", "defects_found"),
        }
        for name, (field, value) in cases.items():
            with self.subTest(case=name):
                changed = json.loads(json.dumps(manifest))
                changed["report_deliverables"][0][field] = value
                write_json(manifest_path, changed)

                errors, _ = proofcheck.check_audit_finalization(self.audit)

                self.assertTrue(
                    any(
                        "report_deliverables[1]" in error
                        and field in error
                        and (
                            "canonical" in error.lower()
                            or "disagree" in error.lower()
                        )
                        for error in errors
                    ),
                    errors,
                )

    def test_declared_user_report_requires_canonical_semantic_sections(
        self,
    ) -> None:
        _, user_report = self.install_declared_user_report_with_orientation(
            "This extra orientation paragraph is permitted user-facing prose."
        )
        manifest_path = self.audit / "AUDIT_MANIFEST.json"

        errors, _ = proofcheck.check_audit_finalization(self.audit)
        self.assertFalse(
            any("report_deliverables[1]" in error for error in errors),
            errors,
        )

        user_text = user_report.read_text(encoding="utf-8")
        results = proofcheck.report_section(
            user_text, "## Results and impact"
        ) or ""
        drifted_results = results.replace(
            "| established |", "| not_established |", 1
        )
        self.assertNotEqual(results, drifted_results)
        drifted = proofcheck.replace_report_section_text(
            user_text,
            "## Results and impact",
            drifted_results,
        )
        user_report.write_text(
            drifted,
            encoding="utf-8",
            newline="\n",
        )
        manifest = read_json(manifest_path)
        manifest["report_deliverables"][0]["sha256"] = (
            proofcheck.sha256_file(user_report)
        )
        write_json(manifest_path, manifest)

        errors, _ = proofcheck.check_audit_finalization(self.audit)
        self.assertTrue(
            any(
                "report_deliverables[1]" in error
                and "Results and impact" in error
                and (
                    "canonical" in error.lower()
                    or "disagree" in error.lower()
                )
                for error in errors
            ),
            errors,
        )

    def prepare_two_unit_challenge_audit(self) -> tuple[Path, Path]:
        main_path = self.make_complete_audit()
        prior_path, _ = self.install_internal_dependency(main_path)

        main = read_json(main_path)
        main_step = next(row for row in main["steps"] if row["id"] == "S003")
        main_step["dependencies"] = []
        main_step["premise_uses"] = [main_step["premise_uses"][0]]
        main_step["inference"]["moves"][0]["premise_ids"] = ["P001"]
        main["review"]["direct_dependencies"] = []
        main["review"]["conclusion_results"][0]["dependency_use_ids"] = []
        main["independent_check"] = {
            "required": False,
            "status": "not_required",
            "independence_level": "none",
            "challenger_verdict": "not_checked",
            "reconciled_verdict": "not_checked",
            "artifact": "",
            "covered_issue_ids": [],
            "source_snapshot_sha256": "",
            "challenged_ledger_sha256": "",
            "challenge_context_sha256": "",
            "challenge_artifact_sha256": "",
            "issue_assessments": [],
            "generated_utc": "",
            "disagreements": [],
            "resolution": "",
        }
        write_json(main_path, main)

        prior = read_json(prior_path)
        prior["independent_check"]["artifact"] = (
            "audit/05_adversarial/lem-prior-challenge.md"
        )
        write_json(prior_path, prior)
        prior_artifact = self.audit / prior["independent_check"]["artifact"]
        prior_artifact.write_text(
            "# Fresh-context challenge for lem:prior\n\n"
            "The blinded reconstruction was checked line by line; "
            "its verdict is verified.\n",
            encoding="utf-8",
            newline="\n",
        )

        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        manifest["audit_scope"]["depth"] = "full"
        manifest["audit_scope"]["critical_units"] = ["lem:prior"]
        write_json(manifest_path, manifest)

        registry_path = (
            self.audit
            / "audit"
            / "03_dependencies"
            / "DEPENDENCY_REGISTRY.json"
        )
        registry = read_json(registry_path)
        registry["internal_uses"] = []
        write_json(registry_path, registry)

        report_path = self.audit / "audit" / "06_reports" / "FINAL_REPORT.md"
        report = report_path.read_text(encoding="utf-8")
        report = report.replace(
            "| lem:main | C001 | verified | valid | established | verified | "
            "not_applicable | S003/M001 | D001 | none |",
            "| lem:main | C001 | verified | valid | established | verified | "
            "not_applicable | S003/M001 | none | none |",
        )
        report = report.replace(
            "| lem:main | D001 | lem:prior | C001 | internal_result | verified | "
            "passed | verified | none |",
            "None.",
        )
        report_path.write_text(report, encoding="utf-8", newline="\n")

        self.upgrade_complete_audit_to_schema5()
        return main_path, prior_path

    def make_schema5_issue(
        self,
        *,
        severity: str,
        status: str,
        issue_id: str = "I-001",
    ) -> dict:
        issue = {
            "id": issue_id,
            "severity": severity,
            "confidence": "high",
            "status": status,
            "finding_status": "resolved" if status == "resolved" else "inconclusive",
            "scope": "unit",
            "load_bearing": True,
            "affected_result": "lem:main",
            "affected_results": ["lem:main"],
            "summary": "A load-bearing proof premise requires explicit resolution.",
            "origin_ref": {
                "kind": "ledger_move",
                "unit_id": "lem:main",
                "step_id": "S003",
                "move_id": "M001",
            },
            "contract_refs": [
                {
                    "kind": "conclusion",
                    "unit_id": "lem:main",
                    "conclusion_id": "C001",
                }
            ],
            "invalidation_kind": "scope_inconclusive",
            "suggested_changes": [
                {
                    "target_ref": {
                        "kind": "source_span",
                        "file": proofcheck.relative_or_absolute(
                            self.paper, self.audit
                        ),
                        "start_line": 6,
                        "end_line": 6,
                        "sha256": proofcheck.source_span_sha256(self.paper, 6, 6),
                    },
                    "action": "repair_step",
                    "repair_scope": (
                        "unit_statement" if severity == "S0" else "local_step"
                    ),
                    "assumption_cost": (
                        "adds_regularity_or_moment"
                        if severity == "S0"
                        else "none"
                    ),
                    "proposal": "Supply the missing premise and recheck the conclusion.",
                    "verification_status": "candidate",
                    "required_rechecks": ["lem:main"],
                }
            ],
        }
        if severity in {"S0", "S1"}:
            issue["repair_search"] = make_repair_search(severity)
        if status == "resolved":
            manifest = read_json(self.audit / "AUDIT_MANIFEST.json")
            issue.update(
                {
                    "resolution": "The missing premise was supplied and rechecked.",
                    "source_revision": "The current locked source contains the repair.",
                    "recheck_evidence": [
                        "The repaired move and conclusion were checked again."
                    ],
                    "source_snapshot_sha256": manifest["source_snapshot"]["sha256"],
                    "rechecked_units": ["lem:main"],
                }
            )
        return issue

    def install_schema5_issue(
        self,
        ledger_path: Path,
        issue: dict,
        *,
        reconcile_report_views: bool = True,
    ) -> None:
        ledger = read_json(ledger_path)
        step = next(
            step for step in ledger["steps"] if step["id"] == "S003"
        )
        step["issue_ids"] = sorted(set([*step["issue_ids"], issue["id"]]))
        result = ledger["review"]["conclusion_results"][0]
        result["issue_ids"] = sorted(
            set([*result["issue_ids"], issue["id"]])
        )
        unresolved_load_bearing = (
            issue["status"] in {"open", "deferred"}
            and issue["load_bearing"] is True
        )
        if unresolved_load_bearing:
            self.mark_s003_conditional(ledger)
            step["side_conditions"] = [
                {
                    "id": "SC001",
                    "generated_by": "M001",
                    "condition": (
                        "Resolve the load-bearing finding before treating the "
                        "conclusion as unconditional."
                    ),
                    "status": "open",
                }
            ]
            step["conditions"] = [
                {
                    "kind": "side_condition",
                    "reference": "SC001",
                    "condition": (
                        "The conclusion is conditional on resolving the linked "
                        "load-bearing finding."
                    ),
                }
            ]
        write_json(ledger_path, ledger)

        progress_path = self.audit / "PROGRESS.json"
        progress = read_json(progress_path)
        progress["conditional_units"] = (
            ["lem:main"] if unresolved_load_bearing else []
        )
        progress["open_high_priority_issues"] = (
            [issue["id"]]
            if unresolved_load_bearing and issue["severity"] in {"S0", "S1"}
            else []
        )
        write_json(progress_path, progress)

        report_path = self.audit / "audit" / "06_reports" / "FINAL_REPORT.md"
        report = report_path.read_text(encoding="utf-8")
        if unresolved_load_bearing:
            report = report.replace(
                "| lem:main | verified | verified | valid | established | verified |",
                "| lem:main | conditionally_verified | verified | conditional | "
                "conditional | verified |",
            )
            report = report.replace(
                "| lem:main | C001 | verified | valid | established | verified |",
                "| lem:main | C001 | verified | conditional | conditional | verified |",
            )
        report = report.replace(
            "| lem:main | C001 | verified | "
            + ("conditional | conditional" if unresolved_load_bearing else "valid | established")
            + " | verified | not_applicable | S003/M001 | none | none |",
            "| lem:main | C001 | verified | "
            + ("conditional | conditional" if unresolved_load_bearing else "valid | established")
            + f" | verified | not_applicable | S003/M001 | none | {issue['id']} |",
        )
        report_path.write_text(report, encoding="utf-8", newline="\n")

        self.install_canonical_issue(
            issue,
            migrate=False,
            reconcile_report_views=reconcile_report_views,
        )
        issue_path = self.audit / "audit" / "06_reports" / "ISSUE_LOG.json"
        issue_log = read_json(issue_path)
        issue_log["schema_version"] = 5
        write_json(issue_path, issue_log)

    def make_archivable_s1_audit(self) -> tuple[Path, dict]:
        ledger_path = self.make_complete_audit()
        self.set_expected_assessment("inconclusive")
        issue = self.make_schema5_issue(severity="S1", status="open")
        self.install_schema5_issue(ledger_path, issue)

        ledger = read_json(ledger_path)
        ledger["independent_check"].update(
            {
                "status": "agreed",
                "challenger_verdict": "conditionally_verified",
                "reconciled_verdict": "conditionally_verified",
                "disagreements": [],
                "resolution": "",
            }
        )
        self.seal_schema5_challenge(
            ledger_path,
            ledger,
            covered_issue_ids=["I-001"],
            artifact_text=(
                "# Historical challenge\n\n"
                "The fresh challenge confirms that I-001 leaves lem:main "
                "conditional pending repair.\n"
            ),
        )
        self.install_canonical_issue(issue, migrate=False)

        errors, _ = proofcheck.check_audit_finalization(self.audit)
        self.assertEqual([], errors)
        with contextlib.redirect_stdout(io.StringIO()):
            status = proofcheck.cmd_finalize(
                argparse.Namespace(root=self.audit)
            )
        self.assertEqual(0, status)
        return ledger_path, issue

    def finalize_and_archive_current_issue(
        self,
        issue_id: str = "I-001",
    ) -> tuple[Path, dict]:
        errors, _ = proofcheck.check_audit_finalization(self.audit)
        self.assertEqual([], errors)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(
                0,
                proofcheck.cmd_finalize(argparse.Namespace(root=self.audit)),
            )
            self.assertEqual(
                0,
                proofcheck.cmd_archive_issue(
                    argparse.Namespace(root=self.audit, issue_id=issue_id)
                ),
            )
        archive_path = (
            self.audit
            / "audit"
            / "06_reports"
            / "history"
            / f"{issue_id}-origin.json"
        )
        issue_path = self.audit / "audit" / "06_reports" / "ISSUE_LOG.json"
        archived_issue = next(
            row
            for row in read_json(issue_path)["issues"]
            if row["id"] == issue_id
        )
        return archive_path, archived_issue

    def make_archivable_interface_origin_audit(
        self,
    ) -> tuple[Path, dict, dict]:
        self.make_complete_audit()
        record = self.make_interface_record(
            specification="ambiguous",
            target_verdict="not_assessable",
            code_to_documented="not_assessable",
        )
        issue = self.make_global_issue(
            finding_status="inconclusive",
            load_bearing=False,
            severity="S3",
            summary=(
                "The method interface has two unresolved population readings."
            ),
        )
        issue.update(
            {
                "interface_id": record["id"],
                "finding_class": "exposition_ambiguity",
                "affected_layer": "specification",
                "evidence_class": "observed",
                "estimator_target_status": "not_assessable",
                "implementation_inspection_status": "inspected",
                "code_to_documented_estimator": "not_assessable",
                "code_to_required_target": "consistent",
                "execution_provenance_status": "not_checked",
                "resolution_evidence_needed": [
                    "State the numerator and denominator laws explicitly."
                ],
                "origin_ref": {
                    "kind": "interface_record",
                    "interface_id": record["id"],
                    "evidence_spans": [
                        dict(
                            record["fitting_sample_laws"][0][
                                "evidence_spans"
                            ][0]
                        )
                    ],
                },
                "invalidation_kind": "scope_inconclusive",
            }
        )
        self.install_interface_issue(record, issue)
        archive_path, archived_issue = self.finalize_and_archive_current_issue()
        return archive_path, archived_issue, record

    def make_archivable_global_origin_audit(
        self,
    ) -> tuple[Path, dict, dict]:
        self.make_complete_audit()
        aspect = "constants_and_rates"
        check = {
            "aspect": aspect,
            "status": "defect",
            "evidence": (
                "The historical global check records a distinctive rate "
                "mismatch before repair."
            ),
            "affected_units": ["lem:main"],
            "issue_ids": ["I-001"],
        }
        issue = self.make_global_issue(
            finding_status="defect",
            load_bearing=False,
            severity="S2",
            summary="The global rate check records a repairable mismatch.",
        )
        issue["origin_ref"] = {
            "kind": "global_check",
            "aspect": aspect,
            "evidence_spans": [
                proofcheck.locked_span(
                    self.paper,
                    2,
                    4,
                    self.audit,
                    role="global_consistency_evidence",
                )
            ],
        }
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        global_pass = manifest["completion"]["global_consistency_pass"]
        canonical_check = next(
            row for row in global_pass["checks"] if row["aspect"] == aspect
        )
        canonical_check.update(check)
        global_pass["status"] = "completed_with_findings"
        write_json(manifest_path, manifest)
        self.set_expected_assessment("defects_found")
        self.install_canonical_issue(issue, migrate=False)
        archive_path, archived_issue = self.finalize_and_archive_current_issue()
        return archive_path, archived_issue, check

    def rebind_tampered_archived_failure(
        self,
        archive: dict,
        replacement_evidence: str,
    ) -> None:
        old_row = list(archive["projection"]["failure"][0])
        new_row = list(old_row)
        new_row[8] = replacement_evidence
        archive["projection"]["failure"] = [new_row]
        archive["projection_sha256"] = proofcheck.canonical_sha256(
            archive["projection"]
        )
        archive["archive_payload_sha256"] = (
            proofcheck.resolution_archive_payload_sha256(archive)
        )

    def make_resolved_s1_lifecycle_audit(
        self,
    ) -> tuple[Path, Path, dict]:
        main_path = self.make_complete_audit()
        self.install_internal_dependency(main_path)
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        registry_path = (
            self.audit
            / "audit"
            / "03_dependencies"
            / "DEPENDENCY_REGISTRY.json"
        )
        inventory_path = (
            self.audit
            / "audit"
            / "01_index"
            / "theorem_inventory.json"
        )
        issue_path = self.audit / "audit" / "06_reports" / "ISSUE_LOG.json"
        summary_path = (
            self.audit / "audit" / "06_reports" / "ISSUE_SUMMARY.md"
        )
        report_path = self.audit / "audit" / "06_reports" / "FINAL_REPORT.md"
        progress_path = self.audit / "PROGRESS.json"
        baseline = {
            "main": read_json(main_path),
            "manifest": read_json(manifest_path),
            "registry": read_json(registry_path),
            "issues": read_json(issue_path),
            "summary": summary_path.read_text(encoding="utf-8"),
            "report": report_path.read_text(encoding="utf-8"),
            "progress": read_json(progress_path),
        }

        self.set_expected_assessment("inconclusive")
        historical_issue = self.make_schema5_issue(
            severity="S1",
            status="open",
        )
        self.install_schema5_issue(main_path, historical_issue)
        historical_report = report_path.read_text(encoding="utf-8")
        historical_report = historical_report.replace(
            "| lem:main | C001 | verified | conditional | conditional | "
            "verified | not_applicable | S003/M001 | D001 | none |",
            "| lem:main | C001 | verified | conditional | conditional | "
            "verified | not_applicable | S003/M001 | D001 | I-001 |",
        )
        report_path.write_text(
            historical_report,
            encoding="utf-8",
            newline="\n",
        )
        historical_ledger = read_json(main_path)
        historical_ledger["independent_check"].update(
            {
                "status": "agreed",
                "challenger_verdict": "conditionally_verified",
                "reconciled_verdict": "conditionally_verified",
                "disagreements": [],
                "resolution": "",
            }
        )
        self.seal_schema5_challenge(
            main_path,
            historical_ledger,
            covered_issue_ids=["I-001"],
            artifact_text=(
                "# Historical challenge\n\n"
                "The fresh challenge confirms that I-001 leaves lem:main "
                "conditional pending repair.\n"
            ),
        )
        self.install_canonical_issue(historical_issue, migrate=False)

        historical_errors, _ = proofcheck.check_audit_finalization(
            self.audit
        )
        self.assertEqual([], historical_errors)
        with contextlib.redirect_stdout(io.StringIO()):
            prior_status = proofcheck.cmd_finalize(
                argparse.Namespace(root=self.audit)
            )
        self.assertEqual(0, prior_status)
        prior_record = read_json(
            self.audit / "audit" / "06_reports" / "FINALIZATION.json"
        )

        historical_manifest = read_json(manifest_path)
        source_snapshot_sha256 = historical_manifest[
            "source_snapshot"
        ]["sha256"]
        with contextlib.redirect_stdout(io.StringIO()):
            archive_status = proofcheck.cmd_archive_issue(
                argparse.Namespace(
                    root=self.audit,
                    issue_id="I-001",
                )
            )
        self.assertEqual(0, archive_status)
        archive_path = (
            self.audit
            / "audit"
            / "06_reports"
            / "history"
            / "I-001-origin.json"
        )
        archive = read_json(archive_path)
        self.assertEqual(
            prior_record,
            archive["prior_finalization_record"],
        )
        self.assertEqual(
            {
                "manifest",
                "issue_log",
                "final_report",
                "inventory",
                "dependency_registry",
                "method_interface_registry",
                "ledgers",
            },
            set(archive["prior_artifacts"]),
        )
        self.assertTrue(archive["prior_sources"])
        self.assertEqual(
            "audit/06_reports/FINAL_REPORT.md",
            archive["prior_artifacts"]["final_report"]["file"],
        )
        self.assertEqual(
            {
                row["file"]
                for row in historical_manifest["source_snapshot"]["files"]
            },
            {row["file"] for row in archive["prior_sources"]},
        )
        sealed_records = [
            archive["prior_artifacts"]["manifest"],
            archive["prior_artifacts"]["issue_log"],
            archive["prior_artifacts"]["final_report"],
            archive["prior_artifacts"]["inventory"],
            archive["prior_artifacts"]["dependency_registry"],
            archive["prior_artifacts"]["method_interface_registry"],
            *archive["prior_artifacts"]["ledgers"],
            *archive["prior_sources"],
        ]
        for record in sealed_records:
            self.assertEqual(
                {"file", "sha256", "content_base64"},
                set(record),
            )
        archived_issue_log = read_json(issue_path)
        archived_issue = next(
            row
            for row in archived_issue_log["issues"]
            if row["id"] == "I-001"
        )
        historical_origin = archived_issue["historical_origin"]

        write_json(main_path, baseline["main"])
        write_json(manifest_path, baseline["manifest"])
        write_json(registry_path, baseline["registry"])
        write_json(issue_path, baseline["issues"])
        summary_path.write_text(
            baseline["summary"],
            encoding="utf-8",
            newline="\n",
        )
        report_path.write_text(
            baseline["report"],
            encoding="utf-8",
            newline="\n",
        )
        write_json(progress_path, baseline["progress"])

        current_ledger = read_json(main_path)
        current_ledger["independent_check"].update(
            {
                "required": True,
                "status": "agreed",
                "independence_level": "fresh_context_same_model",
                "challenger_verdict": "verified",
                "reconciled_verdict": "verified",
                "artifact": (
                    "audit/05_adversarial/"
                    "lem-main-post-repair-challenge.md"
                ),
                "disagreements": [],
                "resolution": "",
            }
        )
        write_json(main_path, current_ledger)

        resolved_issue = json.loads(json.dumps(historical_issue))
        resolved_issue.update(
            {
                "status": "resolved",
                "finding_status": "resolved",
                "resolution": (
                    "The proof move was repaired, D001 was rechecked, and the "
                    "affected result was independently verified."
                ),
                "source_revision": (
                    "The current schema-five ledger records the repaired "
                    "proof move and dependency closure."
                ),
                "recheck_evidence": [
                    "The current ledger and fresh challenge both verify lem:main."
                ],
                "source_snapshot_sha256": source_snapshot_sha256,
                "rechecked_units": ["lem:main"],
                "rechecked_dependency_uses": ["D001"],
                "reconciled_deliverables": [],
                "historical_origin": historical_origin,
                "current_resolution": {
                    "disposition": "repaired",
                    "current_ref": dict(historical_issue["origin_ref"]),
                    "mapping": (
                        "The archived failed move maps to the same S003/M001 "
                        "reference, which is clean in the current ledger."
                    ),
                    "verification_status": "verified_sufficient",
                    "evidence_spans": [
                        proofcheck.locked_span(
                            self.paper,
                            6,
                            6,
                            self.audit,
                            role="repair_verification",
                        )
                    ],
                    "required_rechecks": ["lem:main"],
                    "retired_dependency_uses": [],
                },
            }
        )
        self.install_canonical_issue(resolved_issue, migrate=False)
        self.seal_schema5_challenge(
            main_path,
            read_json(main_path),
            covered_issue_ids=["I-001"],
            artifact_text=(
                "# Post-repair challenge\n\n"
                "A fresh context rechecked the clean S003/M001 move, the "
                "D001 dependency use, and resolved issue I-001.\n"
            ),
        )
        self.install_canonical_issue(resolved_issue, migrate=False)
        return main_path, archive_path, resolved_issue

    def convert_resolved_lifecycle_to_removed_move(
        self,
        main_path: Path,
        issue: dict,
    ) -> dict:
        ledger = read_json(main_path)
        step = next(row for row in ledger["steps"] if row["id"] == "S003")
        move = next(
            row
            for row in step["inference"]["moves"]
            if row["id"] == "M001"
        )
        move["id"] = "M002"
        step["inference"]["conclusion_move"] = "M002"
        ledger["review"]["conclusion_results"][0]["support"]["move_id"] = (
            "M002"
        )
        write_json(main_path, ledger)

        report_path = self.audit / "audit" / "06_reports" / "FINAL_REPORT.md"
        report_path.write_text(
            report_path.read_text(encoding="utf-8").replace(
                "| lem:main | C001 | verified | valid | established | "
                "verified | not_applicable | S003/M001 | D001 | none |",
                "| lem:main | C001 | verified | valid | established | "
                "verified | not_applicable | S003/M002 | D001 | none |",
                1,
            ),
            encoding="utf-8",
            newline="\n",
        )
        issue["resolution"] = (
            "The archived failed M001 move was removed while lem:main was "
            "retained and rechecked through clean move M002."
        )
        issue["source_revision"] = (
            "The retained current ledger no longer contains archived move "
            "S003/M001."
        )
        issue["recheck_evidence"] = [
            "The current ledger and fresh challenge verify retained lem:main."
        ]
        issue["current_resolution"].update(
            {
                "disposition": "removed",
                "current_ref": None,
                "mapping": (
                    "Archived move S003/M001 was deleted inside retained "
                    "lem:main; current move S003/M002 now establishes the "
                    "same conclusion."
                ),
            }
        )
        self.install_canonical_issue(issue, migrate=False)
        self.seal_schema5_challenge(
            main_path,
            read_json(main_path),
            covered_issue_ids=["I-001"],
            artifact_text=(
                "# Post-removal challenge\n\n"
                "A fresh context verified the retained lem:main ledger after "
                "the archived M001 move was removed and the clean M002 move "
                "was reconstructed.\n"
            ),
        )
        self.install_canonical_issue(issue, migrate=False)
        return issue

    def test_cmd_archive_issue_generated_s1_lifecycle_finalizes(self) -> None:
        _, _, issue = self.make_resolved_s1_lifecycle_audit()

        errors, _ = proofcheck.check_audit_finalization(self.audit)

        self.assertEqual([], errors)
        self.assertEqual(
            "verified_sufficient",
            issue["current_resolution"]["verification_status"],
        )
        with contextlib.redirect_stdout(io.StringIO()):
            status = proofcheck.cmd_finalize(
                argparse.Namespace(root=self.audit)
            )
        self.assertEqual(0, status)
        self.assertEqual(
            "passed",
            read_json(
                self.audit
                / "audit"
                / "06_reports"
                / "FINALIZATION.json"
            )["status"],
        )

    def test_prior_version_internal_archive_survives_revalidation(self) -> None:
        prior_version = "1.2"
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        with mock.patch.object(proofcheck, "SKILL_VERSION", prior_version):
            manifest = read_json(manifest_path)
            manifest["protocol"] = proofcheck.protocol_identity()
            write_json(manifest_path, manifest)
            _, archive_path, issue = self.make_resolved_s1_lifecycle_audit()
            archive = read_json(archive_path)

            registry_record = archive["prior_artifacts"]["dependency_registry"]
            prior_registry = json.loads(
                base64.b64decode(registry_record["content_base64"]).decode("utf-8")
            )
            use = prior_registry["internal_uses"][0]
            legacy_edge = {
                "dependent_unit": use["dependent_unit"],
                "use_id": use["use_id"],
                "dependency_id": use["dependency_id"],
                "dependency_conclusion_id": use["dependency_conclusion_id"],
                "kind": "internal_result",
                "source_status": "verified",
                "applicability_status": "passed",
                "effective_status": use["status"],
                "step_ids": use["step_ids"],
                "issue_ids": use["issue_ids"],
                "compatibility_checks": use["compatibility_checks"],
                "prerequisite_map": [],
                "source_evidence": [],
            }
            archive["required_closure"]["dependency_uses"][0][
                "edge_sha256"
            ] = proofcheck.canonical_sha256(legacy_edge)

            report_record = archive["prior_artifacts"]["final_report"]
            report_text = base64.b64decode(
                report_record["content_base64"]
            ).decode("utf-8")
            columns = [
                "Dependent",
                "Use ID",
                "Dependency",
                "Dependency conclusion",
                "Kind",
                "Source status",
                "Applicability status",
                "Effective status",
                "Issue IDs",
            ]
            report_row = [
                use["dependent_unit"],
                use["use_id"],
                use["dependency_id"],
                use["dependency_conclusion_id"],
                "internal_result",
                "verified",
                "passed",
                use["status"],
                proofcheck.canonical_id_field(use["issue_ids"]),
            ]
            legacy_table = "\n".join(
                [
                    "| " + " | ".join(columns) + " |",
                    "| " + " | ".join("---" for _ in columns) + " |",
                    "| " + " | ".join(report_row) + " |",
                ]
            )
            report_text = (
                report_text.rstrip()
                + "\n\n## Dependency closure\n\n"
                + legacy_table
                + "\n"
            )
            report_record["content_base64"] = base64.b64encode(
                report_text.encode("utf-8")
            ).decode("ascii")
            report_record["sha256"] = proofcheck.sha256_text(report_text)

            required_units = set(archive["required_closure"]["units"])
            archive["prior_artifacts"]["ledgers"] = [
                record
                for record in archive["prior_artifacts"]["ledgers"]
                if json.loads(
                    base64.b64decode(record["content_base64"]).decode("utf-8")
                )["unit_id"]
                in required_units
            ]
            archive["ledger_sha256s"] = {
                unit_id: digest
                for unit_id, digest in archive["ledger_sha256s"].items()
                if unit_id in required_units
            }

            prior_record = archive["prior_finalization_record"]
            report_row_record = next(
                row
                for row in prior_record["artifact_manifest"]
                if row["file"] == report_record["file"]
            )
            report_row_record["sha256"] = report_record["sha256"]
            prior_record["audit_state_sha256"] = proofcheck.canonical_sha256(
                prior_record["artifact_manifest"]
            )
            prior_record["record_payload_sha256"] = (
                proofcheck.finalization_payload_sha256(prior_record)
            )
            archive["prior_finalization_record_sha256"] = (
                proofcheck.canonical_sha256(prior_record)
            )
            archive["archive_payload_sha256"] = (
                proofcheck.resolution_archive_payload_sha256(archive)
            )
            write_json(archive_path, archive)
            issue["historical_origin"]["sha256"] = proofcheck.sha256_file(
                archive_path
            )
            issue_path = self.audit / "audit" / "06_reports" / "ISSUE_LOG.json"
            issue_log = read_json(issue_path)
            issue_log["issues"] = [issue]
            write_json(issue_path, issue_log)

        sealed_bytes = archive_path.read_bytes()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = proofcheck.cmd_revalidate_protocol(
                argparse.Namespace(root=self.audit)
            )
        payload = json.loads(output.getvalue())

        self.assertEqual(0, status)
        self.assertEqual("revalidated", payload["status"])
        self.assertEqual(prior_version, payload["previous_skill_version"])
        self.assertEqual(proofcheck.SKILL_VERSION, payload["current_skill_version"])
        self.assertEqual(sealed_bytes, archive_path.read_bytes())
        self.assertEqual(
            prior_version,
            read_json(archive_path)["protocol"]["skill_version"],
        )
        errors: list[str] = []
        loaded = proofcheck.load_resolution_archive(issue, self.audit, errors)
        self.assertIsNotNone(loaded)
        self.assertEqual([], errors)

    def test_archive_issue_seals_prior_method_interface_registry(self) -> None:
        archive_path, _, record = self.make_archivable_interface_origin_audit()
        archive = read_json(archive_path)
        sealed = archive["prior_artifacts"]["method_interface_registry"]
        registry_path = (
            self.audit
            / "audit"
            / "03_dependencies"
            / "METHOD_INTERFACE_REGISTRY.json"
        )
        sealed_bytes = base64.b64decode(sealed["content_base64"])
        sealed_registry = json.loads(sealed_bytes.decode("utf-8"))
        artifact_row = next(
            row
            for row in archive["prior_finalization_record"][
                "artifact_manifest"
            ]
            if row["file"] == sealed["file"]
        )

        self.assertEqual(
            "audit/03_dependencies/METHOD_INTERFACE_REGISTRY.json",
            sealed["file"],
        )
        self.assertEqual(proofcheck.sha256_file(registry_path), sealed["sha256"])
        self.assertEqual(registry_path.read_bytes(), sealed_bytes)
        self.assertEqual(sealed["sha256"], artifact_row["sha256"])
        self.assertEqual([record], sealed_registry["interfaces"])

    def test_resolved_interface_archive_recomputes_sealed_origin_failure(
        self,
    ) -> None:
        archive_path, archived_issue, _ = (
            self.make_archivable_interface_origin_audit()
        )
        baseline_errors: list[str] = []
        proofcheck.load_resolution_archive(
            archived_issue,
            self.audit,
            baseline_errors,
        )
        self.assertEqual([], baseline_errors)

        archive = read_json(archive_path)
        self.rebind_tampered_archived_failure(
            archive,
            json.dumps(
                {
                    "target_relation": {"verdict": "match"},
                    "implementation_relation": {"inspection_status": "inspected"},
                    "issue_ids": ["I-001"],
                },
                ensure_ascii=False,
            ),
        )
        write_json(archive_path, archive)
        resolved_issue = json.loads(json.dumps(archived_issue))
        resolved_issue["status"] = "resolved"
        resolved_issue["finding_status"] = "resolved"
        resolved_issue["historical_origin"]["sha256"] = (
            proofcheck.sha256_file(archive_path)
        )

        errors: list[str] = []
        proofcheck.load_resolution_archive(
            resolved_issue,
            self.audit,
            errors,
        )

        self.assertTrue(
            any("sealed canonical origin record" in error for error in errors),
            errors,
        )
        self.assertFalse(
            any("exact prior finalized report row" in error for error in errors),
            errors,
        )

    def test_global_archive_recomputes_failure_from_sealed_prior_manifest(
        self,
    ) -> None:
        archive_path, archived_issue, _ = self.make_archivable_global_origin_audit()
        baseline_errors: list[str] = []
        proofcheck.load_resolution_archive(
            archived_issue,
            self.audit,
            baseline_errors,
        )
        self.assertEqual([], baseline_errors)

        archive = read_json(archive_path)
        self.rebind_tampered_archived_failure(
            archive,
            json.dumps(
                {
                    "affected_units": ["lem:main"],
                    "aspect": "constants_and_rates",
                    "evidence": "A fabricated clean global-check result.",
                    "issue_ids": ["I-001"],
                    "status": "passed",
                },
                ensure_ascii=False,
            ),
        )
        write_json(archive_path, archive)
        resolved_issue = json.loads(json.dumps(archived_issue))
        resolved_issue["status"] = "resolved"
        resolved_issue["finding_status"] = "resolved"
        resolved_issue["historical_origin"]["sha256"] = (
            proofcheck.sha256_file(archive_path)
        )

        errors: list[str] = []
        proofcheck.load_resolution_archive(
            resolved_issue,
            self.audit,
            errors,
        )

        self.assertTrue(
            any("sealed canonical origin record" in error for error in errors),
            errors,
        )
        self.assertFalse(
            any("exact prior finalized report row" in error for error in errors),
            errors,
        )

    def test_archive_issue_retries_over_confined_temp_before_target_creation(
        self,
    ) -> None:
        self.make_archivable_s1_audit()
        archive_path = (
            self.audit
            / "audit"
            / "06_reports"
            / "history"
            / "I-001-origin.json"
        )
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        transaction_temp = proofcheck.proofcheck_temp_path(archive_path)
        transaction_lock = archive_path.with_name(
            f".{archive_path.name}.proofcheck.lock"
        )
        transaction_temp.write_text(
            "interrupted archive payload",
            encoding="utf-8",
            newline="\n",
        )

        freshness = proofcheck.check_finalization_freshness(self.audit)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = proofcheck.cmd_archive_issue(
                argparse.Namespace(root=self.audit, issue_id="I-001")
            )

        self.assertTrue(freshness["usable_finalization"], freshness)
        self.assertEqual(0, status)
        self.assertTrue(archive_path.is_file())
        self.assertFalse(transaction_temp.exists())
        self.assertFalse(transaction_lock.exists())
        self.assertNotIn(
            "recovered_existing_archive",
            json.loads(output.getvalue()),
        )

    def test_archive_issue_recovers_after_interrupted_issue_log_commit(
        self,
    ) -> None:
        self.make_archivable_s1_audit()
        issue_path = self.audit / "audit" / "06_reports" / "ISSUE_LOG.json"
        archive_path = (
            self.audit
            / "audit"
            / "06_reports"
            / "history"
            / "I-001-origin.json"
        )
        original_atomic_replace = proofcheck.atomic_replace_text

        def interrupt_issue_log_commit(path: Path, text: str) -> None:
            if path.resolve() == issue_path.resolve():
                raise OSError("simulated issue-log commit interruption")
            original_atomic_replace(path, text)

        with mock.patch.object(
            proofcheck,
            "atomic_replace_text",
            side_effect=interrupt_issue_log_commit,
        ):
            with self.assertRaisesRegex(
                OSError, "simulated issue-log commit interruption"
            ):
                proofcheck.cmd_archive_issue(
                    argparse.Namespace(root=self.audit, issue_id="I-001")
                )

        self.assertTrue(archive_path.is_file())
        transaction_lock = archive_path.with_name(
            f".{archive_path.name}.proofcheck.lock"
        )
        self.assertFalse(transaction_lock.exists())
        issue_before_recovery = next(
            row
            for row in read_json(issue_path)["issues"]
            if row["id"] == "I-001"
        )
        self.assertNotIn("historical_origin", issue_before_recovery)
        archive_sha256 = proofcheck.sha256_file(archive_path)
        archive = read_json(archive_path)
        expected_origin = proofcheck.historical_origin_from_archive(
            archive,
            archive_path,
            self.audit.resolve(),
        )
        transaction_temp = proofcheck.proofcheck_temp_path(archive_path)
        transaction_temp.write_text(
            "orphaned transaction payload",
            encoding="utf-8",
            newline="\n",
        )

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = proofcheck.cmd_archive_issue(
                argparse.Namespace(root=self.audit, issue_id="I-001")
            )
        payload = json.loads(output.getvalue())

        self.assertEqual(0, status)
        self.assertIs(True, payload["recovered_existing_archive"])
        self.assertEqual(archive_sha256, payload["archive_sha256"])
        self.assertEqual(archive_sha256, proofcheck.sha256_file(archive_path))
        self.assertFalse(transaction_temp.exists())
        self.assertFalse(transaction_lock.exists())
        recovered_issue = next(
            row
            for row in read_json(issue_path)["issues"]
            if row["id"] == "I-001"
        )
        self.assertEqual(expected_origin, recovered_issue["historical_origin"])

    def test_archive_issue_does_not_ignore_similar_temp_outside_history(
        self,
    ) -> None:
        self.make_archivable_s1_audit()
        outside_temp = (
            self.audit
            / "audit"
            / "06_reports"
            / ".I-001-origin.json.proofcheck.tmp"
        )
        outside_temp.write_text(
            "not a confined archive transaction",
            encoding="utf-8",
            newline="\n",
        )

        state_files = {
            row["file"]
            for row in proofcheck.audit_state_manifest(self.audit)
        }
        freshness = proofcheck.check_finalization_freshness(self.audit)

        self.assertIn(
            "audit/06_reports/.I-001-origin.json.proofcheck.tmp",
            state_files,
        )
        self.assertFalse(freshness["usable_finalization"], freshness)
        with self.assertRaisesRegex(
            ValueError,
            "requires a current passed finalization record",
        ):
            proofcheck.cmd_archive_issue(
                argparse.Namespace(root=self.audit, issue_id="I-001")
            )
        self.assertTrue(outside_temp.is_file())

    def test_archive_issue_rejects_invalid_orphan_archive(self) -> None:
        self.make_archivable_s1_audit()
        issue_path = self.audit / "audit" / "06_reports" / "ISSUE_LOG.json"
        archive_path = (
            self.audit
            / "audit"
            / "06_reports"
            / "history"
            / "I-001-origin.json"
        )
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(archive_path, {"archive_schema_version": 1})

        with self.assertRaisesRegex(
            ValueError, "Existing resolution archive cannot be adopted"
        ):
            proofcheck.cmd_archive_issue(
                argparse.Namespace(root=self.audit, issue_id="I-001")
            )

        issue = next(
            row
            for row in read_json(issue_path)["issues"]
            if row["id"] == "I-001"
        )
        self.assertNotIn("historical_origin", issue)
        self.assertEqual(
            {"archive_schema_version": 1}, read_json(archive_path)
        )

    def test_archive_issue_rejects_symlinked_history_ancestors(self) -> None:
        self.make_archivable_s1_audit()
        cases = (
            (self.audit / "audit", self.base / "redirected-audit"),
            (
                self.audit / "audit" / "06_reports",
                self.base / "redirected-reports",
            ),
        )
        for ancestor, redirected in cases:
            with self.subTest(ancestor=ancestor.relative_to(self.audit)):
                ancestor.rename(redirected)
                try:
                    ancestor.symlink_to(redirected, target_is_directory=True)
                except OSError:
                    redirected.rename(ancestor)
                    original_is_symlink = Path.is_symlink

                    def simulated_is_symlink(path: Path) -> bool:
                        return path == ancestor or original_is_symlink(path)

                    with mock.patch.object(
                        Path,
                        "is_symlink",
                        new=simulated_is_symlink,
                    ):
                        with self.assertRaisesRegex(
                            ValueError,
                            "Resolution history ancestor cannot be a symlink",
                        ):
                            proofcheck.cmd_archive_issue(
                                argparse.Namespace(
                                    root=self.audit,
                                    issue_id="I-001",
                                )
                            )
                    continue
                try:
                    with self.assertRaisesRegex(
                        ValueError,
                        "Resolution history ancestor cannot be a symlink",
                    ):
                        proofcheck.cmd_archive_issue(
                            argparse.Namespace(
                                root=self.audit,
                                issue_id="I-001",
                            )
                        )
                finally:
                    ancestor.unlink()
                    redirected.rename(ancestor)

    def test_removed_move_in_retained_affected_unit_finalizes(self) -> None:
        main_path, _, issue = self.make_resolved_s1_lifecycle_audit()
        self.convert_resolved_lifecycle_to_removed_move(
            main_path,
            issue,
        )

        errors, _ = proofcheck.check_audit_finalization(self.audit)

        self.assertEqual([], errors)

    def test_removed_issue_packet_rejects_mutated_current_origin(self) -> None:
        main_path, _, issue = self.make_resolved_s1_lifecycle_audit()
        self.convert_resolved_lifecycle_to_removed_move(main_path, issue)
        issue_path = self.audit / "audit" / "06_reports" / "ISSUE_LOG.json"
        issue_log = read_json(issue_path)
        issue_log["issues"][0]["origin_ref"]["move_id"] = "M999"
        write_json(issue_path, issue_log)

        with self.assertRaisesRegex(
            ValueError, "removed issue archive is invalid"
        ):
            proofcheck.build_context_packet(
                self.audit, "lem:main", "challenge"
            )

    def test_removed_disposition_rejects_whole_affected_unit_deletion(
        self,
    ) -> None:
        main_path, _, issue = self.make_resolved_s1_lifecycle_audit()
        self.convert_resolved_lifecycle_to_removed_move(
            main_path,
            issue,
        )
        main_path.unlink()

        errors, _ = proofcheck.check_audit_finalization(self.audit)

        self.assertTrue(
            any(
                "removed may retire only the failed origin inside a retained "
                "affected result" in error
                for error in errors
            ),
            errors,
        )

    def reseal_modified_resolution_archive(
        self,
        archive_path: Path,
        issue: dict,
        archive: dict,
    ) -> None:
        archive["archive_payload_sha256"] = (
            proofcheck.resolution_archive_payload_sha256(archive)
        )
        write_json(archive_path, archive)
        issue["historical_origin"]["sha256"] = proofcheck.sha256_file(
            archive_path
        )
        self.install_canonical_issue(
            issue,
            migrate=False,
            reconcile_report_views=False,
        )

    def test_resolved_s1_rejects_tampered_historical_archive(self) -> None:
        _, archive_path, _ = self.make_resolved_s1_lifecycle_audit()
        archive = read_json(archive_path)
        archive["projection"]["severity"][0][0] = "S0"
        write_json(archive_path, archive)

        errors, _ = proofcheck.check_audit_finalization(self.audit)

        self.assertTrue(
            any(
                "historical_origin.sha256" in error
                or "archive payload hash" in error
                or "projection hash" in error
                for error in errors
            ),
            errors,
        )

    def test_resolved_s1_rejects_false_archived_dependency_edge_hash(
        self,
    ) -> None:
        _, archive_path, issue = self.make_resolved_s1_lifecycle_audit()
        archive = read_json(archive_path)
        dependency_uses = archive["required_closure"]["dependency_uses"]
        self.assertTrue(dependency_uses)
        dependency_uses[0]["edge_sha256"] = "0" * 64
        archive["archive_payload_sha256"] = (
            proofcheck.resolution_archive_payload_sha256(archive)
        )
        write_json(archive_path, archive)
        issue["historical_origin"]["sha256"] = proofcheck.sha256_file(
            archive_path
        )
        errors: list[str] = []

        proofcheck.load_resolution_archive(issue, self.audit, errors)

        self.assertTrue(
            any(
                "does not match the sealed normalized closure edge" in error
                for error in errors
            ),
            errors,
        )

    def test_resolved_s1_rejects_archive_issue_not_in_prior_issue_log(
        self,
    ) -> None:
        _, archive_path, issue = self.make_resolved_s1_lifecycle_audit()
        archive = read_json(archive_path)
        archive["issue_record"]["suggested_changes"][0]["proposal"] += (
            " This text was injected only into the archive."
        )
        archive["issue_record_sha256"] = proofcheck.canonical_sha256(
            archive["issue_record"]
        )
        self.reseal_modified_resolution_archive(
            archive_path,
            issue,
            archive,
        )

        errors, _ = proofcheck.check_audit_finalization(self.audit)

        self.assertTrue(
            any(
                "archived issue is not the exact prior issue-log member"
                in error
                for error in errors
            ),
            errors,
        )

    def test_archived_dependency_origin_ignores_non_substantive_step(
        self,
    ) -> None:
        ledger = {
            "source": {"file": "paper.tex"},
            "source_lines": [
                {"line": 1, "text": "Scratch reference."},
                {"line": 2, "text": "The substantive dependency use."},
            ],
            "source_units": [
                {"id": "U001", "lines": [1, 1]},
                {"id": "U002", "lines": [2, 2]},
            ],
            "steps": [
                {
                    "id": "S001",
                    "source_unit_id": "U001",
                    "status": "non_substantive",
                    "dependencies": [{"use_id": "D001"}],
                },
                {
                    "id": "S002",
                    "source_unit_id": "U002",
                    "status": "gap",
                    "dependencies": [{"use_id": "D001"}],
                },
            ],
            "review": {
                "direct_dependencies": [
                    {
                        "id": "lem:source",
                        "use_id": "D001",
                        "conclusion_id": "C001",
                        "status": "gap",
                        "needed_form": "The needed conclusion.",
                        "compatibility_check": "The forms match.",
                    }
                ]
            },
        }
        issue = {
            "affected_result": "thm:main",
            "invalidation_kind": "dependency_gap",
            "origin_ref": {
                "kind": "dependency_use",
                "unit_id": "thm:main",
                "use_id": "D001",
            },
        }
        rows = proofcheck.archived_structured_failure_rows(
            issue,
            {"thm:main": ledger},
            {},
            {
                "D001": {
                    "source_status": "gap",
                    "applicability_status": "passed",
                    "effective_status": "gap",
                    "issue_ids": ["I-001"],
                    "compatibility_checks": [],
                    "prerequisite_map": [],
                    "source_evidence": [],
                }
            },
            {},
            self.audit,
        )

        self.assertIsNotNone(rows)
        self.assertEqual("paper.tex:2-2", rows[0][0])
        self.assertEqual(
            json.dumps("The substantive dependency use."),
            rows[0][2],
        )

    def test_resolved_s1_rejects_tampered_sealed_ledger_bytes(
        self,
    ) -> None:
        _, archive_path, issue = self.make_resolved_s1_lifecycle_audit()
        archive = read_json(archive_path)
        ledger_record = archive["prior_artifacts"]["ledgers"][0]
        ledger = json.loads(
            base64.b64decode(ledger_record["content_base64"]).decode("utf-8")
        )
        step = next(row for row in ledger["steps"] if row["id"] == "S003")
        move = next(
            row
            for row in step["inference"]["moves"]
            if row["id"] == "M001"
        )
        move["rule"] += (
            " Tampered after prior finalization."
        )
        ledger_text = (
            json.dumps(ledger, ensure_ascii=False, indent=2) + "\n"
        )
        ledger_record["content_base64"] = base64.b64encode(
            ledger_text.encode("utf-8")
        ).decode("ascii")
        ledger_record["sha256"] = proofcheck.sha256_text(ledger_text)
        archive["ledger_sha256s"]["lem:main"] = ledger_record["sha256"]
        self.reseal_modified_resolution_archive(
            archive_path,
            issue,
            archive,
        )

        errors, _ = proofcheck.check_audit_finalization(self.audit)

        self.assertTrue(
            any(
                "prior_artifacts.ledgers[1] bytes are not bound by the "
                "prior finalization manifest" in error
                for error in errors
            ),
            errors,
        )

    def test_resolved_s1_rejects_failure_projection_not_matching_sealed_ledger(
        self,
    ) -> None:
        _, archive_path, issue = self.make_resolved_s1_lifecycle_audit()
        archive = read_json(archive_path)
        archive["projection"]["failure"][0][5] = (
            "A different archived claim."
        )
        archive["projection_sha256"] = proofcheck.canonical_sha256(
            archive["projection"]
        )
        self.reseal_modified_resolution_archive(
            archive_path,
            issue,
            archive,
        )

        errors, _ = proofcheck.check_audit_finalization(self.audit)

        self.assertTrue(
            any(
                "archived failure projection does not match the sealed "
                "ledger move" in error
                for error in errors
            ),
            errors,
        )

    def test_resolved_s1_rejects_malformed_sealed_ledger_collection(
        self,
    ) -> None:
        _, archive_path, issue = self.make_resolved_s1_lifecycle_audit()
        archive = read_json(archive_path)
        archive["prior_artifacts"]["ledgers"] = {
            "lem:main": archive["prior_artifacts"]["ledgers"][0]
        }
        self.reseal_modified_resolution_archive(
            archive_path,
            issue,
            archive,
        )

        errors, _ = proofcheck.check_audit_finalization(self.audit)

        self.assertTrue(
            any(
                "prior_artifacts.ledgers must be a list" in error
                for error in errors
            ),
            errors,
        )

    def test_resolved_s1_rejects_malformed_historical_archive_closure(
        self,
    ) -> None:
        _, archive_path, issue = self.make_resolved_s1_lifecycle_audit()
        archive = read_json(archive_path)
        archive["required_closure"]["dependency_uses"] = ["D001"]
        archive["archive_payload_sha256"] = (
            proofcheck.resolution_archive_payload_sha256(archive)
        )
        write_json(archive_path, archive)
        issue["historical_origin"]["sha256"] = proofcheck.sha256_file(
            archive_path
        )
        self.install_canonical_issue(
            issue,
            migrate=False,
            reconcile_report_views=False,
        )

        errors, _ = proofcheck.check_audit_finalization(self.audit)

        self.assertTrue(
            any(
                "archive required_closure.dependency_uses[1] must be an object"
                in error
                for error in errors
            ),
            errors,
        )

    def test_resolved_s1_rejects_missing_current_reference(self) -> None:
        _, _, issue = self.make_resolved_s1_lifecycle_audit()
        issue["current_resolution"]["current_ref"] = {
            "kind": "ledger_move",
            "unit_id": "lem:main",
            "step_id": "S003",
            "move_id": "M999",
        }
        self.install_canonical_issue(
            issue,
            migrate=False,
            reconcile_report_views=False,
        )

        errors, _ = proofcheck.check_audit_finalization(self.audit)

        self.assertTrue(
            any(
                "current_resolution.current_ref does not resolve" in error
                for error in errors
            ),
            errors,
        )

    def test_resolved_s1_rejects_unrelated_replacement_reference(
        self,
    ) -> None:
        _, _, issue = self.make_resolved_s1_lifecycle_audit()
        issue["current_resolution"].update(
            {
                "disposition": "replaced",
                "current_ref": {
                    "kind": "ledger_move",
                    "unit_id": "lem:prior",
                    "step_id": "S001",
                    "move_id": "M001",
                },
                "mapping": (
                    "The archived move is claimed to map to a clean but "
                    "unrelated move in lem:prior."
                ),
            }
        )
        self.install_canonical_issue(
            issue,
            migrate=False,
            reconcile_report_views=False,
        )

        errors, _ = proofcheck.check_audit_finalization(self.audit)

        self.assertTrue(
            any(
                "current_resolution.current_ref" in error
                and (
                    "affected" in error.lower()
                    or "unrelated" in error.lower()
                )
                for error in errors
            ),
            errors,
        )

    def test_resolved_s1_rejects_unrecorded_dependency_retirement(
        self,
    ) -> None:
        main_path, _, issue = self.make_resolved_s1_lifecycle_audit()
        ledger = read_json(main_path)
        step = next(row for row in ledger["steps"] if row["id"] == "S003")
        step["dependencies"] = []
        step["premise_uses"] = [
            premise
            for premise in step["premise_uses"]
            if premise.get("origin", {}).get("reference") != "D001"
        ]
        step["inference"]["moves"][0]["premise_ids"] = [
            premise_id
            for premise_id in step["inference"]["moves"][0]["premise_ids"]
            if premise_id != "P002"
        ]
        ledger["review"]["direct_dependencies"] = []
        ledger["review"]["conclusion_results"][0]["dependency_use_ids"] = []
        write_json(main_path, ledger)

        registry_path = (
            self.audit
            / "audit"
            / "03_dependencies"
            / "DEPENDENCY_REGISTRY.json"
        )
        registry = read_json(registry_path)
        registry["internal_uses"] = []
        write_json(registry_path, registry)

        report_path = self.audit / "audit" / "06_reports" / "FINAL_REPORT.md"
        report = report_path.read_text(encoding="utf-8")
        report = report.replace(
            "| lem:main | C001 | verified | valid | established | verified | "
            "not_applicable | S003/M001 | D001 | none |",
            "| lem:main | C001 | verified | valid | established | verified | "
            "not_applicable | S003/M001 | none | none |",
        )
        report = report.replace(
            "| lem:main | D001 | lem:prior | C001 | internal_result | "
            "verified | passed | verified | none |",
            "None.",
        )
        report_path.write_text(report, encoding="utf-8", newline="\n")
        self.seal_schema5_challenge(
            main_path,
            read_json(main_path),
            covered_issue_ids=["I-001"],
        )

        issue["rechecked_dependency_uses"] = []
        issue["current_resolution"]["retired_dependency_uses"] = []
        self.install_canonical_issue(
            issue,
            migrate=False,
            reconcile_report_views=False,
        )

        errors, _ = proofcheck.check_audit_finalization(self.audit)

        self.assertTrue(
            any(
                "retired_dependency_uses must equal" in error
                for error in errors
            ),
            errors,
        )

    def test_resolved_s1_rejects_stale_post_repair_challenge(self) -> None:
        main_path, _, _ = self.make_resolved_s1_lifecycle_audit()
        ledger = read_json(main_path)
        ledger["independent_check"]["challenged_ledger_sha256"] = "0" * 64
        write_json(main_path, ledger)

        errors, _ = proofcheck.check_audit_finalization(self.audit)

        self.assertTrue(
            any(
                "challenged_ledger_sha256" in error
                and "stale" in error.lower()
                for error in errors
            ),
            errors,
        )

    def test_open_or_deferred_s0_s1_units_require_exact_issue_assessment(
        self,
    ) -> None:
        main_path, _ = self.prepare_two_unit_challenge_audit()
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        report_path = self.audit / "audit" / "06_reports" / "FINAL_REPORT.md"
        summary_path = self.audit / "audit" / "06_reports" / "ISSUE_SUMMARY.md"
        issue_path = self.audit / "audit" / "06_reports" / "ISSUE_LOG.json"
        baseline = {
            "main": read_json(main_path),
            "manifest": read_json(manifest_path),
            "report": report_path.read_text(encoding="utf-8"),
            "summary": summary_path.read_text(encoding="utf-8"),
            "issues": read_json(issue_path),
        }
        cases = (
            ("open_s0", "S0", "open"),
            ("deferred_s1", "S1", "deferred"),
        )
        for name, severity, status in cases:
            with self.subTest(case=name):
                write_json(main_path, baseline["main"])
                write_json(manifest_path, baseline["manifest"])
                report_path.write_text(
                    baseline["report"], encoding="utf-8", newline="\n"
                )
                summary_path.write_text(
                    baseline["summary"], encoding="utf-8", newline="\n"
                )
                write_json(issue_path, baseline["issues"])
                self.set_expected_assessment("inconclusive")
                issue = self.make_schema5_issue(
                    severity=severity, status=status
                )
                self.install_schema5_issue(main_path, issue)
                manifest = read_json(manifest_path)
                required, triggers = proofcheck.required_challenge_requirements(
                    manifest, [issue]
                )
                self.assertIn("lem:main", required)
                self.assertEqual({"I-001"}, triggers["lem:main"])

                errors, _ = proofcheck.check_audit_finalization(self.audit)

                self.assertTrue(
                    any(
                        "In-scope unit lem:main requires an independent"
                        in error
                        for error in errors
                    ),
                    errors,
                )

    def test_s2_does_not_add_a_severe_issue_trigger(
        self,
    ) -> None:
        main_path, _ = self.prepare_two_unit_challenge_audit()
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        report_path = self.audit / "audit" / "06_reports" / "FINAL_REPORT.md"
        summary_path = self.audit / "audit" / "06_reports" / "ISSUE_SUMMARY.md"
        issue_path = self.audit / "audit" / "06_reports" / "ISSUE_LOG.json"
        baseline = {
            "main": read_json(main_path),
            "manifest": read_json(manifest_path),
            "report": report_path.read_text(encoding="utf-8"),
            "summary": summary_path.read_text(encoding="utf-8"),
            "issues": read_json(issue_path),
        }
        cases = (("open_s2", "S2", "open", "inconclusive"),)
        for name, severity, status, assessment in cases:
            with self.subTest(case=name):
                write_json(main_path, baseline["main"])
                write_json(manifest_path, baseline["manifest"])
                report_path.write_text(
                    baseline["report"], encoding="utf-8", newline="\n"
                )
                summary_path.write_text(
                    baseline["summary"], encoding="utf-8", newline="\n"
                )
                write_json(issue_path, baseline["issues"])
                if assessment != "no_defect_found":
                    self.set_expected_assessment(assessment)
                issue = self.make_schema5_issue(
                    severity=severity, status=status
                )
                self.install_schema5_issue(main_path, issue)
                manifest = read_json(manifest_path)
                required, triggers = proofcheck.required_challenge_requirements(
                    manifest, [issue]
                )
                self.assertIn("lem:main", required)
                self.assertNotIn("lem:main", triggers)
                ledger = read_json(main_path)
                ledger["independent_check"].update(
                    {
                        "independence_level": "fresh_context_same_model",
                        "challenger_verdict": ledger["review"]["unit_status"],
                        "artifact": "audit/05_adversarial/lem-main-s2.md",
                        "disagreements": [],
                        "resolution": "",
                    }
                )
                write_json(main_path, ledger)
                artifact = self.audit / ledger["independent_check"]["artifact"]
                artifact.write_text(
                    "# Independent check\n\nThe unit was checked from the blinded packet.\n",
                    encoding="utf-8",
                    newline="\n",
                )
                with contextlib.redirect_stdout(io.StringIO()):
                    proofcheck.cmd_bind_challenge(
                        argparse.Namespace(root=self.audit, unit_id="lem:main")
                    )

                errors, _ = proofcheck.check_audit_finalization(self.audit)
                main_challenge_errors = [
                    error
                    for error in errors
                    if "lem:main" in error and "challenge" in error.lower()
                ]

                self.assertEqual([], main_challenge_errors, errors)

    def test_resolved_s1_retains_issue_triggered_challenge_closure(
        self,
    ) -> None:
        main_path, _ = self.prepare_two_unit_challenge_audit()
        issue = self.make_schema5_issue(
            severity="S1",
            status="resolved",
        )
        self.install_schema5_issue(
            main_path,
            issue,
            reconcile_report_views=False,
        )
        manifest = read_json(self.audit / "AUDIT_MANIFEST.json")

        self.assertNotIn(
            "lem:main",
            manifest["audit_scope"]["critical_units"],
        )
        required_challenges, severe_by_unit = (
            proofcheck.required_challenge_requirements(
                manifest,
                [issue],
            )
        )
        self.assertIn("lem:main", required_challenges)
        self.assertEqual({"I-001"}, severe_by_unit["lem:main"])

        _, summaries, _ = proofcheck.audit_ledgers(self.audit, True)
        summaries_by_id = {
            summary["unit_id"]: summary
            for summary in summaries
        }
        projection = proofcheck.canonical_issue_detail_projection(
            issue,
            summaries_by_id,
            [],
            required_challenges,
            [],
            manifest["audit_scope"]["overall_assessment"],
            evidence_base=self.audit,
        )
        closure = projection["closure"][0]
        self.assertEqual("lem:main", closure[4])
        self.assertEqual("none", closure[5])
        self.assertEqual("open", closure[8])

        errors, _ = proofcheck.check_audit_finalization(self.audit)
        self.assertTrue(
            any(
                "lem:main" in error
                and "independent" in error.lower()
                and "challenge" in error.lower()
                for error in errors
            ),
            errors,
        )

    def test_in_scope_challenge_must_be_fresh_and_issue_aware(
        self,
    ) -> None:
        main_path, _ = self.prepare_two_unit_challenge_audit()
        self.set_expected_assessment("inconclusive")
        issue = self.make_schema5_issue(severity="S1", status="open")
        self.install_schema5_issue(main_path, issue)
        ledger = read_json(main_path)
        artifact = self.audit / "audit" / "05_adversarial" / "main-issue.md"
        artifact.write_text(
            "# Challenge\n\nThis stale challenge does not inspect I-001.\n",
            encoding="utf-8",
            newline="\n",
        )
        ledger["independent_check"] = {
            "required": True,
            "status": "agreed",
            "independence_level": "fresh_context_same_model",
            "challenger_verdict": "conditionally_verified",
            "reconciled_verdict": "conditionally_verified",
            "artifact": "audit/05_adversarial/main-issue.md",
            "disagreements": [],
            "resolution": "",
            "covered_issue_ids": [],
            "source_snapshot_sha256": "",
            "challenged_ledger_sha256": "",
            "challenge_context_sha256": "",
            "challenge_artifact_sha256": "",
            "issue_assessments": [],
            "generated_utc": "",
        }
        write_json(main_path, ledger)

        errors, _ = proofcheck.check_audit_finalization(self.audit)

        for field in (
            "covered_issue_ids",
            "source_snapshot_sha256",
            "challenged_ledger_sha256",
            "challenge_context_sha256",
            "challenge_artifact_sha256",
            "issue_assessments",
            "generated_utc",
        ):
            self.assertTrue(
                any(
                    (
                        "lem:main" in error
                        or "lem-main" in error
                    )
                    and field in error
                    for error in errors
                ),
                (field, errors),
            )

    def test_schema5_issue_rejects_legacy_free_text_evidence_fields(self) -> None:
        main_path, _ = self.prepare_two_unit_challenge_audit()
        self.set_expected_assessment("inconclusive")
        issue = self.make_schema5_issue(severity="S2", status="open")
        issue.update(
            {
                "location": "paper.tex:6",
                "evidence": ["Legacy free-text evidence."],
                "downstream_consequences": ["Legacy authored propagation."],
                "possible_repair": "Legacy unstructured repair.",
            }
        )
        self.install_schema5_issue(
            main_path,
            issue,
            reconcile_report_views=False,
        )

        errors, _ = proofcheck.check_audit_finalization(self.audit)

        retired_errors = [
            error
            for error in errors
            if "I-001" in error
            and (
                "retired" in error.lower()
                or "inspection-only" in error.lower()
            )
        ]
        self.assertEqual(1, len(retired_errors), errors)
        for field in (
            "location",
            "evidence",
            "downstream_consequences",
            "possible_repair",
        ):
            self.assertIn(field, retired_errors[0])

    def test_global_issue_origin_requires_locked_backlinked_evidence(
        self,
    ) -> None:
        self.make_complete_audit()
        issue = self.make_global_issue(
            finding_status="defect",
            load_bearing=False,
            severity="S3",
            summary="The global source-resolution check found a presentation defect.",
        )
        issue["origin_ref"] = {
            "kind": "global_check",
            "aspect": "source_resolution",
            "evidence_spans": [
                proofcheck.locked_span(
                    self.paper,
                    2,
                    4,
                    self.audit,
                    role="global_consistency_evidence",
                )
            ],
        }
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        global_pass = manifest["completion"]["global_consistency_pass"]
        source_resolution = next(
            row
            for row in global_pass["checks"]
            if row["aspect"] == "source_resolution"
        )
        source_resolution.update(
            {
                "status": "defect",
                "evidence": (
                    "The locked theorem span exhibits the recorded presentation "
                    "defect."
                ),
                "affected_units": ["lem:main"],
                "issue_ids": ["I-001"],
            }
        )
        global_pass["status"] = "completed_with_findings"
        write_json(manifest_path, manifest)
        self.set_expected_assessment("defects_found")
        self.install_canonical_issue(issue, migrate=False)

        errors, _ = proofcheck.check_audit_finalization(self.audit)
        self.assertEqual([], errors)
        detail_section = proofcheck.report_section(
            (
                self.audit
                / "audit"
                / "06_reports"
                / "FINAL_REPORT.md"
            ).read_text(encoding="utf-8"),
            "## Findings and repairs",
        )
        failure_row = proofcheck.markdown_tables(
            detail_section or ""
        )[0][2]
        self.assertNotEqual("none", failure_row[1])
        self.assertNotEqual("none", failure_row[2])

        issue_without_evidence = json.loads(json.dumps(issue))
        issue_without_evidence["origin_ref"].pop("evidence_spans")
        self.install_canonical_issue(
            issue_without_evidence,
            migrate=False,
            reconcile_report_views=False,
        )
        errors, _ = proofcheck.check_audit_finalization(self.audit)

        self.assertTrue(
            any(
                "I-001.origin_ref.evidence_spans" in error
                and "nonempty" in error.lower()
                for error in errors
            ),
            errors,
        )

    def test_resolved_global_check_can_map_to_clean_current_record(self) -> None:
        ledger_path = self.make_complete_audit()
        aspect = "source_resolution"
        historical_span = proofcheck.locked_span(
            self.paper,
            2,
            4,
            self.audit,
            role="global_consistency_evidence",
        )
        issue = self.make_global_issue(
            finding_status="defect",
            load_bearing=False,
            severity="S2",
            summary="The global source-resolution check found a repairable defect.",
        )
        issue["origin_ref"] = {
            "kind": "global_check",
            "aspect": aspect,
            "evidence_spans": [historical_span],
        }
        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        global_pass = manifest["completion"]["global_consistency_pass"]
        global_check = next(
            row for row in global_pass["checks"] if row["aspect"] == aspect
        )
        global_check.update(
            {
                "status": "defect",
                "evidence": (
                    "The historical global check records the source-resolution "
                    "defect before repair."
                ),
                "affected_units": ["lem:main"],
                "issue_ids": ["I-001"],
            }
        )
        global_pass["status"] = "completed_with_findings"
        write_json(manifest_path, manifest)
        self.set_expected_assessment("defects_found")
        self.install_canonical_issue(issue, migrate=False)

        historical_errors, _ = proofcheck.check_audit_finalization(
            self.audit
        )
        self.assertEqual([], historical_errors)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(
                0,
                proofcheck.cmd_finalize(argparse.Namespace(root=self.audit)),
            )
            self.assertEqual(
                0,
                proofcheck.cmd_archive_issue(
                    argparse.Namespace(root=self.audit, issue_id="I-001")
                ),
            )

        issue_path = self.audit / "audit" / "06_reports" / "ISSUE_LOG.json"
        archived_issue = next(
            row
            for row in read_json(issue_path)["issues"]
            if row["id"] == "I-001"
        )
        historical_origin = archived_issue["historical_origin"]

        manifest = read_json(manifest_path)
        global_pass = manifest["completion"]["global_consistency_pass"]
        global_check = next(
            row for row in global_pass["checks"] if row["aspect"] == aspect
        )
        global_check.update(
            {
                "status": "passed",
                "evidence": (
                    "The repaired canonical source-resolution check is clean "
                    "under the current locked evidence."
                ),
                "affected_units": [],
                "issue_ids": [],
            }
        )
        global_pass["status"] = "completed"
        write_json(manifest_path, manifest)
        self.set_expected_assessment("no_defect_found")
        report_path = self.audit / "audit" / "06_reports" / "FINAL_REPORT.md"
        report_path.write_text(
            report_path.read_text(encoding="utf-8").replace(
                "- Highest-consequence issue: I-001",
                "- Highest-consequence issue: none",
                1,
            ),
            encoding="utf-8",
            newline="\n",
        )
        self.seal_schema5_challenge(
            ledger_path,
            read_json(ledger_path),
            covered_issue_ids=[],
            artifact_text=(
                "# Post-repair global challenge\n\n"
                "The fresh check confirms the repaired global source-resolution "
                "record is clean and lem:main remains verified.\n"
            ),
        )

        current_span = proofcheck.locked_span(
            self.paper,
            2,
            4,
            self.audit,
            role="repair_verification",
        )
        resolved_issue = json.loads(json.dumps(issue))
        resolved_issue.update(
            {
                "status": "resolved",
                "finding_status": "resolved",
                "resolution": (
                    "The canonical global check was repaired and rerun cleanly."
                ),
                "source_revision": (
                    "The current global consistency record contains the clean "
                    "post-repair result."
                ),
                "recheck_evidence": [
                    "The current locked evidence and fresh challenge verify the repair."
                ],
                "source_snapshot_sha256": read_json(manifest_path)[
                    "source_snapshot"
                ]["sha256"],
                "rechecked_units": ["lem:main"],
                "rechecked_dependency_uses": [],
                "reconciled_deliverables": [],
                "historical_origin": historical_origin,
                "current_resolution": {
                    "disposition": "repaired",
                    "current_ref": {
                        "kind": "global_check",
                        "aspect": aspect,
                        "evidence_spans": [current_span],
                    },
                    "mapping": (
                        "The archived source_resolution finding maps to the "
                        "same canonical aspect after its clean rerun."
                    ),
                    "verification_status": "verified_sufficient",
                    "evidence_spans": [current_span],
                    "required_rechecks": ["lem:main"],
                    "retired_dependency_uses": [],
                },
            }
        )
        self.install_canonical_issue(resolved_issue, migrate=False)

        errors, _ = proofcheck.check_audit_finalization(self.audit)

        self.assertEqual([], errors)

    def test_overlapping_reviewed_proof_locations_fail(self) -> None:
        self.make_complete_audit()
        inventory_path = (
            self.audit / "audit" / "01_index" / "theorem_inventory.json"
        )
        inventory = read_json(inventory_path)
        manual = json.loads(json.dumps(inventory["units"][0]))
        manual["id"] = "lem:overlap"
        manual["label"] = "lem:overlap"
        manual["proof_association"] = {
            "status": "associated",
            "method": "reviewed_manual",
            "target": "lem:overlap",
            "evidence_occurrence_ids": [],
        }
        inventory["units"].append(manual)
        write_json(inventory_path, inventory)

        manifest_path = self.audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        manifest["audit_scope"]["excluded_units"] = [
            {
                "id": "lem:overlap",
                "reason": "Synthetic excluded unit used to test overlap detection.",
            }
        ]
        manifest["audit_scope"]["inventory_overrides"] = [
            {
                "unit_id": "lem:overlap",
                "kind": "manual_unit",
                "reason": "The synthetic unit is added for overlap validation.",
                "evidence": "Its reviewed proof span exactly duplicates lem:main.",
                "reviewed_unit_sha256": proofcheck.canonical_sha256(manual),
            }
        ]
        write_json(manifest_path, manifest)
        report_path = self.audit / "audit" / "06_reports" / "FINAL_REPORT.md"
        report = report_path.read_text(encoding="utf-8").replace(
            "- Results not checked: none",
            "- Results not checked: lem:overlap",
        )
        report_path.write_text(report, encoding="utf-8", newline="\n")
        self.refresh_dependency_review()

        errors, _ = proofcheck.check_audit_finalization(self.audit)
        self.assertTrue(
            any("Reviewed proof spans overlap" in error for error in errors),
            errors,
        )

    def test_public_example_refutation_contract_is_self_consistent(
        self,
    ) -> None:
        example = read_json(
            SCRIPT.parents[1]
            / "assets"
            / "templates"
            / "AUDIT_RECORD_EXAMPLES.json"
        )
        ledger = example["ledger_example"]
        result = ledger["review"]["conclusion_results"][0]
        support = result["support"]
        step = next(
            row for row in ledger["steps"] if row["id"] == support["step_id"]
        )
        move = next(
            row
            for row in step["inference"]["moves"]
            if row["id"] == support["move_id"]
        )
        conclusion = ledger["obligation"]["conclusions"][0]
        issue = example["issue_log_example"]["issues"][0]
        generated = example["generated_issue_report_example"]

        self.assertEqual("refuted", result["statement_status"])
        self.assertEqual("counterexample", move["failure"]["kind"])
        self.assertEqual(conclusion["claim"], move["failure"]["target"])
        self.assertEqual(
            "statement_refuted", issue["invalidation_kind"]
        )
        self.assertEqual(
            "counterexample", generated["failed_move"]["failure_kind"]
        )
        self.assertEqual(
            conclusion["claim"], generated["failed_move"]["target"]
        )
        self.assertEqual(
            "statement_refuted",
            generated["current_invalidation_effect"]["invalidation_kind"],
        )

        source_lines = ledger["source_lines"]
        self.assertEqual([120, 121, 122], [row["line"] for row in source_lines])
        for row in source_lines:
            self.assertEqual(
                proofcheck.sha256_text(row["text"]),
                row["sha256"],
            )
        source_line_by_number = {
            row["line"]: row["text"] for row in source_lines
        }
        flattened_unit_lines: list[int] = []
        for unit in ledger["source_units"]:
            start_line, end_line = unit["lines"]
            covered_lines = list(range(start_line, end_line + 1))
            flattened_unit_lines.extend(covered_lines)
            self.assertEqual(
                proofcheck.sha256_text(
                    "\n".join(
                        source_line_by_number[line] for line in covered_lines
                    )
                ),
                unit["source_sha256"],
            )
        self.assertEqual([120, 121, 122], flattened_unit_lines)
        self.assertEqual(
            {unit["id"] for unit in ledger["source_units"]},
            {step["source_unit_id"] for step in ledger["steps"]},
        )

        dependency = next(
            row
            for row in example["dependency_registry_example"]["internal_uses"]
            if row["use_id"] == "D001"
        )
        downstream_site = dependency["use_site"]
        self.assertEqual(210, downstream_site["start_line"])
        self.assertEqual(210, downstream_site["end_line"])
        self.assertEqual(
            proofcheck.sha256_text(downstream_site["quote"]),
            downstream_site["sha256"],
        )
        self.assertEqual(["paper.tex:210"], ledger["review"]["use_sites"])
        downstream_propagation = next(
            row
            for row in generated["propagation"]
            if row.get("use_id") == "D001"
        )
        self.assertEqual(
            downstream_site,
            downstream_propagation["use_site"],
        )

        failure_quote = "\n".join(
            row["text"] for row in source_lines if row["line"] in {120, 121}
        )
        self.assertEqual(failure_quote, generated["failure_site"]["quote"])
        self.assertEqual(
            proofcheck.sha256_text(failure_quote),
            generated["failure_site"]["sha256"],
        )
        origin_propagation = next(
            row for row in generated["propagation"] if row["relation"] == "origin"
        )
        self.assertEqual(
            generated["failure_site"],
            origin_propagation["use_site"],
        )
        premise_claims = [
            premise["claim"] for premise in step["premise_uses"]
        ]
        self.assertEqual(premise_claims, generated["failed_move"]["premises"])
        self.assertEqual(
            move["failure"]["evidence"],
            generated["failed_move"]["failure_evidence"],
        )
        self.assertEqual(
            {
                proofcheck.canonical_sha256(contract_ref)
                for contract_ref in issue["contract_refs"]
            },
            {
                proofcheck.canonical_sha256(row["contract_ref"])
                for row in generated["normalized_contract"]
            },
        )
        self.assertEqual(
            proofcheck.METHOD_INTERFACE_SCHEMA_VERSION,
            example["method_interface_schema_version"],
        )
        self.assertEqual(1, example["method_interface_schema_version"])

        self.assertEqual(
            "D001 is incorrect. The recorded proof of thm:main therefore "
            "does not establish its conclusion, but this finding does not "
            "by itself refute that downstream conclusion.",
            downstream_propagation["effect"],
        )
        self.assertNotIn("refuted", downstream_propagation["effect"].lower())
        promoted_challenge = example["promoted_challenge_example"]
        self.assertEqual("", promoted_challenge["resolution"])
        downstream_assessment = promoted_challenge[
            "issue_assessments"
        ][0]["downstream_assessment"]
        self.assertIn(
            "the recorded downstream proof remains invalid",
            downstream_assessment,
        )
        self.assertIn(
            "does not by itself refute the downstream conclusion",
            downstream_assessment,
        )

    def test_public_templates_expose_exact_reporting_contracts(self) -> None:
        template_root = SCRIPT.parents[1] / "assets" / "templates"
        report = (template_root / "FINAL_REPORT.md").read_text(encoding="utf-8")
        challenge_template = (
            template_root / "CHALLENGE_ARTIFACT.md"
        ).read_text(encoding="utf-8")
        self.assertIn(
            proofcheck.CHALLENGE_ARTIFACT_SCAFFOLD_MARKER,
            challenge_template,
        )
        self.assertEqual(
            list(proofcheck.REPORT_REQUIRED_SECTIONS),
            re.findall(r"^## (.+)$", report, re.MULTILINE),
        )
        result_rows = proofcheck.markdown_table_rows(
            proofcheck.report_section(report, "## Results and impact") or ""
        )
        self.assertEqual(
            [
                "Result",
                "Conclusion",
                "Contract",
                "Argument",
                "Statement",
                "Dependencies",
                "Later use",
                "Evidence",
                "Issues",
            ],
            result_rows[0],
        )
        scope = proofcheck.report_section(report, "## Scope and assurance") or ""
        challenge_rows = proofcheck.markdown_table_rows(
            proofcheck.report_nested_section(
                scope,
                "### Independent verification",
            )
            or ""
        )
        self.assertEqual(
            [
                "Result",
                "Check status",
                "Independence",
                "Challenger verdict",
                "Final verdict",
                "Reconciliation",
            ],
            challenge_rows[0],
        )
        self.assertEqual(
            "None.",
            (
                proofcheck.report_nested_section(
                    scope,
                    "### Declared external deliverables",
                )
                or ""
            ).strip(),
        )
        self.assertEqual(
            1,
            len(
                re.findall(
                    r"^- Method-interface schema version: 1$",
                    report,
                    re.MULTILINE,
                )
            ),
        )
        self.assertEqual(
            1,
            len(
                re.findall(
                    r"^- Declared external deliverables:\s*$",
                    report,
                    re.MULTILINE,
                )
            ),
        )

        check_plan = (template_root / "CHECK_PLAN.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("**GENERATED VIEW:**", check_plan)
        self.assertIn("sync-views --root <audit-root>", check_plan)
        for heading in (
            "## Scope",
            "## Proof-unit inventory",
            "## Reviewed exceptions",
            "## Method-interface scope",
            "## Progress",
        ):
            self.assertIn(heading, check_plan)

    def test_delivery_check_requires_current_usable_finalization(self) -> None:
        self.make_complete_audit()
        parser = proofcheck.build_parser()

        def run_delivery() -> tuple[int, dict]:
            args = parser.parse_args(
                ["delivery-check", "--root", str(self.audit)]
            )
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                status = args.func(args)
            return status, json.loads(output.getvalue())

        status, result = run_delivery()
        self.assertEqual(1, status)
        self.assertEqual("NONFINAL", result["delivery_status"])
        self.assertFalse(result["usable_finalization"])

        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(
                0,
                proofcheck.cmd_finalize(argparse.Namespace(root=self.audit)),
            )
        status, result = run_delivery()
        self.assertEqual(0, status)
        self.assertEqual("FINAL", result["delivery_status"])
        self.assertTrue(result["usable_finalization"])

        self.paper.write_text(
            self.paper.read_text(encoding="utf-8") + "% source drift\n",
            encoding="utf-8",
            newline="\n",
        )
        status, result = run_delivery()
        self.assertEqual(1, status)
        self.assertEqual("NONFINAL", result["delivery_status"])
        self.assertFalse(result["usable_finalization"])
        self.assertTrue(result["reasons"])

    def test_archive_issue_does_not_require_hard_links(self) -> None:
        self.make_archivable_s1_audit()
        archive_path = (
            self.audit
            / "audit"
            / "06_reports"
            / "history"
            / "I-001-origin.json"
        )

        with mock.patch.object(
            proofcheck.os,
            "link",
            side_effect=AssertionError("hard links are unavailable"),
        ):
            with contextlib.redirect_stdout(io.StringIO()):
                status = proofcheck.cmd_archive_issue(
                    argparse.Namespace(root=self.audit, issue_id="I-001")
                )

        self.assertEqual(0, status)
        self.assertTrue(archive_path.is_file())

    def test_archive_issue_recovers_from_matching_lock_only_interruption(
        self,
    ) -> None:
        self.make_archivable_s1_audit()
        archive_path = (
            self.audit
            / "audit"
            / "06_reports"
            / "history"
            / "I-001-origin.json"
        )
        temporary = proofcheck.proofcheck_temp_path(archive_path)
        lock = archive_path.with_name(
            f".{archive_path.name}.proofcheck.lock"
        )
        original = proofcheck.atomic_write_text

        def interrupt_before_staging(path: Path, text: str) -> None:
            if path.resolve() == temporary.resolve():
                raise OSError("simulated lock-only interruption")
            original(path, text)

        with mock.patch.object(
            proofcheck,
            "utc_now",
            return_value="2030-01-01T00:00:00Z",
        ):
            with mock.patch.object(
                proofcheck,
                "atomic_write_text",
                side_effect=interrupt_before_staging,
            ):
                with self.assertRaisesRegex(
                    OSError, "simulated lock-only interruption"
                ):
                    proofcheck.cmd_archive_issue(
                        argparse.Namespace(root=self.audit, issue_id="I-001")
                    )

        self.assertTrue(lock.is_file())
        self.assertFalse(temporary.exists())
        self.assertFalse(archive_path.exists())
        lock_record = read_json(lock)
        self.assertEqual(1, lock_record["transaction_schema_version"])
        self.assertEqual(archive_path.name, lock_record["target"])
        self.assertRegex(lock_record["expected_sha256"], r"^[0-9a-f]{64}$")

        with mock.patch.object(
            proofcheck,
            "utc_now",
            return_value="2030-01-02T00:00:00Z",
        ):
            with contextlib.redirect_stdout(io.StringIO()):
                status = proofcheck.cmd_archive_issue(
                    argparse.Namespace(root=self.audit, issue_id="I-001")
                )

        self.assertEqual(0, status)
        self.assertTrue(archive_path.is_file())
        self.assertFalse(temporary.exists())
        self.assertFalse(lock.exists())


class PortabilityContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.source_dir = self.base / "inputs with spaces" / "理论"
        self.source_dir.mkdir(parents=True)
        self.paper = self.source_dir / "paper source.tex"
        self.paper.write_text(
            "\\newtheorem{lemma}{Lemma}\n"
            "\\begin{lemma}\\label{lem:portable}\n$x=x$.\n"
            "\\end{lemma}\n"
            "\\begin{proof}\nBy reflexivity.\n\\end{proof}\n",
            encoding="utf-8",
            newline="\n",
        )

    def tearDown(self) -> None:
        try:
            self.paper.chmod(stat.S_IREAD | stat.S_IWRITE)
        except FileNotFoundError:
            pass
        self.temp.cleanup()

    def parse_and_run(self, argv: list[str]) -> tuple[int, dict]:
        args = proofcheck.build_parser().parse_args(argv)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = int(args.func(args))
        return status, json.loads(output.getvalue())

    def scaffold_args(
        self,
        output: Path,
        *,
        paper: Path | None = None,
        input_kind: str = "latex",
        publisher_pdf: Path | None = None,
        portable_sources: bool = False,
        visual_review_status: str = "not_started",
        visual_review_notes: str | None = None,
        project_root: Path | None = None,
    ) -> argparse.Namespace:
        return argparse.Namespace(
            paper=paper or self.paper,
            output=output,
            input_kind=input_kind,
            publisher_pdf=publisher_pdf,
            portable_sources=portable_sources,
            visual_review_status=visual_review_status,
            visual_review_notes=visual_review_notes,
            additional_source=None,
            fls=None,
            project_root=project_root,
        )

    def test_cli_requires_declared_input_kind(self) -> None:
        parser = proofcheck.build_parser()
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                parser.parse_args(
                    [
                        "scaffold",
                        "--paper",
                        str(self.paper),
                        "--output",
                        str(self.base / "audit"),
                    ]
                )

    def test_scaffold_cli_rejects_complete_visual_review_claim(self) -> None:
        parser = proofcheck.build_parser()
        help_output = io.StringIO()
        with contextlib.redirect_stdout(help_output):
            with self.assertRaises(SystemExit) as help_exit:
                parser.parse_args(["scaffold", "--help"])
        self.assertEqual(0, help_exit.exception.code)
        self.assertIn(
            "--visual-review-status {not_started,partial}",
            help_output.getvalue(),
        )

        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as invalid_exit:
                parser.parse_args(
                    [
                        "scaffold",
                        "--paper",
                        str(self.base / "transcription.txt"),
                        "--input-kind",
                        "pdf_transcription",
                        "--publisher-pdf",
                        str(self.base / "publisher.pdf"),
                        "--visual-review-status",
                        "complete",
                        "--output",
                        str(self.base / "audit"),
                    ]
                )
        self.assertEqual(2, invalid_exit.exception.code)

    def test_doctor_runs_from_arbitrary_cwd_with_read_only_unicode_source(
        self,
    ) -> None:
        arbitrary_cwd = self.base / "arbitrary working directory" / "分析"
        arbitrary_cwd.mkdir(parents=True)
        output = self.base / "doctor target with spaces"
        self.paper.chmod(stat.S_IREAD)
        try:
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "doctor",
                    "--paper",
                    str(self.paper),
                    "--output",
                    str(output),
                    "--input-kind",
                    "latex",
                    "--portable-sources",
                ],
                cwd=arbitrary_cwd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
        finally:
            self.paper.chmod(stat.S_IREAD | stat.S_IWRITE)

        self.assertEqual(0, completed.returncode, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual("doctor", result["command"])
        self.assertEqual("passed", result["status"])
        self.assertTrue(result["ready"])
        self.assertFalse(output.exists())
        self.assertTrue(
            all(row["status"] != "failed" for row in result["checks"])
        )

    def test_doctor_classifies_an_unusable_output_parent(self) -> None:
        blocker = self.base / "ordinary file"
        blocker.write_text("not a directory\n", encoding="utf-8")

        status, result = self.parse_and_run(
            [
                "doctor",
                "--paper",
                str(self.paper),
                "--output",
                str(blocker / "audit"),
                "--input-kind",
                "latex",
            ]
        )

        self.assertEqual(1, status)
        self.assertEqual("failed", result["status"])
        self.assertFalse(result["ready"])
        self.assertGreater(result["failures_by_category"]["output_write"], 0)
        self.assertTrue(
            any(
                row["category"] == "output_write"
                and row["status"] == "failed"
                for row in result["checks"]
            )
        )

    def test_doctor_new_mode_rejects_existing_directory_without_residue(self) -> None:
        output = self.base / "existing audit directory"
        output.mkdir()

        status, result = self.parse_and_run(
            [
                "doctor",
                "--mode",
                "new",
                "--paper",
                str(self.paper),
                "--output",
                str(output),
                "--input-kind",
                "latex",
            ]
        )

        self.assertEqual(1, status)
        self.assertEqual("failed", result["status"])
        self.assertFalse(result["ready"])
        self.assertEqual([], list(output.iterdir()))

    def test_doctor_resume_mode_requires_matching_audit_manifest(self) -> None:
        empty = self.base / "empty resume directory"
        empty.mkdir()
        status, result = self.parse_and_run(
            [
                "doctor",
                "--mode",
                "resume",
                "--paper",
                str(self.paper),
                "--output",
                str(empty),
                "--input-kind",
                "latex",
            ]
        )
        self.assertEqual(1, status)
        self.assertFalse(result["ready"])
        self.assertTrue(
            any(row["id"] == "resume_audit" for row in result["checks"])
        )
        self.assertEqual([], list(empty.iterdir()))

        helper = self.source_dir / "resume-helper.tex"
        helper.write_text("Helper source.\n", encoding="utf-8", newline="\n")
        self.paper.write_text(
            "\\input{resume-helper}\n" + self.paper.read_text(encoding="utf-8"),
            encoding="utf-8",
            newline="\n",
        )
        audit = self.base / "valid resume audit"
        with contextlib.redirect_stdout(io.StringIO()):
            proofcheck.cmd_scaffold(
                self.scaffold_args(audit, portable_sources=True)
            )
        status, result = self.parse_and_run(
            [
                "doctor",
                "--mode",
                "resume",
                "--paper",
                str(self.paper),
                "--output",
                str(audit),
                "--input-kind",
                "latex",
            ]
        )
        self.assertEqual(0, status)
        self.assertTrue(result["ready"])
        self.assertEqual("resume", result["mode"])

        status, result = self.parse_and_run(
            [
                "doctor",
                "--mode",
                "resume",
                "--paper",
                str(helper),
                "--output",
                str(audit),
                "--input-kind",
                "latex",
            ]
        )
        self.assertEqual(1, status)
        self.assertFalse(result["ready"])
        self.assertTrue(
            any(
                row["id"] == "resume_audit"
                and "authoritative paper" in row["detail"]
                for row in result["checks"]
            )
        )

    def test_doctor_resume_reconciles_pdf_provenance_and_input_kind(self) -> None:
        transcription = self.source_dir / "transcription.txt"
        transcription.write_text(
            "[Page 1]\nLemma 1. For every x, x=x.\n",
            encoding="utf-8",
            newline="\n",
        )
        publisher = self.source_dir / "publisher.pdf"
        publisher.write_bytes(b"%PDF-1.4\nrecorded publisher\n%%EOF\n")
        wrong_publisher = self.source_dir / "wrong-publisher.pdf"
        wrong_publisher.write_bytes(b"%PDF-1.4\ndifferent publisher\n%%EOF\n")
        audit = self.base / "pdf resume audit"
        with contextlib.redirect_stdout(io.StringIO()):
            proofcheck.cmd_scaffold(
                self.scaffold_args(
                    audit,
                    paper=transcription,
                    input_kind="pdf_transcription",
                    publisher_pdf=publisher,
                    portable_sources=True,
                )
            )

        status, result = self.parse_and_run(
            [
                "doctor",
                "--mode",
                "resume",
                "--paper",
                str(transcription),
                "--publisher-pdf",
                str(wrong_publisher),
                "--output",
                str(audit),
                "--input-kind",
                "pdf_transcription",
            ]
        )
        self.assertEqual(1, status)
        self.assertFalse(result["ready"])
        self.assertTrue(
            any(
                row["id"] == "resume_audit"
                and "publisher PDF" in row["detail"]
                for row in result["checks"]
            )
        )

        status, result = self.parse_and_run(
            [
                "doctor",
                "--mode",
                "resume",
                "--paper",
                str(transcription),
                "--output",
                str(audit),
                "--input-kind",
                "latex",
            ]
        )
        self.assertEqual(1, status)
        self.assertFalse(result["ready"])
        self.assertTrue(
            any(
                row["id"] == "resume_audit"
                and "input kind" in row["detail"]
                for row in result["checks"]
            )
        )

        status, result = self.parse_and_run(
            [
                "doctor",
                "--mode",
                "resume",
                "--paper",
                str(transcription),
                "--publisher-pdf",
                str(publisher),
                "--output",
                str(audit),
                "--input-kind",
                "pdf_transcription",
            ]
        )
        self.assertEqual(0, status)
        self.assertTrue(result["ready"])

        nonportable = self.base / "nonportable pdf resume audit"
        with contextlib.redirect_stdout(io.StringIO()):
            proofcheck.cmd_scaffold(
                self.scaffold_args(
                    nonportable,
                    paper=transcription,
                    input_kind="pdf_transcription",
                    publisher_pdf=publisher,
                )
            )
        publisher.unlink()
        status, result = self.parse_and_run(
            [
                "doctor",
                "--mode",
                "resume",
                "--paper",
                str(transcription),
                "--publisher-pdf",
                str(wrong_publisher),
                "--output",
                str(nonportable),
                "--input-kind",
                "pdf_transcription",
            ]
        )
        self.assertEqual(1, status)
        self.assertFalse(result["ready"])
        self.assertTrue(
            any(
                row["id"] == "resume_audit"
                and "Publisher PDF not found" in row["detail"]
                for row in result["checks"]
            )
        )

    def test_doctor_reports_probe_cleanup_failure(self) -> None:
        output = self.base / "doctor-cleanup-target"
        original_rmtree = proofcheck.shutil.rmtree
        try:
            with mock.patch.object(
                proofcheck.shutil,
                "rmtree",
                side_effect=OSError("simulated cleanup failure"),
            ):
                status, result = self.parse_and_run(
                    [
                        "doctor",
                        "--paper",
                        str(self.paper),
                        "--output",
                        str(output),
                        "--input-kind",
                        "latex",
                    ]
                )
        finally:
            for residue in output.parent.glob(".proofcheck-doctor-*"):
                original_rmtree(residue)

        self.assertEqual(1, status)
        self.assertFalse(result["ready"])
        self.assertTrue(
            any(
                row["id"] == "output_cleanup"
                and row["status"] == "failed"
                for row in result["checks"]
            )
        )

    def test_scaffold_rejects_raw_pdf_without_committing_workspace(self) -> None:
        raw_pdf = self.base / "paper.pdf"
        raw_pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
        output = self.base / "raw-pdf-audit"

        with self.assertRaisesRegex(ValueError, "raw PDF|Raw PDF|\\.pdf"):
            proofcheck.cmd_scaffold(
                self.scaffold_args(
                    output,
                    paper=raw_pdf,
                    input_kind="pdf_transcription",
                    publisher_pdf=raw_pdf,
                )
            )

        self.assertFalse(output.exists())
        self.assertEqual(
            [],
            list(output.parent.glob(f".{output.name}.*.proofcheck.stage")),
        )

    def test_pdf_transcription_bundle_relocates_without_original_sources(
        self,
    ) -> None:
        transcription = self.source_dir / "pages 1-2 transcription.txt"
        transcription.write_text(
            "[Page 1]\nLemma 1. For every x, x=x.\n"
            "[Page 2]\nProof. By reflexivity.\n",
            encoding="utf-8",
            newline="\n",
        )
        publisher_pdf = self.source_dir / "publisher proof.pdf"
        publisher_pdf.write_bytes(b"%PDF-1.4\nportable fixture\n%%EOF\n")
        audit = self.base / "portable PDF audit"
        with contextlib.redirect_stdout(io.StringIO()):
            status = proofcheck.cmd_scaffold(
                self.scaffold_args(
                    audit,
                    paper=transcription,
                    input_kind="pdf_transcription",
                    publisher_pdf=publisher_pdf,
                    portable_sources=True,
                    visual_review_status="partial",
                    visual_review_notes=(
                        "Pages 1 and 2, including the displayed equality, were "
                        "compared against the rendered publisher PDF."
                    ),
                )
            )
        self.assertEqual(0, status)

        manifest_path = audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        visual_review = manifest["input_provenance"]["visual_review"]
        visual_review.update(
            {
                "status": "complete",
                "reviewed_pages": ["1", "2"],
                "completed_utc": "2026-08-18T12:00:00Z",
            }
        )
        write_json(manifest_path, manifest)
        provenance = manifest["input_provenance"]
        self.assertEqual("pdf_transcription", provenance["kind"])
        self.assertTrue(provenance["portable_sources"])
        self.assertTrue(provenance["manual_inventory_required"])
        self.assertEqual(
            manifest["paper_file"], provenance["authoritative_source"]
        )
        self.assertNotIn("\\", manifest["paper_file"])
        self.assertNotIn("\\", provenance["publisher_pdf"]["file"])
        self.assertTrue(
            all("\\" not in value for value in provenance["original_locations"])
        )
        self.assertNotIn(
            "\\", provenance["publisher_pdf"]["original_location"]
        )
        bundled_text = proofcheck.resolve_stored_path(
            provenance["authoritative_source"], audit
        )
        bundled_pdf = proofcheck.resolve_stored_path(
            provenance["publisher_pdf"]["file"], audit
        )
        self.assertTrue(bundled_text.is_file())
        self.assertTrue(bundled_pdf.is_file())
        self.assertEqual(
            proofcheck.sha256_file(transcription),
            proofcheck.sha256_file(bundled_text),
        )
        self.assertEqual(
            proofcheck.sha256_file(publisher_pdf),
            provenance["publisher_pdf"]["sha256"],
        )
        self.assertEqual(
            publisher_pdf.stat().st_size,
            provenance["publisher_pdf"]["size_bytes"],
        )
        self.assertEqual("complete", provenance["visual_review"]["status"])
        self.assertEqual(
            ["1", "2"], provenance["visual_review"]["reviewed_pages"]
        )
        self.assertEqual(
            "2026-08-18T12:00:00Z",
            provenance["visual_review"]["completed_utc"],
        )

        canonical = provenance["authoritative_source"]
        legacy = canonical.replace("/", "\\")
        self.assertEqual(
            proofcheck.resolve_stored_path(canonical, audit),
            proofcheck.resolve_stored_path(legacy, audit),
        )
        if os.name == "nt":
            foreign = "/tmp/foreign-paper.tex"
            message = "Foreign POSIX absolute path"
        else:
            foreign = r"C:\foreign\paper.tex"
            message = "Foreign Windows absolute path"
        with self.assertRaisesRegex(ValueError, message):
            proofcheck.resolve_stored_path(foreign, audit)

        transcription.unlink()
        publisher_pdf.unlink()
        moved = self.base / "moved audit" / "跨平台"
        moved.parent.mkdir()
        audit.rename(moved)
        status, result = self.parse_and_run(
            ["status", "--root", str(moved)]
        )
        self.assertEqual(0, status)
        self.assertEqual("healthy_wip", result["workflow_state"])
        self.assertEqual([], result["progress"]["drift"])

    def test_incomplete_pdf_audit_stays_nonfinal_with_visible_limits(
        self,
    ) -> None:
        transcription = self.source_dir / "incomplete transcription.txt"
        transcription.write_text(
            "[Page 1]\nLemma 1. For every x, x=x.\n",
            encoding="utf-8",
            newline="\n",
        )
        publisher_pdf = self.source_dir / "incomplete publisher.pdf"
        publisher_pdf.write_bytes(b"%PDF-1.4\nfixture\n%%EOF\n")
        audit = self.base / "incomplete PDF audit"
        with contextlib.redirect_stdout(io.StringIO()):
            scaffold_status = proofcheck.cmd_scaffold(
                self.scaffold_args(
                    audit,
                    paper=transcription,
                    input_kind="pdf_transcription",
                    publisher_pdf=publisher_pdf,
                    portable_sources=True,
                    visual_review_status="partial",
                    visual_review_notes=(
                        "Page 1 was compared, but the theorem/proof inventory "
                        "remains incomplete."
                    ),
                )
            )
        self.assertEqual(0, scaffold_status)

        unchecked_result = "thm:untranscribed"
        limitation = (
            "The publisher PDF was only partially reviewed; the theorem/proof "
            "inventory is unavailable."
        )
        manifest_path = audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        manifest["report_context"] = {
            "notes": [f"Result not checked: {unchecked_result}"],
            "limitations": [limitation],
        }
        write_json(manifest_path, manifest)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(0, proofcheck.cmd_report(argparse.Namespace(root=audit)))
        report_path = audit / proofcheck.preferred_report_path(read_json(manifest_path))

        missing_evidence = [
            "pdf_transcription requires visual_review.status complete before "
            "finalization",
            "pdf_transcription visual_review.reviewed_pages must be a nonempty "
            "string list",
            "pdf_transcription visual_review.completed_utc must be a UTC "
            "timestamp",
            "pdf_transcription requires a nonempty manually reviewed "
            "theorem/proof inventory",
            "completion.inventory_reviewed must be true",
        ]
        status_code, status_result = self.parse_and_run(
            ["status", "--root", str(audit), "--verbose"]
        )
        self.assertEqual(0, status_code)
        self.assertEqual("healthy_wip", status_result["workflow_state"])
        self.assertEqual("NONFINAL", status_result["delivery_status"])
        self.assertFalse(status_result["audit_complete"])
        self.assertFalse(
            status_result["finalization"]["usable_finalization"]
        )
        for reason in missing_evidence:
            self.assertIn(
                reason,
                status_result["finalization"]["current_gate_errors"],
            )

        finalize_output = io.StringIO()
        with contextlib.redirect_stdout(finalize_output):
            with contextlib.redirect_stderr(io.StringIO()):
                finalize_status = proofcheck.cmd_finalize(
                    argparse.Namespace(root=audit)
                )
        self.assertEqual(1, finalize_status)
        self.assertGreater(json.loads(finalize_output.getvalue())["errors"], 0)
        self.assertFalse((audit / "audit/06_reports/FINALIZATION.json").exists())

        delivery_code, delivery_result = self.parse_and_run(
            ["delivery-check", "--root", str(audit)]
        )
        self.assertEqual(1, delivery_code)
        self.assertEqual("NONFINAL", delivery_result["delivery_status"])
        self.assertFalse(delivery_result["usable_finalization"])
        self.assertEqual("missing", delivery_result["record_status"])
        self.assertIsNone(delivery_result["report"])
        for reason in missing_evidence:
            self.assertIn(reason, delivery_result["reasons"])

        final_report = report_path.read_text(encoding="utf-8")
        lower_report = final_report.lower()
        self.assertIn("NONFINAL", final_report)
        self.assertIn("Working report. No overall judgment has been released.", final_report)
        self.assertIn(f"Result not checked: {unchecked_result}", final_report)
        self.assertIn(limitation, final_report)
        embedded = re.search(r'<script type="application/json" id="report-data">(.*?)</script>', final_report, re.S)
        self.assertIsNotNone(embedded)
        projection = json.loads(embedded.group(1))
        self.assertEqual("NONFINAL", projection["release"]["status"])
        self.assertIn("audit scope is unresolved", projection["summary"]["overall_judgment"])
        self.assertIsNone(projection["coverage"]["expected_units"])
        self.assertEqual(0, projection["coverage"]["checked_units"])
        self.assertNotIn("no_defect_found", lower_report)
        self.assertNotIn("no defect found", lower_report)
        self.assertNotIn("checked conclusions are established", lower_report)
        self.assertNotIn("mathematically correct", lower_report)

    def test_pdf_complete_label_cannot_bypass_page_and_inventory_evidence(
        self,
    ) -> None:
        transcription = self.base / "transcription.txt"
        transcription.write_text(
            "[Page 1]\nLemma 1. For every x, x=x.\n",
            encoding="utf-8",
            newline="\n",
        )
        publisher_pdf = self.base / "publisher.pdf"
        publisher_pdf.write_bytes(b"%PDF-1.4\nfixture\n%%EOF\n")
        audit = self.base / "pdf-evidence-gates"
        with contextlib.redirect_stdout(io.StringIO()):
            proofcheck.cmd_scaffold(
                self.scaffold_args(
                    audit,
                    paper=transcription,
                    input_kind="pdf_transcription",
                    publisher_pdf=publisher_pdf,
                    portable_sources=True,
                    visual_review_status="partial",
                    visual_review_notes=(
                        "The displayed equality was compared on page 1."
                    ),
                )
            )

        manifest_path = audit / "AUDIT_MANIFEST.json"
        manifest = read_json(manifest_path)
        manifest["input_provenance"]["visual_review"]["status"] = "complete"
        write_json(manifest_path, manifest)

        errors, _ = proofcheck.check_audit_finalization(audit)

        self.assertIn(
            "pdf_transcription visual_review.reviewed_pages must be a "
            "nonempty string list",
            errors,
        )
        self.assertIn(
            "pdf_transcription requires a nonempty manually reviewed "
            "theorem/proof inventory",
            errors,
        )
        self.assertIn("completion.inventory_reviewed must be true", errors)

    def test_portable_latex_detects_late_resolution_of_missing_input(
        self,
    ) -> None:
        project = self.source_dir / "portable project"
        project.mkdir()
        main = project / "main.tex"
        main.write_text(
            "\\input{late}\n"
            "\\newtheorem{lemma}{Lemma}\n"
            "\\begin{lemma}\\label{lem:late}\n$x=x$.\n"
            "\\end{lemma}\n"
            "\\begin{proof}\nBy reflexivity.\n\\end{proof}\n",
            encoding="utf-8",
            newline="\n",
        )
        audit = self.base / "portable-late-input-audit"
        with contextlib.redirect_stdout(io.StringIO()):
            proofcheck.cmd_scaffold(
                self.scaffold_args(
                    audit,
                    paper=main,
                    portable_sources=True,
                )
            )
        manifest = read_json(audit / "AUDIT_MANIFEST.json")
        self.assertEqual(
            [], proofcheck.source_snapshot_freshness_errors(audit, manifest)
        )

        bundled_main = proofcheck.resolve_stored_path(
            manifest["paper_file"], audit
        )
        bundled_late = bundled_main.parent / "late.tex"
        bundled_late.write_text(
            "\\newcommand{\\latefact}{available}\n",
            encoding="utf-8",
            newline="\n",
        )

        freshness_errors = proofcheck.source_snapshot_freshness_errors(
            audit, manifest
        )
        self.assertTrue(
            any(
                "Source closure has new or unrecorded files" in error
                and str(bundled_late) in error
                for error in freshness_errors
            ),
            freshness_errors,
        )
        finalization_errors, _ = proofcheck.check_audit_finalization(audit)
        self.assertTrue(
            any(
                "Source closure has new or unrecorded files" in error
                for error in finalization_errors
            ),
            finalization_errors,
        )

    def test_portable_latex_requires_root_covering_relative_include(
        self,
    ) -> None:
        common_root = self.source_dir / "cross-directory project"
        manuscript_dir = common_root / "manuscript"
        shared_dir = common_root / "shared"
        manuscript_dir.mkdir(parents=True)
        shared_dir.mkdir()
        main = manuscript_dir / "main.tex"
        shared = shared_dir / "foo.tex"
        main.write_text(
            "\\input{../shared/foo}\n"
            "\\newtheorem{lemma}{Lemma}\n"
            "\\begin{lemma}\\label{lem:shared}\n$x=x$.\n"
            "\\end{lemma}\n"
            "\\begin{proof}\nBy reflexivity.\n\\end{proof}\n",
            encoding="utf-8",
            newline="\n",
        )
        shared.write_text(
            "\\newcommand{\\sharedfact}{available}\n",
            encoding="utf-8",
            newline="\n",
        )
        narrow_output = self.base / "narrow-root-audit"

        with self.assertRaisesRegex(
            ValueError, "outside.*project_root|broader --project-root"
        ):
            proofcheck.cmd_scaffold(
                self.scaffold_args(
                    narrow_output,
                    paper=main,
                    portable_sources=True,
                    project_root=manuscript_dir,
                )
            )
        self.assertFalse(narrow_output.exists())
        self.assertEqual(
            [],
            list(
                narrow_output.parent.glob(
                    f".{narrow_output.name}.*.proofcheck.stage"
                )
            ),
        )

        portable = self.base / "broad-root-audit"
        with contextlib.redirect_stdout(io.StringIO()):
            proofcheck.cmd_scaffold(
                self.scaffold_args(
                    portable,
                    paper=main,
                    portable_sources=True,
                    project_root=common_root,
                )
            )
        manifest = read_json(portable / "AUDIT_MANIFEST.json")
        locked_paths = {
            proofcheck.resolve_stored_path(row["file"], portable)
            for row in manifest["source_snapshot"]["files"]
        }
        self.assertEqual(2, len(locked_paths))
        self.assertTrue(all(path.is_file() for path in locked_paths))

        main.unlink()
        shared.unlink()
        moved = self.base / "relocated broad-root audit"
        portable.rename(moved)
        status, result = self.parse_and_run(
            ["status", "--root", str(moved)]
        )
        self.assertEqual(0, status)
        self.assertEqual("healthy_wip", result["workflow_state"])
        self.assertEqual([], result["progress"]["drift"])

    def test_portable_latex_rejects_absolute_input_without_residue(
        self,
    ) -> None:
        project = self.source_dir / "absolute-input-project"
        manuscript_dir = project / "manuscript"
        shared_dir = project / "shared"
        manuscript_dir.mkdir(parents=True)
        shared_dir.mkdir()
        shared = shared_dir / "absolute.tex"
        shared.write_text(
            "\\newcommand{\\absolutefact}{available}\n",
            encoding="utf-8",
            newline="\n",
        )
        main = manuscript_dir / "main.tex"
        main.write_text(
            f"\\input{{{shared.resolve().as_posix()}}}\n"
            "\\newtheorem{lemma}{Lemma}\n"
            "\\begin{lemma}\\label{lem:absolute}\n$x=x$.\n"
            "\\end{lemma}\n"
            "\\begin{proof}\nBy reflexivity.\n\\end{proof}\n",
            encoding="utf-8",
            newline="\n",
        )
        output = self.base / "absolute-input-audit"

        with self.assertRaisesRegex(
            ValueError,
            "absolute or otherwise nonrelocatable inclusion after bundling",
        ):
            proofcheck.cmd_scaffold(
                self.scaffold_args(
                    output,
                    paper=main,
                    portable_sources=True,
                    project_root=project,
                )
            )

        self.assertFalse(output.exists())
        self.assertEqual(
            [],
            list(output.parent.glob(f".{output.name}.*.proofcheck.stage")),
        )

    def test_interrupted_scaffold_removes_staging_workspace(self) -> None:
        output = self.base / "interrupted audit"
        original = proofcheck.atomic_write_json
        calls = 0

        def interrupt_third_write(path: Path, value: object) -> None:
            nonlocal calls
            calls += 1
            if calls == 3:
                raise OSError("simulated scaffold interruption")
            original(path, value)

        with mock.patch.object(
            proofcheck,
            "atomic_write_json",
            side_effect=interrupt_third_write,
        ):
            with self.assertRaisesRegex(
                OSError, "simulated scaffold interruption"
            ):
                proofcheck.cmd_scaffold(
                    self.scaffold_args(output, portable_sources=True)
                )

        self.assertFalse(output.exists())
        self.assertEqual(
            [],
            list(output.parent.glob(f".{output.name}.*.proofcheck.stage")),
        )

    def test_atomic_text_write_preserves_previous_committed_bytes(self) -> None:
        target = self.base / "atomic state.json"
        target.write_text("old committed bytes\n", encoding="utf-8")

        with mock.patch.object(
            proofcheck.os,
            "replace",
            side_effect=OSError("simulated commit interruption"),
        ):
            with self.assertRaisesRegex(
                OSError, "simulated commit interruption"
            ):
                proofcheck.atomic_write_text(target, "new incomplete bytes\n")

        self.assertEqual(
            "old committed bytes\n", target.read_text(encoding="utf-8")
        )

    def test_cross_drive_absolute_fallback_uses_posix_serialization(self) -> None:
        with mock.patch.object(
            proofcheck.os.path,
            "relpath",
            side_effect=ValueError("different drives"),
        ):
            stored = proofcheck.relative_or_absolute(self.paper, self.base)

        self.assertEqual(self.paper.resolve().as_posix(), stored)
        self.assertNotIn("\\", stored)


if __name__ == "__main__":
    unittest.main()
