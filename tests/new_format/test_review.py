"""Independent review: qualification receipts, submission, judgment mapping, reconcile, compare.

Covers ``shared/paper_core/review.py`` and the intake promises of
the review record contract: a qualification receipt carries its
own evidence and is refused when a blob does not hash to what it claims; the worker's response bytes are
preserved verbatim before anything is derived from them and stay verbatim after the coordinator maps it;
a judgment that names a record in the packet resolves at submission while a SourceTarget or an
out-of-scope reference is held as ``needs_revision`` until an explicit mapping arrives; a reconciliation
pins the exact primary and independent check versions it adjudicated; and ``compare`` records
observations only, through a packet whose identity the CLI refuses to guess.

Every refusal test also asserts that the refused command wrote nothing at all.
"""
from __future__ import annotations

import base64
import copy
import json
import unittest
from unittest import mock

from support import Fixture, R, TempCase, edit, locator, run_cli, sha, write_json

from paper_core import controller, packets, review, sources
from paper_core.canonical import canonical_bytes
from paper_core.errors import ConflictError, InvalidRequest

EVIDENCE = b"calibration transcript for checker-B"
CASE_OK = b'{"case": "valid-1", "verdict": "gap"}'
CASE_BAD = b'{"case": "invalid-1", "verdict": "supported"}'


# -- payload builders ------------------------------------------------------------------------------
def blob_entry(payload, *, sha256=None, data=None):
    """One blob envelope; ``sha256`` and ``data`` override the honest values for the refusal tests."""
    return {"sha256": sha(payload) if sha256 is None else sha256, "encoding": "base64",
            "data": base64.b64encode(payload).decode() if data is None else data}


def qualification_body(reviewer="checker-B", *, qualified=True, protocol="item-audit/1"):
    return {"reviewer": reviewer,
            "profile": {"provider": "anthropic", "model": "claude-fable-5-1", "effort": "high", "tools": [],
                        "context_isolation": "fresh session, source only"},
            "protocol_version": protocol,
            "valid_case_results": [{"case_id": "valid-1", "response_blob": sha(CASE_OK), "outcome": "pass"}],
            "invalid_case_results": [{"case_id": "invalid-1", "response_blob": sha(CASE_BAD), "outcome": "pass"}],
            "evidence_blob": sha(EVIDENCE), "qualified": qualified, "limitations": []}


def qualification_receipt(fx, qid="qua_b", *, reviewer="checker-B", qualified=True, protocol="item-audit/1",
                          edits=None, blobs=None):
    body = qualification_body(reviewer, qualified=qualified, protocol=protocol)
    return {"contract_version": 3, "request_id": fx.request_id(),
            "edits": [edit("create", "qualifications", qid, body)] if edits is None else edits,
            "blobs": [blob_entry(b) for b in (EVIDENCE, CASE_OK, CASE_BAD)] if blobs is None else blobs}


def judgment(target, *, kind="composition", outcome="supported", state="complete",
             reasoning="independent reading of the proof", evidence=("anc_lem_proof",)):
    return {"target": target, "kind": kind, "state": state, "outcome": outcome, "reasoning": reasoning,
            "evidence_refs": list(evidence), "conditions": [], "next_action": None, "supersedes": None}


def source_target(anchor_id, description):
    return {"source_anchor_id": anchor_id, "description": description}


def worker_response(packet_id, judgments, *, covered=None, coverage_note="read the statement and the proof",
                    exposure="none_known", exposure_note=""):
    return {"packet_id": packet_id,
            "covered_targets": [R("items", "itm_lem")] if covered is None else list(covered),
            "coverage_note": coverage_note,
            "exposure_report": {"status": exposure, "note": exposure_note},
            "judgments": list(judgments)}


def submission(fx, packet_id, *, reviewer="checker-A", qualification_id="qua_r1", exposure="source_only",
               exposure_note=""):
    return {"contract_version": 3, "request_id": fx.request_id(), "packet_id": packet_id, "reviewer": reviewer,
            "qualification_id": qualification_id, "exposure": exposure, "exposure_note": exposure_note}


def mapping_request(fx, packet_id, response_id, entries, *, reviewer="coord"):
    return {"contract_version": 3, "request_id": fx.request_id(), "packet_id": packet_id,
            "response_id": response_id, "entries": list(entries), "reviewer": reviewer}


def entry(index, target, rationale="the proof passage is this argument"):
    return {"judgment_index": index, "target": target, "rationale": rationale}


def observation_edit(oid="obs_lem", item="itm_lem", anchor="anc_lem"):
    return edit("create", "observations", oid, {
        "target": R("items", item), "result": "matched", "reviewer": "primary-1",
        "note": "statement matches the source", "evidence_refs": [anchor]})


# -- qualification receipts ------------------------------------------------------------------------
class QualificationTests(TempCase):
    """``record_qualification`` is the packetless door through which reviewer evidence enters."""

    def setUp(self):
        super().setUp()
        self.fx = self.fixture()
        self.fx.structure()

    def test_receipt_stores_the_qualification_with_every_blob(self):
        """A well-formed receipt creates the qualification at version 1 and stores each blob byte-for-byte."""
        with self.fx.open() as db:
            receipt = review.record_qualification(db, receipt=qualification_receipt(self.fx))
            self.assertEqual(receipt["changed"],
                             [{"collection": "qualifications", "id": "qua_b", "op": "create", "version": 1}])
            stored = db.head("qualifications", "qua_b")
            self.assertEqual(stored.version, 1)
            self.assertEqual(stored.body["reviewer"], "checker-B")
            self.assertIs(stored.body["qualified"], True)
            self.assertEqual(stored.body["protocol_version"], "item-audit/1")
            self.assertEqual(db.get_blob(stored.body["evidence_blob"]), EVIDENCE)
            self.assertEqual(db.get_blob(stored.body["valid_case_results"][0]["response_blob"]), CASE_OK)
            self.assertEqual(db.get_blob(stored.body["invalid_case_results"][0]["response_blob"]), CASE_BAD)

    def test_blob_whose_hash_does_not_cover_its_data_is_refused(self):
        """A receipt whose blob hash does not match its decoded data is refused and writes nothing."""
        tampered = [blob_entry(EVIDENCE, data=base64.b64encode(b"a different transcript").decode()),
                    blob_entry(CASE_OK), blob_entry(CASE_BAD)]
        with self.fx.open() as db:
            before = db.max_revision()
            with self.assertRaises(InvalidRequest) as caught:
                review.record_qualification(db, receipt=qualification_receipt(self.fx, blobs=tampered))
            self.assertEqual(caught.exception.code, "INVALID_REQUEST")
            self.assertEqual(caught.exception.message, "blobs/0: sha256 does not match the decoded data")
            self.assertIsNone(db.head("qualifications", "qua_b"))
            self.assertFalse(db.has_blob(sha(EVIDENCE)))
            self.assertEqual(db.max_revision(), before)

    def test_blob_data_that_is_not_base64_is_refused(self):
        """A blob whose data is not base64 is named by index and nothing is stored."""
        broken = [blob_entry(EVIDENCE, data="!!! not base64 !!!")]
        with self.fx.open() as db:
            before = db.max_revision()
            with self.assertRaises(InvalidRequest) as caught:
                review.record_qualification(db, receipt=qualification_receipt(self.fx, blobs=broken))
            self.assertEqual(caught.exception.message, "blobs/0: data is not valid base64")
            self.assertIsNone(db.head("qualifications", "qua_b"))
            self.assertEqual(db.max_revision(), before)

    def test_receipt_may_only_create_qualifications(self):
        """A qualification receipt carrying another collection is refused before acceptance runs."""
        with self.fx.open() as db:
            before = db.max_revision()
            with self.assertRaises(InvalidRequest) as caught:
                review.record_qualification(db, receipt=qualification_receipt(
                    self.fx, edits=[observation_edit()], blobs=[]))
            self.assertEqual(caught.exception.message, "qualification receipt rejected")
            self.assertEqual(caught.exception.records,
                             ["edits/0: qualification receipts create qualifications only"])
            self.assertIsNone(db.head("observations", "obs_lem"))
            self.assertEqual(db.max_revision(), before)

    def test_receipt_cannot_replace_a_recorded_qualification(self):
        """A qualification is immutable: the receipt shape accepts create edits only."""
        self.fx.qualification()
        with self.fx.open() as db:
            live = db.head("qualifications", "qua_r1")
            before = db.max_revision()
            amended = dict(live.body)
            amended["qualified"] = False
            with self.assertRaises(InvalidRequest) as caught:
                review.record_qualification(db, receipt=qualification_receipt(self.fx, blobs=[], edits=[
                    edit("replace", "qualifications", "qua_r1", amended, expected=live.version)]))
            self.assertEqual(caught.exception.message, "invalid qualification receipt")
            self.assertIn("/edits/0/op: must equal 'create'", caught.exception.records)
            self.assertIs(db.head("qualifications", "qua_r1").body["qualified"], True)
            self.assertEqual(db.max_revision(), before)

    def test_qualified_requires_passes_in_both_calibration_classes(self):
        """A qualification claim cannot contradict failed, inconclusive, or absent case results."""
        for field in ("valid_case_results", "invalid_case_results"):
            for outcome in ("fail", "inconclusive", "missing"):
                with self.subTest(field=field, outcome=outcome), self.fx.open() as db:
                    payload = qualification_receipt(self.fx)
                    body = payload["edits"][0]["body"]
                    if outcome == "missing":
                        body[field] = []
                    else:
                        body[field][0]["outcome"] = outcome
                    before = db.max_revision()
                    with self.assertRaises(InvalidRequest):
                        review.record_qualification(db, receipt=payload)
                    self.assertIsNone(db.head("qualifications", "qua_b"))
                    self.assertFalse(db.has_blob(sha(EVIDENCE)))
                    self.assertEqual(db.max_revision(), before)

    def test_one_case_cannot_supply_both_valid_and_invalid_calibration(self):
        with self.fx.open() as db:
            payload = qualification_receipt(self.fx)
            body = payload["edits"][0]["body"]
            body["invalid_case_results"][0]["case_id"] = body["valid_case_results"][0]["case_id"]
            with self.assertRaises(InvalidRequest) as caught:
                review.record_qualification(db, receipt=payload)
            self.assertTrue(any("distinct calibration case IDs" in e for e in caught.exception.records))
            self.assertIsNone(db.head("qualifications", "qua_b"))

    def test_unsuccessful_calibration_remains_recordable_as_unqualified(self):
        with self.fx.open() as db:
            payload = qualification_receipt(self.fx, qualified=False)
            for field in ("valid_case_results", "invalid_case_results"):
                payload["edits"][0]["body"][field][0]["outcome"] = "fail"
            review.record_qualification(db, receipt=payload)
            self.assertIs(db.head("qualifications", "qua_b").body["qualified"], False)


# -- submission ------------------------------------------------------------------------------------
class SubmitReviewTests(TempCase):
    """``submit_review`` preserves the worker bytes and derives checks only from resolved judgments."""

    def setUp(self):
        super().setUp()
        self.fx = self.fixture()
        self.fx.primary()

    def independent_packet(self, db, item="itm_lem"):
        return packets.get_packet(db, targets=[R("items", item)], mode="independent")

    def resolved_response(self, packet_id):
        """A judgment naming an item, which the blinded read set does contain."""
        return worker_response(packet_id, [judgment(R("items", "itm_lem"), kind="external_source",
                                                    evidence=("anc_lem",),
                                                    reasoning="the cited source says what the item says")])

    def test_resolved_judgment_is_accepted_at_submission(self):
        """A judgment naming a record inside the packet read set accepts immediately with no pending work."""
        with self.fx.open() as db:
            packet = self.independent_packet(db)
            worker = self.resolved_response(packet["packet_id"])
            result = review.submit_review(db, submission=submission(self.fx, packet["packet_id"]),
                                          response_bytes=json.dumps(worker).encode("utf-8"))
            self.assertEqual(result["state"], "accepted")
            self.assertEqual(result["pending"], [])
            self.assertEqual(result["diagnostics"], [])
            self.assertEqual(result["receipt"]["warnings"], [])
            self.assertEqual(len(result["checks"]), 1)
            self.assertEqual(result["checks"][0]["judgment_index"], 0)
            self.assertEqual(result["checks"][0]["version"], 1)
            self.assertEqual(db.head("responses", result["response_id"]).body["state"], "accepted")

    def test_target_in_broad_packet_still_requires_worker_coverage(self):
        """Seeing a theorem in the packet does not mean the worker reviewed it."""
        with self.fx.open() as db:
            packet = packets.get_packet(db, targets=list(Fixture.ITEM_REFS), mode="independent")
            worker = worker_response(packet["packet_id"], [
                judgment(R("items", "itm_thm"), kind="external_source", evidence=("anc_thm",))])
            raw = json.dumps(worker).encode("utf-8")
            before = len(db.heads("checks"))
            result = review.submit_review(db, submission=submission(self.fx, packet["packet_id"]),
                                          response_bytes=raw)
            self.assertEqual(result["state"], "needs_revision")
            self.assertEqual(result["checks"], [])
            self.assertEqual(len(db.heads("checks")), before)
            self.assertIn("covered scope", result["pending"][0]["reason"])
            stored = db.head("responses", result["response_id"])
            self.assertEqual(stored.body["covered_targets"], [R("items", "itm_lem")])
            self.assertEqual(db.get_blob(stored.body["original_blob"]), raw)

    def test_empty_worker_coverage_cannot_author_resolved_checks(self):
        with self.fx.open() as db:
            packet = self.independent_packet(db)
            worker = self.resolved_response(packet["packet_id"])
            worker["covered_targets"] = []
            raw = json.dumps(worker).encode("utf-8")
            before = len(db.heads("checks"))
            result = review.submit_review(db, submission=submission(self.fx, packet["packet_id"]),
                                          response_bytes=raw)
            self.assertEqual(result["state"], "needs_revision")
            self.assertEqual(result["checks"], [])
            self.assertEqual(len(db.heads("checks")), before)
            self.assertIn("covered scope", result["pending"][0]["reason"])
            stored = db.head("responses", result["response_id"])
            self.assertEqual(stored.body["covered_targets"], [])
            self.assertEqual(db.get_blob(stored.body["original_blob"]), raw)

    def test_derived_check_copies_the_judgment_and_carries_tool_owned_fields(self):
        """The derived check keeps the worker's verdict and gets role, audit, protocol and provenance."""
        with self.fx.open() as db:
            packet = self.independent_packet(db)
            worker = self.resolved_response(packet["packet_id"])
            result = review.submit_review(db, submission=submission(self.fx, packet["packet_id"]),
                                          response_bytes=json.dumps(worker).encode("utf-8"))
            check = db.head("checks", result["checks"][0]["check_id"])
            self.assertEqual(check.body["role"], "independent")
            self.assertEqual(check.body["audit_id"], "aud_1")
            self.assertEqual(check.body["protocol_version"], "item-audit/1")
            self.assertEqual(check.body["reviewer"], "checker-A")
            self.assertEqual(check.body["response_id"], result["response_id"])
            self.assertEqual(check.body["target"], R("items", "itm_lem"))
            self.assertEqual(check.body["kind"], "external_source")
            self.assertEqual(check.body["state"], "complete")
            self.assertEqual(check.body["outcome"], "supported")
            self.assertEqual(check.body["reasoning"], "the cited source says what the item says")
            self.assertEqual(check.body["evidence_refs"], ["anc_lem"])

    def test_worker_bytes_are_stored_verbatim(self):
        """The response blob is the submitted bytes exactly, whitespace and all, not a re-serialisation."""
        with self.fx.open() as db:
            packet = self.independent_packet(db)
            worker = self.resolved_response(packet["packet_id"])
            raw = b"  " + json.dumps(worker, indent=3).encode("utf-8") + b"\n\n"
            self.assertNotEqual(raw, json.dumps(worker).encode("utf-8"))
            result = review.submit_review(db, submission=submission(self.fx, packet["packet_id"]),
                                          response_bytes=raw)
            stored = db.head("responses", result["response_id"])
            self.assertEqual(stored.body["original_blob"], sha(raw))
            self.assertEqual(db.get_blob(stored.body["original_blob"]), raw)

    def test_response_record_reports_the_packet_qualification_and_coverage(self):
        """The response record binds the submission to its packet, audit, reviewer and qualification."""
        with self.fx.open() as db:
            packet = self.independent_packet(db)
            worker = self.resolved_response(packet["packet_id"])
            result = review.submit_review(db, submission=submission(self.fx, packet["packet_id"]),
                                          response_bytes=json.dumps(worker).encode("utf-8"))
            stored = db.head("responses", result["response_id"])
            self.assertEqual(stored.version, 1)
            self.assertEqual(stored.body["packet_id"], packet["packet_id"])
            self.assertEqual(stored.body["audit_id"], "aud_1")
            self.assertEqual(stored.body["reviewer"], "checker-A")
            self.assertEqual(stored.body["qualification_id"], "qua_r1")
            self.assertEqual(stored.body["covered_targets"], [R("items", "itm_lem")])
            self.assertEqual(stored.body["coverage_note"], "read the statement and the proof")
            self.assertEqual(stored.body["exposure"], "source_only")

    def test_unreadable_response_is_kept_with_diagnostics_and_marked_compromised(self):
        """Bytes that are not JSON are still preserved; the response needs revision and exposure is unknown."""
        raw = b"this is not JSON at all"
        with self.fx.open() as db:
            packet = self.independent_packet(db)
            result = review.submit_review(db, submission=submission(self.fx, packet["packet_id"]),
                                          response_bytes=raw)
            self.assertEqual(result["state"], "needs_revision")
            self.assertEqual(result["checks"], [])
            self.assertEqual(len(result["diagnostics"]), 1)
            self.assertTrue(result["diagnostics"][0].startswith("response is not valid JSON:"))
            self.assertEqual(result["receipt"]["warnings"], result["diagnostics"])
            stored = db.head("responses", result["response_id"])
            self.assertEqual(db.get_blob(stored.body["original_blob"]), raw)
            self.assertEqual(stored.body["covered_targets"], [])
            self.assertEqual(stored.body["exposure"], "compromised")
            self.assertEqual(stored.body["exposure_note"],
                             "coordinator: source_only; worker: possible_exposure (response unreadable)")

    def test_response_naming_another_packet_is_a_diagnostic(self):
        """A worker response that names a different packet does not derive checks."""
        with self.fx.open() as db:
            packet = self.independent_packet(db)
            worker = self.resolved_response(packet["packet_id"])
            worker["packet_id"] = "pkt_elsewhere"
            result = review.submit_review(db, submission=submission(self.fx, packet["packet_id"]),
                                          response_bytes=json.dumps(worker).encode("utf-8"))
            self.assertEqual(result["state"], "needs_revision")
            self.assertEqual(result["checks"], [])
            self.assertEqual(result["diagnostics"], [
                f"worker response names packet pkt_elsewhere but the submission names {packet['packet_id']}"])

    def test_covered_target_outside_the_declared_scope_is_dropped(self):
        """Coverage the packet never granted is reported and never recorded as covered."""
        with self.fx.open() as db:
            packet = self.independent_packet(db)
            worker = self.resolved_response(packet["packet_id"])
            worker["covered_targets"] = [R("items", "itm_thm")]
            result = review.submit_review(db, submission=submission(self.fx, packet["packet_id"]),
                                          response_bytes=json.dumps(worker).encode("utf-8"))
            self.assertEqual(result["state"], "needs_revision")
            self.assertEqual(result["diagnostics"],
                             ["covered target items:itm_thm lies outside the declared scope"])
            self.assertEqual(db.head("responses", result["response_id"]).body["covered_targets"], [])

    def test_worker_exposure_report_overrides_the_coordinator_claim(self):
        """A worker who reports possible exposure marks the response compromised even on a clean submission."""
        with self.fx.open() as db:
            packet = self.independent_packet(db)
            worker = self.resolved_response(packet["packet_id"])
            worker["exposure_report"] = {"status": "possible_exposure", "note": "saw a draft"}
            result = review.submit_review(db, submission=submission(self.fx, packet["packet_id"]),
                                          response_bytes=json.dumps(worker).encode("utf-8"))
            self.assertEqual(result["state"], "accepted")
            self.assertEqual(result["exposure"], "compromised")
            self.assertEqual(db.head("responses", result["response_id"]).body["exposure_note"],
                             "coordinator: source_only; worker: possible_exposure (saw a draft)")

    def test_unqualified_reviewer_cannot_submit_at_all(self):
        """A reviewer whose qualification says ``qualified: false`` is refused; no response, no check."""
        with self.fx.open() as db:
            review.record_qualification(db, receipt=qualification_receipt(
                self.fx, qid="qua_unq", reviewer="checker-B", qualified=False))
            packet = self.independent_packet(db)
            worker = self.resolved_response(packet["packet_id"])
            before_revision = db.max_revision()
            before_responses = len(db.heads("responses"))
            before_checks = len(db.heads("checks"))
            with self.assertRaises(InvalidRequest) as caught:
                review.submit_review(db, submission=submission(
                    self.fx, packet["packet_id"], reviewer="checker-B", qualification_id="qua_unq"),
                    response_bytes=json.dumps(worker).encode("utf-8"))
            self.assertEqual(caught.exception.code, "INVALID_REQUEST")
            self.assertEqual(caught.exception.message, "reviewer 'checker-B' is not qualified under qua_unq")
            self.assertEqual(db.max_revision(), before_revision)
            self.assertEqual(len(db.heads("responses")), before_responses)
            self.assertEqual(len(db.heads("checks")), before_checks)

    def test_qualification_must_belong_to_the_named_reviewer(self):
        """One reviewer cannot submit under another reviewer's qualification."""
        with self.fx.open() as db:
            review.record_qualification(db, receipt=qualification_receipt(
                self.fx, qid="qua_other", reviewer="checker-B"))
            packet = self.independent_packet(db)
            before = db.max_revision()
            with self.assertRaises(InvalidRequest) as caught:
                review.submit_review(db, submission=submission(
                    self.fx, packet["packet_id"], reviewer="checker-A", qualification_id="qua_other"),
                    response_bytes=b"{}")
            self.assertEqual(caught.exception.message,
                             "qualification qua_other belongs to reviewer 'checker-B', not 'checker-A'")
            self.assertEqual(db.max_revision(), before)

    def test_qualification_protocol_must_match_the_audit(self):
        """A qualification earned under another protocol cannot be spent on this audit."""
        with self.fx.open() as db:
            review.record_qualification(db, receipt=qualification_receipt(
                self.fx, qid="qua_proto", reviewer="checker-C", protocol="item-audit/9"))
            packet = self.independent_packet(db)
            before = db.max_revision()
            with self.assertRaises(InvalidRequest) as caught:
                review.submit_review(db, submission=submission(
                    self.fx, packet["packet_id"], reviewer="checker-C", qualification_id="qua_proto"),
                    response_bytes=b"{}")
            self.assertEqual(caught.exception.code, "PROTOCOL_MISMATCH")
            self.assertEqual(caught.exception.message,
                             "qualification protocol item-audit/9 does not match audit protocol item-audit/1")
            self.assertEqual(db.max_revision(), before)

    def test_qualification_must_be_a_live_record(self):
        """An unknown qualification id is refused before the response is touched."""
        with self.fx.open() as db:
            packet = self.independent_packet(db)
            before = db.max_revision()
            with self.assertRaises(InvalidRequest) as caught:
                review.submit_review(db, submission=submission(
                    self.fx, packet["packet_id"], qualification_id="qua_ghost"), response_bytes=b"{}")
            self.assertEqual(caught.exception.message, "qualification qua_ghost is not a live record")
            self.assertEqual(db.max_revision(), before)

    def test_submission_needs_an_independent_packet(self):
        """A primary packet cannot be used to file an independent response."""
        with self.fx.open() as db:
            packet = self.fx.packet(db, *Fixture.ITEMS, mode="primary")
            before = db.max_revision()
            with self.assertRaises(InvalidRequest) as caught:
                review.submit_review(db, submission=submission(self.fx, packet["packet_id"]),
                                     response_bytes=b"{}")
            self.assertEqual(caught.exception.code, "PACKET_MODE")
            self.assertIn("review submit needs an independent packet", caught.exception.message)
            self.assertEqual(db.max_revision(), before)

    def test_unknown_packet_is_refused(self):
        """A submission against a packet the database never issued is refused."""
        with self.fx.open() as db:
            before = db.max_revision()
            with self.assertRaises(InvalidRequest) as caught:
                review.submit_review(db, submission=submission(self.fx, "pkt_nope"), response_bytes=b"{}")
            self.assertEqual(caught.exception.code, "PACKET_UNKNOWN")
            self.assertEqual(caught.exception.message, "unknown packet pkt_nope")
            self.assertEqual(db.max_revision(), before)

    def test_response_must_be_supplied_as_bytes(self):
        """A decoded string is refused: the core stores the bytes it was handed, it does not encode them."""
        with self.fx.open() as db:
            packet = self.independent_packet(db)
            before = db.max_revision()
            with self.assertRaises(InvalidRequest) as caught:
                review.submit_review(db, submission=submission(self.fx, packet["packet_id"]),
                                     response_bytes="{}")
            self.assertEqual(caught.exception.message, "the worker response must be supplied as bytes")
            self.assertEqual(db.max_revision(), before)

    def test_invalid_envelope_names_every_missing_field(self):
        """An incomplete submission envelope is refused with one record per missing field."""
        with self.fx.open() as db:
            with self.assertRaises(InvalidRequest) as caught:
                review.submit_review(db, submission={"contract_version": 3, "request_id": "req_x"},
                                     response_bytes=b"{}")
            self.assertEqual(caught.exception.message, "invalid submission envelope")
            self.assertIn("/packet_id: missing required field", caught.exception.records)
            self.assertIn("/reviewer: missing required field", caught.exception.records)
            self.assertIn("/qualification_id: missing required field", caught.exception.records)

    def test_replaying_one_submission_returns_the_original_receipt(self):
        """The same request id with the same bytes is idempotent: one response, one receipt."""
        with self.fx.open() as db:
            packet = self.independent_packet(db)
            raw = json.dumps(self.resolved_response(packet["packet_id"])).encode("utf-8")
            request = submission(self.fx, packet["packet_id"])
            first = review.submit_review(db, submission=dict(request), response_bytes=raw)
            after_first = db.max_revision()
            replay = review.submit_review(db, submission=dict(request), response_bytes=raw)
            self.assertEqual(replay["receipt"], first["receipt"])
            self.assertEqual(replay["response_id"], first["response_id"])
            self.assertEqual(db.max_revision(), after_first)
            self.assertEqual(len(db.heads("responses")), 1)

    def test_reusing_a_request_id_for_different_bytes_is_refused(self):
        """A request id may not be recycled for a different response; nothing is written."""
        with self.fx.open() as db:
            packet = self.independent_packet(db)
            raw = json.dumps(self.resolved_response(packet["packet_id"])).encode("utf-8")
            request = submission(self.fx, packet["packet_id"])
            review.submit_review(db, submission=dict(request), response_bytes=raw)
            before = db.max_revision()
            with self.assertRaises(InvalidRequest) as caught:
                review.submit_review(db, submission=dict(request), response_bytes=raw + b" ")
            self.assertEqual(caught.exception.code, "REQUEST_ID_REUSED")
            self.assertEqual(db.max_revision(), before)
            self.assertEqual(len(db.heads("responses")), 1)


# -- judgment classification -----------------------------------------------------------------------
class ClassifyJudgmentsTests(TempCase):
    """``classify_judgments`` decides, from the packet alone, which judgments can become checks."""

    def setUp(self):
        super().setUp()
        self.fx = self.fixture()
        self.fx.primary()

    def classify(self, db, judgments):
        """Classify against a primary manifest, whose read set does contain arguments and groups."""
        packet = packets.get_packet(db, targets=list(Fixture.ITEM_REFS), mode="primary")
        manifest = {key: packet[key] for key in ("mode", "read_set", "targets")}
        response = worker_response(packet["packet_id"], judgments)
        return review.classify_judgments(manifest, response, packet)

    def test_judgment_naming_a_record_in_the_read_set_resolves(self):
        """A judgment that names an argument directly resolves to that canonical target."""
        with self.fx.open() as db:
            resolved, pending = self.classify(db, [judgment(R("arguments", "arg_lem"))])
            self.assertEqual(resolved, [(0, R("arguments", "arg_lem"))])
            self.assertEqual(pending, [])

    def test_source_target_awaits_coordinator_mapping(self):
        """A SourceTarget never becomes a check by itself; it is held with the worker's own description."""
        with self.fx.open() as db:
            resolved, pending = self.classify(
                db, [judgment(source_target("anc_lem_proof", "the proof of the lemma"))])
            self.assertEqual(resolved, [])
            self.assertEqual(pending, [(0, "SourceTarget on anchor anc_lem_proof awaits mapping: "
                                           "the proof of the lemma")])

    def test_target_outside_the_packet_read_set_is_refused(self):
        """A judgment about something the packet never showed the worker cannot resolve."""
        with self.fx.open() as db:
            resolved, pending = self.classify(db, [judgment(R("arguments", "arg_ghost"))])
            self.assertEqual(resolved, [])
            self.assertEqual(pending, [(0, "target arguments:arg_ghost is not in the packet read set")])

    def test_kind_that_cannot_target_the_collection_is_refused(self):
        """The check kind constrains the target collection, even for a record inside the read set."""
        with self.fx.open() as db:
            resolved, pending = self.classify(db, [judgment(R("groups", "grp_lem"))])
            self.assertEqual(resolved, [])
            self.assertEqual(pending, [(0, "kind composition cannot target groups")])

    def test_evidence_anchor_outside_the_read_set_is_refused(self):
        """Evidence must point at source the packet actually carried."""
        with self.fx.open() as db:
            resolved, pending = self.classify(
                db, [judgment(R("arguments", "arg_lem"), evidence=("anc_ghost",))])
            self.assertEqual(resolved, [])
            self.assertEqual(pending, [(0, "evidence anchor anc_ghost is not in the packet read set")])

    def test_all_problems_with_one_judgment_are_reported_together(self):
        """Every problem on a judgment is joined into one reason, not reported one round trip at a time."""
        with self.fx.open() as db:
            resolved, pending = self.classify(
                db, [judgment(R("groups", "grp_ghost"), evidence=("anc_ghost",))])
            self.assertEqual(resolved, [])
            self.assertEqual(pending, [(0, "kind composition cannot target groups; "
                                           "target groups:grp_ghost is not in the packet read set; "
                                           "evidence anchor anc_ghost is not in the packet read set")])

    def test_resolved_and_pending_judgments_keep_their_indexes(self):
        """Indexes are the worker's own judgment positions, which the coordinator later maps by number."""
        with self.fx.open() as db:
            resolved, pending = self.classify(db, [
                judgment(source_target("anc_lem_proof", "the proof of the lemma")),
                judgment(R("arguments", "arg_lem")),
                judgment(R("arguments", "arg_ghost"))])
            self.assertEqual(resolved, [(1, R("arguments", "arg_lem"))])
            self.assertEqual([index for index, _ in pending], [0, 2])


# -- mapping ---------------------------------------------------------------------------------------
class MapResponseTests(TempCase):
    """``map_response`` resolves held judgments to canonical targets without rewriting the response."""

    def setUp(self):
        super().setUp()
        self.fx = self.fixture()
        self.fx.primary()

    def pending_submission(self, db, descriptions=("the proof of the lemma",), kinds=None):
        """Submit one SourceTarget judgment per description; returns (result, raw bytes)."""
        packet = packets.get_packet(db, targets=[R("items", "itm_lem")], mode="independent")
        worker = worker_response(packet["packet_id"],
                                 [judgment(source_target("anc_lem_proof", text),
                                           kind=kinds[i] if kinds else "composition")
                                  for i, text in enumerate(descriptions)])
        raw = json.dumps(worker).encode("utf-8")
        result = review.submit_review(db, submission=submission(self.fx, packet["packet_id"]),
                                      response_bytes=raw)
        return result, raw

    def coordinator_packet(self, db):
        return self.fx.packet(db, *Fixture.ITEMS, mode="primary")

    def test_source_target_submission_is_held_for_revision(self):
        """A SourceTarget response is stored as needs_revision with no check and a pending judgment."""
        with self.fx.open() as db:
            result, raw = self.pending_submission(db)
            self.assertEqual(result["state"], "needs_revision")
            self.assertEqual(result["checks"], [])
            self.assertEqual(result["pending"], [{
                "judgment_index": 0,
                "reason": "SourceTarget on anchor anc_lem_proof awaits mapping: the proof of the lemma"}])
            self.assertEqual(result["receipt"]["warnings"], [
                "judgment 0: SourceTarget on anchor anc_lem_proof awaits mapping: the proof of the lemma"])
            stored = db.head("responses", result["response_id"])
            self.assertEqual(stored.version, 1)
            self.assertEqual(stored.body["state"], "needs_revision")
            self.assertEqual(db.get_blob(stored.body["original_blob"]), raw)

    def test_mapping_the_last_judgment_accepts_the_response(self):
        """Once nothing is pending the response advances to accepted as a new version of the same record."""
        with self.fx.open() as db:
            result, raw = self.pending_submission(db)
            mapped = review.map_response(db, mapping=mapping_request(
                self.fx, self.coordinator_packet(db)["packet_id"], result["response_id"],
                [entry(0, R("arguments", "arg_lem"))]))
            self.assertEqual(mapped["state"], "accepted")
            self.assertEqual(mapped["remaining"], [])
            self.assertEqual(mapped["response_id"], result["response_id"])
            self.assertEqual(len(mapped["checks"]), 1)
            self.assertEqual(mapped["checks"][0]["judgment_index"], 0)
            stored = db.head("responses", result["response_id"])
            self.assertEqual(stored.version, 2)
            self.assertEqual(stored.body["state"], "accepted")
            self.assertEqual([v.body["state"] for v in db.versions_of("responses", result["response_id"])],
                             ["needs_revision", "accepted"])

    def test_source_judgment_maps_to_private_intermediate_argument(self):
        from test_work_packets import intermediate_edits, selection, task
        with self.fx.open() as db:
            self.fx.apply(db, intermediate_edits(self.fx, origin="reconstruction"))
            local = task("private_step_review", R("arguments", "arg_step"), "composition", role="independent")
            prepared = packets.prepare_assignment(db, audit_id="aud_1", mode="independent",
                                                  selection=selection((local,)))
            worker = worker_response(prepared["packet_id"],
                [judgment(source_target("anc_lem_proof", "The induction inference written in this passage"),
                    reasoning="Examined the written induction inference for the bound on a_n.")],
                covered=[R("items", "itm_thm")], coverage_note="Reviewed this local induction inference in source context.")
            raw = canonical_bytes(worker)
            envelope = {"contract_version": 4, "request_id": self.fx.request_id(),
                "packet_id": prepared["packet_id"], "rebase_packet_id": None,
                "reviewer": "checker-A", "qualification_id": "qua_r1", "exposure": "source_only",
                "exposure_note": "Fresh source-only reviewer."}
            pending = controller.submit_work(db, envelope_bytes=canonical_bytes(envelope), response_bytes=raw)
            self.assertEqual("needs_revision", pending["state"], pending)
            private = self.fx.packet(db, "items:itm_thm", mode="reconcile")
            mapped = review.map_response(db, mapping=mapping_request(self.fx, private["packet_id"],
                pending["response_id"], [entry(0, R("arguments", "arg_step"))]))
            self.assertEqual("accepted", mapped["state"])
            check = db.head("checks", mapped["checks"][0]["check_id"])
            self.assertEqual(R("arguments", "arg_step"), check.body["target"])
            self.assertFalse(any(row.body["role"] == "independent" and row.body["target"] == R("arguments", "arg_thm")
                                 for row in db.heads("checks")))
            self.assertEqual(worker["judgments"][0]["reasoning"], check.body["reasoning"])
            self.assertEqual(raw, db.get_blob(db.head("responses", pending["response_id"]).body["original_blob"]))
            bound = db.binding("checks", check.id, check.version)["bindings"]
            self.assertTrue(any(row["ref"]["id"] == "itm_step" and "setup_digest" in row for row in bound["records"]))
            self.assertTrue(any(row["ref"]["id"] == "scp_step" for row in bound["records"]))

    def test_mapping_preserves_the_original_response_bytes(self):
        """Mapping never substitutes the blob: the worker's bytes are byte-for-byte what they were."""
        with self.fx.open() as db:
            result, raw = self.pending_submission(db)
            review.map_response(db, mapping=mapping_request(
                self.fx, self.coordinator_packet(db)["packet_id"], result["response_id"],
                [entry(0, R("arguments", "arg_lem"))]))
            stored = db.head("responses", result["response_id"])
            self.assertEqual(stored.body["original_blob"], sha(raw))
            self.assertEqual(db.get_blob(stored.body["original_blob"]), raw)

    def test_mapped_check_keeps_the_worker_verdict_on_the_canonical_target(self):
        """The mapping supplies the target only; kind, outcome, reasoning and evidence stay the worker's."""
        with self.fx.open() as db:
            result, _ = self.pending_submission(db)
            mapped = review.map_response(db, mapping=mapping_request(
                self.fx, self.coordinator_packet(db)["packet_id"], result["response_id"],
                [entry(0, R("arguments", "arg_lem"))]))
            check = db.head("checks", mapped["checks"][0]["check_id"])
            self.assertEqual(check.body["target"], R("arguments", "arg_lem"))
            self.assertEqual(check.body["kind"], "composition")
            self.assertEqual(check.body["outcome"], "supported")
            self.assertEqual(check.body["reasoning"], "independent reading of the proof")
            self.assertEqual(check.body["evidence_refs"], ["anc_lem_proof"])
            self.assertEqual(check.body["role"], "independent")
            self.assertEqual(check.body["reviewer"], "checker-A")
            self.assertEqual(check.body["response_id"], result["response_id"])

    def test_identity_map_records_the_judgment_key_and_the_source_blob(self):
        """The mapping is stored as provenance keyed by judgment index and pinned to the response blob."""
        with self.fx.open() as db:
            result, raw = self.pending_submission(db)
            mapped = review.map_response(db, mapping=mapping_request(
                self.fx, self.coordinator_packet(db)["packet_id"], result["response_id"],
                [entry(0, R("arguments", "arg_lem"), "the passage names this argument")]))
            identity_map = db.head("identity_maps", mapped["identity_map_id"])
            self.assertEqual(identity_map.body, {
                "reason": "response_mapping", "source_blob": sha(raw), "response_id": result["response_id"],
                "entries": [{"old": "judgment:0", "new_refs": [R("arguments", "arg_lem")],
                             "rationale": "the passage names this argument"}],
                "reviewer": "coord", "note": ""})

    def test_partial_mapping_leaves_the_response_unaccepted(self):
        """With a judgment still pending the response keeps version 1 and state needs_revision."""
        with self.fx.open() as db:
            result, _ = self.pending_submission(db, descriptions=("the proof", "the local derivation"),
                                                kinds=("composition", "derivation"))
            self.assertEqual([p["judgment_index"] for p in result["pending"]], [0, 1])
            partial = review.map_response(db, mapping=mapping_request(
                self.fx, self.coordinator_packet(db)["packet_id"], result["response_id"],
                [entry(0, R("arguments", "arg_lem"))]))
            self.assertEqual(partial["state"], "needs_revision")
            self.assertEqual(partial["remaining"], [1])
            stored = db.head("responses", result["response_id"])
            self.assertEqual(stored.version, 1)
            self.assertEqual(stored.body["state"], "needs_revision")
            final = review.map_response(db, mapping=mapping_request(
                self.fx, self.coordinator_packet(db)["packet_id"], result["response_id"],
                [entry(1, R("groups", "grp_lem"), "the step is the lemma derivation")]))
            self.assertEqual(final["state"], "accepted")
            self.assertEqual(final["remaining"], [])
            self.assertEqual(db.head("responses", result["response_id"]).version, 2)

    def test_judgment_index_out_of_range_is_refused(self):
        """An entry naming a judgment the response does not have is refused and writes nothing."""
        with self.fx.open() as db:
            result, _ = self.pending_submission(db)
            packet_id = self.coordinator_packet(db)["packet_id"]
            before = db.max_revision()
            with self.assertRaises(InvalidRequest) as caught:
                review.map_response(db, mapping=mapping_request(
                    self.fx, packet_id, result["response_id"], [entry(7, R("arguments", "arg_lem"))]))
            self.assertEqual(caught.exception.message, "mapping rejected")
            self.assertEqual(caught.exception.records,
                             ["entries/0: judgment 7 does not exist (response has 1)"])
            self.assertEqual(db.max_revision(), before)
            self.assertEqual(db.head("responses", result["response_id"]).body["state"], "needs_revision")

    def test_mapping_a_judgment_twice_is_refused(self):
        """A judgment that already has an identity map cannot be remapped to something else."""
        with self.fx.open() as db:
            result, _ = self.pending_submission(db, descriptions=("the proof", "the statement step"))
            review.map_response(db, mapping=mapping_request(
                self.fx, self.coordinator_packet(db)["packet_id"], result["response_id"],
                [entry(0, R("arguments", "arg_lem"))]))
            packet_id = self.coordinator_packet(db)["packet_id"]
            before = db.max_revision()
            with self.assertRaises(InvalidRequest) as caught:
                review.map_response(db, mapping=mapping_request(
                    self.fx, packet_id, result["response_id"], [entry(0, R("arguments", "arg_thm"))]))
            self.assertEqual(caught.exception.records, ["entries/0: judgment 0 is already mapped"])
            self.assertEqual(db.max_revision(), before)

    def test_mapping_needs_at_least_one_entry(self):
        """An empty mapping request is refused rather than silently accepting the response."""
        with self.fx.open() as db:
            result, _ = self.pending_submission(db)
            packet_id = self.coordinator_packet(db)["packet_id"]
            before = db.max_revision()
            with self.assertRaises(InvalidRequest) as caught:
                review.map_response(db, mapping=mapping_request(
                    self.fx, packet_id, result["response_id"], []))
            self.assertEqual(caught.exception.message, "mapping request lists no entries")
            self.assertEqual(db.max_revision(), before)
            self.assertEqual(db.head("responses", result["response_id"]).body["state"], "needs_revision")

    def test_mapping_cannot_move_a_judgment_to_an_incompatible_collection(self):
        """The worker's kind still constrains the target the coordinator may choose."""
        with self.fx.open() as db:
            result, _ = self.pending_submission(db)
            packet_id = self.coordinator_packet(db)["packet_id"]
            before = db.max_revision()
            with self.assertRaises(InvalidRequest) as caught:
                review.map_response(db, mapping=mapping_request(
                    self.fx, packet_id, result["response_id"], [entry(0, R("groups", "grp_lem"))]))
            self.assertEqual(caught.exception.records, ["entries/0: kind composition cannot target groups"])
            self.assertEqual(db.max_revision(), before)

    def test_mapping_target_must_be_a_live_record(self):
        """A target that is not a live record of this database is refused and writes nothing."""
        with self.fx.open() as db:
            result, _ = self.pending_submission(db)
            packet_id = self.coordinator_packet(db)["packet_id"]
            before = db.max_revision()
            with self.assertRaises(InvalidRequest) as caught:
                review.map_response(db, mapping=mapping_request(
                    self.fx, packet_id, result["response_id"], [entry(0, R("arguments", "arg_ghost"))]))
            self.assertEqual(caught.exception.records,
                             ["entries/0: target arguments:arg_ghost is not a live record"])
            self.assertEqual(db.max_revision(), before)
            self.assertIsNone(db.head("arguments", "arg_ghost"))

    def test_mapping_target_outside_the_mapping_packet_is_rejected(self):
        """A lemma packet cannot credit an independent review to an unread theorem argument."""
        with self.fx.open() as db:
            result, _ = self.pending_submission(db)
            narrow = packets.get_packet(db, targets=[R("items", "itm_lem")], mode="primary")
            read_set = {(r["collection"], r["id"]) for r in narrow["read_set"]}
            self.assertNotIn(("arguments", "arg_thm"), read_set)
            before = db.max_revision()
            with self.assertRaises(InvalidRequest) as caught:
                review.map_response(db, mapping=mapping_request(
                    self.fx, narrow["packet_id"], result["response_id"],
                    [entry(0, R("arguments", "arg_thm"), "the wrong argument")]))
            self.assertTrue(any("not in the mapping packet" in e for e in caught.exception.records))
            self.assertEqual(db.max_revision(), before)
            self.assertEqual(db.head("responses", result["response_id"]).body["state"], "needs_revision")

    def test_broad_coordinator_packet_does_not_expand_worker_coverage(self):
        with self.fx.open() as db:
            result, raw = self.pending_submission(db)
            packet = self.coordinator_packet(db)
            self.assertIn(R("arguments", "arg_thm"),
                          [{"collection": r["collection"], "id": r["id"]} for r in packet["read_set"]])
            before = db.max_revision()
            with self.assertRaises(InvalidRequest) as caught:
                review.map_response(db, mapping=mapping_request(
                    self.fx, packet["packet_id"], result["response_id"], [entry(0, R("arguments", "arg_thm"))]))
            self.assertTrue(any("original independent review's covered scope" in e for e in caught.exception.records))
            self.assertEqual(db.max_revision(), before)
            self.assertEqual(db.get_blob(sha(raw)), raw)

    def test_mapping_old_response_after_changed_statement_requires_new_review(self):
        with self.fx.open() as db:
            result, raw = self.pending_submission(db)
            item = db.head("items", "itm_lem")
            body = copy.deepcopy(item.body)
            body["statement"]["text"] = "For every real x, x = x + 1."
            self.fx.apply(db, [edit("replace", "items", item.id, body, expected=item.version)],
                          "items:itm_lem", mode="author")
            packet = self.coordinator_packet(db)
            before = db.max_revision()
            with self.assertRaises(ConflictError) as caught:
                review.map_response(db, mapping=mapping_request(
                    self.fx, packet["packet_id"], result["response_id"], [entry(0, R("arguments", "arg_lem"))]))
            self.assertIn("independent worker's inputs changed", caught.exception.message)
            self.assertEqual(db.max_revision(), before)
            self.assertEqual(db.get_blob(sha(raw)), raw)

    def test_mapping_after_recaptured_and_rebound_proof_preserves_old_response(self):
        with self.fx.open() as db:
            result, raw = self.pending_submission(db)
            source = self.fx.source_root / "paper.tex"
            lines = source.read_text(encoding="utf-8").splitlines()
            lines[8] = "The claim follows because every real number equals zero."
            source.write_text("\n".join(lines) + "\n", encoding="utf-8")
            sources.capture_sources(db, files=["paper.tex"])
            anchor = db.head("anchors", "anc_lem_proof")
            packet = self.fx.packet(db)
            sources.anchor_sources(db, request={"contract_version": 3, "request_id": self.fx.request_id(),
                "packet_id": packet["packet_id"], "anchors": [{"id": anchor.id,
                "expected_version": anchor.version, "source_id": self.fx.source_id,
                "locator": locator(start=8, end=10)}]})
            before = db.max_revision()
            with self.assertRaises((InvalidRequest, ConflictError)):
                review.map_response(db, mapping=mapping_request(
                    self.fx, self.coordinator_packet(db)["packet_id"], result["response_id"],
                    [entry(0, R("arguments", "arg_lem"))]))
            self.assertEqual(db.max_revision(), before)
            self.assertEqual(db.head("responses", result["response_id"]).body["state"], "needs_revision")
            self.assertEqual(db.get_blob(sha(raw)), raw)

    def test_unrelated_record_edit_does_not_prevent_original_response_mapping(self):
        with self.fx.open() as db:
            result, _ = self.pending_submission(db)
            item = db.head("items", "itm_thm")
            body = copy.deepcopy(item.body)
            body["caption"] = "A different theorem caption"
            self.fx.apply(db, [edit("replace", "items", item.id, body, expected=item.version)],
                          "items:itm_thm", mode="author")
            mapped = review.map_response(db, mapping=mapping_request(
                self.fx, self.coordinator_packet(db)["packet_id"], result["response_id"],
                [entry(0, R("arguments", "arg_lem"))]))
            self.assertEqual(mapped["state"], "accepted")

    def test_original_read_set_is_rechecked_inside_mapping_transaction(self):
        """A source statement shown only to the worker cannot change in the precheck/commit window."""
        with self.fx.open() as db:
            self.fx.apply(db, [Fixture.item_edit("itm_definition", "definition", "Definition 1",
                                                 "anc_lem", "anc_lem_proof")])
            prepared = controller.prepare_work(db, audit_id="aud_1", mode="independent", focus=R("items", "itm_lem"))
            extended = packets.extend_work_assignment(db, packet_id=prepared["packet_id"], request={
                "source_refs": [db.head("items", "itm_definition").pinned],
                "reason": "The reviewer requested this auxiliary source definition."})
            worker = worker_response(extended["packet_id"], [judgment(source_target("anc_lem_proof", "The lemma proof"))])
            raw = json.dumps(worker).encode("utf-8")
            result = review.submit_review(db, submission=submission(self.fx, extended["packet_id"]), response_bytes=raw)
            packet = packets.get_packet(db, targets=[R("items", "itm_lem")], mode="primary")
            self.assertNotIn(("items", "itm_definition"),
                             {(r["collection"], r["id"]) for r in packet["read_set"]})
            real_accept = review.accept
            changed_revision = []

            def interleave(*args, **kwargs):
                with self.fx.open() as other:
                    definition = other.head("items", "itm_definition")
                    body = copy.deepcopy(definition.body)
                    body["statement"]["text"] = "A changed definition the independent worker did not see."
                    self.fx.apply(other, [edit("replace", "items", definition.id, body,
                                               expected=definition.version)])
                    changed_revision.append(other.max_revision())
                return real_accept(*args, **kwargs)

            with mock.patch.object(review, "accept", side_effect=interleave):
                with self.assertRaises(ConflictError) as caught:
                    review.map_response(db, mapping=mapping_request(
                        self.fx, packet["packet_id"], result["response_id"], [entry(0, R("arguments", "arg_lem"))]))
            self.assertIn("independent worker's inputs changed", caught.exception.message)
            self.assertEqual(db.max_revision(), changed_revision[0])
            self.assertEqual(db.get_blob(sha(raw)), raw)
            self.assertEqual(db.head("responses", result["response_id"]).body["state"], "needs_revision")

    def test_mapping_cannot_supply_evidence_the_worker_packet_omitted(self):
        with self.fx.open() as db:
            packet = packets.get_packet(db, targets=[R("items", "itm_lem")], mode="independent")
            worker = worker_response(packet["packet_id"], [judgment(
                source_target("anc_thm_proof", "unseen proof"), evidence=("anc_thm_proof",))])
            raw = json.dumps(worker).encode()
            result = review.submit_review(db, submission=submission(self.fx, packet["packet_id"]), response_bytes=raw)
            before = db.max_revision()
            with self.assertRaises(InvalidRequest) as caught:
                review.map_response(db, mapping=mapping_request(
                    self.fx, self.coordinator_packet(db)["packet_id"], result["response_id"],
                    [entry(0, R("arguments", "arg_lem"))]))
            self.assertTrue(any("evidence absent from the original" in e for e in caught.exception.records))
            self.assertEqual(db.max_revision(), before)
            self.assertEqual(db.get_blob(sha(raw)), raw)

    def test_mapping_does_not_repair_a_response_naming_the_wrong_packet(self):
        with self.fx.open() as db:
            packet = packets.get_packet(db, targets=[R("items", "itm_lem")], mode="independent")
            worker = worker_response("pkt_wrong", [judgment(source_target("anc_lem_proof", "lemma proof"))])
            result = review.submit_review(db, submission=submission(self.fx, packet["packet_id"]),
                                          response_bytes=json.dumps(worker).encode())
            before = db.max_revision()
            with self.assertRaises(InvalidRequest) as caught:
                review.map_response(db, mapping=mapping_request(
                    self.fx, self.coordinator_packet(db)["packet_id"], result["response_id"],
                    [entry(0, R("arguments", "arg_lem"))]))
            self.assertEqual(caught.exception.code, "RESPONSE_SCOPE")
            self.assertEqual(db.max_revision(), before)

    def test_accepted_response_cannot_repeat_the_same_exact_mapping(self):
        """Routine reuse may add a target but never duplicate the same mapping."""
        with self.fx.open() as db:
            result, _ = self.pending_submission(db)
            review.map_response(db, mapping=mapping_request(
                self.fx, self.coordinator_packet(db)["packet_id"], result["response_id"],
                [entry(0, R("arguments", "arg_lem"))]))
            packet_id = self.coordinator_packet(db)["packet_id"]
            before = db.max_revision()
            with self.assertRaises(InvalidRequest) as caught:
                review.map_response(db, mapping=mapping_request(
                    self.fx, packet_id, result["response_id"], [entry(0, R("arguments", "arg_lem"))]))
            self.assertTrue(any("already maps to this exact target" in row for row in caught.exception.records))
            self.assertEqual(db.max_revision(), before)

    def test_mapping_needs_a_coordinator_packet(self):
        """An author packet cannot author independent checks."""
        with self.fx.open() as db:
            result, _ = self.pending_submission(db)
            author = self.fx.packet(db, *Fixture.ITEMS, mode="author")
            before = db.max_revision()
            with self.assertRaises(InvalidRequest) as caught:
                review.map_response(db, mapping=mapping_request(
                    self.fx, author["packet_id"], result["response_id"], [entry(0, R("arguments", "arg_lem"))]))
            self.assertEqual(caught.exception.code, "PACKET_MODE")
            self.assertEqual(db.max_revision(), before)

    def test_mapping_an_unknown_response_is_refused(self):
        """A response id the database does not hold is refused before any packet work."""
        with self.fx.open() as db:
            packet_id = self.coordinator_packet(db)["packet_id"]
            before = db.max_revision()
            with self.assertRaises(InvalidRequest) as caught:
                review.map_response(db, mapping=mapping_request(
                    self.fx, packet_id, "rsp_ghost", [entry(0, R("arguments", "arg_lem"))]))
            self.assertEqual(caught.exception.message, "response rsp_ghost is not a live record")
            self.assertEqual(db.max_revision(), before)


# -- reconciliation --------------------------------------------------------------------------------
class ReconcileTests(TempCase):
    """``reconcile`` records the adjudication and pins exactly which check versions it read."""

    def setUp(self):
        super().setUp()
        self.fx = self.fixture()
        self.fx.independent()

    def reconcile_packet(self, db):
        return self.fx.packet(db, *Fixture.ITEMS, mode="reconcile")

    def test_reconciliation_pins_the_exact_check_versions_it_adjudicated(self):
        """The stored reconciliation names the primary and independent checks with their current versions."""
        with self.fx.open() as db:
            independent_id = self.fx.independent_checks["itm_lem"]
            packet = self.reconcile_packet(db)
            review.reconcile(db, batch=self.fx.batch([self.fx.reconciliation_edit(
                db, "rec_lem", "arg_lem", "chk_comp_lem", independent_id)], packet["packet_id"]))
            stored = db.head("reconciliations", "rec_lem")
            self.assertEqual(stored.version, 1)
            self.assertEqual(stored.body["primary_checks"],
                             [{"collection": "checks", "id": "chk_comp_lem", "version": 1}])
            self.assertEqual(stored.body["independent_checks"],
                             [{"collection": "checks", "id": independent_id, "version": 1}])
            self.assertEqual(stored.body["primary_checks"][0]["version"],
                             db.head("checks", "chk_comp_lem").version)
            self.assertEqual(stored.body["independent_checks"][0]["version"],
                             db.head("checks", independent_id).version)
            self.assertEqual(stored.body["target"], R("arguments", "arg_lem"))
            self.assertEqual(stored.body["decision"], "agree")

    def test_receipt_reports_each_reconciliation_created_at_version_one(self):
        """Both adjudications land in one commit, each as a create at version 1."""
        with self.fx.open() as db:
            packet = self.reconcile_packet(db)
            receipt = review.reconcile(db, batch=self.fx.batch([
                self.fx.reconciliation_edit(db, "rec_lem", "arg_lem", "chk_comp_lem",
                                            self.fx.independent_checks["itm_lem"]),
                self.fx.reconciliation_edit(db, "rec_thm", "arg_thm", "chk_comp_thm",
                                            self.fx.independent_checks["itm_thm"])], packet["packet_id"]))
            self.assertEqual(receipt["changed"], [
                {"collection": "reconciliations", "id": "rec_lem", "op": "create", "version": 1},
                {"collection": "reconciliations", "id": "rec_thm", "op": "create", "version": 1}])
            self.assertEqual(receipt["warnings"], [])

    def test_pinning_a_check_version_that_does_not_exist_is_refused(self):
        """A stale or invented pin is refused by reference check; no reconciliation is written."""
        with self.fx.open() as db:
            packet = self.reconcile_packet(db)
            stale = self.fx.reconciliation_edit(db, "rec_lem", "arg_lem", "chk_comp_lem",
                                                self.fx.independent_checks["itm_lem"])
            stale["body"]["primary_checks"] = [{"collection": "checks", "id": "chk_comp_lem", "version": 2}]
            before = db.max_revision()
            with self.assertRaises(InvalidRequest) as caught:
                review.reconcile(db, batch=self.fx.batch([stale], packet["packet_id"]))
            self.assertEqual(caught.exception.code, "INVALID_BATCH")
            self.assertEqual(caught.exception.records, [
                "edits/0 reconciliations:rec_lem /primary_checks/0: checks record chk_comp_lem has no version 2"])
            self.assertIsNone(db.head("reconciliations", "rec_lem"))
            self.assertEqual(db.max_revision(), before)

    def test_every_independent_check_on_the_target_must_be_listed(self):
        """A reconciliation cannot quietly ignore the independent check it was supposed to adjudicate."""
        with self.fx.open() as db:
            packet = self.reconcile_packet(db)
            dropped = self.fx.reconciliation_edit(db, "rec_lem", "arg_lem", "chk_comp_lem",
                                                  self.fx.independent_checks["itm_lem"])
            dropped["body"]["independent_checks"] = []
            before = db.max_revision()
            with self.assertRaises(InvalidRequest) as caught:
                review.reconcile(db, batch=self.fx.batch([dropped], packet["packet_id"]))
            self.assertEqual(caught.exception.code, "INVALID_BATCH")
            self.assertEqual(len(caught.exception.records), 1)
            self.assertIn("is not listed", caught.exception.records[0])
            self.assertIsNone(db.head("reconciliations", "rec_lem"))
            self.assertEqual(db.max_revision(), before)

    def test_reconcile_needs_a_reconcile_packet(self):
        """A primary packet cannot adjudicate its own work."""
        with self.fx.open() as db:
            packet = self.fx.packet(db, *Fixture.ITEMS, mode="primary")
            edits = [self.fx.reconciliation_edit(db, "rec_lem", "arg_lem", "chk_comp_lem",
                                                 self.fx.independent_checks["itm_lem"])]
            before = db.max_revision()
            with self.assertRaises(InvalidRequest) as caught:
                review.reconcile(db, batch=self.fx.batch(edits, packet["packet_id"]))
            self.assertEqual(caught.exception.code, "PACKET_MODE")
            self.assertIsNone(db.head("reconciliations", "rec_lem"))
            self.assertEqual(db.max_revision(), before)

    def test_reconcile_refuses_an_unknown_packet(self):
        """A packet id the database never issued is refused."""
        with self.fx.open() as db:
            edits = [self.fx.reconciliation_edit(db, "rec_lem", "arg_lem", "chk_comp_lem",
                                                 self.fx.independent_checks["itm_lem"])]
            before = db.max_revision()
            with self.assertRaises(InvalidRequest) as caught:
                review.reconcile(db, batch=self.fx.batch(edits, "pkt_nonexistent"))
            self.assertEqual(caught.exception.code, "PACKET_UNKNOWN")
            self.assertEqual(db.max_revision(), before)

    def test_reconcile_envelope_must_declare_a_supported_contract_version(self):
        """The batch envelope is validated before anything reaches acceptance."""
        with self.fx.open() as db:
            with self.assertRaises(InvalidRequest) as caught:
                review.reconcile(db, batch={"contract_version": 2, "request_id": "req_old",
                                            "packet_id": "pkt_x", "edits": []})
            self.assertEqual(caught.exception.message, "invalid edit envelope")
            self.assertIn("/contract_version: supported request contract versions are 3 and 4", caught.exception.records)

    def test_recorded_reconciliation_cannot_be_replaced(self):
        """A reconciliation is immutable once created; a later rationale needs a new record."""
        with self.fx.open() as db:
            packet = self.reconcile_packet(db)
            review.reconcile(db, batch=self.fx.batch([self.fx.reconciliation_edit(
                db, "rec_lem", "arg_lem", "chk_comp_lem", self.fx.independent_checks["itm_lem"])],
                packet["packet_id"]))
            stored = db.head("reconciliations", "rec_lem")
            amended = dict(stored.body)
            amended["rationale"] = "changed my mind"
            later = self.reconcile_packet(db)
            before = db.max_revision()
            with self.assertRaises(InvalidRequest) as caught:
                review.reconcile(db, batch=self.fx.batch([
                    edit("replace", "reconciliations", "rec_lem", amended, expected=stored.version)],
                    later["packet_id"]))
            self.assertEqual(caught.exception.code, "WRITE_SCOPE")
            self.assertEqual(db.head("reconciliations", "rec_lem").body["rationale"], "adjudicated")
            self.assertEqual(db.max_revision(), before)


# -- compare ---------------------------------------------------------------------------------------
class CompareTests(TempCase):
    """``compare`` records source-versus-record observations, and only those."""

    def setUp(self):
        super().setUp()
        self.fx = self.fixture()
        self.fx.audit()

    def observation_batch(self):
        with self.fx.open() as db:
            packet = self.fx.packet(db, *Fixture.ITEMS, mode="primary")
            batch = self.fx.batch([observation_edit()], packet["packet_id"])
        return batch, write_json(self.path("compare.json"), batch)

    def test_cli_packet_option_must_name_the_batch_packet(self):
        """``--packet`` disagreeing with the batch is ARGUMENT_MISMATCH and no observation is written."""
        _, batch_path = self.observation_batch()
        payload, _ = run_cli("compare", self.fx.path, "--packet", "pkt_wrong", "--batch", batch_path, expect=2)
        self.assertEqual(payload["error"]["code"], "ARGUMENT_MISMATCH")
        self.assertEqual(payload["error"]["records"], [])
        self.assertIn("--packet pkt_wrong does not match the packet named in the file",
                      payload["error"]["message"])
        with self.fx.open(write=False) as db:
            self.assertIsNone(db.head("observations", "obs_lem"))

    def test_matching_packet_records_the_observation(self):
        """With the packet named consistently the observation is recorded at version 1."""
        batch, batch_path = self.observation_batch()
        payload, _ = run_cli("compare", self.fx.path, "--packet", batch["packet_id"], "--batch", batch_path)
        self.assertEqual(payload["receipt"]["changed"],
                         [{"collection": "observations", "id": "obs_lem", "op": "create", "version": 1}])
        with self.fx.open(write=False) as db:
            stored = db.head("observations", "obs_lem")
            self.assertEqual(stored.version, 1)
            self.assertEqual(stored.body["target"], R("items", "itm_lem"))
            self.assertEqual(stored.body["result"], "matched")

    def test_compare_cannot_author_checks(self):
        """``compare`` is confined to observations; a check edit is refused and nothing is written."""
        with self.fx.open() as db:
            packet = self.fx.packet(db, *Fixture.ITEMS, mode="primary")
            before = db.max_revision()
            with self.assertRaises(InvalidRequest) as caught:
                review.compare(db, batch=self.fx.batch(
                    [Fixture.check_edit("chk_x", R("arguments", "arg_lem"), "composition")],
                    packet["packet_id"]))
            self.assertEqual(caught.exception.code, "INVALID_BATCH")
            self.assertEqual(caught.exception.records,
                             ["edits/0: command compare cannot create checks records"])
            self.assertIsNone(db.head("checks", "chk_x"))
            self.assertEqual(db.max_revision(), before)

    def test_compare_needs_an_author_or_primary_packet(self):
        """A reconcile packet cannot be used to record observations."""
        with self.fx.open() as db:
            packet = self.fx.packet(db, *Fixture.ITEMS, mode="reconcile")
            before = db.max_revision()
            with self.assertRaises(InvalidRequest) as caught:
                review.compare(db, batch=self.fx.batch([observation_edit()], packet["packet_id"]))
            self.assertEqual(caught.exception.code, "PACKET_MODE")
            self.assertIn("['author', 'primary']", caught.exception.message)
            self.assertIsNone(db.head("observations", "obs_lem"))
            self.assertEqual(db.max_revision(), before)


if __name__ == "__main__":
    unittest.main()
