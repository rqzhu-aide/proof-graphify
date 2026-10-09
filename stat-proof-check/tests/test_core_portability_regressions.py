from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
import unicodedata
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "proofcheck.py"
SPEC = importlib.util.spec_from_file_location("proofcheck_core_regressions", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Cannot load {SCRIPT}")
proofcheck = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(proofcheck)


class DefinitionBodyDiscoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.main = self.base / "main.tex"
        self.hidden = self.base / "hidden.tex"
        self.hidden.write_text(
            "Hidden proof source.\n", encoding="utf-8", newline="\n"
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_definition_body_inclusion_is_mandatory_warning(self) -> None:
        self.main.write_text(
            "\\newcommand{\\loadproof}[1]{\\input{#1}}\n"
            "\\newenvironment{loadappendix}{\\subfile{hidden}}{}\n"
            "\\loadproof{hidden}\n",
            encoding="utf-8",
            newline="\n",
        )

        closure = proofcheck.discover_source_closure(self.main)

        warnings = [
            warning
            for warning in closure["warnings"]
            if "definition body contains a source inclusion command" in warning
        ]
        self.assertEqual(2, len(warnings), closure)
        self.assertNotIn(self.hidden.resolve(), closure["files"])

    def test_fls_adds_source_but_does_not_suppress_definition_warning(self) -> None:
        self.main.write_text(
            "\\newcommand{\\loadproof}[1]{\\input{#1}}\n"
            "\\loadproof{hidden}\n",
            encoding="utf-8",
            newline="\n",
        )
        fls = self.base / "paper.fls"
        fls.write_text(
            f"PWD {self.base}\nINPUT {self.main}\nINPUT {self.hidden}\n",
            encoding="utf-8",
            newline="\n",
        )

        closure = proofcheck.discover_source_closure(
            self.main,
            fls_file=fls,
            project_root=self.base,
        )

        self.assertIn(self.hidden.resolve(), closure["files"])
        self.assertTrue(
            any(
                "definition body contains a source inclusion command" in warning
                for warning in closure["warnings"]
            ),
            closure,
        )

    def test_statically_inactive_definition_body_is_not_warned(self) -> None:
        self.main.write_text(
            "\\iffalse\n"
            "\\newcommand{\\loadproof}{\\input{hidden}}\n"
            "\\fi\n",
            encoding="utf-8",
            newline="\n",
        )

        closure = proofcheck.discover_source_closure(self.main)

        self.assertFalse(
            any(
                "definition body contains a source inclusion command" in warning
                for warning in closure["warnings"]
            ),
            closure,
        )


class DoctorDiscoveryParityTests(unittest.TestCase):
    def test_doctor_validates_discovery_inputs_without_residue(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            project = base / "project with spaces"
            project.mkdir()
            main = project / "main paper.tex"
            child = project / "child.tex"
            supplement = project / "supplement source.tex"
            fls = project / "paper trace.fls"
            output = base / "audit output"
            main.write_text(
                "\\input{child}\nMain.\n", encoding="utf-8", newline="\n"
            )
            child.write_text("Child.\n", encoding="utf-8", newline="\n")
            supplement.write_text(
                "Supplement.\n", encoding="utf-8", newline="\n"
            )
            fls.write_text(
                f"PWD {project}\nINPUT {main}\nINPUT {child}\n",
                encoding="utf-8",
                newline="\n",
            )
            before = {
                path.relative_to(base).as_posix(): path.read_bytes()
                for path in base.rglob("*")
                if path.is_file()
            }
            args = proofcheck.build_parser().parse_args(
                [
                    "doctor",
                    "--paper",
                    str(main),
                    "--output",
                    str(output),
                    "--input-kind",
                    "latex",
                    "--portable-sources",
                    "--project-root",
                    str(project),
                    "--additional-source",
                    str(supplement),
                    "Load-bearing appendix",
                    "The appendix supplies a prerequisite proof.",
                    "--fls",
                    str(fls),
                ]
            )
            captured = io.StringIO()
            with contextlib.redirect_stdout(captured):
                status = args.func(args)
            result = json.loads(captured.getvalue())
            after = {
                path.relative_to(base).as_posix(): path.read_bytes()
                for path in base.rglob("*")
                if path.is_file()
            }

            self.assertEqual(0, status, result)
            self.assertTrue(result["ready"], result)
            self.assertEqual(before, after)
            self.assertFalse(output.exists())
            self.assertEqual(
                [],
                list(base.glob(".proofcheck-doctor-*")),
            )
            checks = {row["id"]: row for row in result["checks"]}
            self.assertEqual("passed", checks["project_root"]["status"])
            self.assertEqual("passed", checks["additional_sources"]["status"])
            self.assertEqual("passed", checks["recorder_file"]["status"])
            self.assertEqual("passed", checks["source_discovery"]["status"])
            self.assertEqual("passed", result["source_discovery"]["status"])
            self.assertEqual(3, len(result["source_discovery"]["files"]))
            self.assertIsNotNone(
                result["source_discovery"]["closure_sha256"]
            )


class MarkdownAndIdentifierRegressionTests(unittest.TestCase):
    def test_markdown_free_text_is_single_line_and_preserves_latex(self) -> None:
        value = (
            "quoted $\\alpha$"
            "\r\n## injected\v\f\x00\x85\u2028\u2029"
            " and a | table marker\ud800"
        )

        escaped = proofcheck.escape_markdown(value)
        heading = proofcheck.escape_markdown_heading("<tag> " + value)
        table = proofcheck.render_markdown_table(["Finding"], [[value]])

        self.assertEqual(3, len(table.splitlines()))
        table.encode("utf-8")
        self.assertIn("$\\alpha$", escaped)
        self.assertIn("\\|", escaped)
        self.assertIn("\uFFFD", escaped)
        self.assertNotIn("\ud800", escaped)
        self.assertIn("&lt;tag&gt;", heading)
        for rendered in (escaped, heading):
            self.assertFalse(
                any(
                    unicodedata.category(character) in {"Cc", "Zl", "Zp"}
                    for character in rendered
                ),
                repr(rendered),
            )
        self.assertNotIn("\n## injected", table)

    def test_generated_numeric_ids_scale_past_999_without_extra_zeroes(self) -> None:
        ledger = {
            "source": {"start_line": 1, "end_line": 1001},
            "source_lines": [
                {"line": line, "text": f"line {line}"}
                for line in range(1, 1002)
            ],
        }

        units, ranges = proofcheck.build_compiled_source_units(ledger, [])

        self.assertEqual("U1001", units[-1]["id"])
        self.assertEqual("U1001", ranges[(1001, 1001)])
        conditions = proofcheck.build_compact_side_conditions(
            [
                {
                    "condition": f"Side condition {index} must hold.",
                    "status": "open",
                }
                for index in range(1, 1001)
            ],
            "side_conditions",
            [],
        )
        self.assertEqual("SC1000", conditions[-1]["id"])
        self.assertTrue(
            all(condition["generated_by"] == "M001" for condition in conditions)
        )
        for pattern, value in (
            (proofcheck.SOURCE_UNIT_ID_RE, "U1000"),
            (proofcheck.STEP_ID_RE, "S1000"),
            (proofcheck.PREMISE_ID_RE, "P1000"),
            (proofcheck.SIDE_CONDITION_ID_RE, "SC1000"),
            (proofcheck.CANDIDATE_PATH_ID_RE, "CP1000"),
        ):
            self.assertIsNotNone(pattern.fullmatch(value), value)
        self.assertIsNone(proofcheck.SOURCE_UNIT_ID_RE.fullmatch("U0001"))


class AuditStateOrderingTests(unittest.TestCase):
    def test_state_manifest_orders_by_posix_string_not_path_objects(self) -> None:
        """The audit-state hash must be identical across platforms.

        Path-object ordering is case-insensitive on Windows and
        case-sensitive elsewhere, and parts-tuple ordering disagrees with
        string ordering around '-' versus '/'. Sorting by the canonical posix
        string is the only ordering every platform reproduces, so a
        finalization made on one operating system stays FINAL on another.
        """
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "audit-extra").mkdir()
            (root / "audit").mkdir()
            for relative in (
                "AUDIT_MANIFEST.json",
                "PROGRESS.json",
                "audit-extra/inner.json",
                "audit/file.json",
            ):
                target = root / relative
                target.write_text("{}", encoding="utf-8", newline="\n")
            rows = proofcheck.audit_state_manifest(root)
            files = [row["file"] for row in rows]
            self.assertEqual(files, sorted(files))
            self.assertEqual(
                [
                    "AUDIT_MANIFEST.json",
                    "PROGRESS.json",
                    "audit-extra/inner.json",
                    "audit/file.json",
                ],
                files,
            )
            self.assertEqual(
                proofcheck.canonical_sha256(rows),
                proofcheck.audit_state_sha256(root),
            )


if __name__ == "__main__":
    unittest.main()
