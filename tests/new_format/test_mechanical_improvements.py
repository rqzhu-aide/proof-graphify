"""Transport, contextual recovery and presentation changes preserve existing work."""
import copy
import io
import json
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock, patch
from xml.etree import ElementTree as ET

from support import CLI_ENV, TempCase, edit, node_available, run_cli
from paper_core import cli, controller, publish
from paper_core.errors import InvalidRequest
from paper_core.math_render import _convert, render_text


class CommonFormulaTests(TempCase):
    def test_common_notation_keeps_operators_scripts_and_original_tex(self):
        namespace = {"m": "http://www.w3.org/1998/Math/MathML"}
        for tex, operators in ((r"R\perp\!\!\perp_Z S\mid X", ["⫫", "∣"]),
                               (r"\arg\min_x f(x)", ["arg", "min"]),
                               (r"\Bigl\lVert x \Bigr\rVert_{\mathcal H}^2", ["‖"]),
                               (r"\binom nk^{-1}", [])):
            with self.subTest(tex=tex):
                markup, reason = _convert(tex, "inline")
                self.assertIsNotNone(markup, reason)
                root = ET.fromstring(markup)
                present = [element.text for element in root.findall(".//m:mo", namespace)]
                for operator in operators:
                    self.assertIn(operator, present)
                self.assertEqual(tex, root.find(".//m:annotation", namespace).text)
                if "perp" in tex:
                    self.assertEqual("⫫", root.find(".//m:msub/m:mo", namespace).text)
                    self.assertEqual([], root.findall(".//m:mspace", namespace))
                if "Bigl" in tex:
                    fences = [element for element in root.findall(".//m:mo", namespace)
                              if element.text == "‖"]
                    self.assertEqual(len(fences), 2)
                    for fence in fences:
                        self.assertEqual(fence.get("minsize"), "1.623em")
                        self.assertEqual(fence.get("maxsize"), "1.623em")
                    scripted = root.find(".//m:msubsup", namespace)
                    self.assertEqual("".join(scripted[0].itertext()), "‖")
                    self.assertEqual("".join(scripted[1].itertext()), "H")
                    self.assertEqual(scripted[2].text, "2")
                if "binom" in tex:
                    self.assertIsNotNone(root.find(".//m:msup", namespace))

    def test_unsupported_spacing_and_damaged_commands_remain_literal(self):
        for text, kind in ((r"$x\!y$", "unsupported_expression"),
                           (r"$\\mathbf{U}$", "damaged_escape"),
                           ("$\theta$", "damaged_escape")):
            with self.subTest(text=text):
                notes = []
                markup = render_text(text, diagnostics=notes)
                self.assertIn("math-fallback", markup)
                self.assertNotIn("<math", markup)
                self.assertEqual(text, notes[0]["excerpt"])
                self.assertEqual(kind, notes[0]["kind"])

    def test_legitimate_rows_and_single_perpendicular_are_preserved(self):
        for tex in (r"\begin{matrix}a\\beta\end{matrix}", r"\substack{a\\beta}", r"R\perp S"):
            markup, reason = _convert(tex, "block")
            self.assertIsNotNone(markup, reason)
            self.assertNotIn("⫫", markup)

    def test_rendering_new_notation_preserves_scientific_records_and_progress(self):
        if not node_available():
            self.skipTest("Node is unavailable")
        fx = self.fixture().primary()
        with fx.open() as db:
            item = db.head("items", "itm_lem")
            text = r"$R\perp\!\!\perp S\mid X$, $\arg\min_x f(x)$, $\Bigl\lVert x\Bigr\rVert$; $x\!y$."
            fx.apply(db, [edit("replace", "items", item.id,
                              dict(item.body, statement={"form": "transcription", "text": text}), item.version)])
            projected = cli.build_projection(db, audit_id=fx.audit_id)
            before = db.all_versions()
            result = publish.publish_report(db, projection=projected, output=self.path("common-math.html"), release=False)
            self.assertEqual(before, db.all_versions())
            self.assertEqual(projected["summary"]["progress"],
                             cli.build_projection(db, audit_id=fx.audit_id)["summary"]["progress"])
            self.assertEqual(text, db.head("items", item.id).body["statement"]["text"])
            self.assertEqual("pass", result["receipt"]["python_acceptance"]["status"])
            groups = result["receipt"]["math_diagnostics"]["groups"]
            self.assertTrue(any("negative spacing" in row["reason"] for row in groups))


class ClosedPipeTests(TempCase):
    def test_write_and_flush_failures_keep_the_command_result_without_reemission(self):
        for stage in ("write", "flush"):
            for payload, code in (({}, 0), ({"exit_code": 3}, 3), (InvalidRequest("bad input"), 2)):
                with self.subTest(stage=stage, code=code):
                    stream = Mock()
                    getattr(stream, stage).side_effect = BrokenPipeError()
                    stream.fileno.return_value = 42
                    func = Mock(side_effect=payload) if isinstance(payload, Exception) else Mock(return_value=payload)
                    args = SimpleNamespace(command="work", func=func)
                    parser = Mock()
                    parser.parse_args.return_value = args
                    with patch.object(cli, "build_parser", return_value=parser), \
                         patch.object(cli.sys, "stdout", stream), patch.object(cli.sys, "stderr", io.StringIO()), \
                         patch.object(cli.os, "dup2") as redirect:
                        self.assertEqual(code, cli.main([]))
                    self.assertEqual(1, stream.write.call_count)
                    func.assert_called_once_with(args)
                    redirect.assert_called_once()

    def test_other_io_errors_are_not_hidden(self):
        stream = Mock()
        stream.write.side_effect = PermissionError("write denied")
        with patch.object(cli.sys, "stdout", stream), self.assertRaises(PermissionError):
            cli._emit({})

    def test_real_status_pipe_can_close_after_64_bytes(self):
        fx = self.fixture().primary()
        child = subprocess.Popen([sys.executable, "-B", "-m", "paper_core.cli", "status", str(fx.path)],
                                 env=CLI_ENV, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            self.assertEqual(64, len(child.stdout.read(64)))
            child.stdout.close()
            child.stdout = None
            _, stderr = child.communicate(timeout=30)
            self.assertEqual(0, child.returncode, stderr)
            self.assertEqual(b"", stderr)
        finally:
            if child.poll() is None:
                child.kill()
                child.communicate()


class MechanicalReceiptTests(TempCase):
    def test_get_receipt_count_and_preparation_deferrals_need_no_extra_query(self):
        fx = self.fixture().audit(independent_required=False)
        receipt, _ = run_cli("get", fx.path, "--target", "items:itm_lem", "--mode", "primary",
                             "--out", self.path("packet.json"))
        packet = json.loads(self.path("packet.json").read_text(encoding="utf-8"))
        self.assertEqual(len(packet["records"]), receipt["record_count"])
        self.assertEqual(receipt["records"], receipt["record_count"])
        prepared, _ = run_cli("work", "prepare", fx.path, "--audit", fx.audit_id,
                              "--mode", "primary", "--max-units", "1", "--out", self.path("assignment"))
        self.assertTrue(prepared["prepared"])
        self.assertTrue(prepared["deferred_reasons"])
        self.assertIn("Proceed", prepared["continuation_note"])
        self.assertEqual(2048, prepared["packet_limits"]["max_records"])

    def test_scope_error_distinguishes_wrong_version_from_missing_context_and_role(self):
        for mode in ("primary", "independent"):
            manifest = {"mode": mode, "read_set": [{"collection": "checks", "id": "chk_a", "version": 2}]}
            for ref, reason in (({"collection": "checks", "id": "chk_a", "version": 1}, "wrong_version"),
                                ({"collection": "anchors", "id": "anc_missing", "version": 1}, "missing_context")):
                with self.subTest(mode=mode, reason=reason), self.assertRaises(InvalidRequest) as caught:
                    controller._reference(ref, manifest, pinned=True, where="supersedes")
                error = caught.exception.to_json()["error"]
                self.assertEqual([ref], error["records"])
                self.assertEqual(reason, error["retry"]["reason"])
                self.assertEqual("supersedes", error["retry"]["field"])
                if reason == "wrong_version":
                    self.assertEqual([2], error["retry"]["available_versions"])
                elif mode == "independent":
                    self.assertIn("save a new response", error["retry"]["action"])


class DisplayDiagnosticTests(TempCase):
    def test_publication_notes_do_not_change_scientific_records_or_completion(self):
        if not node_available():
            self.skipTest("Node is unavailable")
        fx = self.fixture().primary()
        with fx.open() as db:
            item = db.head("items", "itm_lem")
            fx.apply(db, [edit("replace", "items", item.id,
                dict(item.body, statement={"form": "transcription", "text": r"$\private{x}$"}), item.version)])
            projection = cli.build_projection(db, audit_id=fx.audit_id)
            before = [(r.collection, r.id, r.version, r.body) for r in db.records_at(db.max_revision())]
            output = self.path("display-notes.html")
            result = publish.publish_report(db, projection=projection, output=output, release=False)
            after = [(r.collection, r.id, r.version, r.body) for r in db.records_at(db.max_revision())]
            current = cli.build_projection(db, audit_id=fx.audit_id)
        self.assertEqual(before, after)
        self.assertEqual(projection["summary"]["progress"], current["summary"]["progress"])
        notes = result["receipt"]["math_diagnostics"]
        self.assertGreater(notes["count"], 0)
        self.assertTrue(notes["nonblocking"])
        self.assertIn(b'id="proof-math-notes"', output.read_bytes())
        self.assertEqual("pass", result["receipt"]["python_acceptance"]["status"])

    def test_diagnostics_preserve_text_and_distinguish_converter_failure(self):
        for text, kind in ((r"$\private{x}$", "unsupported_expression"), ("open $x", "unmatched_delimiter"),
                           ("$\theta$", "damaged_escape"), (r"\\(x\\)", "damaged_escape")):
            with self.subTest(kind=kind):
                notes = []
                rendered = render_text(text, notes)
                self.assertIn("math-fallback", rendered)
                self.assertEqual(kind, notes[0]["kind"])
                self.assertEqual(text[text.index("$"):] if "$" in text and text.startswith("open") else text,
                                 notes[0]["excerpt"])
        notes = []
        _convert.cache_clear()
        with patch.dict(sys.modules, {"latex2mathml.converter": None}):
            render_text("$z_{converter}$", notes)
        _convert.cache_clear()
        self.assertEqual("converter_unavailable", notes[0]["kind"])
        notes = []
        self.assertNotIn("math-fallback", render_text(r"$\mathcal X$ and $\mathfrak S$", notes))
        render_text("ordinary prose", notes)
        self.assertEqual([], notes)

    def test_hundreds_of_fallbacks_have_bounded_samples_and_unchanged_record_fields(self):
        projection = {"records": [{"ref": {"collection": "items", "id": "itm_a", "version": 1},
                                  "body": {"statement": {"text": r"$\private{x}$ " * 600},
                                           "conditions": [r"$\private{x}$"]}}]}
        original = copy.deepcopy(projection)
        entries = []
        fragments = publish.display_fragments(projection, entries)
        self.assertEqual(original, projection)
        self.assertEqual(600, fragments["items:itm_a:1"]["statement_html"].count('class="math-fallback"'))
        summary = publish.summarize_math_diagnostics(entries)
        self.assertEqual(601, summary["count"])
        self.assertEqual(601, summary["groups"][0]["count"])
        self.assertTrue(summary["nonblocking"])
        self.assertLess(len(json.dumps(summary)), 1800)
        self.assertEqual({"statement.text", "conditions/0"}, {row["field"] for row in summary["groups"][0]["samples"]})
