"""Overview edits preserve examinations while current support follows consumed inputs."""
import base64
from copy import deepcopy

from support import Fixture, R, TempCase, edit
import test_v3_engine as engine_tests
from paper_core import acceptance, assessment, finalization, overview, storage
from paper_core.canonical import digest, sha256_bytes


class OverviewPreservationTests(TempCase):
    def setUp(self):
        super().setUp()
        self.fx = Fixture(self.path("case")).audit(independent_required=False)
        engine_tests.CoherentEngineTests.primary_units(self, self.fx)
        with self.fx.open() as db:
            paper = storage.paper_record(db)
            files = [{"id": r.id, "path": r.body["path"], "media_type": "text/plain",
                      "sha256": r.body["blob_sha256"],
                      "content_base64": base64.b64encode(db.get_blob(r.body["blob_sha256"])).decode("ascii")}
                     for r in db.heads("sources")]
            anchors = [{"id": r.id, "file_id": r.body["source_id"], "locator": r.body["locator"],
                        "excerpt": r.body["excerpt"], "excerpt_hash": r.body["excerpt_sha256"],
                        "verification": {"status": "checked", "method": r.body["method"]}}
                       for r in db.heads("anchors")]
            items = [{"id": r.id, **{k: deepcopy(r.body[k]) for k in ("kind", "label", "caption", "statement", "passages")}}
                     for r in db.heads("items")]
            uses = [{"id": r.id, "from": r.body["from"]["id"], "to": r.body["to"]["id"],
                     **{k: deepcopy(r.body[k]) for k in ("type", "reason", "regime", "evidence_refs")}}
                    for r in db.heads("uses")]
            data = {"schema_version": 3, "title": paper.body["title"], "scope": "Selected audited statements",
                    "source_revision": {"title": "Captured manuscript", "created_at": "2026-10-09T00:00:00Z", "files": files},
                    "items": items, "uses": uses, "anchors": anchors, "observations": [], "main_items": []}
            body = dict(paper.body, scope=data["scope"])
            edits = [edit("replace", "papers", paper.id, body, paper.version),
                     edit("create", "overview_selections", overview.SELECTION_ID,
                          overview.selection_body(paper.id, data, profile="focused"))]
            acceptance.accept(db, request_id="select-overview", request_digest=digest(edits), packet_id=None,
                              edits=edits, command="overview")
            self.baseline_revision = db.max_revision()
            self.baseline_checks = [r for r in db.all_versions() if r.collection == "checks"]
            self.baseline_bindings = db.conn.execute("SELECT * FROM evidence_bindings ORDER BY owner_collection,owner_id,owner_version").fetchall()
            self.baseline_bindings = [tuple(row) for row in self.baseline_bindings]
            self.assertEqual(assessment.derive_assessment(db, audit_id="aud_1")["support"],
                             {"items:itm_lem": "available", "items:itm_thm": "available"})

    def update(self, change):
        with storage.Database(self.fx.path, write=True, write_scope="overview") as db:
            db.begin_immediate()
            before, _ = overview.project(db)
            after = deepcopy(before)
            change(after)
            overview.update(db, before, after, profile="focused")
            db.commit()

    def assert_history(self, db):
        self.assertEqual([r for r in db.all_versions() if r.collection == "checks"], self.baseline_checks)
        self.assertEqual([tuple(row) for row in db.conn.execute(
            "SELECT * FROM evidence_bindings ORDER BY owner_collection,owner_id,owner_version").fetchall()], self.baseline_bindings)

    def test_presentation_edit_keeps_support_and_frozen_science(self):
        frozen_dir = self.path("frozen")
        with self.fx.open(write=False) as db:
            finalization.finalize_audit(db, audit_id="aud_1", output=frozen_dir)
        original = {p.name: p.read_bytes() for p in frozen_dir.iterdir() if p.is_file()}
        self.update(lambda data: data["items"][0].update(caption="A clearer caption", proof_idea="Apply the lemma, then conclude."))
        with self.fx.open(write=False) as db:
            self.assert_history(db)
            result = assessment.derive_assessment(db, audit_id="aud_1")
            self.assertEqual(set(result["support"].values()), {"available"})
            past = assessment.derive_assessment(db, revision=self.baseline_revision, audit_id="aud_1")
            self.assertEqual(set(past["support"].values()), {"available"})
        self.assertEqual({p.name: p.read_bytes() for p in frozen_dir.iterdir() if p.is_file()}, original)
        snapshot, _ = finalization.load_finalization(frozen_dir)
        self.assertEqual(snapshot["revision"], self.baseline_revision)

    def test_changed_consumed_hypothesis_withdraws_current_support(self):
        self.update(lambda data: data["items"][0].update(statement={"form": "synopsis", "text": "The bound requires a new hypothesis."}))
        with self.fx.open(write=False) as db:
            self.assert_history(db)
            result = assessment.derive_assessment(db, audit_id="aud_1")
            self.assertNotEqual(result["support"]["items:itm_lem"], "available")
            self.assertNotEqual(result["support"]["items:itm_thm"], "available")
            snap = assessment.Snapshot(db, db.max_revision())
            self.assertEqual(assessment.judgment_freshness(snap, db.head("checks", "chk_comp_thm"), superseded=False)["freshness"], "needs_review")
            self.assertEqual(assessment.judgment_freshness(snap, db.head("observations", "obs_lem"), superseded=False)["freshness"], "historical")

    def test_changed_source_bytes_withdraw_consuming_support(self):
        def change(data):
            source = data["source_revision"]["files"][0]
            raw = base64.b64decode(source["content_base64"]) + b"% A material source revision.\n"
            source.update(content_base64=base64.b64encode(raw).decode("ascii"), sha256=sha256_bytes(raw))
        self.update(change)
        with self.fx.open(write=False) as db:
            self.assert_history(db)
            result = assessment.derive_assessment(db, audit_id="aud_1")
            self.assertTrue(all(value != "available" for value in result["support"].values()))
            snap = assessment.Snapshot(db, db.max_revision())
            for check in db.heads("checks"):
                # A changed coherent unit is historical; the immutable whole
                # examination no longer describes that unit's written inputs.
                self.assertEqual(assessment.judgment_freshness(snap, check, superseded=False)["freshness"], "historical")

    def test_changed_passage_does_not_invalidate_unrelated_unit(self):
        def change(data):
            raw = b"A corrected proof of the theorem.\n"
            data["source_revision"]["files"].append({"id": "source-corrected-proof", "path": "corrected-proof.txt",
                "media_type": "text/plain", "sha256": sha256_bytes(raw),
                "content_base64": base64.b64encode(raw).decode("ascii")})
            anchor = next(r for r in data["anchors"] if r["id"] == "anc_thm_proof")
            anchor.update(file_id="source-corrected-proof", locator={"start_line": 1, "end_line": 1},
                          excerpt=raw.decode("utf-8").strip(), excerpt_hash=sha256_bytes(raw.decode("utf-8").strip().encode("utf-8")))
        self.update(change)
        with self.fx.open(write=False) as db:
            self.assert_history(db)
            snap = assessment.Snapshot(db, db.max_revision())
            self.assertEqual(assessment.judgment_freshness(snap, db.head("checks", "chk_comp_lem"), superseded=False)["freshness"], "current")
            self.assertEqual(assessment.judgment_freshness(snap, db.head("checks", "chk_comp_thm"), superseded=False)["freshness"], "historical")
