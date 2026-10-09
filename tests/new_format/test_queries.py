"""Behaviour tests for ``paper_core.queries`` (implementation-handoff 5 and 9).

``queries`` is the read-only face of the database: ``status`` answers "where is this audit", ``changes``
answers "what moved since revision N and which judgments that stales", and ``validate_snapshot`` answers
"is this snapshot internally consistent". None of the three may ever write, and none may turn an
incomplete mathematical assessment into an error, so these tests pin the exact keys, the exact derived
values at each fixture stage, the exact error codes on the failure paths, and the fact that a database
whose rows have been corrupted behind the append-only triggers is *reported*, not raised.

Two rules keep the failure paths honest. Every rejection test runs against a database opened for
*writing*, so "nothing was written" is a claim the query could actually break rather than something the
read-only connection guaranteed for free; and every corruption case works on a copy of the fixture
database, so the original is never mutated.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import unittest
from pathlib import Path

from support import R, TempCase, edit, locator, node_available

from paper_core import (CONTRACT_NAME, CONTRACT_VERSION, CORE_VERSION, DEFAULT_FEATURES, PROJECTION_VERSION, STORAGE_FORMAT,
                        SUPPORTED_FEATURES, acceptance, assessment, packets, projection, publish, queries, review,
                        sources, storage)
from paper_core.errors import InvalidRequest

# The documented result surface of status(); a query that grows or loses a key breaks its callers.
STATUS_KEYS = {"revision", "head_revision", "storage", "paper", "counts", "sources", "audit", "audits",
               "mode", "process_complete", "progress", "obligations", "assessments", "independent",
               "findings", "source_limits", "published_revision", "publications", "context", "problems", "factual_summary",
               "coverage_diagnostics", "coverage_diagnostic_count", "coverage_diagnostics_truncated"}
CHANGES_KEYS = {"since", "revision", "total", "limit", "offset", "returned", "next_offset", "records",
                "source_context", "affected_checks"}
VALIDATE_KEYS = {"revision", "ok", "records", "errors", "warnings", "stale_bindings", "projection_problems",
                 "integrity"}
PUBLIC_ASSESSMENT_KEYS = {"state", "label", "explanation", "check_refs", "finding_refs",
                          "missing_obligation_ids", "independent_review"}
CONTEXT_KEYS = {"source_context_digest", "judgments_in_older_context"}

# Stage values verified against the real API by the manual validation pass (support.Fixture).
STRUCTURE_COUNTS = {"anchors": 4, "application_details": 1, "arguments": 2, "groups": 2, "items": 2, "papers": 1, "scopes": 1,
                    "sources": 1, "uses": 1}
COMPLETE_COUNTS = {"anchors": 4, "application_details": 1, "arguments": 2, "audits": 1, "checks": 7, "coverage": 2, "groups": 2, "identity_maps": 2,
                   "items": 2, "observations": 4, "papers": 1, "proof_boundaries": 2, "qualifications": 1, "reconciliations": 2,
                   "responses": 2, "scopes": 1, "source_reviews": 1, "sources": 1, "target_specs": 2, "uses": 1}
PROGRESS_OVERVIEW = {"process_complete": False, "required_obligations": 0, "completed_current_obligations": 0,
                     "draft_checks": 0, "major_results": 0, "source_unbound_items": 0}
PROGRESS_AFTER_AUDIT = {"process_complete": False, "required_obligations": 13,
                        "completed_current_obligations": 0, "draft_checks": 0, "major_results": 2,
                        "source_unbound_items": 0}
PROGRESS_AFTER_PRIMARY = {"process_complete": False, "required_obligations": 13,
                          "completed_current_obligations": 9, "draft_checks": 0, "major_results": 2,
                          "source_unbound_items": 0}
PROGRESS_AFTER_COMPLETE = {"process_complete": True, "required_obligations": 13,
                           "completed_current_obligations": 13, "draft_checks": 0, "major_results": 2,
                           "source_unbound_items": 0}
EMPTY_FINDINGS = {"open": [], "resolved": [], "superseded": [], "refs": []}
ASSESSED_KEYS = {"arguments:arg_lem", "arguments:arg_thm", "audits:aud_1", "groups:grp_lem", "groups:grp_thm",
                 "items:itm_lem", "items:itm_thm", "uses:use_lem_thm"}
SKIPPED_PROJECTION = "projection skipped because the snapshot has contract violations"
PRIMARY_CHECK_IDS = ["chk_app", "chk_comp_lem", "chk_comp_thm", "chk_der_lem", "chk_der_thm"]
# validate_snapshot scans every bound collection, so the compared statement is stale too; changes() scans
# only checks.
STALE_AFTER_LEMMA_EDIT = sorted(PRIMARY_CHECK_IDS + ["obs_lem", "obs_exact_lem"])
ISO_UTC = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$"
SHA256_HEX = r"^[0-9a-f]{64}$"

EXTRA_SCOPE = {"argument_id": None, "parent_id": None, "assumptions": [], "binders": [], "conditions": [],
               "evidence_refs": []}
REVISED_LEMMA = {"kind": "lemma", "label": "Lemma 1", "caption": "Lemma 1 (revised)",
                 "statement": {"form": "verbatim", "text": "Lemma 1 text revised"},
                 "passages": [{"role": "statement", "anchor_id": "anc_lem"},
                              {"role": "proof", "anchor_id": "anc_lem_proof"}],
                 "aliases": [], "uncertainty": None, "origin": "source", "owner_id": None, "scope_id": None}
TRIAGE_AUDIT = {"mode": "triage", "targets": [R("items", "itm_thm")], "exclusions": [],
                "protocol_version": "item-audit/1", "independent_required": False,
                "qualification_id": "qua_r1", "report_path": "reports/triage.html", "global_tasks": []}
OPEN_ISSUE = {"source_id": None, "anchor_id": "anc_lem", "category": "locator_limit",
              "description": "the lemma label resolves ambiguously", "lifecycle": "open",
              "resolution": None, "reviewer": "checker-A"}
OPEN_FINDING = {"audit_id": "aud_1", "target": R("arguments", "arg_lem"), "category": "proof_gap",
                "lifecycle": "open", "description": "the induction step is not justified",
                "evidence_refs": ["anc_lem_proof"], "check_refs": [], "affected_uses": [],
                "impact_reason": "the lemma is used by the theorem", "resolution": None}


def retire_edit(collection: str, id: str, version: int, reason: str) -> dict:
    """A retire edit; it carries a reason instead of a body, so ``support.edit`` cannot build it."""
    return {"op": "retire", "collection": collection, "id": id, "expected_version": version, "reason": reason}


def corrupt_copy(source, destination, statements) -> Path:
    """Copy a database and mutate the copy behind the append-only trigger; the original is untouched."""
    shutil.copy2(source, destination)
    conn = sqlite3.connect(str(destination))
    try:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("DROP TRIGGER immutable_versions_update")
        for sql, params in statements:
            conn.execute(sql, params)
        conn.commit()
    finally:
        conn.close()
    return Path(destination)


def body_sql(collection: str, id: str, version: int, body) -> tuple:
    return ("UPDATE record_versions SET body_json = ? WHERE collection = ? AND id = ? AND version = ?",
            (json.dumps(body, sort_keys=True), collection, id, version))


def file_digest(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def replace_the_lemma(fixture) -> None:
    """Commit a new version of the judged lemma, which stales every judgment bound to its statement."""
    with fixture.open() as db:
        fixture.apply(db, [edit("replace", "items", "itm_lem", dict(REVISED_LEMMA), expected=1)],
                      *fixture.ITEMS, mode="author")


class QueryCase(TempCase):
    """Shared assertions for read-only queries."""

    def frozen(self, db):
        """A fingerprint of everything a read-only query must leave alone, the file bytes included."""
        return (db.max_revision(), len(db.all_versions()), len(db.publications()), file_digest(db.path))

    def assert_invalid(self, code, call, *args, **kwargs):
        """Assert the call raises ``InvalidRequest`` with ``code`` and returns the error for inspection."""
        with self.assertRaises(InvalidRequest) as caught:
            call(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)
        return caught.exception


class StatusTests(QueryCase):
    """``status`` reports progress and presentation state without ever failing for incompleteness."""

    def test_status_reports_exactly_the_documented_keys_at_every_stage(self):
        """status() returns the documented keys before an audit exists and after completion."""
        fixture = self.fixture()
        fixture.structure()
        with fixture.open(write=False) as db:
            self.assertEqual(set(queries.status(db)), STATUS_KEYS)
        fixture.complete()
        with fixture.open(write=False) as db:
            head = db.max_revision()
            result = queries.status(db)
        self.assertEqual(set(result), STATUS_KEYS)
        self.assertEqual(result["revision"], head)
        self.assertEqual(result["head_revision"], head)

    def test_status_exposes_coverage_blockers_and_preserves_historical_scope(self):
        """Missing coverage is actionable in status and disappears only at the examined revision."""
        fixture = self.fixture().audit()
        with fixture.open(write=False) as db:
            revision = db.max_revision()
            result = queries.status(db)
            expected = assessment.derive_assessment(db, audit_id="aud_1")
            for field in ("coverage_diagnostics", "coverage_diagnostic_count", "coverage_diagnostics_truncated"):
                self.assertEqual(result[field], expected[field])
            self.assertGreater(result["coverage_diagnostic_count"], 0)
            self.assertFalse(result["coverage_diagnostics_truncated"])
            self.assertTrue(any(row["code"] == "missing_coverage" for row in result["coverage_diagnostics"]))
        fixture.complete()
        with fixture.open(write=False) as db:
            self.assertEqual(queries.status(db)["coverage_diagnostics"], [])
            self.assertEqual(queries.status(db)["coverage_diagnostic_count"], 0)
            self.assertEqual(queries.status(db, revision=revision)["coverage_diagnostics"],
                             result["coverage_diagnostics"])

    def test_status_reports_assessment_coverage_truncation_without_losing_total_count(self):
        """A large uncovered argument keeps the assessment's bounded list and full diagnostic count."""
        fixture = self.fixture().audit()
        with fixture.open() as db:
            anchor_ids = [f"anc_extra_{index}" for index in range(101)]
            sources.anchor_sources(db, request={
                "contract_version": 3, "request_id": fixture.request_id(),
                "packet_id": fixture.packet(db)["packet_id"],
                "anchors": [{"id": aid, "expected_version": None, "source_id": fixture.source_id,
                             "locator": locator(start=8, end=10)} for aid in anchor_ids]})
            prior = db.head("arguments", "arg_lem")
            fixture.apply(db, [edit("replace", "arguments", prior.id,
                                   dict(prior.body, evidence_refs=prior.body["evidence_refs"] + anchor_ids),
                                   expected=prior.version)], *fixture.ITEMS)
            result = queries.status(db)
            expected = assessment.derive_assessment(db, audit_id="aud_1")
            self.assertEqual(len(result["coverage_diagnostics"]), 100)
            self.assertGreater(result["coverage_diagnostic_count"], 100)
            self.assertTrue(result["coverage_diagnostics_truncated"])
            for field in ("coverage_diagnostics", "coverage_diagnostic_count", "coverage_diagnostics_truncated"):
                self.assertEqual(result[field], expected[field])

    def test_status_before_an_audit_is_overview_mode_with_nothing_assessed(self):
        """Without a registered audit the snapshot is mode "overview": no audit, no obligations, no assessments."""
        fixture = self.fixture()
        fixture.structure()
        with fixture.open(write=False) as db:
            result = queries.status(db)
        self.assertEqual(result["mode"], "overview")
        self.assertIsNone(result["audit"])
        self.assertEqual(result["audits"], [])
        self.assertIs(result["process_complete"], False)
        self.assertEqual(result["progress"], PROGRESS_OVERVIEW)
        self.assertEqual(result["obligations"], {"required": [], "unsatisfied": []})
        self.assertEqual(result["assessments"], {})
        self.assertEqual(result["independent"], {})
        self.assertEqual(result["findings"], EMPTY_FINDINGS)
        self.assertEqual(result["source_limits"], [])
        self.assertIsNone(result["published_revision"])
        self.assertEqual(result["publications"], [])
        self.assertEqual(result["problems"], [])

    def test_status_counts_only_live_records_of_the_snapshot(self):
        """counts is the live record census: it grows with the audit and never counts a retired record."""
        fixture = self.fixture()
        fixture.structure()
        with fixture.open(write=False) as db:
            self.assertEqual(queries.status(db)["counts"], STRUCTURE_COUNTS)
        with fixture.open() as db:
            fixture.apply(db, [edit("create", "scopes", "scp_extra", dict(EXTRA_SCOPE))], mode="author")
        with fixture.open(write=False) as db:
            self.assertEqual(queries.status(db)["counts"], dict(STRUCTURE_COUNTS, scopes=2))
        with fixture.open() as db:
            packet = fixture.packet(db, mode="author")
            acceptance.apply_batch(db, fixture.batch([retire_edit("scopes", "scp_extra", 1, "not needed")],
                                                     packet["packet_id"]))
        with fixture.open(write=False) as db:
            self.assertEqual(queries.status(db)["counts"], STRUCTURE_COUNTS)
        fixture.complete()
        with fixture.open(write=False) as db:
            self.assertEqual(queries.status(db)["counts"], COMPLETE_COUNTS)

    def test_status_storage_block_stamps_this_core_and_the_stored_metadata(self):
        """The storage block is the compatibility stamp a reader checks before trusting the rest."""
        fixture = self.fixture()
        fixture.structure()
        with fixture.open(write=False) as db:
            storage_block = queries.status(db)["storage"]
        self.assertEqual(storage_block["storage_format"], STORAGE_FORMAT)
        self.assertEqual(storage_block["contract_version"], CONTRACT_VERSION)
        self.assertEqual(storage_block["contract"], CONTRACT_NAME)
        self.assertEqual(storage_block["core_version"], CORE_VERSION)
        self.assertEqual(storage_block["projection_version"], PROJECTION_VERSION)
        self.assertEqual(storage_block["metadata"]["storage_format"], str(STORAGE_FORMAT))
        self.assertEqual(storage_block["metadata"]["contract_version"], str(CONTRACT_VERSION))
        self.assertEqual(json.loads(storage_block["metadata"]["features"]), list(DEFAULT_FEATURES))
        self.assertEqual(storage_block["metadata"]["protocol_version"], "item-audit/1")

    def test_status_paper_block_carries_the_live_paper_record(self):
        """paper is the single live papers record: its id, its version and its body fields."""
        fixture = self.fixture(title="Convergence of a sequence")
        fixture.structure()
        with fixture.open(write=False) as db:
            paper = queries.status(db)["paper"]
        self.assertEqual(paper["id"], fixture.paper_id)
        self.assertEqual(paper["version"], 1)
        self.assertEqual(paper["title"], "Convergence of a sequence")
        self.assertEqual(paper["main_items"], [])
        self.assertEqual(paper["report_paths"], [])
        self.assertEqual(Path(paper["source_root"]).resolve(), fixture.source_root.resolve())

    def test_status_sources_block_reports_the_context_digest_and_limited_sources(self):
        """A source registered outside the root is listed under sources.limited with its limitation text."""
        fixture = self.fixture()
        fixture.structure()
        outside = self.path("outside", "notes.txt")
        outside.write_text("supplementary notes\n", encoding="utf-8")
        with fixture.open() as db:
            sources.capture_sources(db, files=["paper.tex", str(outside)])
        with fixture.open(write=False) as db:
            result = queries.status(db)
            digest = packets.source_context_digest(db)
        self.assertEqual(result["sources"]["count"], 2)
        self.assertEqual(result["sources"]["context_digest"], digest)
        self.assertEqual(result["context"]["source_context_digest"], digest)
        self.assertEqual([entry["limitation"] for entry in result["sources"]["limited"]],
                         ["registered by absolute path outside the source root"])
        self.assertEqual(Path(result["sources"]["limited"][0]["path"]).resolve(), outside.resolve())

    def test_status_context_block_pairs_the_source_digest_with_the_older_context_count(self):
        """context carries exactly the live source-context digest and the count of judgments behind it."""
        fixture = self.fixture()
        fixture.complete()
        with fixture.open(write=False) as db:
            result = queries.status(db)
            digest = packets.source_context_digest(db)
        self.assertEqual(set(result["context"]), CONTEXT_KEYS)
        self.assertEqual(result["context"], {"source_context_digest": digest,
                                             "judgments_in_older_context": 0})
        self.assertRegex(digest, SHA256_HEX)

    def test_registering_an_audit_switches_the_mode_and_raises_the_obligations(self):
        """Registering a focused audit moves mode off "overview" and creates eleven required obligations."""
        fixture = self.fixture()
        fixture.audit()
        with fixture.open(write=False) as db:
            result = queries.status(db)
        self.assertEqual(result["mode"], "focused")
        self.assertEqual(result["audits"], ["aud_1"])
        self.assertEqual(result["audit"], {"id": "aud_1", "version": 1, "mode": "focused",
                                           "protocol_version": "item-audit/1",
                                           "targets": [R("items", "itm_lem"), R("items", "itm_thm")],
                                           "independent_required": True})
        self.assertEqual(result["progress"], PROGRESS_AFTER_AUDIT)
        self.assertEqual(len(result["obligations"]["required"]), 13)
        self.assertEqual(result["obligations"]["unsatisfied"], result["obligations"]["required"])
        self.assertEqual(result["obligations"]["required"], sorted(result["obligations"]["required"]))
        self.assertTrue(all(oid.startswith("obl_") for oid in result["obligations"]["required"]))
        self.assertEqual(result["independent"], {"items:itm_lem": "pending", "items:itm_thm": "pending"})

    def test_primary_judgments_alone_leave_the_process_incomplete(self):
        """Primary checks satisfy seven of eleven obligations; independent review is still pending."""
        fixture = self.fixture()
        fixture.primary()
        with fixture.open(write=False) as db:
            result = queries.status(db)
        self.assertIs(result["process_complete"], False)
        self.assertEqual(result["progress"], PROGRESS_AFTER_PRIMARY)
        self.assertEqual(len(result["obligations"]["unsatisfied"]), 4)
        self.assertEqual(result["independent"], {"items:itm_lem": "pending", "items:itm_thm": "pending"})
        self.assertEqual(result["assessments"]["items:itm_lem"]["independent_review"], "pending")
        self.assertEqual(result["problems"], [])
        self.assertEqual(result["findings"], EMPTY_FINDINGS)

    def test_reconciliation_completes_the_process(self):
        """After reconciliation every required obligation is satisfied and both arguments assess green."""
        fixture = self.fixture()
        fixture.complete()
        with fixture.open(write=False) as db:
            result = queries.status(db)
        self.assertIs(result["process_complete"], True)
        self.assertEqual(result["progress"], PROGRESS_AFTER_COMPLETE)
        self.assertEqual(result["obligations"]["unsatisfied"], [])
        self.assertEqual(result["independent"], {"items:itm_lem": "complete", "items:itm_thm": "complete"})
        self.assertEqual(result["problems"], [])
        self.assertEqual(result["source_limits"], [])
        self.assertEqual(set(result["assessments"]), ASSESSED_KEYS)
        self.assertEqual(set(result["assessments"]["arguments:arg_lem"]), PUBLIC_ASSESSMENT_KEYS)
        for key in ("arguments:arg_lem", "arguments:arg_thm", "items:itm_lem", "items:itm_thm"):
            self.assertEqual(result["assessments"][key]["state"], "green", key)
            self.assertEqual(result["assessments"][key]["label"], "supported", key)
            self.assertEqual(result["assessments"][key]["missing_obligation_ids"], [], key)
            self.assertEqual(result["assessments"][key]["finding_refs"], [], key)
            self.assertEqual(result["assessments"][key]["independent_review"], "complete", key)
        self.assertEqual(result["assessments"]["groups:grp_lem"]["independent_review"], "not_required")
        self.assertEqual(result["assessments"]["audits:aud_1"]["state"], "gray")

    def test_an_open_source_issue_keeps_the_process_incomplete(self):
        """Satisfying every obligation is not enough: an open source issue holds process_complete at false."""
        fixture = self.fixture()
        fixture.complete()
        issue = dict(OPEN_ISSUE, source_id=fixture.source_id)
        with fixture.open() as db:
            packet = fixture.packet(db, *fixture.ITEMS, mode="primary")
            sources.review_sources(db, batch=fixture.batch(
                [edit("create", "source_issues", "iss_1", issue)], packet["packet_id"]))
        with fixture.open(write=False) as db:
            blocked = queries.status(db)
            report = queries.validate_snapshot(db)
        self.assertIs(blocked["process_complete"], False)
        self.assertIs(blocked["progress"]["process_complete"], False)
        self.assertEqual(blocked["progress"]["completed_current_obligations"], 13)
        self.assertEqual(blocked["obligations"]["unsatisfied"], [])
        self.assertEqual(blocked["source_limits"], [{"collection": "source_issues", "id": "iss_1",
                                                     "version": 1}])
        self.assertEqual(blocked["counts"], dict(COMPLETE_COUNTS, source_issues=1))
        self.assertIs(report["ok"], True)
        with fixture.open() as db:
            packet = fixture.packet(db, *fixture.ITEMS, mode="primary")
            sources.review_sources(db, batch=fixture.batch(
                [edit("replace", "source_issues", "iss_1",
                      dict(issue, lifecycle="resolved", resolution="the label was disambiguated"),
                      expected=1)], packet["packet_id"]))
        with fixture.open(write=False) as db:
            cleared = queries.status(db)
        self.assertEqual(cleared["source_limits"], [])
        self.assertIs(cleared["process_complete"], True)

    def test_status_lists_an_open_finding_and_attaches_it_to_the_targets_it_touches(self):
        """An open finding is reported under findings and in the finding_refs of its target and that item."""
        fixture = self.fixture()
        fixture.complete()
        with fixture.open() as db:
            packet = fixture.packet(db, *fixture.ITEMS, mode="reconcile")
            review.reconcile(db, batch=fixture.batch(
                [edit("create", "findings", "fnd_1", dict(OPEN_FINDING))], packet["packet_id"]))
        with fixture.open(write=False) as db:
            result = queries.status(db)
        pinned = {"collection": "findings", "id": "fnd_1", "version": 1}
        self.assertEqual(result["findings"], {
            "open": [pinned], "resolved": [], "superseded": [],
            "refs": [{"ref": pinned, "category": "proof_gap", "target": R("arguments", "arg_lem"),
                      "lifecycle": "open"}]})
        self.assertEqual(result["counts"], dict(COMPLETE_COUNTS, findings=1))
        self.assertEqual({key: value["finding_refs"] for key, value in result["assessments"].items()},
                         {"arguments:arg_lem": ["fnd_1"], "items:itm_lem": ["fnd_1"],
                          "arguments:arg_thm": [], "audits:aud_1": [], "groups:grp_lem": [],
                          "groups:grp_thm": [], "items:itm_thm": [], "uses:use_lem_thm": []})

    def test_status_at_an_older_revision_describes_that_snapshot_not_the_head(self):
        """revision= reports the past snapshot while head_revision keeps naming the newest commit."""
        fixture = self.fixture()
        fixture.structure()
        with fixture.open(write=False) as db:
            structure_revision = db.max_revision()
        fixture.complete()
        with fixture.open(write=False) as db:
            head = db.max_revision()
            past = queries.status(db, revision=structure_revision)
            now = queries.status(db)
        self.assertGreater(head, structure_revision)
        self.assertEqual(past["revision"], structure_revision)
        self.assertEqual(past["head_revision"], head)
        self.assertEqual(past["mode"], "overview")
        self.assertIs(past["process_complete"], False)
        self.assertEqual(past["counts"], STRUCTURE_COUNTS)
        self.assertEqual(past["audits"], [])
        self.assertEqual(past["assessments"], {})
        self.assertIs(now["process_complete"], True)

    def test_status_defaults_to_the_most_recently_registered_audit(self):
        """With two audits the newest is the default; an explicit audit_id still reports the older one."""
        fixture = self.fixture()
        fixture.complete()
        with fixture.open() as db:
            fixture.apply(db, [edit("create", "audits", "aud_2", dict(TRIAGE_AUDIT, paper_id=fixture.paper_id))],
                          "items:itm_thm", mode="primary")
        with fixture.open(write=False) as db:
            default = queries.status(db)
            first = queries.status(db, audit_id="aud_1")
            second = queries.status(db, audit_id="aud_2")
        self.assertEqual(default["audits"], ["aud_1", "aud_2"])
        self.assertEqual(default["audit"]["id"], "aud_2")
        self.assertEqual(default["mode"], "triage")
        self.assertEqual(first["audit"]["id"], "aud_1")
        self.assertEqual(first["mode"], "focused")
        self.assertIs(first["process_complete"], True)
        self.assertEqual(second["audit"]["id"], "aud_2")
        self.assertIs(second["process_complete"], False)
        # The new audit also includes the consumed assumption and local hidden claim.
        self.assertEqual(second["progress"]["required_obligations"], 5)

    def test_status_still_answers_when_the_snapshot_holds_two_paper_records(self):
        """A snapshot that breaks the one-paper invariant reports paper null instead of raising."""
        fixture = self.fixture()
        fixture.complete()
        copy = corrupt_copy(fixture.path, self.path("twopapers_status.db"), [
            ("""INSERT INTO record_versions (collection, id, version, revision, retired, body_json, body_digest)
                SELECT 'papers', 'pap_ghost', 1, 1, 0, body_json, body_digest FROM record_versions
                WHERE collection = 'papers' AND version = 1""", ()),
            ("INSERT INTO record_heads (collection, id, version) VALUES ('papers', 'pap_ghost', 1)", ())])
        with storage.Database(copy, write=False) as db:
            result = queries.status(db)
        self.assertIsNone(result["paper"])
        self.assertEqual(result["counts"], dict(COMPLETE_COUNTS, papers=2))
        self.assertEqual(result["mode"], "focused")
        self.assertIs(result["process_complete"], True)

    def test_status_rejects_a_revision_outside_the_range(self):
        """A revision below 1, above the head, or not an integer is REVISION_RANGE and writes nothing."""
        fixture = self.fixture()
        fixture.primary()
        with fixture.open(write=True) as db:
            head = db.max_revision()
            before = self.frozen(db)
            for bad in (0, -1, head + 1, "3", 2.0, True, False):
                error = self.assert_invalid("REVISION_RANGE", queries.status, db, revision=bad)
                self.assertIn(f"1..{head}", error.message)
            self.assertEqual(self.frozen(db), before)
            self.assertEqual(queries.status(db, revision=head)["revision"], head)
            self.assertEqual(queries.status(db, revision=1)["revision"], 1)

    def test_status_rejects_an_audit_that_is_not_live_at_the_snapshot(self):
        """An unknown audit id, or one registered after the requested revision, is AUDIT_UNKNOWN."""
        fixture = self.fixture()
        fixture.structure()
        with fixture.open(write=False) as db:
            structure_revision = db.max_revision()
        fixture.complete()
        with fixture.open(write=True) as db:
            before = self.frozen(db)
            missing = self.assert_invalid("AUDIT_UNKNOWN", queries.status, db, audit_id="aud_nope")
            self.assertIn("aud_nope", missing.message)
            too_early = self.assert_invalid("AUDIT_UNKNOWN", queries.status, db, audit_id="aud_1",
                                            revision=structure_revision)
            self.assertIn(str(structure_revision), too_early.message)
            self.assertEqual(self.frozen(db), before)

    @unittest.skipUnless(node_available(), "the report renderer needs node on PATH")
    def test_status_reports_publications_recorded_at_or_before_the_snapshot(self):
        """A published report shows up in publications and sets published_revision, but not for older snapshots."""
        fixture = self.fixture()
        fixture.complete()
        output = self.path("reports", "audit.html")
        with fixture.open(write=False) as db:
            head = db.max_revision()
        with fixture.open() as db:
            built = projection.build_projection(db, audit_id="aud_1")
            published = publish.publish_report(db, projection=built, output=output)
        with fixture.open(write=False) as db:
            now = queries.status(db)
            past = queries.status(db, revision=head - 1)
            rows = db.publications()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], published["publication_id"])
        self.assertRegex(rows[0]["created_at"], ISO_UTC)
        self.assertEqual(now["published_revision"], head)
        self.assertEqual(now["publications"], [{"publication_id": published["publication_id"], "revision": head,
                                                "kind": "working", "state": "published",
                                                "output_path": str(output),
                                                "created_at": rows[0]["created_at"]}])
        self.assertEqual(past["publications"], [])
        self.assertIsNone(past["published_revision"])

    # Consumed source records, rather than every source in the paper, determine
    # whether a judgment was made in an older source context.
    def test_status_counts_judgments_bound_in_an_older_source_context(self):
        """Re-capturing the source must leave the five primary judgments counted as made in an older context."""
        fixture = self.fixture()
        fixture.primary()
        with fixture.open(write=False) as db:
            binding = db.binding("checks", "chk_comp_lem", 1)["bindings"]
            source_bindings = [entry for entry in binding["records"] if entry["ref"]["collection"] == "sources"]
            before_context = queries.status(db)["context"]["source_context_digest"]
        paper_tex = fixture.source_root / "paper.tex"
        paper_tex.write_text(paper_tex.read_text(encoding="utf-8") + "% appended\n", encoding="utf-8")
        with fixture.open() as db:
            sources.capture_sources(db, files=["paper.tex"])
        with fixture.open(write=False) as db:
            result = queries.status(db)
        self.assertIsNone(binding["source_context_digest"])
        self.assertEqual(len(source_bindings), 1)
        self.assertRegex(source_bindings[0]["digest"], SHA256_HEX)
        self.assertNotEqual(result["context"]["source_context_digest"], before_context)
        self.assertEqual(result["context"]["judgments_in_older_context"], len(PRIMARY_CHECK_IDS))


class ChangesTests(QueryCase):
    """``changes`` pages through the version log and reports what the new versions staled."""

    def test_changes_since_zero_lists_every_version_in_revision_order(self):
        """since=0 returns the whole log, ordered by (revision, collection, id), with the paper first."""
        fixture = self.fixture()
        fixture.complete()
        with fixture.open(write=False) as db:
            total_versions = len(db.all_versions())
            result = queries.changes(db, since=0)
            again = queries.changes(db, since=0)
            head = db.max_revision()
        self.assertEqual(set(result), CHANGES_KEYS)
        self.assertEqual(result["since"], 0)
        self.assertEqual(result["revision"], head)
        self.assertEqual(result["total"], total_versions)
        self.assertEqual(result["returned"], total_versions)
        self.assertEqual(result["limit"], 200)
        self.assertEqual(result["offset"], 0)
        self.assertIsNone(result["next_offset"])
        keys = [(r["revision"], r["collection"], r["id"]) for r in result["records"]]
        self.assertEqual(keys, sorted(keys))
        self.assertEqual(len(set(keys)), len(keys))
        self.assertEqual(again["records"], result["records"])
        self.assertEqual(result["records"][0], {"collection": "papers", "id": fixture.paper_id, "version": 1,
                                                "revision": 1, "retired": False, "op": "create"})

    def test_changes_derives_the_op_from_the_version_and_the_retired_flag(self):
        """The first version is a create, a later version a replace, and a retiring version a retire."""
        fixture = self.fixture()
        fixture.structure()
        with fixture.open(write=False) as db:
            baseline = db.max_revision()
        with fixture.open() as db:
            fixture.apply(db, [edit("create", "scopes", "scp_extra", dict(EXTRA_SCOPE))], mode="author")
        replace_the_lemma(fixture)
        with fixture.open() as db:
            packet = fixture.packet(db, mode="author")
            acceptance.apply_batch(db, fixture.batch([retire_edit("scopes", "scp_extra", 1, "not needed")],
                                                     packet["packet_id"]))
        with fixture.open(write=False) as db:
            records = queries.changes(db, since=baseline)["records"]
        self.assertEqual([(r["collection"], r["id"], r["version"], r["retired"], r["op"]) for r in records],
                         [("scopes", "scp_extra", 1, False, "create"),
                          ("items", "itm_lem", 2, False, "replace"),
                          ("scopes", "scp_extra", 2, True, "retire")])
        self.assertEqual([r["revision"] for r in records], [baseline + 1, baseline + 2, baseline + 3])

    def test_changes_pages_without_gaps_or_overlap(self):
        """Walking next_offset with a small limit reproduces the single-page listing exactly once."""
        fixture = self.fixture()
        fixture.complete()
        with fixture.open(write=False) as db:
            whole = queries.changes(db, since=0)
            walked, offset, pages = [], 0, 0
            while True:
                page = queries.changes(db, since=0, limit=4, offset=offset)
                pages += 1
                self.assertEqual(page["total"], whole["total"])
                self.assertEqual(page["limit"], 4)
                self.assertEqual(page["offset"], offset)
                self.assertEqual(page["returned"], len(page["records"]))
                self.assertEqual(page["records"], whole["records"][offset:offset + 4])
                walked.extend(page["records"])
                if page["next_offset"] is None:
                    break
                self.assertEqual(page["next_offset"], offset + page["returned"])
                offset = page["next_offset"]
            beyond = queries.changes(db, since=0, limit=10, offset=whole["total"])
        self.assertGreater(whole["total"], 4)
        self.assertEqual(pages, -(-whole["total"] // 4))
        self.assertEqual(walked, whole["records"])
        self.assertEqual(beyond["records"], [])
        self.assertEqual(beyond["returned"], 0)
        self.assertIsNone(beyond["next_offset"])

    def test_changes_reports_the_same_affected_checks_on_every_page(self):
        """Freshness is computed over the whole change set, so a one-record page still names all five checks."""
        fixture = self.fixture()
        fixture.primary()
        with fixture.open(write=False) as db:
            baseline = db.max_revision()
        replace_the_lemma(fixture)
        with fixture.open() as db:
            fixture.apply(db, [edit("create", "scopes", "scp_extra", dict(EXTRA_SCOPE))], mode="author")
        with fixture.open(write=False) as db:
            whole = queries.changes(db, since=baseline)
            first = queries.changes(db, since=baseline, limit=1, offset=0)
            second = queries.changes(db, since=baseline, limit=1, offset=1)
        self.assertEqual(whole["total"], 2)
        self.assertEqual([entry["ref"]["id"] for entry in whole["affected_checks"]], PRIMARY_CHECK_IDS)
        self.assertEqual(first["affected_checks"], whole["affected_checks"])
        self.assertEqual(second["affected_checks"], whole["affected_checks"])
        self.assertNotEqual(first["records"], second["records"])
        self.assertEqual({reason["changed_since"] for entry in whole["affected_checks"]
                          for reason in entry["reasons"]}, {True})

    def test_changes_at_the_head_reports_nothing_new_even_when_judgments_are_stale(self):
        """since=head reports nothing new, though the same database is stale one revision back."""
        fixture = self.fixture()
        fixture.primary()
        replace_the_lemma(fixture)
        with fixture.open(write=False) as db:
            head = db.max_revision()
            at_head = queries.changes(db, since=head)
            one_back = queries.changes(db, since=head - 1)
            digest = packets.source_context_digest(db)
        self.assertEqual(at_head["total"], 0)
        self.assertEqual(at_head["records"], [])
        self.assertEqual(at_head["returned"], 0)
        self.assertIsNone(at_head["next_offset"])
        self.assertEqual(at_head["affected_checks"], [])
        self.assertEqual(at_head["source_context"], {"changed": False, "since_digest": digest,
                                                     "current_digest": digest})
        self.assertEqual([entry["ref"]["id"] for entry in one_back["affected_checks"]], PRIMARY_CHECK_IDS)

    def test_changes_since_zero_has_no_baseline_source_digest(self):
        """Revision 0 predates every source, so since_digest is null and the context is not "changed"."""
        fixture = self.fixture()
        fixture.structure()
        with fixture.open(write=False) as db:
            context = queries.changes(db, since=0)["source_context"]
            digest = packets.source_context_digest(db)
        self.assertIsNone(context["since_digest"])
        self.assertIs(context["changed"], False)
        self.assertEqual(context["current_digest"], digest)

    def test_changes_reports_a_recaptured_source_as_a_changed_context(self):
        """Re-capturing an edited source changes the context digest, which changes flags for the reviewer."""
        fixture = self.fixture()
        fixture.structure()
        with fixture.open(write=False) as db:
            baseline = db.max_revision()
            before_digest = packets.source_context_digest(db)
        (fixture.source_root / "paper.tex").write_text(
            (fixture.source_root / "paper.tex").read_text(encoding="utf-8") + "% appended\n", encoding="utf-8")
        with fixture.open() as db:
            captured = sources.capture_sources(db, files=["paper.tex"])
        self.assertIs(captured["changed"], True)
        with fixture.open(write=False) as db:
            result = queries.changes(db, since=baseline)
            after_digest = packets.source_context_digest(db)
        self.assertNotEqual(before_digest, after_digest)
        self.assertEqual(result["source_context"], {"changed": True, "since_digest": before_digest,
                                                    "current_digest": after_digest})
        self.assertEqual([(r["collection"], r["version"], r["op"]) for r in result["records"]],
                         [("sources", 2, "replace")])

    def test_changes_names_the_checks_a_new_record_version_staled(self):
        """Replacing a judged item reports every check bound to its statement facet as stale."""
        fixture = self.fixture()
        fixture.primary()
        with fixture.open(write=False) as db:
            baseline = db.max_revision()
            self.assertEqual(queries.changes(db, since=baseline - 1)["affected_checks"], [])
        replace_the_lemma(fixture)
        with fixture.open(write=False) as db:
            affected = queries.changes(db, since=baseline)["affected_checks"]
        self.assertEqual([entry["ref"]["id"] for entry in affected], PRIMARY_CHECK_IDS)
        self.assertEqual({entry["freshness"] for entry in affected}, {"stale"})
        by_id = {entry["ref"]["id"]: entry for entry in affected}
        self.assertEqual(by_id["chk_comp_lem"]["ref"], {"collection": "checks", "id": "chk_comp_lem", "version": 1})
        self.assertEqual(by_id["chk_comp_lem"]["reasons"],
                         [{"kind": "record", "ref": {"collection": "items", "id": "itm_lem", "version": 1},
                           "facet": "statement", "changed_since": True}])

    def test_changes_marks_drift_that_predates_since_as_not_changed_since(self):
        """A check staled before the requested revision is still listed, with changed_since false."""
        fixture = self.fixture()
        fixture.primary()
        replace_the_lemma(fixture)
        with fixture.open(write=False) as db:
            edited_at = db.max_revision()
        with fixture.open() as db:
            fixture.apply(db, [edit("create", "scopes", "scp_extra", dict(EXTRA_SCOPE))], mode="author")
        with fixture.open(write=False) as db:
            result = queries.changes(db, since=edited_at)
        self.assertEqual([(r["collection"], r["id"]) for r in result["records"]], [("scopes", "scp_extra")])
        self.assertEqual([entry["ref"]["id"] for entry in result["affected_checks"]], PRIMARY_CHECK_IDS)
        flags = {reason["changed_since"] for entry in result["affected_checks"] for reason in entry["reasons"]}
        self.assertEqual(flags, {False})

    def test_changes_rejects_a_revision_outside_the_range(self):
        """A negative since, a since past the head, or a non-integer since is REVISION_RANGE and writes nothing."""
        fixture = self.fixture()
        fixture.primary()
        with fixture.open(write=True) as db:
            head = db.max_revision()
            before = self.frozen(db)
            for bad in (-1, head + 1, head + 99, "2", 2.5, True, False):
                error = self.assert_invalid("REVISION_RANGE", queries.changes, db, since=bad)
                self.assertIn(f"0..{head}", error.message)
            self.assertEqual(self.frozen(db), before)
            self.assertEqual(queries.changes(db, since=head)["since"], head)
            self.assertEqual(queries.changes(db, since=0)["since"], 0)

    def test_changes_rejects_a_bad_limit_or_offset(self):
        """limit outside 1..5000 and a negative offset are INVALID_REQUEST, and nothing is written."""
        fixture = self.fixture()
        fixture.structure()
        with fixture.open(write=True) as db:
            before = self.frozen(db)
            for bad in (0, -1, 5001, True, "10"):
                error = self.assert_invalid("INVALID_REQUEST", queries.changes, db, since=0, limit=bad)
                self.assertEqual(error.message, "limit must be an integer in 1..5000")
            for bad in (-1, True, "0"):
                error = self.assert_invalid("INVALID_REQUEST", queries.changes, db, since=0, offset=bad)
                self.assertEqual(error.message, "offset must be a non-negative integer")
            self.assertEqual(self.frozen(db), before)
            self.assertEqual(queries.changes(db, since=0, limit=5000, offset=0)["limit"], 5000)
            self.assertEqual(queries.changes(db, since=0, limit=1, offset=0)["returned"], 1)


class ValidateSnapshotTests(QueryCase):
    """``validate_snapshot`` reports a broken snapshot; it never presents corruption as a crash."""

    def corrupt(self, fixture, name, statements):
        """Validate a mutated copy of the fixture database and return the report."""
        copy = corrupt_copy(fixture.path, self.path(name), statements)
        with storage.Database(copy, write=False) as db:
            return queries.validate_snapshot(db)

    def test_validate_snapshot_passes_on_a_healthy_database(self):
        """A database built through the public API validates clean: no errors, warnings, drift or problems."""
        fixture = self.fixture()
        fixture.complete()
        with fixture.open(write=False) as db:
            head = db.max_revision()
            result = queries.validate_snapshot(db)
        self.assertEqual(set(result), VALIDATE_KEYS)
        self.assertIs(result["ok"], True)
        self.assertEqual(result["revision"], head)
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["warnings"], [])
        self.assertEqual(result["stale_bindings"], [])
        self.assertEqual(result["projection_problems"], [])
        self.assertEqual(result["integrity"], {"foreign_key_violations": [], "integrity": ["ok"]})
        self.assertEqual(result["records"], COMPLETE_COUNTS)

    def test_validate_snapshot_validates_the_requested_older_revision(self):
        """revision= validates that past snapshot: its record census, not the head's."""
        fixture = self.fixture()
        fixture.structure()
        with fixture.open(write=False) as db:
            structure_revision = db.max_revision()
        fixture.complete()
        with fixture.open(write=False) as db:
            past = queries.validate_snapshot(db, revision=structure_revision)
            head = queries.validate_snapshot(db)
        self.assertIs(past["ok"], True)
        self.assertEqual(past["revision"], structure_revision)
        self.assertEqual(past["records"], STRUCTURE_COUNTS)
        self.assertEqual(head["records"], COMPLETE_COUNTS)

    def test_validate_snapshot_rejects_a_revision_outside_the_range(self):
        """A revision below 1, above the head, or not an integer is REVISION_RANGE and writes nothing."""
        fixture = self.fixture()
        fixture.primary()
        with fixture.open(write=True) as db:
            head = db.max_revision()
            before = self.frozen(db)
            for bad in (0, -1, head + 1, "1", 1.5, True, False):
                error = self.assert_invalid("REVISION_RANGE", queries.validate_snapshot, db, revision=bad)
                self.assertIn(f"1..{head}", error.message)
            self.assertEqual(self.frozen(db), before)
            self.assertEqual(queries.validate_snapshot(db, revision=head)["revision"], head)

    def test_stale_bindings_are_reported_as_a_warning_and_leave_the_snapshot_valid(self):
        """Drift is a warning, never an error: the assessment already presents those judgments as stale."""
        fixture = self.fixture()
        fixture.primary()
        replace_the_lemma(fixture)
        with fixture.open(write=False) as db:
            result = queries.validate_snapshot(db)
        self.assertIs(result["ok"], True)
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["warnings"],
                         ["7 bound records have stale bindings (their judgments read as stale)"])
        self.assertEqual(sorted(entry["ref"]["id"] for entry in result["stale_bindings"]),
                         STALE_AFTER_LEMMA_EDIT)
        entry = next(e for e in result["stale_bindings"] if e["ref"]["id"] == "chk_comp_lem")
        self.assertEqual(entry["ref"], {"collection": "checks", "id": "chk_comp_lem", "version": 1})
        self.assertEqual(entry["relations"], [])
        self.assertEqual([(d["ref"], d["facet"], d["live_version"]) for d in entry["records"]],
                         [({"collection": "items", "id": "itm_lem", "version": 1}, "statement", 2)])
        drift = entry["records"][0]
        self.assertRegex(drift["expected"], SHA256_HEX)
        self.assertRegex(drift["actual"], SHA256_HEX)
        self.assertNotEqual(drift["expected"], drift["actual"])

    def test_a_bound_record_with_no_stored_binding_is_reported_as_a_warning(self):
        """Losing the evidence binding of a completed check is a warning naming that check, not an error."""
        fixture = self.fixture()
        fixture.complete()
        result = self.corrupt(fixture, "nobinding.db", [
            ("DELETE FROM evidence_bindings WHERE owner_collection = ? AND owner_id = ?",
             ("checks", "chk_der_thm"))])
        self.assertIs(result["ok"], True)
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["warnings"], ["checks:chk_der_thm@1: no stored binding"])
        self.assertEqual(result["stale_bindings"], [])
        self.assertEqual(result["projection_problems"], [
            {"audit_id": "aud_1", "problem": f"proof coverage for {owner}, anchor anc_thm_proof: "
                                             "uncovered or unchecked spans [0, 94)"}
            for owner in ("arg_thm", "items:itm_thm")])

    def test_a_contract_violation_is_reported_and_the_projection_is_skipped(self):
        """A body that lost its required fields is listed field by field; the projection never runs on it."""
        fixture = self.fixture()
        fixture.complete()
        result = self.corrupt(fixture, "violated.db",
                              [body_sql("checks", "chk_comp_lem", 1, {"audit_id": "aud_1"})])
        self.assertIs(result["ok"], False)
        self.assertIn("checks:chk_comp_lem@1: /target: missing required field", result["errors"])
        self.assertIn("checks:chk_comp_lem@1: /outcome: missing required field", result["errors"])
        self.assertIn(SKIPPED_PROJECTION, result["warnings"])
        self.assertEqual(result["projection_problems"], [])
        self.assertEqual([e for e in result["errors"] if e.startswith("projection ")], [])
        self.assertEqual(result["records"], COMPLETE_COUNTS)

    def test_a_violated_audit_body_is_a_violation_not_a_projection_crash(self):
        """The projection would dereference audit fields; a corrupt audit body is still reported as errors."""
        fixture = self.fixture()
        fixture.complete()
        result = self.corrupt(fixture, "audit.db",
                              [body_sql("audits", "aud_1", 1, {"paper_id": fixture.paper_id})])
        self.assertIs(result["ok"], False)
        self.assertIn("audits:aud_1@1: /mode: missing required field", result["errors"])
        self.assertIn("audits:aud_1@1: /targets: missing required field", result["errors"])
        self.assertEqual(result["warnings"], [SKIPPED_PROJECTION])
        self.assertEqual(result["projection_problems"], [])

    def test_a_reference_with_no_live_target_is_reported(self):
        """A body whose reference points at a record that is not live names the field and the revision."""
        fixture = self.fixture()
        fixture.complete()
        with fixture.open(write=False) as db:
            head = db.max_revision()
            broken = dict(db.head("application_details", "use_lem_thm").body, group_id="grp_missing")
        result = self.corrupt(fixture, "dangling.db", [body_sql("application_details", "use_lem_thm", 1, broken)])
        self.assertIs(result["ok"], False)
        self.assertEqual(result["errors"],
                         [f"application_details:use_lem_thm@1 /group_id: no live groups record grp_missing at revision {head}"])
        self.assertIn(SKIPPED_PROJECTION, result["warnings"])
        self.assertEqual(result["projection_problems"], [])

    def test_a_second_live_paper_record_is_reported(self):
        """Exactly one live papers record is an invariant, and validate_snapshot says so when it breaks."""
        fixture = self.fixture()
        fixture.complete()
        result = self.corrupt(fixture, "twopapers.db", [
            ("""INSERT INTO record_versions (collection, id, version, revision, retired, body_json, body_digest)
                SELECT 'papers', 'pap_ghost', 1, 1, 0, body_json, body_digest FROM record_versions
                WHERE collection = 'papers' AND version = 1""", ()),
            ("INSERT INTO record_heads (collection, id, version) VALUES ('papers', 'pap_ghost', 1)", ())])
        self.assertIs(result["ok"], False)
        self.assertIn("expected exactly one live paper record, found 2", result["errors"])
        self.assertEqual(result["records"], dict(COMPLETE_COUNTS, papers=2))

    def test_a_foreign_key_violation_is_reported_with_the_integrity_detail(self):
        """A reference row pointing at no record head is counted in errors and detailed under integrity."""
        fixture = self.fixture()
        fixture.complete()
        result = self.corrupt(fixture, "fk.db", [(
            """INSERT INTO record_refs (owner_collection, owner_id, owner_version, field_path,
                                        target_collection, target_id, target_version)
               VALUES ('uses', 'use_lem_thm', 1, '/ghost', 'items', 'itm_ghost', NULL)""", ())])
        self.assertIs(result["ok"], False)
        self.assertIn("1 foreign key violations", result["errors"])
        self.assertEqual(len(result["integrity"]["foreign_key_violations"]), 1)
        self.assertEqual(result["integrity"]["foreign_key_violations"][0]["table"], "record_refs")
        self.assertEqual(result["integrity"]["integrity"], ["ok"])

    # REGRESSION: validate_snapshot used to skip the projection for a contract-violating snapshot
    # but still run the stale-binding scan over the same malformed bodies, so binding_changes ->
    # facet_digests raised KeyError out of the one command that exists to diagnose a corrupted
    # database. The scan now skips a record whose body violates the contract, and any violation it
    # reaches through a binding becomes a warning rather than an exception.
    def test_a_violated_item_body_is_reported_rather_than_raised(self):
        """A corrupted items body must come back as a validation failure, never as an exception."""
        fixture = self.fixture()
        fixture.primary()
        result = self.corrupt(fixture, "item.db", [body_sql("items", "itm_lem", 1, {"kind": "lemma"})])
        self.assertIs(result["ok"], False)
        self.assertIn("items:itm_lem@1: /statement: missing required field", result["errors"])
        self.assertIn(SKIPPED_PROJECTION, result["warnings"])


class NoWriteTests(QueryCase):
    """The whole module is read-only; given a writable handle it still must not touch a single byte."""

    def test_no_query_writes_even_through_a_writable_connection(self):
        """status, changes and validate_snapshot leave the database file and its directory byte-identical."""
        fixture = self.fixture()
        fixture.complete()
        root = fixture.path.parent
        before_digest = file_digest(fixture.path)
        before_files = sorted(entry.name for entry in root.iterdir())
        with fixture.open(write=True) as db:
            head = db.max_revision()
            self.assertEqual(queries.status(db)["head_revision"], head)
            self.assertEqual(queries.changes(db, since=0)["total"], len(db.all_versions()))
            self.assertIs(queries.validate_snapshot(db)["ok"], True)
            self.assertEqual(db.max_revision(), head)
        self.assertEqual(file_digest(fixture.path), before_digest)
        self.assertEqual(sorted(entry.name for entry in root.iterdir()), before_files)


if __name__ == "__main__":
    unittest.main()
