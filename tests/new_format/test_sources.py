"""Behaviour of ``paper_core.sources``: capture, discovery, anchoring, and source review.

Every case drives the real public API against a throwaway database, so the assertions pin the
observable contract a caller depends on: the shapes the commands return, the record versions they
write, the exact error codes they raise, and the fact that a rejected command writes nothing.
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import support
from support import R, edit, locator, sha
from paper_core import acceptance, queries, sources, storage
from paper_core.errors import ConflictError, InvalidRequest, SourceUnavailable

# A second paper whose LaTeX exercises headings, titles, duplicate labels and a bare label.
ALT_TEX = "\n".join([
    r"\documentclass{article}",
    r"\newtheorem{prop}[theorem]{Proposition}",
    r"\begin{document}",
    r"\section{Intro}\label{sec:intro}",
    r"\begin{prop}[Nice bound]\label{prp:a}",
    r"Body.",
    r"\end{prop}",
    r"\begin{lemma}\label{dup}",
    r"One.",
    r"\end{lemma}",
    r"\begin{lemma}\label{dup}",
    r"Two.",
    r"\end{lemma}",
    r"\end{document}", ""])

# A root whose inputs cover every discovery outcome: resolved, dynamic, outside, missing, unsupported.
DISCOVERY_TEX = "\n".join([
    r"\documentclass{article}",
    r"\usepackage{mysty}",
    r"\input{sec/extra}",
    r"\input{\dynamic}",
    r"\input{../away}",
    r"\input{missing}",
    r"\include",
    r"\begin{document}\end{document}", ""])

COMMENTED_TEX = "\n".join([
    r"\documentclass{article}",
    r"\begin{document}",
    r"% \begin{lemma}\label{lem:hidden}",
    r"% Hidden.",
    r"% \end{lemma}",
    r"\begin{lemma}\label{lem:real}",
    r"Real.",
    r"\end{lemma}",
    r"\end{document}", ""])

# Declared environments whose kind comes from a shorthand rather than a heading word.
SHORTHAND_TEX = "\n".join([
    r"\documentclass{article}",
    r"\newtheorem{thm}{}",
    r"\declaretheorem{cor}",
    r"\declaretheorem{widget}",
    r"\begin{document}",
    r"\begin{thm}\label{t}", r"A.", r"\end{thm}",
    r"\begin{cor}\label{c}", r"B.", r"\end{cor}",
    r"\begin{widget}\label{w}", r"C.", r"\end{widget}",
    r"\begin{figure}\label{f}", r"D.", r"\end{figure}",
    r"\end{document}", ""])

CITATION_TEX = "\n".join([
    r"\cite{alpha, beta} \citep[see][p.~2]{gamma} \Citet{delta} \cite{alpha}",
    r"% \cite{commented}",
    r"\bibitem[Lab]{bk2} \bibitem{bk1}",
    r"@article{entry1, title={T}}", ""])


def mini_pdf(pages: int) -> bytes:
    """A minimal but structurally valid PDF with ``pages`` empty pages, built with a real xref table."""
    kids = " ".join(f"{3 + i} 0 R" for i in range(pages))
    objects = ["<</Type/Catalog/Pages 2 0 R>>", f"<</Type/Pages/Kids[{kids}]/Count {pages}>>"]
    objects += ["<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>"] * pages
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n{body}\nendobj\n".encode("ascii")
    start = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode("ascii") + b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode("ascii")
    out += f"trailer\n<</Size {len(objects) + 1}/Root 1 0 R>>\nstartxref\n{start}\n%%EOF\n".encode("ascii")
    return bytes(out)


TWO_PAGE_PDF = mini_pdf(2)
NO_PYPDF = sources.PdfReader is None


def build_paper(case, name, files, *, title="Alternate paper"):
    """Write ``files`` (relative path -> text or bytes) into a fresh root and initialize a database."""
    root = case.path(name, "src")
    root.mkdir(parents=True, exist_ok=True)
    for relative, content in files.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
    path = case.path(name, "paper.db")
    storage.initialize(path, source_root=root, title=title)
    return root, path


def rewrite(path, text) -> None:
    """Replace a source file with LF bytes, so line numbers and digests match on every platform."""
    path.write_bytes(text.encode("utf-8") if isinstance(text, str) else text)


def anchor_request(packet_id, request_id, entries):
    return {"contract_version": 3, "request_id": request_id, "packet_id": packet_id, "anchors": entries}


def anchor_entry(id, source_id, loc, expected=None):
    return {"id": id, "expected_version": expected, "source_id": source_id, "locator": loc}


class PureFunctions(unittest.TestCase):
    """``media_type``, ``uncomment``, ``declarations`` and ``citations`` are pure text functions."""

    def test_media_type_classifies_every_recognised_suffix(self):
        """Each known extension maps to its contract media_type and anything else is 'other'."""
        expected = {".tex": "tex", ".ltx": "tex", ".sty": "tex", ".cls": "tex", ".bib": "bib", ".bbl": "bib",
                    ".pdf": "pdf", ".txt": "text", ".md": "text", ".rst": "text",
                    ".png": "other", ".gz": "other", "": "other"}
        self.assertEqual({s: sources.media_type("paper" + s) for s in expected}, expected)

    def test_media_type_only_returns_values_the_contract_enum_allows(self):
        """Nothing classifies outside the sources.media_type enum, whatever the extension looks like."""
        allowed = {"tex", "bib", "pdf", "text", "other"}
        samples = ["a.tex", "a.PDF", "a.bbl", "a.md", "a.exe", "a", ".hidden", "a.tex.bak", "a.TXT"]
        self.assertEqual(set(sources.media_type(s) for s in samples) - allowed, set())
        self.assertEqual(set(sources.MEDIA_BY_SUFFIX.values()) - allowed, set())

    def test_media_type_is_case_insensitive_and_uses_only_the_final_suffix(self):
        """Classification reads the last suffix of the final path component, folded to lower case."""
        self.assertEqual(sources.media_type("REPORT.PDF"), "pdf")
        self.assertEqual(sources.media_type("Main.TeX"), "tex")
        self.assertEqual(sources.media_type("archive.tex.gz"), "other")
        self.assertEqual(sources.media_type("dir.bib/paper.tex"), "tex")
        self.assertEqual(sources.media_type("Makefile"), "other")

    def test_uncomment_drops_comments_but_keeps_every_newline(self):
        """Comment text disappears while the line count stays put, so line offsets still map."""
        text = "alpha % gone\nbeta\n%whole line\ngamma % tail"
        self.assertEqual(sources.uncomment(text), "alpha \nbeta\n\ngamma ")
        self.assertEqual(sources.uncomment("beta\n%one\n%two\ngamma"), "beta\n\n\ngamma")

    def test_uncomment_leaves_text_without_comments_untouched(self):
        """A source with no percent sign comes back byte for byte, including its trailing newline."""
        self.assertEqual(sources.uncomment(support.PAPER_TEX), support.PAPER_TEX)

    def test_uncomment_keeps_an_escaped_percent_sign(self):
        r"""A literal ``\%`` is content, not a comment, and only the unescaped one starts a comment."""
        self.assertEqual(sources.uncomment(r"50\% off % note"), "50\\% off ")
        self.assertEqual(sources.uncomment(r"\%"), "\\%")
        self.assertEqual(sources.uncomment(r"100\%\% done % note"), "100\\%\\% done ")

    # REGRESSION: uncomment() used to inspect only the single character before the percent sign, so
    # the second backslash of the TeX line-break macro "\\" masked a real comment and commented-out
    # markup reached _resolve_label and declarations as if it were live source. A "%" opens a comment
    # unless an odd number of backslashes precedes it, which is what the pattern now matches.
    def test_uncomment_drops_a_comment_after_a_tex_line_break(self):
        r"""A comment that follows the ``\\`` line-break macro is dropped like any other comment."""
        self.assertEqual(sources.uncomment("a \\\\% \\label{lem:ghost}\nb"), "a \\\\\nb")

    def test_declarations_reads_the_fixture_lemma_and_theorem(self):
        """The two-item fixture yields lemma lem:a on 5-7 with proof 8-10 and theorem thm:b on 11-13."""
        found = sources.declarations(support.PAPER_TEX)
        self.assertEqual([d["label"] for d in found], ["lem:a", "thm:b"])
        self.assertEqual(found[0], {"environment": "lemma", "kind": "lemma", "heading": "Lemma", "title": None,
                                    "label": "lem:a", "start_line": 5, "end_line": 7,
                                    "proof": {"start_line": 8, "end_line": 10}})
        self.assertEqual(found[1], {"environment": "theorem", "kind": "theorem", "heading": "Theorem", "title": None,
                                    "label": "thm:b", "start_line": 11, "end_line": 13,
                                    "proof": {"start_line": 14, "end_line": 16}})

    def test_declarations_only_attaches_a_proof_that_directly_follows(self):
        """A proof separated from its statement by other prose is not attached to that statement."""
        spaced = support.PAPER_TEX.replace("\\end{lemma}\n\\begin{proof}",
                                           "\\end{lemma}\nIntervening prose.\n\\begin{proof}")
        found = sources.declarations(spaced)
        self.assertEqual([(d["label"], d["proof"]) for d in found],
                         [("lem:a", None), ("thm:b", {"start_line": 15, "end_line": 17})])

    def test_declarations_uses_newtheorem_headings_and_bracket_titles(self):
        r"""A ``\newtheorem`` alias takes its declared heading and kind; ``[...]`` becomes the title."""
        found = {(d["label"], d["start_line"]): d for d in sources.declarations(ALT_TEX)}
        prop = found[("prp:a", 5)]
        self.assertEqual((prop["environment"], prop["heading"], prop["kind"]), ("prop", "Proposition", "proposition"))
        self.assertEqual((prop["title"], prop["end_line"], prop["proof"]), ("Nice bound", 7, None))
        self.assertEqual(sorted(k[1] for k in found if k[0] == "dup"), [8, 11])

    def test_declarations_falls_back_to_the_shorthand_kind_and_reports_none_when_unknown(self):
        r"""``thm``/``cor`` take their kind from the shorthand table; an unknown alias has kind None."""
        found = [(d["environment"], d["heading"], d["kind"], d["start_line"], d["end_line"])
                 for d in sources.declarations(SHORTHAND_TEX)]
        self.assertEqual(found, [("thm", "thm", "theorem", 6, 8), ("cor", "Cor", "corollary", 9, 11),
                                 ("widget", "Widget", None, 12, 14)])

    def test_declarations_ignores_environments_that_are_not_theorem_like(self):
        r"""A ``figure`` block is not declared as a theorem environment, so it is never reported."""
        self.assertNotIn("figure", [d["environment"] for d in sources.declarations(SHORTHAND_TEX)])
        self.assertEqual(sources.declarations("Just prose, no environments at all.\n"), [])

    def test_declarations_ignores_commented_out_environments(self):
        """A commented block is not a declaration; only the live lemma is reported."""
        found = sources.declarations(COMMENTED_TEX)
        self.assertEqual([(d["label"], d["start_line"], d["end_line"]) for d in found], [("lem:real", 6, 8)])

    def test_citations_collects_cite_keys_and_bibitems_from_tex(self):
        """Every cite variant contributes its keys once, commented citations do not, and keys are sorted."""
        self.assertEqual(sources.citations(CITATION_TEX, "tex"),
                         {"cite_keys": ["alpha", "beta", "delta", "gamma"], "bibitems": ["bk1", "bk2"],
                          "bib_entries": []})

    def test_citations_reads_bib_entries_only_for_bib_media(self):
        """``@type{key,`` entries are collected for bib sources and never for tex or text sources."""
        self.assertEqual(sources.citations(CITATION_TEX, "bib")["bib_entries"], ["entry1"])
        self.assertEqual(sources.citations(CITATION_TEX, "text")["bib_entries"], [])
        self.assertEqual(sources.citations(support.PAPER_TEX, "tex"),
                         {"cite_keys": [], "bibitems": [], "bib_entries": []})

    def test_citations_strips_comments_only_for_tex_media(self):
        """Non-tex media are scanned verbatim, so a percent-prefixed key is still a key there."""
        self.assertNotIn("commented", sources.citations(CITATION_TEX, "tex")["cite_keys"])
        self.assertIn("commented", sources.citations(CITATION_TEX, "text")["cite_keys"])


class Discovery(support.TempCase):
    """``discover`` resolves the listed files plus the literal local inputs they name."""

    def discovery_root(self):
        root, _ = build_paper(self, "disc", {
            "main.tex": DISCOVERY_TEX, "sec/extra.tex": "extra\n", "mysty.sty": "\\ProvidesPackage{mysty}\n"})
        rewrite(root.parent / "away.tex", "away\n")
        return root

    def test_discover_describes_each_listed_file(self):
        """A listed file is captured with its bytes, its sha256, method 'listed' and no limitation."""
        root = self.discovery_root()
        captured, _ = sources.discover(root, ["main.tex"])
        main = next(c for c in captured if c["path"] == "main.tex")
        self.assertEqual(sorted(main), ["bytes", "capture_method", "limitation", "media_type", "path", "sha256"])
        self.assertEqual(main["bytes"], DISCOVERY_TEX.encode("utf-8"))
        self.assertEqual(main["sha256"], sha(DISCOVERY_TEX.encode("utf-8")))
        self.assertEqual((main["media_type"], main["capture_method"], main["limitation"]), ("tex", "listed", None))

    def test_discover_follows_local_inputs_and_packages(self):
        """Resolved inputs and local style files join the capture as 'tex_input' with posix paths."""
        captured, _ = sources.discover(self.discovery_root(), ["main.tex"])
        self.assertEqual([(c["path"], c["capture_method"]) for c in captured],
                         [("main.tex", "listed"), ("sec/extra.tex", "tex_input"), ("mysty.sty", "tex_input")])

    def test_discover_resolves_an_input_against_the_compile_root_not_the_including_directory(self):
        r"""A file in a subdirectory resolves ``\input`` against the directory holding \documentclass."""
        root, _ = build_paper(self, "croot", {
            "main.tex": "\\documentclass{article}\n\\begin{document}\\end{document}\n",
            "sec/a.tex": "\\input{shared/defs}\n", "shared/defs.tex": "defs\n"})
        captured, notes = sources.discover(root, ["main.tex", "sec/a.tex"])
        self.assertEqual([(c["path"], c["capture_method"]) for c in captured],
                         [("main.tex", "listed"), ("sec/a.tex", "listed"), ("shared/defs.tex", "tex_input")])
        self.assertEqual(notes, [])

    def test_discover_also_resolves_an_input_relative_to_the_including_file(self):
        r"""When the compile root has no such file, the including file's own directory is tried."""
        root, _ = build_paper(self, "sibling", {
            "main.tex": "\\documentclass{article}\n\\input{sec/a}\n",
            "sec/a.tex": "\\input{local}\n", "sec/local.tex": "local\n"})
        captured, notes = sources.discover(root, ["main.tex"])
        self.assertEqual([c["path"] for c in captured], ["main.tex", "sec/a.tex", "sec/local.tex"])
        self.assertEqual(notes, [])

    def test_discover_notes_every_input_it_cannot_capture(self):
        """Dynamic, outside-root, missing and unsupported input forms each produce one note."""
        _, notes = sources.discover(self.discovery_root(), ["main.tex"])
        self.assertEqual(notes, [
            "main.tex: dynamic input '\\\\dynamic'; register the resolved source explicitly",
            "main.tex: input '../away' lies outside the source root; register it explicitly",
            "main.tex: unresolved input 'missing'; register or explain the missing source",
            "main.tex: an input form needs manual source registration"])

    def test_discover_captures_each_file_once(self):
        """A file that is both listed and input appears once, keeping its 'listed' capture method."""
        root, _ = build_paper(self, "once", {
            "main.tex": "\\documentclass{article}\n\\input{extra}\n\\input{extra.tex}\n", "extra.tex": "hi\n"})
        captured, notes = sources.discover(root, ["main.tex", "extra.tex"])
        self.assertEqual([(c["path"], c["capture_method"]) for c in captured],
                         [("main.tex", "listed"), ("extra.tex", "listed")])
        self.assertEqual(notes, [])

    def test_an_absolute_entry_inside_the_root_keeps_its_relative_path(self):
        """An absolute registration that lands inside the root is displayed relative and unlimited."""
        root = self.discovery_root()
        captured, _ = sources.discover(root, [str(root / "main.tex")])
        main = next(c for c in captured if c["media_type"] == "tex" and c["capture_method"] == "listed")
        self.assertEqual((main["path"], main["limitation"]), ("main.tex", None))

    def test_an_absolute_entry_outside_the_root_keeps_its_absolute_path_and_a_limitation(self):
        """An explicit registration outside the root is captured, but flagged so a reader can see it."""
        root = self.discovery_root()
        away = (root.parent / "away.tex").resolve()
        captured, _ = sources.discover(root, ["main.tex", str(away)])
        entry = next(c for c in captured if c["path"] == away.as_posix())
        self.assertEqual(entry["limitation"], "registered by absolute path outside the source root")
        self.assertEqual((entry["capture_method"], entry["bytes"]), ("listed", b"away\n"))

    def test_discover_rejects_a_path_that_escapes_the_source_root(self):
        """A relative entry resolving outside the registered root is refused as an invalid request."""
        with self.assertRaises(InvalidRequest) as caught:
            sources.discover(self.discovery_root(), ["../away.tex"])
        self.assertEqual(str(caught.exception), "path '../away.tex' escapes the registered source root")
        self.assertEqual(caught.exception.code, "INVALID_REQUEST")

    def test_discover_rejects_a_file_list_that_is_not_nonempty_strings(self):
        """The file list must be a nonempty array of nonblank path strings."""
        root = self.discovery_root()
        for bad in ([], "main.tex", [""], ["  "], [None], None, ["main.tex", ""]):
            with self.subTest(files=bad):
                with self.assertRaises(InvalidRequest) as caught:
                    sources.discover(root, bad)
                self.assertEqual(str(caught.exception), "LIST.json must be a nonempty array of path strings")

    def test_discover_fails_when_a_named_file_is_missing(self):
        """A listed path with no readable file raises SOURCE_UNAVAILABLE naming the path."""
        root = self.discovery_root()
        with self.assertRaises(SourceUnavailable) as caught:
            sources.discover(root, ["chapters/absent.tex"])
        self.assertEqual(caught.exception.code, "SOURCE_UNAVAILABLE")
        self.assertIn("chapters/absent.tex: not a readable file", str(caught.exception))

    def test_discover_fails_when_a_named_path_is_a_directory(self):
        """A directory is not a readable file, so listing one is SOURCE_UNAVAILABLE, never an empty capture."""
        root = self.discovery_root()
        with self.assertRaises(SourceUnavailable) as caught:
            sources.discover(root, ["sec"])
        self.assertEqual(caught.exception.code, "SOURCE_UNAVAILABLE")
        self.assertIn("not a readable file", str(caught.exception))

    def test_discover_fails_when_the_root_is_not_a_directory(self):
        """A source root that is absent (or a file) raises SOURCE_UNAVAILABLE before any read."""
        root = self.discovery_root()
        for bad in (root / "nowhere", root / "main.tex"):
            with self.subTest(root=bad.name):
                with self.assertRaises(SourceUnavailable) as caught:
                    sources.discover(bad, ["main.tex"])
                self.assertEqual(caught.exception.code, "SOURCE_UNAVAILABLE")
                self.assertIn("registered source root is not a directory", str(caught.exception))


class Capture(support.TempCase):
    """``capture_sources`` records source versions only when the bytes on disk changed."""

    def test_capture_returns_the_documented_shape_and_stores_the_blob(self):
        """The first capture creates one source at version 1 and stores its bytes as a blob."""
        fx = self.fixture()
        with fx.open() as db:
            result = sources.capture_sources(db, files=["paper.tex"])
            self.assertEqual(sorted(result),
                             ["changed", "citations", "declarations", "limitations", "receipt", "sources"])
            self.assertIs(result["changed"], True)
            self.assertEqual(len(result["sources"]), 1)
            listed = result["sources"][0]
            self.assertEqual(sorted(listed), ["blob_sha256", "changed", "id", "media_type", "path", "version"])
            self.assertEqual((listed["path"], listed["media_type"], listed["version"], listed["changed"]),
                             ("paper.tex", "tex", 1, True))
            on_disk = (fx.source_root / "paper.tex").read_bytes()
            self.assertEqual(listed["blob_sha256"], sha(on_disk))
            self.assertEqual(result["receipt"]["changed"],
                             [{"collection": "sources", "id": listed["id"], "version": 1, "op": "create"}])
            self.assertEqual(result["receipt"]["warnings"], [])
            record = db.head("sources", listed["id"])
            self.assertEqual(record.body, {"paper_id": fx.paper_id, "path": "paper.tex", "media_type": "tex",
                                           "blob_sha256": listed["blob_sha256"], "capture_method": "listed",
                                           "limitation": None})
            self.assertEqual(db.get_blob(listed["blob_sha256"]), on_disk)

    def test_capture_reports_declarations_and_citations_against_the_source_id(self):
        """Declarations carry their source id and path; a paper with no citations reports none."""
        fx = self.fixture()
        with fx.open() as db:
            result = sources.capture_sources(db, files=["paper.tex"])
            source_id = result["sources"][0]["id"]
            self.assertEqual([(d["source_id"], d["path"], d["label"], d["start_line"])
                              for d in result["declarations"]],
                             [(source_id, "paper.tex", "lem:a", 5), (source_id, "paper.tex", "thm:b", 11)])
            self.assertEqual(result["citations"], [])
            self.assertEqual(result["limitations"], [])

    def test_capture_carries_discovery_notes_into_the_receipt_warnings(self):
        """An input the capture could not resolve is a receipt warning as well as a reported limitation."""
        _, path = build_paper(self, "warn", {
            "main.tex": "\\documentclass{article}\n\\input{gone}\n\\begin{document}\\end{document}\n"})
        note = "main.tex: unresolved input 'gone'; register or explain the missing source"
        with storage.Database(path, write=True) as db:
            result = sources.capture_sources(db, files=["main.tex"])
            self.assertEqual(result["receipt"]["warnings"], [note])
            self.assertEqual(result["limitations"], [note])

    def test_capture_records_each_media_type_and_its_citation_scan(self):
        """A bib companion is captured as its own source and contributes bib_entries, not cite keys."""
        _, path = build_paper(self, "multi", {
            "main.tex": "\\documentclass{article}\n\\begin{document}\\cite{k1}\\end{document}\n",
            "refs.bib": "@article{k1, title={A}}\n"})
        with storage.Database(path, write=True) as db:
            result = sources.capture_sources(db, files=["main.tex", "refs.bib"])
            self.assertEqual([(s["path"], s["media_type"], s["version"]) for s in result["sources"]],
                             [("main.tex", "tex", 1), ("refs.bib", "bib", 1)])
            self.assertEqual([(c["path"], c["cite_keys"], c["bib_entries"]) for c in result["citations"]],
                             [("main.tex", ["k1"], []), ("refs.bib", [], ["k1"])])

    def test_recapture_rewrites_only_the_file_whose_bytes_moved(self):
        """In a mixed capture the untouched file keeps version 1 and only the edited one is rewritten."""
        root, path = build_paper(self, "mixed", {
            "main.tex": "\\documentclass{article}\n\\begin{document}\\end{document}\n",
            "refs.bib": "@article{k1, title={A}}\n"})
        with storage.Database(path, write=True) as db:
            first = sources.capture_sources(db, files=["main.tex", "refs.bib"])
            ids = {s["path"]: s["id"] for s in first["sources"]}
            rewrite(root / "refs.bib", "@article{k1, title={A}}\n@book{k2, title={B}}\n")
            second = sources.capture_sources(db, files=["main.tex", "refs.bib"])
            self.assertEqual([(s["path"], s["version"], s["changed"]) for s in second["sources"]],
                             [("main.tex", 1, False), ("refs.bib", 2, True)])
            self.assertEqual(second["receipt"]["changed"],
                             [{"collection": "sources", "id": ids["refs.bib"], "version": 2, "op": "replace"}])
            self.assertEqual(db.head("sources", ids["main.tex"]).version, 1)

    def test_recapture_of_unchanged_files_writes_nothing(self):
        """A second capture of identical bytes returns no receipt and commits no revision."""
        fx = self.fixture().capture()
        with fx.open() as db:
            before = db.max_revision()
            head = db.head("sources", fx.source_id)
            result = sources.capture_sources(db, files=["paper.tex"])
            self.assertIsNone(result["receipt"])
            self.assertIs(result["changed"], False)
            self.assertEqual(result["sources"], [{"id": fx.source_id, "version": 1, "path": "paper.tex",
                                                  "media_type": "tex", "blob_sha256": head.body["blob_sha256"],
                                                  "changed": False}])
            self.assertEqual(db.max_revision(), before)
            self.assertEqual(db.head("sources", fx.source_id).version, 1)

    def test_a_file_edited_on_disk_is_captured_as_a_new_version(self):
        """Changed bytes become source version 2; version 1 and its blob stay readable."""
        fx = self.fixture().capture()
        original = (fx.source_root / "paper.tex").read_bytes()
        edited = original.replace(b"By induction on $n$.", b"By induction on $n$, carefully.")
        self.assertNotEqual(edited, original)
        rewrite(fx.source_root / "paper.tex", edited)
        with fx.open() as db:
            first = db.head("sources", fx.source_id).body["blob_sha256"]
            result = sources.capture_sources(db, files=["paper.tex"])
            self.assertIs(result["changed"], True)
            self.assertEqual(result["sources"], [{"id": fx.source_id, "version": 2, "path": "paper.tex",
                                                  "media_type": "tex", "blob_sha256": sha(edited),
                                                  "changed": True}])
            self.assertEqual(db.head("sources", fx.source_id).version, 2)
            self.assertEqual(db.version("sources", fx.source_id, 1).body["blob_sha256"], first)
            self.assertEqual(first, sha(original))
            self.assertEqual(db.get_blob(first), original)
            self.assertEqual(db.get_blob(sha(edited)), edited)

    def test_capture_reports_pdf_encoding_and_outside_root_limitations(self):
        """Each capture limitation the contract names is reported once, keyed by the source path."""
        root, path = build_paper(self, "limits", {
            "main.tex": "\\documentclass{article}\n\\begin{document}\\end{document}\n",
            "broken.tex": b"\\documentclass{article}\n\\begin{lemma}\xff\xfe\n\\end{lemma}\n",
            "figure.pdf": TWO_PAGE_PDF})
        outside = self.path("limits", "away.tex")
        rewrite(outside, "Prose with no environments.\n")
        with storage.Database(path, write=True) as db:
            result = sources.capture_sources(db, files=["main.tex", "broken.tex", "figure.pdf", str(outside)])
            away = outside.resolve().as_posix()
            self.assertEqual(result["limitations"], [
                "broken.tex: source discovery requires UTF-8; register relevant inputs explicitly",
                "broken.tex: not UTF-8 text; declarations and citations were not scanned",
                "figure.pdf: PDF sources anchor by reviewed page; text extraction is approximate",
                f"{away}: registered by absolute path outside the source root"])
            bodies = {s.body["path"]: s.body for s in db.heads("sources")}
            self.assertEqual(bodies[away]["limitation"], "registered by absolute path outside the source root")
            self.assertEqual(bodies["figure.pdf"]["media_type"], "pdf")
            self.assertIsNone(bodies["main.tex"]["limitation"])
            self.assertEqual(result["declarations"], [])
            broken = (root / "broken.tex").read_bytes()
            self.assertEqual(bodies["broken.tex"]["blob_sha256"], sha(broken))
            self.assertEqual(db.get_blob(sha(broken)), broken)

    def test_capture_needs_a_writable_database(self):
        """A read-only handle is refused before any discovery work."""
        fx = self.fixture().capture()
        with fx.open(write=False) as db:
            with self.assertRaises(InvalidRequest) as caught:
                sources.capture_sources(db, files=["paper.tex"])
            self.assertEqual(str(caught.exception), "source capture needs a writable database")

    def test_capture_fails_and_writes_nothing_when_a_file_disappeared(self):
        """Losing a previously captured file is SOURCE_UNAVAILABLE; the recorded version survives."""
        fx = self.fixture().capture()
        (fx.source_root / "paper.tex").unlink()
        with fx.open() as db:
            revision = db.max_revision()
            with self.assertRaises(SourceUnavailable):
                sources.capture_sources(db, files=["paper.tex"])
            self.assertEqual(db.max_revision(), revision)
            self.assertEqual(db.head("sources", fx.source_id).version, 1)

    def test_capture_fails_and_writes_nothing_when_the_root_disappeared(self):
        """A missing registered root is SOURCE_UNAVAILABLE and leaves the database untouched."""
        fx = self.fixture().capture()
        support.rmtree_force(fx.source_root)
        with fx.open() as db:
            revision = db.max_revision()
            with self.assertRaises(SourceUnavailable) as caught:
                sources.capture_sources(db, files=["paper.tex"])
            self.assertIn("registered source root is not a directory", str(caught.exception))
            self.assertEqual(db.max_revision(), revision)

    def test_a_second_file_that_cannot_be_read_aborts_the_whole_capture(self):
        """One unreadable entry stops the batch: the readable file beside it is not recorded either."""
        _, path = build_paper(self, "atomic", {
            "main.tex": "\\documentclass{article}\n\\begin{document}\\end{document}\n"})
        with storage.Database(path, write=True) as db:
            revision = db.max_revision()
            with self.assertRaises(SourceUnavailable):
                sources.capture_sources(db, files=["main.tex", "absent.tex"])
            self.assertEqual(db.max_revision(), revision)
            self.assertEqual(list(db.heads("sources")), [])


class SourceContextChange(support.TempCase):
    """A source file that moves under a recorded audit is detected, not silently accepted."""

    def test_recapturing_a_changed_file_moves_the_status_context_digest(self):
        """The source-context digest is a function of the live source versions and their blobs."""
        fx = self.fixture().structure()
        with fx.open() as db:
            before = queries.status(db)["context"]["source_context_digest"]
        rewrite(fx.source_root / "paper.tex", "% shifted\n" + support.PAPER_TEX)
        with fx.open() as db:
            sources.capture_sources(db, files=["paper.tex"])
            status = queries.status(db)
            self.assertNotEqual(status["context"]["source_context_digest"], before)
            self.assertEqual(status["sources"]["context_digest"], status["context"]["source_context_digest"])
            self.assertEqual(db.head("sources", fx.source_id).version, 2)

    def test_a_source_change_invalidates_packets_minted_before_it(self):
        """A batch on a pre-change packet is a CONFLICT flagged as source_context_changed, not a write."""
        fx = self.fixture().structure()
        with fx.open() as db:
            stale = fx.packet(db)
            before_digest = queries.status(db)["context"]["source_context_digest"]
            rewrite(fx.source_root / "paper.tex", "% shifted\n" + support.PAPER_TEX)
            sources.capture_sources(db, files=["paper.tex"])
            revision = db.max_revision()
            self.assertNotEqual(queries.status(db)["context"]["source_context_digest"], before_digest)
            batch = fx.batch([edit("create", "scopes", "scp_late", {
                "argument_id": None, "parent_id": None, "assumptions": [], "binders": [], "conditions": [],
                "evidence_refs": []})], stale["packet_id"])
            with self.assertRaises(ConflictError) as caught:
                acceptance.apply_batch(db, batch)
            self.assertEqual(caught.exception.code, "CONFLICT")
            self.assertIs(caught.exception.records[0]["source_context_changed"], True)
            self.assertEqual(caught.exception.retry["mode"], "author")
            self.assertEqual(db.max_revision(), revision)
            self.assertIsNone(db.head("scopes", "scp_late"))

    def test_a_packet_minted_after_the_change_accepts_the_same_batch(self):
        """The conflict is about the stale context, not the edit: a fresh packet commits it."""
        fx = self.fixture().structure()
        rewrite(fx.source_root / "paper.tex", "% shifted\n" + support.PAPER_TEX)
        with fx.open() as db:
            sources.capture_sources(db, files=["paper.tex"])
            receipt = fx.apply(db, [edit("create", "scopes", "scp_late", {
                "argument_id": None, "parent_id": None, "assumptions": [], "binders": [], "conditions": [],
                "evidence_refs": []})])
            self.assertEqual(receipt["changed"],
                             [{"collection": "scopes", "id": "scp_late", "version": 1, "op": "create"}])
            self.assertEqual(db.head("scopes", "scp_late").version, 1)

    # REGRESSION: judgment_freshness used to read the stored context digest off the
    # {"packet_id", "bindings"} wrapper Database.binding() returns instead of off the binding itself,
    # so context_changed could never become True and judgments_in_older_context was stuck at zero for
    # every database. The digest is now read from the same unwrapped binding binding_changes gets.
    def test_judgments_bound_before_a_source_change_report_an_older_context(self):
        """Recapturing a changed source puts every previously bound judgment in an older context."""
        fx = self.fixture().complete()
        rewrite(fx.source_root / "paper.tex", "% shifted\n" + support.PAPER_TEX)
        with fx.open() as db:
            bound = db.binding("checks", "chk_comp_lem", 1)["bindings"]["source_context_digest"]
            sources.capture_sources(db, files=["paper.tex"])
            status = queries.status(db)
            self.assertNotEqual(status["context"]["source_context_digest"], bound)
            self.assertEqual(status["context"]["judgments_in_older_context"], len(db.heads("checks")))


class AnchorResolution(support.TempCase):
    """``resolve_anchor`` extracts one excerpt and names the method that produced it."""

    def alt_source(self):
        """An initialized database over ALT_TEX plus a two-page PDF; returns (db, sources-by-path)."""
        _, path = build_paper(self, "anch", {"main.tex": ALT_TEX, "figure.pdf": TWO_PAGE_PDF,
                                             "broken.tex": b"\\documentclass{a}\n\xff\xfe\n"})
        db = storage.Database(path, write=True)
        self.addCleanup(db.close)
        sources.capture_sources(db, files=["main.tex", "figure.pdf", "broken.tex"])
        return db, {s.body["path"]: s for s in db.heads("sources")}

    def test_a_label_locator_resolves_to_its_environment(self):
        """A label anchors the whole enclosing environment and reports method 'label_match'."""
        db, by_path = self.alt_source()
        resolved = sources.resolve_anchor(db, by_path["main.tex"], locator(label="prp:a"))
        self.assertEqual(resolved["method"], "label_match")
        self.assertEqual(resolved["locator"], {"start_line": 5, "end_line": 7, "page": None, "label": "prp:a"})
        self.assertEqual(resolved["excerpt"], "\\begin{prop}[Nice bound]\\label{prp:a}\nBody.\n\\end{prop}")
        self.assertEqual(resolved["excerpt_sha256"], sha(resolved["excerpt"].encode("utf-8")))
        self.assertEqual((resolved["source_id"], resolved["source_version"], resolved["limitation"]),
                         (by_path["main.tex"].id, 1, None))

    def test_a_line_locator_keeps_the_range_it_was_given(self):
        """Explicit lines are taken verbatim and reported as 'exact_lines'."""
        db, by_path = self.alt_source()
        resolved = sources.resolve_anchor(db, by_path["main.tex"], locator(start=8, end=10))
        self.assertEqual(resolved["method"], "exact_lines")
        self.assertEqual(resolved["locator"], {"start_line": 8, "end_line": 10, "page": None, "label": None})
        self.assertEqual(resolved["excerpt"], "\\begin{lemma}\\label{dup}\nOne.\n\\end{lemma}")

    def test_a_single_line_locator_extracts_exactly_that_line(self):
        """A one-line range yields that line alone, with no separator and no neighbouring text."""
        db, by_path = self.alt_source()
        resolved = sources.resolve_anchor(db, by_path["main.tex"], locator(start=6, end=6))
        self.assertEqual(resolved["excerpt"], "Body.")
        self.assertEqual(resolved["excerpt_sha256"], sha(b"Body."))

    def test_a_label_given_with_lines_is_verified_inside_the_range(self):
        """Lines plus a label stay 'exact_lines' and the excerpt is the named range, not the environment."""
        db, by_path = self.alt_source()
        resolved = sources.resolve_anchor(db, by_path["main.tex"], locator(start=5, end=6, label="prp:a"))
        self.assertEqual(resolved["method"], "exact_lines")
        self.assertEqual(resolved["locator"], {"start_line": 5, "end_line": 6, "page": None, "label": "prp:a"})
        self.assertEqual(resolved["excerpt"], "\\begin{prop}[Nice bound]\\label{prp:a}\nBody.")

    def test_a_label_outside_the_named_range_is_rejected(self):
        """LABEL_NOT_IN_RANGE guards a locator whose lines and label disagree."""
        db, by_path = self.alt_source()
        with self.assertRaises(InvalidRequest) as caught:
            sources.resolve_anchor(db, by_path["main.tex"], locator(start=8, end=10, label="prp:a"))
        self.assertEqual(caught.exception.code, "LABEL_NOT_IN_RANGE")
        self.assertEqual(str(caught.exception), "label 'prp:a' does not occur within lines 8-10")

    def test_an_unknown_label_is_reported_as_label_not_found(self):
        """A label that never occurs raises LABEL_NOT_FOUND rather than guessing a range."""
        db, by_path = self.alt_source()
        with self.assertRaises(InvalidRequest) as caught:
            sources.resolve_anchor(db, by_path["main.tex"], locator(label="lem:absent"))
        self.assertEqual(caught.exception.code, "LABEL_NOT_FOUND")
        self.assertEqual(str(caught.exception), "label 'lem:absent' does not occur in the source")

    def test_a_commented_out_label_does_not_resolve(self):
        """A label hidden behind a TeX comment is not live source, so it cannot be anchored."""
        _, path = build_paper(self, "hidden", {"main.tex": COMMENTED_TEX})
        with storage.Database(path, write=True) as db:
            sources.capture_sources(db, files=["main.tex"])
            source = db.heads("sources")[0]
            with self.assertRaises(InvalidRequest) as caught:
                sources.resolve_anchor(db, source, locator(label="lem:hidden"))
            self.assertEqual(caught.exception.code, "LABEL_NOT_FOUND")
            live = sources.resolve_anchor(db, source, locator(label="lem:real"))
            self.assertEqual((live["locator"]["start_line"], live["locator"]["end_line"]), (6, 8))

    def test_a_duplicated_label_is_reported_with_its_line_numbers(self):
        """AMBIGUOUS_LABEL carries every line the label occurs on so a reviewer can disambiguate."""
        db, by_path = self.alt_source()
        with self.assertRaises(InvalidRequest) as caught:
            sources.resolve_anchor(db, by_path["main.tex"], locator(label="dup"))
        self.assertEqual(caught.exception.code, "AMBIGUOUS_LABEL")
        self.assertEqual(caught.exception.records, [8, 11])
        self.assertIn("occurs 2 times", str(caught.exception))

    def test_a_line_range_past_the_end_of_the_file_is_rejected(self):
        """LINES_OUT_OF_RANGE names the real length instead of silently truncating the excerpt."""
        db, by_path = self.alt_source()
        with self.assertRaises(InvalidRequest) as caught:
            sources.resolve_anchor(db, by_path["main.tex"], locator(start=13, end=99))
        self.assertEqual(caught.exception.code, "LINES_OUT_OF_RANGE")
        self.assertEqual(str(caught.exception),
                         "lines 13-99 exceed the source (14 lines); re-anchor this passage")

    def test_the_last_line_of_the_file_is_still_in_range(self):
        """The boundary is inclusive: the final line resolves, one line past it does not."""
        db, by_path = self.alt_source()
        resolved = sources.resolve_anchor(db, by_path["main.tex"], locator(start=14, end=14))
        self.assertEqual(resolved["excerpt"], "\\end{document}")
        with self.assertRaises(InvalidRequest) as caught:
            sources.resolve_anchor(db, by_path["main.tex"], locator(start=14, end=15))
        self.assertEqual(caught.exception.code, "LINES_OUT_OF_RANGE")

    def test_a_label_outside_any_environment_anchors_one_line_with_a_limitation(self):
        """A bare label anchors only its own line and says so in the anchor's limitation."""
        db, by_path = self.alt_source()
        resolved = sources.resolve_anchor(db, by_path["main.tex"], locator(label="sec:intro"))
        self.assertEqual(resolved["locator"]["start_line"], resolved["locator"]["end_line"])
        self.assertEqual(resolved["locator"]["start_line"], 4)
        self.assertEqual(resolved["excerpt"], "\\section{Intro}\\label{sec:intro}")
        self.assertEqual(resolved["limitation"],
                         "label is not inside an environment; anchored to the label line only")

    def test_re_resolving_an_unchanged_anchor_keeps_its_original_method(self):
        """``exact_relocation`` is reserved for a move: an identical re-resolution stays 'label_match'."""
        db, by_path = self.alt_source()
        source = by_path["main.tex"]
        first = sources.resolve_anchor(db, source, locator(label="prp:a"))

        class Prior:
            body = first
        again = sources.resolve_anchor(db, source, locator(label="prp:a"), Prior)
        self.assertEqual(again["method"], "label_match")
        self.assertEqual(again["excerpt_sha256"], first["excerpt_sha256"])

    def test_the_same_excerpt_reached_by_a_different_locator_is_a_relocation(self):
        """Identical excerpt bytes plus a changed locator record 'exact_relocation', not 'exact_lines'."""
        db, by_path = self.alt_source()
        source = by_path["main.tex"]
        first = sources.resolve_anchor(db, source, locator(label="prp:a"))

        class Prior:
            body = first
        moved = sources.resolve_anchor(db, source, locator(start=5, end=7), Prior)
        self.assertEqual(moved["method"], "exact_relocation")
        self.assertEqual(moved["excerpt_sha256"], first["excerpt_sha256"])
        self.assertEqual(moved["locator"]["label"], None)

    def test_page_and_line_locators_must_match_the_media(self):
        """Pages belong to PDFs, lines to text, and the two locator forms never combine."""
        db, by_path = self.alt_source()
        cases = [(by_path["main.tex"], locator(page=1), "page locators require a PDF source"),
                 (by_path["figure.pdf"], locator(start=1, end=1), "PDF sources anchor by page"),
                 (by_path["figure.pdf"], locator(page=1, start=1, end=1),
                  "a page locator cannot combine with line numbers")]
        for source, loc, message in cases:
            with self.subTest(message=message):
                with self.assertRaises(InvalidRequest) as caught:
                    sources.resolve_anchor(db, source, loc)
                self.assertEqual(str(caught.exception), message)

    @unittest.skipIf(NO_PYPDF, "pypdf is not installed, so page extraction cannot be exercised")
    def test_a_page_locator_on_a_pdf_records_a_reviewed_page(self):
        """A PDF page anchors by review: method 'reviewed_page' plus the extraction limitation."""
        db, by_path = self.alt_source()
        resolved = sources.resolve_anchor(db, by_path["figure.pdf"], locator(page=2))
        self.assertEqual(resolved["method"], "reviewed_page")
        self.assertEqual(resolved["locator"], {"start_line": None, "end_line": None, "page": 2, "label": None})
        self.assertIn("figure.pdf, physical PDF page 2", resolved["limitation"])
        self.assertIn("compare important formulas", resolved["limitation"])
        self.assertNotIn("reviewed by a person", resolved["limitation"])
        self.assertEqual(resolved["excerpt_sha256"], sha(resolved["excerpt"].encode("utf-8")))

    def test_damaged_pdf_text_retains_the_source_and_reports_unrecovered_glyphs(self):
        db, by_path = self.alt_source()
        source = by_path['figure.pdf']
        raw = db.get_blob(source.body['blob_sha256'])
        page = Mock(extract_text=Mock(return_value='x\x00y\x10z\n\r\t'))
        with patch.object(sources, 'PdfReader', return_value=SimpleNamespace(pages=[page])):
            resolved = sources.resolve_anchor(db, source, locator(page=1))
        self.assertEqual(resolved['excerpt'], 'x\ufffdy\ufffdz\n\r\t')
        self.assertEqual(resolved['excerpt_sha256'], sha(resolved['excerpt'].encode('utf-8')))
        self.assertIn('2 unsupported control character(s)', resolved['limitation'])
        self.assertIn('figure.pdf, physical PDF page 1', resolved['limitation'])
        self.assertNotIn('reviewed by a person', resolved['limitation'])
        self.assertEqual(db.get_blob(source.body['blob_sha256']), raw)
        self.assertEqual(db.heads('source_reviews'), [])

    @unittest.skipIf(NO_PYPDF, "pypdf is not installed, so the page count cannot be read")
    def test_a_page_past_the_end_of_the_pdf_is_rejected(self):
        """PAGE_OUT_OF_RANGE names the real page count rather than anchoring an empty excerpt."""
        db, by_path = self.alt_source()
        with self.assertRaises(InvalidRequest) as caught:
            sources.resolve_anchor(db, by_path["figure.pdf"], locator(page=3))
        self.assertEqual(caught.exception.code, "PAGE_OUT_OF_RANGE")
        self.assertEqual(str(caught.exception), "page 3 exceeds the PDF (2 pages)")

    def test_a_non_utf8_source_cannot_serve_line_anchors(self):
        """Undecodable bytes are refused explicitly instead of anchoring mojibake."""
        db, by_path = self.alt_source()
        with self.assertRaises(InvalidRequest) as caught:
            sources.resolve_anchor(db, by_path["broken.tex"], locator(start=1, end=1))
        self.assertIn("is not UTF-8 text; line anchors need text", str(caught.exception))


class SourceDiagnosticTests(support.TempCase):
    def diagnostic_fixture(self):
        fx = self.fixture().primary()
        (fx.source_root / "supplement.pdf").write_bytes(TWO_PAGE_PDF)
        with fx.open() as db:
            captured = sources.capture_sources(db, files=["supplement.pdf"])
            source_id = captured["sources"][0]["id"]
            pages = [Mock(extract_text=Mock(return_value=text)) for text in ("a\x00b\x10c", "Clean source text.")]
            packet = fx.packet(db)
            with patch.object(sources, "PdfReader", return_value=SimpleNamespace(pages=pages)):
                sources.anchor_sources(db, request={"contract_version": 4, "request_id": fx.request_id(),
                    "packet_id": packet["packet_id"], "anchors": [
                        {"id": f"anc_pdf_{page}", "expected_version": None, "source_id": source_id,
                         "locator": locator(page=page)} for page in (1, 2)]})
            item, use = db.head("items", "itm_lem"), db.head("uses", "use_lem_thm")
            fx.apply(db, [edit("replace", "items", item.id,
                              dict(item.body, passages=item.body["passages"] +
                                   [{"role": "evidence", "anchor_id": "anc_pdf_1"}]), item.version),
                          edit("replace", "uses", use.id, dict(use.body, evidence_refs=["anc_pdf_1"]), use.version)])
        return fx, source_id

    def test_degraded_filter_reports_shared_owners_and_captured_source_without_mutation(self):
        fx, source_id = self.diagnostic_fixture()
        with fx.open(write=False) as db:
            before = db.all_versions()
            assessment = queries.status(db, audit_id=fx.audit_id)
            result = sources.source_diagnostics(db, degraded=True)
            self.assertEqual(before, db.all_versions())
            self.assertEqual(assessment, queries.status(db, audit_id=fx.audit_id))
        self.assertEqual(2, result["pdf_anchor_count"])
        self.assertEqual(1, result["degraded_anchor_count"])
        self.assertEqual(1, result["returned_anchor_count"])
        row = result["anchors"][0]
        self.assertEqual("supplement.pdf", row["file"])
        self.assertEqual({"collection": "sources", "id": source_id, "version": 1}, row["source_ref"])
        self.assertEqual(1, row["locator"]["page"])
        self.assertEqual(2, row["replacement_count"])
        self.assertIn("Missing glyph meanings were not recovered", row["extraction_note"])
        self.assertEqual({("items", "itm_lem"), ("uses", "use_lem_thm")},
                         {(r["collection"], r["id"]) for r in row["targets"]})
        self.assertNotIn("excerpt", row)

    def test_cli_is_read_only_and_all_anchors_includes_clean_pages(self):
        fx, _ = self.diagnostic_fixture()
        original = fx.path.read_bytes()
        result, stderr = support.run_cli("source", "diagnostics", fx.path)
        self.assertEqual("", stderr)
        self.assertEqual(2, result["returned_anchor_count"])
        self.assertEqual([2, 0], [row["replacement_count"] for row in result["anchors"]])
        filtered, _ = support.run_cli("source", "diagnostics", fx.path, "--degraded")
        self.assertEqual(1, filtered["returned_anchor_count"])
        self.assertEqual(original, fx.path.read_bytes())

    def test_recapture_keeps_the_anchor_bound_to_its_actual_source_version(self):
        fx, source_id = self.diagnostic_fixture()
        with fx.open() as db:
            (fx.source_root / "supplement.pdf").write_bytes(TWO_PAGE_PDF + b"\n% later capture\n")
            sources.capture_sources(db, files=["supplement.pdf"])
            self.assertEqual(2, db.head("sources", source_id).version)
            row = sources.source_diagnostics(db, degraded=True)["anchors"][0]
            self.assertEqual(1, row["source_ref"]["version"])

    def test_unreferenced_damage_is_visible_without_rewriting_a_focused_assessment(self):
        fx, _ = self.diagnostic_fixture()
        with fx.open() as db:
            item, use = db.head("items", "itm_lem"), db.head("uses", "use_lem_thm")
            fx.apply(db, [edit("replace", "items", item.id, dict(item.body,
                passages=[p for p in item.body["passages"] if p["anchor_id"] != "anc_pdf_1"]), item.version),
                edit("replace", "uses", use.id, dict(use.body, evidence_refs=["anc_thm_proof"]), use.version)])
            before = queries.status(db, audit_id=fx.audit_id)
            self.assertEqual([], sources.source_diagnostics(db, degraded=True)["anchors"][0]["targets"])
            self.assertEqual(before, queries.status(db, audit_id=fx.audit_id))

    def test_non_pdf_anchors_are_not_classified_as_pdf_damage(self):
        fx = self.fixture().structure()
        with fx.open(write=False) as db:
            result = sources.source_diagnostics(db, degraded=True)
            self.assertEqual([], result["anchors"])
            self.assertEqual(0, result["pdf_anchor_count"])


class AnchorCommand(support.TempCase):
    """``anchor_sources`` turns an anchor request into anchor record versions through a packet."""

    def test_anchors_are_created_and_listed_with_their_resolution(self):
        """A create request commits version 1 anchors and echoes the method and excerpt hash."""
        fx = self.fixture().capture()
        with fx.open() as db:
            packet = fx.packet(db)
            result = sources.anchor_sources(db, request=anchor_request(packet["packet_id"], "req_a1", [
                anchor_entry("anc_one", fx.source_id, locator(label="lem:a")),
                anchor_entry("anc_two", fx.source_id, locator(start=8, end=10))]))
            self.assertEqual(result["unchanged"], [])
            self.assertEqual([(a["id"], a["version"], a["method"], a["source_version"])
                              for a in result["anchors"]],
                             [("anc_one", 1, "label_match", 1), ("anc_two", 1, "exact_lines", 1)])
            self.assertEqual(result["anchors"][0]["locator"],
                             {"start_line": 5, "end_line": 7, "page": None, "label": "lem:a"})
            self.assertEqual(result["receipt"]["changed"],
                             [{"collection": "anchors", "id": "anc_one", "version": 1, "op": "create"},
                              {"collection": "anchors", "id": "anc_two", "version": 1, "op": "create"}])
            stored = db.head("anchors", "anc_one")
            self.assertEqual(stored.body["excerpt_sha256"], result["anchors"][0]["excerpt_sha256"])
            self.assertEqual(stored.body["excerpt"], "\\begin{lemma}\\label{lem:a}\n"
                                                     "For every $n$, $a_n \\le 1$.\n\\end{lemma}")
            proof = "\\begin{proof}\nBy induction on $n$.\n\\end{proof}"
            self.assertEqual(db.head("anchors", "anc_two").body, {
                "source_id": fx.source_id, "source_version": 1, "method": "exact_lines", "limitation": None,
                "locator": {"start_line": 8, "end_line": 10, "page": None, "label": None},
                "excerpt": proof, "excerpt_sha256": sha(proof.encode("utf-8"))})
            self.assertEqual(result["receipt"]["revision"], db.max_revision())

    @unittest.skipIf(NO_PYPDF, "pypdf is not installed, so page extraction cannot be exercised")
    def test_a_page_anchor_is_stored_with_the_reviewed_page_method(self):
        """A page locator survives the command: the stored record keeps page, method and limitation."""
        _, path = build_paper(self, "pdfanc", {
            "main.tex": "\\documentclass{article}\n\\begin{document}\\end{document}\n",
            "figure.pdf": TWO_PAGE_PDF})
        with storage.Database(path, write=True) as db:
            captured = sources.capture_sources(db, files=["main.tex", "figure.pdf"])
            pdf_id = next(s["id"] for s in captured["sources"] if s["media_type"] == "pdf")
            from paper_core import packets
            packet = packets.get_packet(db, targets=[R("papers", db.heads("papers")[0].id)], mode="author")
            result = sources.anchor_sources(db, request=anchor_request(packet["packet_id"], "req_pdf", [
                anchor_entry("anc_page", pdf_id, locator(page=1))]))
            self.assertEqual(result["anchors"][0]["method"], "reviewed_page")
            stored = db.head("anchors", "anc_page").body
            self.assertEqual(stored["locator"], {"start_line": None, "end_line": None, "page": 1, "label": None})
            self.assertIn("figure.pdf, physical PDF page 1", stored["limitation"])
            self.assertIn("compare important formulas", stored["limitation"])
            self.assertNotIn("reviewed by a person", stored["limitation"])

    def test_recreating_a_live_anchor_needs_an_expected_version(self):
        """Re-creating an existing anchor is refused with the version the caller must pass."""
        fx = self.fixture().anchors()
        with fx.open() as db:
            revision = db.max_revision()
            packet = fx.packet(db)
            with self.assertRaises(InvalidRequest) as caught:
                sources.anchor_sources(db, request=anchor_request(packet["packet_id"], "req_dup", [
                    anchor_entry("anc_lem", fx.source_id, locator(label="lem:a"))]))
            self.assertEqual(str(caught.exception),
                             "anchors/0: anchor anc_lem exists at version 1; pass expected_version to rebind it")
            self.assertEqual(db.max_revision(), revision)
            self.assertEqual(db.head("anchors", "anc_lem").version, 1)

    def test_a_rebind_whose_expected_version_is_wrong_conflicts(self):
        """A stale expected_version is a CONFLICT naming the real head, and nothing is written."""
        fx = self.fixture().anchors()
        with fx.open() as db:
            revision = db.max_revision()
            packet = fx.packet(db)
            with self.assertRaises(ConflictError) as caught:
                sources.anchor_sources(db, request=anchor_request(packet["packet_id"], "req_stale", [
                    anchor_entry("anc_lem", fx.source_id, locator(start=5, end=6), expected=7)]))
            self.assertEqual(caught.exception.code, "CONFLICT")
            self.assertEqual(caught.exception.records[0]["changed"],
                             [{"ref": R("anchors", "anc_lem"), "expected_version": 7, "actual_version": 1,
                               "retired": False}])
            self.assertEqual(db.max_revision(), revision)
            self.assertEqual(db.head("anchors", "anc_lem").version, 1)
            self.assertEqual(db.head("anchors", "anc_lem").body["locator"]["end_line"], 7)

    def test_rebinding_an_anchor_that_does_not_exist_is_rejected(self):
        """An expected_version for an unknown anchor is an invalid request, not a create."""
        fx = self.fixture().anchors()
        with fx.open() as db:
            revision = db.max_revision()
            packet = fx.packet(db)
            with self.assertRaises(InvalidRequest) as caught:
                sources.anchor_sources(db, request=anchor_request(packet["packet_id"], "req_ghost", [
                    anchor_entry("anc_ghost", fx.source_id, locator(label="lem:a"), expected=1)]))
            self.assertEqual(str(caught.exception), "anchors/0: anchor anc_ghost does not exist")
            self.assertIsNone(db.head("anchors", "anc_ghost"))
            self.assertEqual(db.max_revision(), revision)

    def test_an_anchor_on_an_unknown_source_is_rejected(self):
        """Every anchor names a live source record."""
        fx = self.fixture().capture()
        with fx.open() as db:
            revision = db.max_revision()
            packet = fx.packet(db)
            with self.assertRaises(InvalidRequest) as caught:
                sources.anchor_sources(db, request=anchor_request(packet["packet_id"], "req_src", [
                    anchor_entry("anc_x", "src_missing", locator(label="lem:a"))]))
            self.assertEqual(str(caught.exception), "anchors/0: source src_missing is not a live record")
            self.assertIsNone(db.head("anchors", "anc_x"))
            self.assertEqual(db.max_revision(), revision)

    def test_one_unresolvable_entry_discards_the_whole_request(self):
        """Anchors commit together: a later bad locator leaves the earlier good anchor unwritten."""
        fx = self.fixture().capture()
        with fx.open() as db:
            revision = db.max_revision()
            packet = fx.packet(db)
            with self.assertRaises(InvalidRequest) as caught:
                sources.anchor_sources(db, request=anchor_request(packet["packet_id"], "req_mixed", [
                    anchor_entry("anc_good", fx.source_id, locator(label="lem:a")),
                    anchor_entry("anc_bad", fx.source_id, locator(label="lem:nowhere"))]))
            self.assertEqual(caught.exception.code, "LABEL_NOT_FOUND")
            self.assertIsNone(db.head("anchors", "anc_good"))
            self.assertIsNone(db.head("anchors", "anc_bad"))
            self.assertEqual(db.max_revision(), revision)

    def test_an_empty_anchor_request_is_rejected(self):
        """A request that lists no anchors is refused rather than committing an empty revision."""
        fx = self.fixture().capture()
        with fx.open() as db:
            packet = fx.packet(db)
            revision = db.max_revision()
            with self.assertRaises(InvalidRequest) as caught:
                sources.anchor_sources(db, request=anchor_request(packet["packet_id"], "req_none", []))
            self.assertEqual(str(caught.exception), "anchor request lists no anchors")
            self.assertEqual(db.max_revision(), revision)

    def test_a_malformed_anchor_request_reports_the_offending_field(self):
        """Envelope and locator shape errors come back as records on one invalid-request error."""
        fx = self.fixture().capture()
        with fx.open() as db:
            packet = fx.packet(db)
            revision = db.max_revision()
            cases = [
                (dict(anchor_request(packet["packet_id"], "req_v", []), contract_version=2),
                 ["/contract_version: supported request contract versions are 3 and 4"]),
                (anchor_request(packet["packet_id"], "req_half", [
                    anchor_entry("anc_x", fx.source_id, locator(start=5))]),
                 ["/anchors/0/locator: start_line and end_line must appear together"]),
                (anchor_request(packet["packet_id"], "req_bare", [
                    anchor_entry("anc_x", fx.source_id, locator())]),
                 ["/anchors/0/locator: at least one location method is required"]),
                (anchor_request(packet["packet_id"], "req_rev", [
                    anchor_entry("anc_x", fx.source_id, locator(start=9, end=5))]),
                 ["/anchors/0/locator: start_line must not exceed end_line"]),
                ({"contract_version": 3, "request_id": "req_nopkt", "anchors": []},
                 ["/packet_id: missing required field"])]
            for request, records in cases:
                with self.subTest(records=records):
                    with self.assertRaises(InvalidRequest) as caught:
                        sources.anchor_sources(db, request=request)
                    self.assertEqual(str(caught.exception), "invalid anchor request")
                    self.assertEqual(caught.exception.records, records)
            self.assertIsNone(db.head("anchors", "anc_x"))
            self.assertEqual(db.max_revision(), revision)

    def test_anchoring_needs_an_authoring_packet(self):
        """An independent packet cannot author anchors: PACKET_MODE names the modes that can."""
        from paper_core import packets
        fx = self.fixture().primary()
        with fx.open() as db:
            revision = db.max_revision()
            packet = packets.get_packet(db, targets=[R("items", "itm_lem")], mode="independent")
            with self.assertRaises(InvalidRequest) as caught:
                sources.anchor_sources(db, request=anchor_request(packet["packet_id"], "req_mode", [
                    anchor_entry("anc_new", fx.source_id, locator(start=1, end=2))]))
            self.assertEqual(caught.exception.code, "PACKET_MODE")
            self.assertIn("needs a packet in mode ['author', 'primary', 'reconcile']", str(caught.exception))
            self.assertIsNone(db.head("anchors", "anc_new"))
            self.assertEqual(db.max_revision(), revision)

    def test_anchoring_against_an_unknown_packet_is_rejected(self):
        """A packet id that was never minted is PACKET_UNKNOWN and writes nothing."""
        fx = self.fixture().capture()
        with fx.open() as db:
            revision = db.max_revision()
            with self.assertRaises(InvalidRequest) as caught:
                sources.anchor_sources(db, request=anchor_request("pkt_never", "req_nopacket", [
                    anchor_entry("anc_new", fx.source_id, locator(start=1, end=2))]))
            self.assertEqual(caught.exception.code, "PACKET_UNKNOWN")
            self.assertIsNone(db.head("anchors", "anc_new"))
            self.assertEqual(db.max_revision(), revision)

    def test_a_rebind_that_resolves_identically_writes_nothing(self):
        """An unchanged rebind is listed under 'unchanged' with no receipt and no new revision."""
        fx = self.fixture().anchors()
        with fx.open() as db:
            revision = db.max_revision()
            packet = fx.packet(db)
            result = sources.anchor_sources(db, request=anchor_request(packet["packet_id"], "req_same", [
                anchor_entry("anc_lem", fx.source_id, locator(label="lem:a"), expected=1)]))
            self.assertIsNone(result["receipt"])
            self.assertEqual(result["anchors"], [])
            self.assertEqual(result["unchanged"], [{"id": "anc_lem", "version": 1}])
            self.assertEqual(db.max_revision(), revision)
            self.assertEqual(db.head("anchors", "anc_lem").version, 1)

    def test_an_anchor_relocates_when_the_source_shifts_but_the_text_is_identical(self):
        """A rebind after an edit above the passage keeps the excerpt and records 'exact_relocation'."""
        fx = self.fixture().anchors()
        rewrite(fx.source_root / "paper.tex", "% shifted\n" + support.PAPER_TEX)
        with fx.open() as db:
            sources.capture_sources(db, files=["paper.tex"])
            packet = fx.packet(db)
            result = sources.anchor_sources(db, request=anchor_request(packet["packet_id"], "req_move", [
                anchor_entry("anc_lem", fx.source_id, locator(label="lem:a"), expected=1)]))
            moved = result["anchors"][0]
            self.assertEqual((moved["version"], moved["method"], moved["source_version"]), (2, "exact_relocation", 2))
            self.assertEqual(moved["locator"], {"start_line": 6, "end_line": 8, "page": None, "label": "lem:a"})
            first, second = db.version("anchors", "anc_lem", 1), db.version("anchors", "anc_lem", 2)
            self.assertEqual(first.body["excerpt_sha256"], second.body["excerpt_sha256"])
            self.assertEqual(first.body["locator"]["start_line"], 5)
            self.assertEqual(first.body["source_version"], 1)
            self.assertEqual(first.body["method"], "label_match")

    def test_replaying_one_anchor_request_returns_the_recorded_receipt(self):
        """Re-sending the same request_id and payload is idempotent: same receipt, no new revision."""
        fx = self.fixture().anchors()
        rewrite(fx.source_root / "paper.tex", "% shifted\n" + support.PAPER_TEX)
        with fx.open() as db:
            sources.capture_sources(db, files=["paper.tex"])
            packet = fx.packet(db)
            request = anchor_request(packet["packet_id"], "req_replay", [
                anchor_entry("anc_lem", fx.source_id, locator(label="lem:a"), expected=1)])
            first = sources.anchor_sources(db, request=request)
            revision = db.max_revision()
            again = sources.anchor_sources(db, request=request)
            self.assertEqual(again["receipt"], first["receipt"])
            self.assertEqual(db.max_revision(), revision)
            self.assertEqual(db.head("anchors", "anc_lem").version, 2)

    def test_reusing_a_request_id_for_different_anchors_is_refused(self):
        """Idempotency is keyed on the payload too: the same id with a new locator is REQUEST_ID_REUSED."""
        fx = self.fixture().capture()
        with fx.open() as db:
            packet = fx.packet(db)
            sources.anchor_sources(db, request=anchor_request(packet["packet_id"], "req_once", [
                anchor_entry("anc_one", fx.source_id, locator(label="lem:a"))]))
            revision = db.max_revision()
            with self.assertRaises(InvalidRequest) as caught:
                sources.anchor_sources(db, request=anchor_request(packet["packet_id"], "req_once", [
                    anchor_entry("anc_other", fx.source_id, locator(start=8, end=10))]))
            self.assertEqual(caught.exception.code, "REQUEST_ID_REUSED")
            self.assertIsNone(db.head("anchors", "anc_other"))
            self.assertEqual(db.max_revision(), revision)

    def test_accepted_anchor_retry_returns_historical_listing_after_source_and_anchor_changes(self):
        """Replay restores its original changed/unchanged versions, without resolving today's source."""
        fx = self.fixture().anchors()
        with fx.open() as db:
            request = anchor_request(fx.packet(db)["packet_id"], "req_history", [
                anchor_entry("anc_lem", fx.source_id, locator(label="lem:a"), expected=1),
                anchor_entry("anc_new", fx.source_id, locator(label="thm:b"))])
            first = sources.anchor_sources(db, request=request)
            rewrite(fx.source_root / "paper.tex", "% shifted\n" + support.PAPER_TEX)
            sources.capture_sources(db, files=["paper.tex"])
            sources.anchor_sources(db, request=anchor_request(fx.packet(db)["packet_id"], "req_move_both", [
                anchor_entry("anc_lem", fx.source_id, locator(label="lem:a"), expected=1),
                anchor_entry("anc_new", fx.source_id, locator(label="thm:b"), expected=1)]))
            before = (db.max_revision(), len(db.all_versions()))
            with patch.object(sources, "resolve_anchor", side_effect=AssertionError("must replay history")):
                self.assertEqual(sources.anchor_sources(db, request=request), first)
            self.assertEqual(first["anchors"][0]["source_version"], 1)
            self.assertEqual(first["unchanged"], [{"id": "anc_lem", "version": 1}])
            self.assertEqual(db.head("anchors", "anc_new").body["source_version"], 2)
            self.assertEqual((db.max_revision(), len(db.all_versions())), before)
            changed = dict(request, anchors=[anchor_entry("anc_lem", fx.source_id, locator(label="absent"))])
            with self.assertRaises(InvalidRequest) as caught:
                sources.anchor_sources(db, request=changed)
            self.assertEqual(caught.exception.code, "REQUEST_ID_REUSED")
            # An unaccepted ID still resolves and validates the live source normally.
            fresh = anchor_request(fx.packet(db)["packet_id"], "req_new_bad", [
                anchor_entry("anc_missing", fx.source_id, locator(label="absent"))])
            with self.assertRaises(InvalidRequest) as caught:
                sources.anchor_sources(db, request=fresh)
            self.assertEqual(caught.exception.code, "LABEL_NOT_FOUND")
            self.assertEqual((db.max_revision(), len(db.all_versions())), before)


class SourceReviewAndLimits(support.TempCase):
    """``review_sources`` records source reviews and issues, and open issues limit the audit."""

    @staticmethod
    def issue_body(source_id, *, lifecycle="open", resolution=None, anchor_id=None,
                   category="ambiguous_label"):
        return {"source_id": source_id, "anchor_id": anchor_id, "category": category,
                "description": "the label lem:a is used twice in the sources", "lifecycle": lifecycle,
                "resolution": resolution, "reviewer": "coord"}

    def spare_anchor(self, db, fx, anchor_id="anc_spare"):
        """Create one anchor that no item, argument, group or use refers to; returns its id."""
        sources.anchor_sources(db, request=anchor_request(fx.packet(db)["packet_id"], f"req_{anchor_id}", [
            anchor_entry(anchor_id, fx.source_id, locator(start=1, end=2))]))
        return anchor_id

    def test_a_source_review_batch_commits_its_records(self):
        """Reviews and issues land as version 1 records bound to the packet that authorised them."""
        fx = self.fixture().structure()
        with fx.open() as db:
            source = db.head("sources", fx.source_id)
            anchor = db.head("anchors", "anc_lem")
            packet = fx.packet(db)
            receipt = sources.review_sources(db, batch=fx.batch([
                edit("create", "source_issues", "sis_1", self.issue_body(fx.source_id)),
                edit("create", "source_reviews", "srv_1", {
                    "source_refs": [{"collection": "sources", "id": source.id, "version": source.version}],
                    "anchor_refs": [{"collection": "anchors", "id": anchor.id, "version": anchor.version}],
                    "purpose": "locator_confirmation", "decision": "accepted",
                    "rationale": "the excerpt matches the statement", "reviewer": "coord"})],
                packet["packet_id"]))
            self.assertEqual(receipt["changed"],
                             [{"collection": "source_issues", "id": "sis_1", "version": 1, "op": "create"},
                              {"collection": "source_reviews", "id": "srv_1", "version": 1, "op": "create"}])
            self.assertEqual(db.head("source_issues", "sis_1").body["lifecycle"], "open")
            self.assertEqual(db.head("source_reviews", "srv_1").body["decision"], "accepted")
            self.assertEqual(db.head("source_reviews", "srv_1").body["anchor_refs"],
                             [{"collection": "anchors", "id": "anc_lem", "version": 1}])
            self.assertEqual(db.binding("source_reviews", "srv_1", 1)["packet_id"], packet["packet_id"])

    def test_a_source_review_batch_carries_only_source_collections(self):
        """Edits to any other collection are refused before anything is written."""
        fx = self.fixture().structure()
        with fx.open() as db:
            revision = db.max_revision()
            packet = fx.packet(db)
            with self.assertRaises(InvalidRequest) as caught:
                sources.review_sources(db, batch=fx.batch([
                    edit("create", "observations", "obs_x", {
                        "target": R("items", "itm_lem"), "result": "matched", "reviewer": "coord",
                        "note": "", "evidence_refs": []})], packet["packet_id"]))
            self.assertEqual(caught.exception.records,
                             ["edits/0: source review batches carry source_reviews and source_issues only"])
            self.assertEqual(db.max_revision(), revision)
            self.assertIsNone(db.head("observations", "obs_x"))

    def test_accepted_review_retry_preserves_receipt_after_its_source_and_anchor_pins_go_stale(self):
        """Old acceptance is replayable; new or changed requests cannot bypass current pin checks."""
        fx = self.fixture().anchors()
        with fx.open() as db:
            batch = fx.batch([edit("create", "source_reviews", "srv_replay", {
                "source_refs": [fx.pin(db, "sources", fx.source_id)],
                "anchor_refs": [fx.pin(db, "anchors", "anc_lem")],
                "purpose": "locator_confirmation", "decision": "accepted",
                "rationale": "the original excerpt matches", "reviewer": "coord"})], fx.packet(db)["packet_id"])
            first = sources.review_sources(db, batch=batch)
            rewrite(fx.source_root / "paper.tex", "% shifted\n" + support.PAPER_TEX)
            sources.capture_sources(db, files=["paper.tex"])
            sources.anchor_sources(db, request=anchor_request(fx.packet(db)["packet_id"], "req_reanchor", [
                anchor_entry("anc_lem", fx.source_id, locator(label="lem:a"), expected=1)]))
            before = (db.max_revision(), len(db.all_versions()))
            self.assertEqual(sources.review_sources(db, batch=batch), first)
            self.assertLess(first["revision"], db.max_revision())
            changed_edit = dict(batch["edits"][0], body=dict(batch["edits"][0]["body"], rationale="different"))
            with self.assertRaises(InvalidRequest) as caught:
                sources.review_sources(db, batch=dict(batch, edits=[changed_edit]))
            self.assertEqual(caught.exception.code, "REQUEST_ID_REUSED")
            with self.assertRaises(InvalidRequest) as caught:
                sources.review_sources(db, batch=dict(batch, request_id="req_new_stale",
                                                     packet_id=fx.packet(db)["packet_id"]))
            self.assertIn(f"edits/0: source_refs entry {fx.source_id} must pin the live version",
                          caught.exception.records)
            self.assertIn("edits/0: anchor_refs entry anc_lem must pin the live version", caught.exception.records)
            self.assertEqual((db.max_revision(), len(db.all_versions())), before)

    def test_review_cannot_replay_an_accepted_batch_from_another_command(self):
        """A previously accepted apply envelope is still outside the source-review command's scope."""
        fx = self.fixture().structure()
        with fx.open() as db:
            scope = {"argument_id": None, "parent_id": None, "assumptions": [], "binders": [],
                     "conditions": [], "evidence_refs": []}
            batch = fx.batch([edit("create", "scopes", "scp_other", scope)], fx.packet(db)["packet_id"])
            acceptance.apply_batch(db, batch)
            revision = db.max_revision()
            with self.assertRaises(InvalidRequest) as caught:
                sources.review_sources(db, batch=batch)
            self.assertEqual(caught.exception.records,
                             ["edits/0: source review batches carry source_reviews and source_issues only"])
            self.assertEqual(db.max_revision(), revision)

    def test_a_malformed_review_envelope_is_reported_before_any_record_check(self):
        """A wrong contract_version fails the envelope shape, not the per-edit rules."""
        fx = self.fixture().structure()
        with fx.open() as db:
            revision = db.max_revision()
            batch = dict(fx.batch([], fx.packet(db)["packet_id"]), contract_version=2)
            with self.assertRaises(InvalidRequest) as caught:
                sources.review_sources(db, batch=batch)
            self.assertEqual(str(caught.exception), "invalid edit envelope")
            self.assertEqual(caught.exception.records, ["/contract_version: supported request contract versions are 3 and 4"])
            self.assertEqual(db.max_revision(), revision)

    def test_a_source_review_must_pin_the_live_source_and_anchor_versions(self):
        """A stale pin in source_refs or anchor_refs is named and the batch writes nothing."""
        fx = self.fixture().structure()
        with fx.open() as db:
            revision = db.max_revision()
            packet = fx.packet(db)
            cases = [({"source_refs": [{"collection": "sources", "id": fx.source_id, "version": 99}],
                       "anchor_refs": []},
                      f"edits/0: source_refs entry {fx.source_id} must pin the live version"),
                     ({"source_refs": [],
                       "anchor_refs": [{"collection": "anchors", "id": "anc_lem", "version": 99}]},
                      "edits/0: anchor_refs entry anc_lem must pin the live version"),
                     ({"source_refs": [],
                       "anchor_refs": [{"collection": "anchors", "id": "anc_absent", "version": 1}]},
                      "edits/0: anchor_refs entry anc_absent must pin the live version")]
            for index, (refs, message) in enumerate(cases):
                with self.subTest(message=message):
                    body = dict(refs, purpose="context_change", decision="accepted",
                                rationale="checked", reviewer="coord")
                    with self.assertRaises(InvalidRequest) as caught:
                        sources.review_sources(db, batch=fx.batch(
                            [edit("create", "source_reviews", f"srv_bad{index}", body)], packet["packet_id"]))
                    self.assertEqual(str(caught.exception), "source review rejected")
                    self.assertEqual(caught.exception.records, [message])
                    self.assertIsNone(db.head("source_reviews", f"srv_bad{index}"))
            self.assertEqual(db.max_revision(), revision)

    def test_a_source_issue_body_must_satisfy_the_record_contract(self):
        """An unknown category and a resolved issue with a blank resolution are both INVALID_BATCH."""
        fx = self.fixture().structure()
        with fx.open() as db:
            revision = db.max_revision()
            cases = [
                (self.issue_body(fx.source_id, category="nonsense"),
                 "/category: must be one of ['unresolved_branch', 'ambiguous_label', 'missing_source', "
                 "'missing_citation', 'locator_limit', 'other_resolution']"),
                (self.issue_body(fx.source_id, lifecycle="resolved", resolution="   "),
                 "/: a resolved source issue needs a nonempty resolution")]
            for index, (body, tail) in enumerate(cases):
                with self.subTest(tail=tail):
                    issue_id = f"sis_bad{index}"
                    with self.assertRaises(InvalidRequest) as caught:
                        sources.review_sources(db, batch=fx.batch(
                            [edit("create", "source_issues", issue_id, body)], fx.packet(db)["packet_id"]))
                    self.assertEqual(caught.exception.code, "INVALID_BATCH")
                    self.assertEqual(caught.exception.records,
                                     [f"edits/0 source_issues:{issue_id} {tail}"])
                    self.assertIsNone(db.head("source_issues", issue_id))
            self.assertEqual(db.max_revision(), revision)

    def test_an_open_source_issue_blocks_a_complete_process(self):
        """A recorded open issue appears in status.source_limits and clears process_complete."""
        fx = self.fixture().complete()
        with fx.open() as db:
            before = queries.status(db)
            self.assertIs(before["process_complete"], True)
            self.assertEqual(before["source_limits"], [])
            sources.review_sources(db, batch=fx.batch(
                [edit("create", "source_issues", "sis_1", self.issue_body(fx.source_id))],
                fx.packet(db)["packet_id"]))
            after = queries.status(db)
            self.assertIs(after["process_complete"], False)
            self.assertEqual(after["source_limits"], [{"collection": "source_issues", "id": "sis_1", "version": 1}])
            self.assertEqual(after["problems"], [])
            self.assertEqual(after["obligations"]["unsatisfied"], [])
            self.assertEqual(after["progress"]["completed_current_obligations"],
                             after["progress"]["required_obligations"])

    def test_an_anchor_scoped_issue_blocks_the_audit_it_touches(self):
        """An issue pinned to an anchor the statements use is a source limit for that audit."""
        fx = self.fixture().complete()
        with fx.open() as db:
            sources.review_sources(db, batch=fx.batch([edit("create", "source_issues", "sis_anc", self.issue_body(
                fx.source_id, anchor_id="anc_lem", category="locator_limit"))], fx.packet(db)["packet_id"]))
            status = queries.status(db)
            self.assertIs(status["process_complete"], False)
            self.assertEqual(status["source_limits"],
                             [{"collection": "source_issues", "id": "sis_anc", "version": 1}])

    def test_an_issue_on_an_anchor_outside_the_audit_is_not_a_limit(self):
        """A focused audit is limited only by issues touching the passages it actually reads."""
        fx = self.fixture().complete()
        with fx.open() as db:
            spare = self.spare_anchor(db, fx)
            self.assertEqual(queries.status(db)["source_limits"], [])
            sources.review_sources(db, batch=fx.batch([edit("create", "source_issues", "sis_out", self.issue_body(
                fx.source_id, anchor_id=spare, category="locator_limit"))], fx.packet(db)["packet_id"]))
            status = queries.status(db)
            self.assertEqual(status["source_limits"], [])
            self.assertIs(status["process_complete"], True)
            self.assertEqual(db.head("source_issues", "sis_out").body["anchor_id"], spare)

    def test_a_superseded_issue_is_not_a_limit(self):
        """Only an issue whose lifecycle is still open limits the audit."""
        fx = self.fixture().complete()
        with fx.open() as db:
            sources.review_sources(db, batch=fx.batch([edit("create", "source_issues", "sis_sup", self.issue_body(
                fx.source_id, lifecycle="superseded"))], fx.packet(db)["packet_id"]))
            status = queries.status(db)
            self.assertEqual(status["source_limits"], [])
            self.assertIs(status["process_complete"], True)

    def test_resolving_the_issue_clears_the_limit_and_restores_completion(self):
        """Once the issue is resolved the limit disappears and the process is complete again."""
        fx = self.fixture().complete()
        with fx.open() as db:
            sources.review_sources(db, batch=fx.batch(
                [edit("create", "source_issues", "sis_1", self.issue_body(fx.source_id))],
                fx.packet(db)["packet_id"]))
            self.assertIs(queries.status(db)["process_complete"], False)
            packet = fx.packet(db)
            self.assertIn(R("source_issues", "sis_1"), packet["write_scope"])
            sources.review_sources(db, batch=fx.batch([edit("replace", "source_issues", "sis_1", self.issue_body(
                fx.source_id, lifecycle="resolved", resolution="re-anchored by exact lines"), expected=1)],
                packet["packet_id"]))
            after = queries.status(db)
            self.assertEqual(db.head("source_issues", "sis_1").version, 2)
            self.assertEqual(db.head("source_issues", "sis_1").body["resolution"], "re-anchored by exact lines")
            self.assertEqual(after["source_limits"], [])
            self.assertIs(after["process_complete"], True)

    def test_replacing_an_issue_with_the_wrong_expected_version_conflicts(self):
        """Optimistic concurrency reaches the source-review path too, and the issue stays open."""
        fx = self.fixture().complete()
        with fx.open() as db:
            sources.review_sources(db, batch=fx.batch(
                [edit("create", "source_issues", "sis_1", self.issue_body(fx.source_id))],
                fx.packet(db)["packet_id"]))
            revision = db.max_revision()
            with self.assertRaises(ConflictError) as caught:
                sources.review_sources(db, batch=fx.batch([edit("replace", "source_issues", "sis_1",
                    self.issue_body(fx.source_id, lifecycle="resolved", resolution="done"), expected=4)],
                    fx.packet(db)["packet_id"]))
            self.assertEqual(caught.exception.code, "CONFLICT")
            self.assertEqual(caught.exception.records[0]["changed"],
                             [{"ref": R("source_issues", "sis_1"), "expected_version": 4, "actual_version": 1,
                               "retired": False}])
            self.assertEqual(db.max_revision(), revision)
            self.assertEqual(db.head("source_issues", "sis_1").body["lifecycle"], "open")


if __name__ == "__main__":
    unittest.main()
