"""Graphify identity covers its nested display inputs, without hashing the whole core."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import proof_overview


class RendererIdentityTests(unittest.TestCase):
    def test_reachable_nested_display_inputs_change_the_fingerprint(self):
        nested = ["paper_core/math_render.py", "paper_core/renderer/scientific_reader.mjs",
                  "paper_core/renderer/scientific_reader.css", "paper_core/renderer/html_scan.mjs",
                  "paper_core/renderer/assets/archify/utils.mjs", "paper_core/renderer/assets/archify/i18n.mjs",
                  "paper_core/renderer/assets/archify/template.html"]
        preserved = ["overview_math.py", "render.mjs", "../assets/archify/legacy.css"]
        unrelated = ["paper_core/controller.py", "paper_core/renderer/reader_content.mjs"]
        with tempfile.TemporaryDirectory() as temporary:
            scripts = Path(temporary) / "skill" / "scripts"
            for name in nested + preserved + unrelated:
                path = scripts / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("original", encoding="utf-8")
            with mock.patch.object(proof_overview, "SCRIPT_DIR", scripts):
                original = proof_overview._renderer_version()
                for name in nested + preserved + unrelated:
                    with self.subTest(path=name):
                        path = scripts / name
                        path.write_text("changed", encoding="utf-8")
                        changed = proof_overview._renderer_version()
                        if name in unrelated:
                            self.assertEqual(changed, original)
                        else:
                            self.assertNotEqual(changed, original)
                        path.write_text("original", encoding="utf-8")
                        self.assertEqual(proof_overview._renderer_version(), original)
