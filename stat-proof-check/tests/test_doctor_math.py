"""Early typesetting guidance must not replace source-readiness checks."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from test_proofcheck import proofcheck as pc


class DoctorMathTests(unittest.TestCase):
    def test_converter_availability_is_nonfatal_and_preserves_source_failures(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            paper = base / "paper.tex"
            paper.write_text("\\documentclass{article}\n\\begin{document}\nA readable source.\n\\end{document}\n", encoding="utf-8")
            parser = pc.build_parser()
            for available in (True, False):
                for present in (True, False):
                    with self.subTest(available=available, source_present=present):
                        args = parser.parse_args([
                            "doctor", "--paper", str(paper if present else base / "missing.tex"),
                            "--output", str(base / "audit"), "--input-kind", "latex",
                            "--portable-sources"])
                        output = io.StringIO()
                        info = {"available": available, "engine": "latex2mathml", "version": "test-version"}
                        with mock.patch.object(pc.report_renderer().math_renderer(), "renderer_info", return_value=info), contextlib.redirect_stdout(output):
                            code = pc.cmd_doctor(args)
                        result = json.loads(output.getvalue())
                        self.assertEqual(0 if present else 1, code)
                        self.assertEqual(present, result["ready"])
                        check = next(row for row in result["checks"] if row["id"] == "math_renderer")
                        self.assertEqual("passed" if available else "warning", check["status"])
                        if not available:
                            self.assertIn("literal LaTeX", check["detail"])
                            self.assertIn("shared interpreter", check["detail"])
                            self.assertIn("-m pip install --user latex2mathml", check["detail"])
                        self.assertEqual(0, result["failures_by_category"]["environment"])
                        self.assertFalse((base / "audit").exists())


if __name__ == "__main__":
    unittest.main()
