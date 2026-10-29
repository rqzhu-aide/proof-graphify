"""Handoff tests from native v3 overviews into the shared audit backend.

Fixtures are built by the v3 overview CLI in isolated subprocesses. The tests
pin evidence, ownership, grouping, scope, and applicable review preservation.
Older overview versions are refused without writing or requiring old runtimes.
"""
from __future__ import annotations

from contextlib import closing
import base64
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

from support import Fixture, GLOBAL_TASKS, OVERVIEW, R, TempCase, edit, node_available, run_cli, sha, write_json
from test_sources import mini_pdf

from paper_core import acceptance, packets, review, storage
from paper_core.assessment import derive_assessment, obligation_id
from paper_core.errors import IncompatibleError
from paper_core.projection import build_projection

OVERVIEW_SCRIPTS = OVERVIEW / "scripts"

try:
    import pypdf  # noqa: F401
    NO_PYPDF = False
except ImportError:  # the legacy CLIs run on this same interpreter
    NO_PYPDF = True

BRIDGE_TEX = "\n".join([
    r"\documentclass{article}",
    r"\begin{document}",
    r"\begin{lemma}\label{lem:bridge}",
    r"Every bridge map is monotone.",
    r"\end{lemma}",
    r"\begin{theorem}\label{thm:main}",
    r"The bridge theorem holds.",
    r"\end{theorem}",
    r"The key equation is $b(x) = a(x) + 1$.",
    r"\end{document}"])
PDF_BYTES = mini_pdf(1)

SPLIT_GROUP_LIMITATION = ("use use-split-b: overview group 'grp-split' spans several conclusions; "
                          "it migrates as one groups record per conclusion")
ARCHIVED_OBSERVATION_LIMITATION = ("1 historical observations preserved with their original "
                                   "comparison inputs; they do not acquire current comparison credit")


def archived_observation_limitation(count: int) -> str:
    return (f"{count} historical observations preserved with their original "
            "comparison inputs; they do not acquire current comparison credit")


# -- legacy fixture helpers ---------------------------------------------------------------
def run_overview_cli(scripts, *args, expect=0):
    """Run one shipped overview CLI in a subprocess: its own scripts folder, no repository imports."""
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    if args[0] == "init":
        # This lane explicitly constructs the supported historical format.
        # Ordinary shipped init now creates the common store.
        code = "import sys,json; sys.path.insert(0,sys.argv[1]); import paper_database as p; print(json.dumps(p._native_init_database(sys.argv[2],sys.argv[3])))"
        command = [sys.executable, "-B", "-c", code, str(scripts), str(args[1]), str(args[2])]
    else:
        command = [sys.executable, "-B", str(Path(scripts) / "paper_database.py"), *[str(a) for a in args]]
    proc = subprocess.run(command, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != expect:
        raise AssertionError(f"exit {proc.returncode} != {expect} for the overview CLI {args}\n"
                             f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
    return (json.loads(proc.stdout) if proc.stdout.strip() else None), proc.stderr


def source_file(id, path, media_type, data: bytes) -> dict:
    return {"id": id, "path": path, "media_type": media_type, "sha256": sha(data),
            "content_base64": base64.b64encode(data).decode("ascii")}


def source_revision_id(files) -> str:
    """``paper_records._source_digest`` re-derived: the digest of the sorted id/path/media/sha rows."""
    manifest = sorted(({"id": row["id"], "path": row["path"], "media_type": row["media_type"],
                        "sha256": row["sha256"]} for row in files), key=lambda row: row["id"])
    text = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def line_excerpt(data: bytes, start: int, end: int) -> str:
    """The exact excerpt a checked line-range anchor must carry."""
    return "\n".join(data.decode("utf-8-sig").splitlines()[start - 1:end])


def anchor_row(id, revision, file_id, locator, excerpt, method, status="checked", note=None) -> dict:
    row = {"id": id, "source_revision": revision, "locator": locator, "excerpt": excerpt,
           "excerpt_hash": sha(excerpt.encode("utf-8")),
           "verification": {"status": status, "method": method}}
    if file_id is not None:
        row["file_id"] = file_id
    if note is not None:
        row["verification"]["note"] = note
    return row


def expected_note(obs) -> str:
    """The contract-3 note migrate-overview builds: legacy provenance in brackets, then the text."""
    parts = [f"[legacy created_at {obs['created_at']}]", f"[legacy input_snapshot {obs['input_snapshot']}]"]
    if obs.get("carried_from") is not None:
        parts.append(f"[legacy carried_from {obs['carried_from']}]")
    parts.append(obs["note"])
    return " ".join(parts).strip()


# -- schema 3 (v2 overview CLI) -------------------------------------------------------------
@unittest.skipIf(NO_PYPDF, "pypdf is not installed, so the PDF page anchor cannot be built")
class OverviewBridgeSchema3Test(TempCase):
    """A schema-3 database with groups, owned intermediates and four anchor shapes, built by v2."""

    def setUp(self):
        super().setUp()
        self.src = self.work / "legacy3" / "src"
        self.src.mkdir(parents=True)
        (self.src / "paper.tex").write_text(BRIDGE_TEX, encoding="utf-8", newline="\n")
        (self.src / "appendix.pdf").write_bytes(PDF_BYTES)
        files = [source_file("file-tex", "paper.tex", "text/plain", BRIDGE_TEX.encode("utf-8")),
                 source_file("file-pdf", "appendix.pdf", "application/pdf", PDF_BYTES)]
        revision = source_revision_id(files)
        seed = {"schema_version": 3, "title": "Bridge theorems", "scope": "Bridge maps on finite volumes.",
                "source_revision": {"id": revision, "title": "Bridge sources",
                                    "created_at": "2026-09-17T00:00:00+00:00", "files": files},
                "anchors": [
                    anchor_row("anc-lem", revision, "file-tex",
                               {"start_line": 3, "end_line": 5, "label": "lem:bridge"},
                               line_excerpt(BRIDGE_TEX.encode("utf-8"), 3, 5), "line_range, tex_label"),
                    anchor_row("anc-thm", revision, "file-tex", {"label": "thm:main"}, "", "tex_label"),
                    anchor_row("anc-eq", revision, "file-tex", {"start_line": 9, "end_line": 9},
                               line_excerpt(BRIDGE_TEX.encode("utf-8"), 9, 9), "line_range"),
                    anchor_row("anc-pdf", revision, "file-pdf", {"page": 1}, "", "pdf_page_bounds"),
                ],
                "items": [
                    {"id": "lem-bridge", "kind": "lemma", "label": "Lemma 1", "caption": "The bridge lemma",
                     "statement": {"text": "Every bridge map is monotone.", "form": "synopsis"},
                     "passages": [{"role": "statement", "anchor_id": "anc-lem"}],
                     "aliases": ["lem:bridge"], "issue": "Boundary monotonicity is unchecked."},
                    {"id": "thm-main", "kind": "theorem", "label": "Theorem 1", "caption": "The bridge theorem",
                     "statement": {"text": "The bridge theorem holds.", "form": "synopsis"},
                     "passages": [{"role": "statement", "anchor_id": "anc-thm"},
                                  {"role": "proof", "anchor_id": "anc-pdf"}]},
                    {"id": "eq-key", "kind": "equation", "label": "Equation 1", "caption": "The key equation",
                     "statement": {"text": "$b(x) = a(x) + 1$.", "form": "verbatim"},
                     "passages": [{"role": "statement", "anchor_id": "anc-eq"}], "owner": "thm-main"},
                    {"id": "clm-mid", "kind": "claim", "label": "Claim 1", "caption": "The midpoint claim",
                     "statement": {"text": "The midpoint map is a bridge map.", "form": "synopsis"},
                     "passages": [{"role": "statement", "anchor_id": "anc-thm"}], "owner": "thm-main"},
                    {"id": "drv-proof", "kind": "derivation", "label": "Derivation 1", "caption": "The main derivation",
                     "statement": {"text": "Combine Equation 1 with Lemma 1.", "form": "synopsis"},
                     "passages": [{"role": "statement", "anchor_id": "anc-eq"}], "owner": "thm-main"},
                ],
                "uses": [
                    {"id": "use-lem-thm", "from": "lem-bridge", "to": "thm-main", "type": "proof_argument",
                     "reason": "Monotonicity enters the main argument.", "evidence_refs": ["anc-lem"],
                     "regime": "finite volume", "issue": "Only checked for compact domains.",
                     "group": {"id": "grp-joint-1", "kind": "joint"}},
                    {"id": "use-eq-thm", "from": "eq-key", "to": "thm-main", "type": "dependency",
                     "reason": "The key equation defines the bridge map.", "evidence_refs": ["anc-eq"],
                     "group": {"id": "grp-joint-1", "kind": "joint"}},
                    {"id": "use-clm-thm", "from": "clm-mid", "to": "thm-main", "type": "dependency",
                     "reason": "The midpoint claim covers the base case.", "evidence_refs": [],
                     "regime": "base case", "group": {"id": "grp-cases-1", "kind": "cases"}},
                    {"id": "use-drv-thm", "from": "drv-proof", "to": "thm-main", "type": "proof_argument",
                     "reason": "The derivation covers the inductive step.", "evidence_refs": [],
                     "regime": "inductive step", "group": {"id": "grp-cases-1", "kind": "cases"}},
                    {"id": "use-split-a", "from": "eq-key", "to": "lem-bridge", "type": "dependency",
                     "reason": "The equation restricts bridge maps.", "evidence_refs": [],
                     "group": {"id": "grp-split", "kind": "joint"}},
                    {"id": "use-split-b", "from": "clm-mid", "to": "thm-main", "type": "dependency",
                     "reason": "The midpoint claim also enters the final step.", "evidence_refs": [],
                     "group": {"id": "grp-split", "kind": "joint"}},
                ],
                "observations": [], "main_items": ["lem-bridge", "thm-main"]}
        self.db = self.path("legacy3", "overview.db")
        self.backup = self.path("legacy3", "overview.backup.db")
        seed_path = write_json(self.src / "overview-seed.json", seed)
        info, _ = run_overview_cli(OVERVIEW_SCRIPTS, "init", self.db, seed_path)
        self.snap1 = info["snapshot_id"]
        batch = write_json(self.path("legacy3", "compare1.json"),
                           {"basis": "typeset", "expected_snapshot": self.snap1,
                            "targets": [R("items", "thm-main"), R("uses", "use-lem-thm")],
                            "reviewer": "reader-a", "note": "Compared against the TeX and the PDF.",
                            "result": "matched"})
        run_overview_cli(OVERVIEW_SCRIPTS, "compare", self.db, batch)
        batch = write_json(self.path("legacy3", "apply1.json"),
                           {"expected_snapshot": self.snap1, "edits": [],
                            "set": {"scope": "Bridge maps on all measure spaces."}})
        applied, _ = run_overview_cli(OVERVIEW_SCRIPTS, "apply", self.db, batch)
        self.snap2 = applied["snapshot_id"]
        batch = write_json(self.path("legacy3", "compare2.json"),
                           {"basis": "typeset", "expected_snapshot": self.snap2, "targets": [R("items", "lem-bridge")],
                            "reviewer": "reader-b", "result": "needs_attention",
                            "note": "The boundary statement drifts from the source."})
        run_overview_cli(OVERVIEW_SCRIPTS, "compare", self.db, batch)
        batch = write_json(self.path("legacy3", "compare3.json"),
                           {"expected_snapshot": self.snap2, "targets": [R("items", "thm-main")],
                            "reviewer": "reader-a", "result": "matched", "reuse_from": self.snap1,
                            "changes_reviewed": True,
                            "note": "Only the scope text changed; the theorem and its evidence are untouched."})
        run_overview_cli(OVERVIEW_SCRIPTS, "compare", self.db, batch)
        export_path = self.path("legacy3", "export.json")
        run_overview_cli(OVERVIEW_SCRIPTS, "export", self.db, export_path)
        self.exported = json.loads(export_path.read_text(encoding="utf-8"))

    def migrate(self) -> dict:
        payload, _ = run_cli("migrate-overview", self.db, "--backup", self.backup)
        return payload

    def read(self):
        db = storage.Database(self.db)
        self.addCleanup(db.close)
        return db

    def test_fixture_is_a_real_schema_three_overview(self):
        """The v3 CLI built the fixture: two snapshots, four observations, one carried comparison."""
        self.assertNotEqual(self.snap1, self.snap2)
        self.assertEqual(self.exported["schema_version"], 3)
        self.assertEqual(self.exported["scope"], "Bridge maps on all measure spaces.")
        observations = self.exported["observations"]
        self.assertEqual(len(observations), 4)
        carried = [obs for obs in observations if obs.get("carried_from") is not None]
        self.assertEqual(len(carried), 1)
        self.assertEqual(carried[0]["target"], R("items", "thm-main"))
        self.assertEqual({obs["target"]["id"] for obs in observations},
                         {"thm-main", "use-lem-thm", "lem-bridge"})
        self.assertEqual(sorted(obs["result"] for obs in observations),
                         ["matched", "matched", "matched", "needs_attention"])

    def test_migration_carries_every_record_field(self):
        """Items, uses, anchors, sources and the paper record survive with no field dropped."""
        result = self.migrate()
        self.assertEqual(result["counts"], {"sources": 2, "anchors": 4, "items": 5, "uses": 6,
                                            "groups": 4, "observations": 4})
        self.assertEqual(result["limitations"],
                         [SPLIT_GROUP_LIMITATION, ARCHIVED_OBSERVATION_LIMITATION])
        self.assertEqual(len(result["remapped"]), 1)
        db = self.read()
        items = {item.id: item.body for item in db.heads("items")}
        legacy_items = {row["id"]: row for row in self.exported["items"]}
        self.assertEqual(set(items), set(legacy_items))
        for iid, body in items.items():
            old = legacy_items[iid]
            with self.subTest(item=iid):
                self.assertEqual(body["kind"], old["kind"])
                self.assertEqual(body["label"], old["label"])
                self.assertEqual(body["caption"], old["caption"])
                self.assertEqual(body["statement"], old["statement"])
                self.assertEqual(body["passages"], old["passages"])
                self.assertEqual(body["aliases"], old.get("aliases", []))
                self.assertEqual(body["uncertainty"], old.get("issue"))
                self.assertEqual(body["origin"], "source")
                self.assertIsNone(body["scope_id"])
                self.assertEqual(body["owner_id"], old.get("owner"))
        uses = {use.id: use.body for use in db.heads("uses")}
        legacy_uses = {row["id"]: row for row in self.exported["uses"]}
        self.assertEqual(set(uses), set(legacy_uses))
        for uid, body in uses.items():
            old = legacy_uses[uid]
            with self.subTest(use=uid):
                self.assertEqual(body["from"], R("items", old["from"]))
                self.assertEqual(body["to"], R("items", old["to"]))
                self.assertEqual(body["type"], old["type"])
                self.assertEqual(body["reason"], old["reason"])
                self.assertEqual(body["evidence_refs"], old["evidence_refs"])
                self.assertEqual(body["regime"], old.get("regime"))
                self.assertEqual(body["uncertainty"], old.get("issue"))
        anchors = {anchor.id: anchor.body for anchor in db.heads("anchors")}
        legacy_anchors = {row["id"]: row for row in self.exported["anchors"]}
        self.assertEqual(set(anchors), set(legacy_anchors))
        methods = {"anc-lem": "exact_lines", "anc-thm": "label_match",
                   "anc-eq": "exact_lines", "anc-pdf": "reviewed_page"}
        locators = {"anc-lem": {"start_line": 3, "end_line": 5, "page": None, "label": "lem:bridge"},
                    "anc-thm": {"start_line": None, "end_line": None, "page": None, "label": "thm:main"},
                    "anc-eq": {"start_line": 9, "end_line": 9, "page": None, "label": None},
                    "anc-pdf": {"start_line": None, "end_line": None, "page": 1, "label": None}}
        for aid, body in anchors.items():
            old = legacy_anchors[aid]
            with self.subTest(anchor=aid):
                self.assertEqual(body["method"], methods[aid])
                self.assertEqual(body["locator"], locators[aid])
                self.assertEqual(body["excerpt"], old["excerpt"])
                self.assertEqual(body["excerpt_sha256"], old["excerpt_hash"])
                self.assertEqual(body["source_id"], old["file_id"])
                self.assertEqual(body["source_version"], 1)
                self.assertIsNone(body["limitation"])
        sources = {source.id: source.body for source in db.heads("sources")}
        self.assertEqual(sorted(sources), ["file-pdf", "file-tex"])
        self.assertEqual(sources["file-tex"]["media_type"], "tex")
        self.assertEqual(sources["file-pdf"]["media_type"], "pdf")
        for body in sources.values():
            self.assertEqual(body["capture_method"], "legacy_overview_import")
            self.assertIsNone(body["limitation"])
        self.assertEqual(db.get_blob(sources["file-tex"]["blob_sha256"]), BRIDGE_TEX.encode("utf-8"))
        self.assertEqual(db.get_blob(sources["file-pdf"]["blob_sha256"]), PDF_BYTES)
        paper = storage.paper_record(db)
        self.assertEqual(paper.body["title"], "Bridge theorems")
        self.assertEqual(paper.body["main_items"], ["lem-bridge", "thm-main"])
        self.assertEqual(paper.body["scope"], "Bridge maps on all measure spaces.")
        self.assertEqual(paper.body["exclusions"], [])

    def test_overview_groups_become_provenance_groups(self):
        """Each (group id, conclusion) pair is one group with both audit fields null; splits are loud."""
        result = self.migrate()
        db = self.read()
        groups = {group.id: group.body for group in db.heads("groups")}
        uses = {use.id: use.body for use in db.heads("application_details")}
        self.assertTrue(all(use["state"] == "draft" for use in uses.values()))
        self.assertEqual(uses["use-lem-thm"]["group_id"], "grp-joint-1")
        self.assertEqual(uses["use-eq-thm"]["group_id"], "grp-joint-1")
        self.assertEqual(uses["use-clm-thm"]["group_id"], "grp-cases-1")
        self.assertEqual(uses["use-drv-thm"]["group_id"], "grp-cases-1")
        joint, cases = groups["grp-joint-1"], groups["grp-cases-1"]
        for body, kind in ((joint, "joint"), (cases, "cases")):
            self.assertIsNone(body["argument_id"])
            self.assertIsNone(body["scope_id"])
            self.assertEqual(body["conclusion"], R("items", "thm-main"))
            self.assertEqual(body["kind"], kind)
            self.assertEqual(body["case_scope_ids"], [])
            self.assertEqual(body["discharges"], [])
            self.assertEqual(body["evidence_refs"], [])
        self.assertIn("grp-joint-1", joint["rationale"])
        # grp-split spans two conclusions: one record each, the second under a minted id
        self.assertEqual(result["remapped"],
                         [{"collection": "groups", "old": "grp-split", "new": mock.ANY}])
        remapped = result["remapped"][0]["new"]
        self.assertEqual(uses["use-split-a"]["group_id"], "grp-split")
        self.assertEqual(uses["use-split-b"]["group_id"], remapped)
        self.assertEqual(groups["grp-split"]["conclusion"], R("items", "lem-bridge"))
        self.assertEqual(groups[remapped]["conclusion"], R("items", "thm-main"))
        self.assertIsNone(groups[remapped]["argument_id"])
        self.assertEqual(len(groups), 4)

    def test_migration_preserves_history_without_crediting_inapplicable_observations(self):
        """History retains its original inputs; only per-target winners are current."""
        result = self.migrate()
        self.assertEqual(result["counts"]["observations"], 4)
        db = self.read()
        observations = {obs.id: obs.body for obs in db.heads("observations")}
        legacy = {obs["id"]: obs for obs in self.exported["observations"]}
        # The older matched comparison on thm-main is superseded by the newer carried one on the
        # same unchanged input; it stays in the archived legacy export, not in live records.
        carried = [obs for obs in legacy.values() if obs.get("carried_from") is not None][0]
        superseded = [obs for obs in legacy.values()
                      if obs["target"] == carried["target"] and obs["id"] != carried["id"]][0]
        self.assertEqual(set(observations), set(legacy))
        self.assertIs(observations[superseded["id"]]["context_data"]["applicable_on_import"], False)
        for oid, body in observations.items():
            old = legacy[oid]
            with self.subTest(observation=oid):
                self.assertEqual(body["target"], old["target"])
                self.assertEqual(body["result"], old["result"])
                self.assertEqual(body["reviewer"], old["reviewer"])
                self.assertEqual(body["note"], expected_note(old))
                self.assertEqual(body["created_at"], old["created_at"])
                self.assertEqual(body["evidence_refs"], [])
        self.assertIn(f"[legacy carried_from {carried['carried_from']}]",
                      observations[carried["id"]]["note"])
        self.assertEqual(result["limitations"].count(ARCHIVED_OBSERVATION_LIMITATION), 1)
        # Nothing is lost: the archived legacy export inside the identity map keeps every row.
        identity_map = db.heads("identity_maps")[0]
        archived = json.loads(db.get_blob(identity_map.body["source_blob"]).decode("utf-8"))
        self.assertEqual({obs["id"] for obs in archived["observations"]}, set(legacy))

    def test_migrated_database_validates_and_renders(self):
        """The overview renders with intermediates while ordinary audit writes remain unavailable."""
        self.migrate()
        payload, _ = run_cli("validate", self.db)
        self.assertIs(payload["ok"], True)
        self.assertEqual(payload["errors"], [])
        if node_available():
            html = self.path("legacy3", "overview.html")
            rejected, _ = run_cli("checkpoint", self.db, "--out", html, expect=4)
            self.assertEqual(rejected["error"]["code"], "LEGACY_PROTOCOL_READ_ONLY")
            self.assertFalse(html.exists())
            payload, _ = run_overview_cli(OVERVIEW_SCRIPTS, "render", self.db, html, "--full-diagnostics")
            self.assertTrue(html.is_file())
            self.assertEqual(payload["sha256"], sha(html.read_bytes()))

    def test_migrated_provenance_groups_render_with_their_case_uses(self):
        """Argument-less groups join the item details: the cases group keeps its case qualification."""
        self.migrate()
        with storage.Database(self.db) as db:
            projection = build_projection(db)

            def section(detail_key, section_key):
                detail = projection["details"][detail_key]
                return [ref["id"] for s in detail["sections"] if s["key"] == section_key
                        for ref in s["record_refs"]]

            remapped = [use.body["group_id"] for use in db.heads("application_details")
                        if use.id == "use-split-b"][0]
            theorem_groups = section("item:thm-main", "derivations")
            self.assertEqual([g for g in theorem_groups if g.startswith("grp")],
                             ["grp-cases-1", "grp-joint-1", remapped])
            self.assertEqual(section("item:lem-bridge", "derivations"), ["grp-split"])
            applications = section("item:thm-main", "applications")
            self.assertIn("use-clm-thm", applications)
            self.assertIn("use-drv-thm", applications)
        payload, _ = run_cli("validate", self.db)
        self.assertIs(payload["ok"], True)
        self.assertEqual(payload["projection_problems"], [])
        if node_available():
            html = self.path("legacy3", "overview-groups.html")
            run_overview_cli(OVERVIEW_SCRIPTS, "render", self.db, html)
            text = html.read_text(encoding="utf-8")
            self.assertIn("grp-cases-1", text)
            self.assertIn("base case", text)
            self.assertIn("inductive step", text)

    def test_migrated_database_requires_the_overview_bridge_feature(self):
        """The rebuilt file stamps overview-bridge/1; a core without that name refuses to open it."""
        self.migrate()
        with storage.Database(self.db) as db:
            features = json.loads(db.conn.execute("SELECT value FROM metadata WHERE key = 'features'")
                                  .fetchone()[0])
        self.assertIn("overview-bridge/1", features)
        older = tuple(name for name in storage.SUPPORTED_FEATURES if name != "overview-bridge/1")
        with mock.patch.object(storage, "SUPPORTED_FEATURES", older):
            with self.assertRaises(IncompatibleError) as caught:
                storage.Database(self.db)
        self.assertEqual(caught.exception.code, "INCOMPATIBLE")
        self.assertEqual(caught.exception.exit_code, 4)
        self.assertIn("overview-bridge/1", caught.exception.message)
        with storage.Database(self.db) as reopened:
            self.assertEqual(reopened.check_compatibility()["storage_format"], "4")

    def test_second_migration_is_refused_and_writes_nothing(self):
        """Re-running migrate-overview on the rebuilt file is ALREADY_MIGRATED at the CLI boundary."""
        self.migrate()
        migrated = self.db.read_bytes()
        second_backup = self.path("legacy3", "second.backup.db")
        payload, _ = run_cli("migrate-overview", self.db, "--backup", second_backup, expect=2)
        self.assertEqual(payload["error"]["code"], "ALREADY_MIGRATED")
        self.assertFalse(second_backup.exists())
        self.assertEqual(self.db.read_bytes(), migrated)


# -- unsupported overview versions ---------------------------------------------------------
class UnsupportedOverviewVersionTest(TempCase):
    def test_old_or_noninteger_versions_are_refused_without_writes(self):
        for version in (1, 2, 3.0, True):
            with self.subTest(version=version):
                path = self.path(f"unsupported-{version}.db")
                backup = self.path(f"unsupported-{version}.backup.db")
                with closing(sqlite3.connect(path)) as conn, conn:
                    conn.executescript("""
                        CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT);
                        CREATE TABLE current_snapshot(singleton INTEGER PRIMARY KEY, snapshot_id TEXT);
                        CREATE TABLE snapshots(id TEXT PRIMARY KEY, payload TEXT, created_at TEXT);
                        INSERT INTO metadata VALUES('format', 'archify-paper-database-1');
                        INSERT INTO current_snapshot VALUES(1, 'old');
                    """)
                    conn.execute("INSERT INTO snapshots VALUES(?,?,?)",
                                 ('old', json.dumps({'schema_version': version}), '2026-09-19'))
                original = path.read_bytes()
                payload, _ = run_cli('migrate-overview', path, '--backup', backup, expect=4)
                self.assertEqual(payload['error']['code'], 'INCOMPATIBLE')
                self.assertIn('native schema-3', payload['error']['message'])
                self.assertEqual(path.read_bytes(), original)
                self.assertFalse(backup.exists())


# -- review applicability across migration (F1) ------------------------------------------------------
REVIEW_TEX = "\n".join([
    r"\documentclass{article}",
    r"\begin{document}",
    r"\begin{lemma}\label{lem:base}",
    r"Every base map is monotone.",
    r"\end{lemma}",
    r"\begin{theorem}\label{thm:main}",
    r"The main theorem holds.",
    r"\end{theorem}",
    r"\end{document}"])
STALE_MATCH_NOTE = "Matched the original statement."
OLDER_MATCH_NOTE = "Lemma matches the source."
NEWER_CONCERN_NOTE = "On re-reading, the boundary drifts."


class OverviewBridgeReviewApplicabilityTest(TempCase):
    """F1: a stale or superseded legacy review must not migrate as current support.

    The fixture is the audit's two reproductions built with the v2 CLI: a matched comparison on
    the theorem goes stale when the recorded statement changes, and the unchanged lemma gets an
    older matched comparison followed by a newer needs_attention on the same input.
    """

    def setUp(self):
        super().setUp()
        self.src = self.work / "review" / "src"
        self.src.mkdir(parents=True)
        (self.src / "paper.tex").write_text(REVIEW_TEX, encoding="utf-8", newline="\n")
        files = [source_file("file-tex", "paper.tex", "text/plain", REVIEW_TEX.encode("utf-8"))]
        revision = source_revision_id(files)
        theorem = {"id": "thm-main", "kind": "theorem", "label": "Theorem 1", "caption": "The main theorem",
                   "statement": {"text": "The main theorem holds.", "form": "synopsis"},
                   "passages": [{"role": "statement", "anchor_id": "anc-thm"}], "aliases": ["thm:main"]}
        seed = {"schema_version": 3, "title": "Review paper", "scope": "Two results.",
                "source_revision": {"id": revision, "title": "Review sources",
                                    "created_at": "2026-09-18T00:00:00+00:00", "files": files},
                "anchors": [
                    anchor_row("anc-lem", revision, "file-tex",
                               {"start_line": 3, "end_line": 5, "label": "lem:base"},
                               line_excerpt(REVIEW_TEX.encode("utf-8"), 3, 5), "line_range, tex_label"),
                    anchor_row("anc-thm", revision, "file-tex",
                               {"start_line": 6, "end_line": 8, "label": "thm:main"},
                               line_excerpt(REVIEW_TEX.encode("utf-8"), 6, 8), "line_range, tex_label"),
                ],
                "items": [
                    {"id": "lem-base", "kind": "lemma", "label": "Lemma 1", "caption": "The base lemma",
                     "statement": {"text": "Every base map is monotone.", "form": "synopsis"},
                     "passages": [{"role": "statement", "anchor_id": "anc-lem"}], "aliases": ["lem:base"]},
                    theorem,
                ],
                "uses": [{"id": "use-lem-thm", "from": "lem-base", "to": "thm-main", "type": "proof_argument",
                          "reason": "Monotonicity enters the main argument.", "evidence_refs": ["anc-lem"]}],
                "observations": [], "main_items": ["lem-base", "thm-main"]}
        self.db = self.path("review", "overview.db")
        self.backup = self.path("review", "overview.backup.db")
        seed_path = write_json(self.src / "overview-seed.json", seed)
        info, _ = run_overview_cli(OVERVIEW_SCRIPTS, "init", self.db, seed_path)
        snap1 = info["snapshot_id"]
        batch = write_json(self.path("review", "compare1.json"),
                           {"basis": "typeset", "expected_snapshot": snap1, "targets": [R("items", "thm-main")],
                            "reviewer": "reader-a", "result": "matched", "note": STALE_MATCH_NOTE})
        run_overview_cli(OVERVIEW_SCRIPTS, "compare", self.db, batch)
        changed = dict(theorem, statement={"text": "The main theorem holds for all base maps.",
                                           "form": "synopsis"})
        batch = write_json(self.path("review", "apply1.json"),
                           {"expected_snapshot": snap1,
                            "edits": [{"collection": "items", "op": "upsert", "id": "thm-main",
                                       "record": changed}]})
        applied, _ = run_overview_cli(OVERVIEW_SCRIPTS, "apply", self.db, batch)
        snap2 = applied["snapshot_id"]
        batch = write_json(self.path("review", "compare2.json"),
                           {"basis": "typeset", "expected_snapshot": snap2, "targets": [R("items", "lem-base")],
                            "reviewer": "reader-a", "result": "matched", "note": OLDER_MATCH_NOTE})
        run_overview_cli(OVERVIEW_SCRIPTS, "compare", self.db, batch)
        batch = write_json(self.path("review", "compare3.json"),
                           {"basis": "typeset", "expected_snapshot": snap2, "targets": [R("items", "lem-base")],
                            "reviewer": "reader-b", "result": "needs_attention",
                            "note": NEWER_CONCERN_NOTE})
        run_overview_cli(OVERVIEW_SCRIPTS, "compare", self.db, batch)
        batch = write_json(self.path("review", "compare4.json"),
                           {"basis": "typeset", "expected_snapshot": snap2, "targets": [R("uses", "use-lem-thm")],
                            "reviewer": "reader-a", "result": "matched", "note": "Use matches."})
        run_overview_cli(OVERVIEW_SCRIPTS, "compare", self.db, batch)
        export_path = self.path("review", "export.json")
        run_overview_cli(OVERVIEW_SCRIPTS, "export", self.db, export_path)
        self.exported = json.loads(export_path.read_text(encoding="utf-8"))

    def migrate(self) -> dict:
        payload, _ = run_cli("migrate-overview", self.db, "--backup", self.backup)
        return payload

    def legacy_by_note(self, note: str) -> dict:
        return next(obs for obs in self.exported["observations"] if obs["note"] == note)

    def register_audit(self):
        """A focused audit over both items, recorded through the ordinary acceptance path."""
        with storage.Database(self.db, write=True) as db:
            paper = storage.paper_record(db)
            targets = [R("items", "thm-main"), R("items", "lem-base")]
            packet = packets.get_packet(db, targets=targets, mode="primary")
            acceptance.apply_batch(db, {"contract_version": 3, "request_id": "req_bridge_audit",
                                        "packet_id": packet["packet_id"],
                                        "edits": [edit("create", "audits", "aud_1", {
                                            "paper_id": paper.id, "mode": "focused", "targets": targets,
                                            "exclusions": [], "protocol_version": "item-audit/1",
                                            "independent_required": False, "qualification_id": None,
                                            "report_path": "",
                                            "global_tasks": [dict(task) for task in GLOBAL_TASKS]})]})

    def fidelity_constituent(self, item_id: str) -> dict:
        with storage.Database(self.db) as db:
            result = derive_assessment(db, audit_id="aud_1")
        oid = obligation_id("aud_1", R("items", item_id), "source_fidelity", "primary")
        return result["constituents"][oid]

    def test_migration_preserves_stale_and_superseded_reviews_without_current_credit(self):
        """All observations survive, with only the two applicable inputs current."""
        result = self.migrate()
        self.assertEqual(result["counts"]["observations"], 4)
        self.assertIn(archived_observation_limitation(2), result["limitations"])
        with storage.Database(self.db) as db:
            observations = {obs.id: obs.body for obs in db.heads("observations")}
            identity_map = db.heads("identity_maps")[0]
            archived = json.loads(db.get_blob(identity_map.body["source_blob"]).decode("utf-8"))
        stale, older = self.legacy_by_note(STALE_MATCH_NOTE), self.legacy_by_note(OLDER_MATCH_NOTE)
        newer = self.legacy_by_note(NEWER_CONCERN_NOTE)
        self.assertIs(observations[stale["id"]]["context_data"]["applicable_on_import"], False)
        self.assertIs(observations[older["id"]]["context_data"]["applicable_on_import"], False)
        self.assertEqual({identity for identity, body in observations.items() if body["context_data"]["applicable_on_import"]},
                         {newer["id"], self.legacy_by_note("Use matches.")["id"]})
        self.assertEqual({obs["id"] for obs in archived["observations"]},
                         {obs["id"] for obs in self.exported["observations"]})
        concern = observations[newer["id"]]
        self.assertEqual(concern["result"], "needs_attention")
        self.assertEqual(concern["created_at"], newer["created_at"])
        self.assertEqual(concern["note"], expected_note(newer))

    def test_a_stale_match_is_not_current_support_in_status(self):
        """F1(a): the theorem's source-fidelity obligation is unmet, not supported by stale history."""
        self.migrate()
        self.register_audit()
        thm_oid = obligation_id("aud_1", R("items", "thm-main"), "source_fidelity", "primary")
        lem_oid = obligation_id("aud_1", R("items", "lem-base"), "source_fidelity", "primary")
        payload, _ = run_cli("status", self.db)
        self.assertIn(thm_oid, payload["obligations"]["required"])
        self.assertIn(thm_oid, payload["obligations"]["unsatisfied"])
        self.assertNotIn(lem_oid, payload["obligations"]["unsatisfied"])
        constituent = self.fidelity_constituent("thm-main")
        self.assertEqual(constituent["state"], "complete")
        self.assertEqual(constituent["freshness"], "needs_review")
        self.assertEqual([ref["id"] for ref in constituent["check_refs"]], [self.legacy_by_note(STALE_MATCH_NOTE)["id"]])

    def test_the_newer_concern_outranks_the_older_match_in_status(self):
        """F1(b): on unchanged content the newer needs_attention, not the older match, is current."""
        self.migrate()
        self.register_audit()
        constituent = self.fidelity_constituent("lem-base")
        self.assertEqual(constituent["state"], "complete")
        self.assertEqual(constituent["freshness"], "current")
        self.assertEqual(constituent["outcome"], "needs_attention")
        newer = self.legacy_by_note(NEWER_CONCERN_NOTE)
        self.assertEqual([ref["id"] for ref in constituent["check_refs"]], [newer["id"]])
        payload, _ = run_cli("status", self.db)
        assessment = payload["assessments"]["items:lem-base"]
        self.assertIn("source attention", assessment["explanation"])

    def test_a_comparison_after_migration_outranks_the_imported_history(self):
        """created_at orders the legacy past; a post-migration comparison is newer by revision."""
        self.migrate()
        self.register_audit()
        with storage.Database(self.db, write=True) as db:
            packet = packets.get_packet(db, targets=[R("items", "lem-base")], mode="primary")
            review.compare(db, batch={"contract_version": 3, "request_id": "req_bridge_compare",
                                      "packet_id": packet["packet_id"],
                                      "edits": [edit("create", "observations", "obs_post_migration", {
                                          "target": R("items", "lem-base"), "result": "matched",
                                          "reviewer": "reader-c", "note": "Re-checked after the migration.",
                                          "evidence_refs": []})]})
        with storage.Database(self.db) as db:
            body = db.head("observations", "obs_post_migration").body
        self.assertNotIn("created_at", body)
        constituent = self.fidelity_constituent("lem-base")
        self.assertEqual(constituent["outcome"], "supported")
        self.assertEqual(constituent["freshness"], "current")
        self.assertEqual([ref["id"] for ref in constituent["check_refs"]], ["obs_post_migration"])


# -- scope and unavailable sources across migration (F3) ---------------------------------------------
SCOPE_TEX = "\n".join([
    r"\documentclass{article}",
    r"\begin{document}",
    r"\begin{lemma}\label{lem:base}",
    r"Every base map is monotone.",
    r"\end{lemma}",
    r"\begin{theorem}\label{thm:main}",
    r"The main theorem holds.",
    r"\end{theorem}",
    r"\input{missing-appendix}",
    r"\end{document}"])
SCOPE_TEXT = "Main text only; the supplementary appendix proofs are unavailable and excluded."
EXCLUSION_TEXT = "The supplementary appendix proofs are not captured; their results are out of scope."
UNRESOLVED_TEXT = "paper.tex: unresolved input 'missing-appendix'; register or explain the missing source."


class OverviewBridgeScopeTest(TempCase):
    """F3: scope, exclusions and unavailable sources stay actively disclosed after migration."""

    def setUp(self):
        super().setUp()
        self.src = self.work / "scope" / "src"
        self.src.mkdir(parents=True)
        (self.src / "paper.tex").write_text(SCOPE_TEX, encoding="utf-8", newline="\n")
        files = [source_file("file-tex", "paper.tex", "text/plain", SCOPE_TEX.encode("utf-8"))]
        revision = source_revision_id(files)
        seed = {"schema_version": 3, "title": "Scoped paper", "scope": SCOPE_TEXT,
                "source_revision": {"id": revision, "title": "Scoped sources",
                                    "created_at": "2026-09-18T00:00:00+00:00", "files": files},
                "anchors": [
                    anchor_row("anc-lem", revision, "file-tex",
                               {"start_line": 3, "end_line": 5, "label": "lem:base"},
                               line_excerpt(SCOPE_TEX.encode("utf-8"), 3, 5), "line_range, tex_label"),
                    anchor_row("anc-thm", revision, "file-tex",
                               {"start_line": 6, "end_line": 8, "label": "thm:main"},
                               line_excerpt(SCOPE_TEX.encode("utf-8"), 6, 8), "line_range, tex_label"),
                ],
                "items": [
                    {"id": "lem-base", "kind": "lemma", "label": "Lemma 1", "caption": "The base lemma",
                     "statement": {"text": "Every base map is monotone.", "form": "synopsis"},
                     "passages": [{"role": "statement", "anchor_id": "anc-lem"}], "aliases": ["lem:base"]},
                    {"id": "thm-main", "kind": "theorem", "label": "Theorem 1", "caption": "The main theorem",
                     "statement": {"text": "The main theorem holds.", "form": "synopsis"},
                     "passages": [{"role": "statement", "anchor_id": "anc-thm"}], "aliases": ["thm:main"]},
                ],
                "uses": [{"id": "use-lem-thm", "from": "lem-base", "to": "thm-main", "type": "proof_argument",
                          "reason": "Monotonicity enters the main argument.", "evidence_refs": ["anc-lem"]}],
                "observations": [], "main_items": ["lem-base", "thm-main"]}
        self.db = self.path("scope", "overview.db")
        self.backup = self.path("scope", "overview.backup.db")
        seed_path = write_json(self.src / "overview-seed.json", seed)
        info, _ = run_overview_cli(OVERVIEW_SCRIPTS, "init", self.db, seed_path)
        snap1 = info["snapshot_id"]
        batch = write_json(self.path("scope", "apply1.json"),
                           {"expected_snapshot": snap1, "edits": [],
                            "set": {"inventory": {"excluded": [EXCLUSION_TEXT]}}})
        applied, _ = run_overview_cli(OVERVIEW_SCRIPTS, "apply", self.db, batch)
        run_overview_cli(OVERVIEW_SCRIPTS, "refresh", self.db,
                         "--expected-snapshot", applied["snapshot_id"])
        export_path = self.path("scope", "export.json")
        run_overview_cli(OVERVIEW_SCRIPTS, "export", self.db, export_path)
        self.exported = json.loads(export_path.read_text(encoding="utf-8"))

    def migrate(self) -> dict:
        payload, _ = run_cli("migrate-overview", self.db, "--backup", self.backup)
        return payload

    def test_fixture_records_the_scope_exclusion_and_the_unresolved_input(self):
        """The v2 CLI itself reports the missing appendix in inventory.unresolved."""
        self.assertEqual(self.exported["scope"], SCOPE_TEXT)
        self.assertEqual(self.exported["inventory"]["excluded"], [EXCLUSION_TEXT])
        self.assertEqual(self.exported["inventory"]["unresolved"], [UNRESOLVED_TEXT])

    def test_scope_and_exclusions_reach_the_paper_record(self):
        """The migrated paper discloses the restriction in live records, not only in the archive."""
        result = self.migrate()
        self.assertEqual(result["limitations"], [])
        self.assertEqual(result["counts"]["source_issues"], 1)
        with storage.Database(self.db) as db:
            paper = storage.paper_record(db)
        self.assertEqual(paper.body["scope"], SCOPE_TEXT)
        self.assertEqual(paper.body["exclusions"], [EXCLUSION_TEXT])
        payload, _ = run_cli("status", self.db)
        self.assertEqual(payload["paper"]["scope"], SCOPE_TEXT)
        self.assertEqual(payload["paper"]["exclusions"], [EXCLUSION_TEXT])

    def test_the_missing_source_becomes_an_open_issue(self):
        """The unresolved appendix is an open missing_source issue on its importing source."""
        self.migrate()
        with storage.Database(self.db) as db:
            issues = db.heads("source_issues")
            sources = {source.id: source.body for source in db.heads("sources")}
        self.assertEqual(len(issues), 1)
        body = issues[0].body
        self.assertEqual(body["category"], "missing_source")
        self.assertEqual(body["lifecycle"], "open")
        self.assertIsNone(body["resolution"])
        self.assertEqual(body["description"], UNRESOLVED_TEXT)
        self.assertEqual(sources[body["source_id"]]["path"], "paper.tex")
        payload, _ = run_cli("status", self.db)
        self.assertEqual(payload["source_limits"],
                         [{"collection": "source_issues", "id": issues[0].id, "version": 1}])
        payload, _ = run_cli("validate", self.db)
        self.assertIs(payload["ok"], True)
        self.assertEqual(payload["projection_problems"], [])

    def checkpoint_summary(self, database=None, audit=None):
        html = self.path("scope", "checkpoint.html")
        args = ["checkpoint", database or self.db, "--out", html]
        if audit is not None:
            args.extend(["--audit", audit])
        run_cli(*args)
        # Inspect the visible summary, not the embedded projection JSON.
        match = re.search(r'<section id="proof-summary"[^>]*>.*?</section>',
                          html.read_text(encoding="utf-8"), re.S)
        self.assertIsNotNone(match)
        return match.group(0)

    @unittest.skipUnless(node_available(), "Node.js is needed for checkpoint rendering")
    def test_checkpoint_discloses_original_boundaries_and_missing_source(self):
        """The visible reader keeps original coverage, not a whole-paper coverage claim."""
        self.migrate()
        with storage.Database(self.db) as db:
            summary = build_projection(db)["summary"]
        self.assertEqual(summary["overview_scope"], {"text": SCOPE_TEXT, "exclusions": [EXCLUSION_TEXT]})
        self.assertEqual(summary["scope"], {"mode": "overview", "target_refs": [], "exclusions": []})
        visible = self.checkpoint_summary()
        self.assertIn(SCOPE_TEXT, visible)
        self.assertIn(EXCLUSION_TEXT, visible)
        self.assertIn("missing-appendix", visible)
        self.assertIn("Original overview boundaries", visible)
        self.assertIn("Recorded items; no audit selected", visible)
        self.assertNotIn("whole paper", visible)

    @unittest.skipUnless(node_available(), "Node.js is needed for checkpoint rendering")
    def test_audit_selection_stays_distinct_from_original_overview_boundaries(self):
        self.migrate()
        targets = [R("items", "thm-main")]
        exclusion = {"target": R("items", "lem-base"), "source_anchor_ids": [],
                     "reason": "The base lemma is outside this focused audit.",
                     "consequence": "Its proof is not audited here."}
        with storage.Database(self.db, write=True) as db:
            paper = storage.paper_record(db)
            packet = packets.get_packet(db, targets=targets + [R("items", "lem-base")], mode="primary")
            acceptance.apply_batch(db, {"contract_version": 3, "request_id": "req_scope_audit",
                                        "packet_id": packet["packet_id"],
                                        "edits": [edit("create", "audits", "aud_scope", {
                                            "paper_id": paper.id, "mode": "focused", "targets": targets,
                                            "exclusions": [exclusion], "protocol_version": "item-audit/1",
                                            "independent_required": False, "qualification_id": None,
                                            "report_path": "",
                                            "global_tasks": [dict(task) for task in GLOBAL_TASKS]})]})
            summary = build_projection(db, audit_id="aud_scope")["summary"]
        self.assertEqual(summary["scope"], {"mode": "focused", "target_refs": targets, "exclusions": [exclusion]})
        self.assertEqual(summary["overview_scope"], {"text": SCOPE_TEXT, "exclusions": [EXCLUSION_TEXT]})
        visible = self.checkpoint_summary(audit="aud_scope")
        self.assertIn(SCOPE_TEXT, visible)
        self.assertIn(EXCLUSION_TEXT, visible)
        self.assertIn(exclusion["reason"], visible)
        self.assertIn('data-jump-record="items:thm-main:1"', visible)
        self.assertNotIn("Recorded items; no audit selected", visible)
        self.assertNotIn("whole paper", visible)

    @unittest.skipUnless(node_available(), "Node.js is needed for checkpoint rendering")
    def test_native_reports_do_not_invent_original_overview_boundaries(self):
        fixture = Fixture(self.work / "native").structure()
        with fixture.open(write=False) as db:
            self.assertNotIn("overview_scope", build_projection(db)["summary"])
        visible = self.checkpoint_summary(database=fixture.path)
        self.assertNotIn("Original overview boundaries", visible)
        self.assertIn("Recorded items; no audit selected", visible)
        self.assertNotIn("whole paper", visible)
        fixture.audit()
        visible = self.checkpoint_summary(database=fixture.path, audit="aud_1")
        self.assertIn('data-jump-record="items:itm_lem:1"', visible)
        self.assertIn('data-jump-record="items:itm_thm:1"', visible)
        self.assertNotIn("Original overview boundaries", visible)
        self.assertNotIn("Recorded items; no audit selected", visible)
        self.assertNotIn("whole paper", visible)


# -- loud refusals ---------------------------------------------------------------------------
class OverviewBridgeRefusalTest(TempCase):
    """Locators an overview recorded without mechanical checks get a loud refusal, never a silent drop."""

    def build(self, extra_anchor) -> Path:
        src = self.work / "refusal" / "src"
        src.mkdir(parents=True, exist_ok=True)
        (src / "paper.tex").write_text(BRIDGE_TEX, encoding="utf-8", newline="\n")
        files = [source_file("file-tex", "paper.tex", "text/plain", BRIDGE_TEX.encode("utf-8"))]
        revision = source_revision_id(files)
        seed = {"schema_version": 3, "title": "Refusal fixture", "scope": "One lemma.",
                "source_revision": {"id": revision, "title": "Refusal sources",
                                    "created_at": "2026-09-17T00:00:00+00:00", "files": files},
                "anchors": [anchor_row("anc-lem", revision, "file-tex",
                                       {"start_line": 3, "end_line": 5, "label": "lem:bridge"},
                                       line_excerpt(BRIDGE_TEX.encode("utf-8"), 3, 5),
                                       "line_range, tex_label"),
                            extra_anchor(revision)],
                "items": [{"id": "lem-bridge", "kind": "lemma", "label": "Lemma 1", "caption": "The bridge lemma",
                           "statement": {"text": "Every bridge map is monotone.", "form": "synopsis"},
                           "passages": [{"role": "statement", "anchor_id": "anc-lem"}]}],
                "uses": [], "observations": []}
        db = self.path("refusal", "overview.db")
        info, _ = run_overview_cli(OVERVIEW_SCRIPTS, "init", db, write_json(src / "overview-seed.json", seed))
        self.snapshot_id = info["snapshot_id"]
        self.original = db.read_bytes()
        return db

    def assert_refused_after_backup(self, db, payload, backup, phrase):
        """The legacy file keeps every byte; the verified pre-rebuild backup survives the refusal."""
        self.assertEqual(payload["error"]["code"], "INCOMPATIBLE")
        self.assertIn("anc-bad", payload["error"]["message"])
        self.assertIn(phrase, payload["error"]["message"])
        self.assertEqual(db.read_bytes(), self.original)
        conn = sqlite3.connect(backup.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            row = conn.execute("SELECT snapshot_id FROM current_snapshot WHERE singleton = 1").fetchone()
        finally:
            conn.close()
        self.assertEqual(row[0], self.snapshot_id)

    def test_a_page_locator_on_a_text_source_is_refused(self):
        """A reviewed page of a non-PDF has no contract-3 meaning; migrate-overview says so."""
        db = self.build(lambda revision: anchor_row(
            "anc-bad", revision, "file-tex", {"page": 1}, "", "entered_locator", status="unverified",
            note="The entered physical PDF page has not been checked against a captured PDF."))
        backup = self.path("refusal", "overview.backup.db")
        payload, _ = run_cli("migrate-overview", db, "--backup", backup, expect=4)
        self.assert_refused_after_backup(db, payload, backup, "not a captured PDF")

    def test_an_anchor_without_a_source_file_is_refused(self):
        """An overview anchor may lack file_id; a contract-3 anchor must name a captured source."""
        db = self.build(lambda revision: anchor_row(
            "anc-bad", revision, None, {"label": "lem:bridge"}, "", "entered_locator", status="unverified",
            note="No file content is registered for this locator."))
        backup = self.path("refusal", "overview.backup.db")
        payload, _ = run_cli("migrate-overview", db, "--backup", backup, expect=4)
        self.assert_refused_after_backup(db, payload, backup, "no registered source file")


if __name__ == "__main__":
    unittest.main()
