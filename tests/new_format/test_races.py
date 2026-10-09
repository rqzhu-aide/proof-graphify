"""Race fixtures for two batches meeting at one database (implementation-handoff 4.4).

Handoff 4.4 "Required race fixtures" names seven concurrency fixtures; each class below discharges one
clause of that sentence and each test's docstring says which:

* ``UnrelatedUpdateTests``              - unrelated draft updates both commit
* ``SameRecordUpdateTests``             - same-record updates conflict
* ``IncomingPremiseTests``              - an incoming premise conflicts with final-composition submission
* ``OutgoingConsumerTests``             - an outgoing consumer does not stale the supplier
* ``TheoremPartTests``                  - a theorem part conflicts with whole-result completion
* ``ResponseVersusReconciliationTests`` - a response racing reconciliation is never silently omitted
* ``RepeatedRequestTests``              - repeating a successful request returns one commit

Two further classes pin the sentences 4.3 uses to bound what a conflict is, because a core that called
everything a conflict would satisfy 4.4's refusals without being usable:

* ``CosmeticEditTests``          - a label edit conflicts with a replacement yet leaves evidence current
* ``PublicationVersusEditTests`` - a report build or usage receipt never conflicts with a mathematical edit

"Two packets from one revision" is built literally everywhere it is claimed: both packets are issued
before either batch is applied, which is meaningful because issuing a packet never commits. No test
rewrites ``expected_version`` to simulate a race. The receipt's ``rebased_from`` is asserted for the
same reason: it is non-null exactly when the packet's base revision is older than the commit's parent,
so it is the receipt's own record that the batch was prepared before the other batch landed.

Three habits keep the assertions falsifiable rather than merely green:

* every refusal goes through ``RaceCase.refuse``, which pins the documented error code, asserts the head
  revision did not move, asserts no commit row was written and asserts the refused request id is unknown
  to the commit index; each refusal test then also asserts the record it would have written is absent,
  and each conflict test applies the same edits through a replacement packet, so a core that refused
  everything would fail here rather than pass;
* every test that claims a batch "does not conflict" asserts the receipt's ``changed`` list, the stored
  record's version and body and the commit count, so a core whose writes silently did nothing fails;
* every test that claims a guard did not fire also shows, on the same database, a guard that did fire
  (or the exact membership guards the packet carries), so a core carrying no guards at all fails.

The guard sets, binding relations and progress counters below are literals read out of the core once;
they are deliberately not recomputed from ``packets``/``bindings``/``assessment`` at test time.
"""
import copy
import json
import unittest

import support
from support import R, edit

from paper_core import acceptance, assessment, packets, projection, publish, review, telemetry
from paper_core.bindings import binding_changes
from paper_core.errors import ConflictError, CoreError, InvalidRequest
from paper_core.refs import relation_members

# The conflict envelope acceptance.accept raises, verbatim (shared/paper_core/acceptance.py).
CONFLICT_MESSAGE = "the packet's inputs changed; request a replacement packet and rebase the batch"

# assessment.judgment_freshness for a judgment nothing has disturbed.
FRESH = {"freshness": "current", "reused": False, "unbound": False, "changes": None, "context_changed": False}

# Every membership guard a primary packet for one result carries. Written out rather than derived so a
# packet builder that silently stopped emitting guards fails the tests that rely on a guard firing.
LEMMA_GUARDS = [
    ("arguments_for_target", "items", "itm_lem"),
    ("checks_or_findings_for_target", "items", "itm_lem"),
    ("coverage_in_argument", "arguments", "arg_lem"),
    ("groups_in_argument", "arguments", "arg_lem"),
    ("incoming_uses", "items", "itm_lem"),
    ("parts_of_item", "items", "itm_lem"),
    ("scopes_in_argument", "arguments", "arg_lem"),
    ("target_specs_for_target", "items", "itm_lem"),
    ("uses_in_group", "groups", "grp_lem"),
]
THEOREM_GUARDS = [
    ("arguments_for_target", "items", "itm_thm"),
    ("checks_or_findings_for_target", "items", "itm_thm"),
    ("coverage_in_argument", "arguments", "arg_thm"),
    ("groups_in_argument", "arguments", "arg_thm"),
    ("incoming_uses", "items", "itm_thm"),
    ("parts_of_item", "items", "itm_thm"),
    ("scopes_in_argument", "arguments", "arg_thm"),
    ("target_specs_for_target", "items", "itm_lem"),
    ("target_specs_for_target", "items", "itm_thm"),
    ("uses_in_group", "groups", "grp_thm"),
]
# A reconcile packet over both results: both result closures plus the adjudicable targets themselves.
RECONCILE_GUARDS = [
    ("arguments_for_target", "items", "itm_lem"),
    ("arguments_for_target", "items", "itm_thm"),
    ("checks_or_findings_for_target", "arguments", "arg_lem"),
    ("checks_or_findings_for_target", "arguments", "arg_thm"),
    ("checks_or_findings_for_target", "groups", "grp_lem"),
    ("checks_or_findings_for_target", "groups", "grp_thm"),
    ("checks_or_findings_for_target", "items", "itm_lem"),
    ("checks_or_findings_for_target", "items", "itm_thm"),
    ("checks_or_findings_for_target", "uses", "use_lem_thm"),
    ("coverage_in_argument", "arguments", "arg_lem"),
    ("coverage_in_argument", "arguments", "arg_thm"),
    ("groups_in_argument", "arguments", "arg_lem"),
    ("groups_in_argument", "arguments", "arg_thm"),
    ("incoming_uses", "items", "itm_lem"),
    ("incoming_uses", "items", "itm_thm"),
    ("parts_of_item", "items", "itm_lem"),
    ("parts_of_item", "items", "itm_thm"),
    ("scopes_in_argument", "arguments", "arg_lem"),
    ("scopes_in_argument", "arguments", "arg_thm"),
    ("target_specs_for_target", "items", "itm_lem"),
    ("target_specs_for_target", "items", "itm_thm"),
    ("uses_in_group", "groups", "grp_lem"),
    ("uses_in_group", "groups", "grp_thm"),
]
# The stored binding of the lemma's composition check. Nothing here names the theorem, the theorem's
# argument or the use that consumes the lemma: "an outgoing consumer is not a supplier-check guard".
LEMMA_CHECK_BINDING_RELATIONS = [
    ("coverage_in_argument", "arguments", "arg_lem"),
    ("groups_in_argument", "arguments", "arg_lem"),
    ("incoming_uses", "items", "itm_lem"),
    ("parts_of_item", "items", "itm_lem"),
    ("scopes_in_argument", "arguments", "arg_lem"),
    ("target_specs_for_target", "items", "itm_lem"),
    ("uses_in_group", "groups", "grp_lem"),
]
LEMMA_CHECK_BINDING_RECORDS = [
    ("anchors", "anc_lem", 1, "statement"),
    ("anchors", "anc_lem_proof", 1, "proof"),
    ("anchors", "anc_lem_proof", 1, "source"),
    ("arguments", "arg_lem", 1, "proof"),
    ("coverage", "cov_lem", 1, "coverage"),
    ("groups", "grp_lem", 1, "inference"),
    ("items", "itm_lem", 1, "statement"),
    ("proof_boundaries", "bnd_lem", 1, "coverage"),
    ("scopes", "scp_plain", 1, "scope"),
    ("source_reviews", "srv_boundaries", 1, "source"),
    ("target_specs", "tgt_lem", 1, "statement"),
]
# assessment.derive_assessment progress for the finished fixture, and after one late independent reading.
COMPLETE_PROGRESS = {"process_complete": True, "required_obligations": 13, "completed_current_obligations": 13,
                     "draft_checks": 0, "major_results": 2, "source_unbound_items": 0}
REOPENED_PROGRESS = {"process_complete": False, "required_obligations": 13, "completed_current_obligations": 12,
                     "draft_checks": 0, "major_results": 2, "source_unbound_items": 0}
DRAFT_PROGRESS = {"process_complete": True, "required_obligations": 13, "completed_current_obligations": 13,
                  "draft_checks": 1, "major_results": 2, "source_unbound_items": 0}
# A primary packet's write scope for one result, minus the captured source (whose id is content addressed).
LEMMA_WRITE_SCOPE = [("anchors", "anc_lem"), ("anchors", "anc_lem_proof"), ("arguments", "arg_lem"),
                     ("audits", "aud_1"), ("groups", "grp_lem"), ("items", "itm_lem"),
                     ("proof_boundaries", "bnd_lem"), ("scopes", "scp_plain"),
                     ("source_reviews", "srv_boundaries"), ("target_specs", "tgt_lem")]


# -- body builders ---------------------------------------------------------------------------------

def relabel(db, collection, id, label):
    """A replace edit changing only the label, pinned to the version that is live right now."""
    head = db.head(collection, id)
    body = dict(head.body)
    body["label"] = label
    return edit("replace", collection, id, body, head.version)


def premise_edit(uid="use_extra_premise"):
    """An incoming premise for the theorem: a use whose ``to`` is items:itm_thm."""
    return edit("create", "uses", uid, {
        "from": R("items", "itm_lem"), "to": R("items", "itm_thm"), "type": "dependency",
        "group_id": None, "reason": "a second premise discovered later", "needed_form": None,
        "substitutions": [], "evidence_refs": ["anc_thm_proof"], "regime": None, "uncertainty": None})


def consumer_edit(uid="use_lem_thm_b"):
    """An outgoing consumer of the lemma: a use whose ``from`` is items:itm_lem.

    ``group_id`` is None so the use differs from the fixture's ``use_lem_thm`` under the identity
    validation._unique_applications enforces (from, to, type, group_id, needed_form, substitutions,
    regime); otherwise the batch would be refused as a duplicate application instead of racing.
    """
    return edit("create", "uses", uid, {
        "from": R("items", "itm_lem"), "to": R("items", "itm_thm"), "type": "dependency",
        "group_id": None, "reason": "a second, ungrouped application of the lemma", "needed_form": None,
        "substitutions": [], "evidence_refs": ["anc_thm_proof"], "regime": None, "uncertainty": None})


def part_edit(pid="prt_thm_case_b", item="itm_thm", label="Theorem 1(b)", anchor="anc_thm"):
    """A second part of a result, which is what splits a whole result into pieces."""
    return edit("create", "parts", pid, {
        "item_id": item, "label": label,
        "statement": {"form": "verbatim", "text": "the second claim"},
        "passages": [{"role": "statement", "anchor_id": anchor}], "scope_id": None, "origin": "source"})


def finding_edit(fid="fnd_gap", **overrides):
    """An audit finding against the theorem; the record clause 7 must not duplicate."""
    body = {"audit_id": "aud_1", "target": R("items", "itm_thm"), "category": "proof_gap",
            "lifecycle": "open", "description": "the convergence step is not justified",
            "evidence_refs": ["anc_thm_proof"], "check_refs": [], "affected_uses": [],
            "impact_reason": "the theorem's proof depends on this step", "resolution": None}
    body.update(overrides)
    return edit("create", "findings", fid, body)


def worker_response(packet_id, item_id, judgment_target, kind, anchor):
    """One blinded worker response covering ``item_id`` with a single complete judgment."""
    return {"packet_id": packet_id, "covered_targets": [R("items", item_id)],
            "coverage_note": "read the statement and proof from the source",
            "exposure_report": {"status": "none_known", "note": ""},
            "judgments": [{"target": judgment_target, "kind": kind, "state": "complete", "outcome": "supported",
                           "reasoning": "independent reading of the source", "evidence_refs": [anchor],
                           "conditions": [], "next_action": None, "supersedes": None}]}


def submission(packet_id, request_id, reviewer="checker-A"):
    """The coordinator envelope that carries a worker response into the database."""
    return {"contract_version": 3, "request_id": request_id, "packet_id": packet_id, "reviewer": reviewer,
            "qualification_id": "qua_r1", "exposure": "source_only", "exposure_note": ""}


def independent_checks(db):
    """The ids of the live checks that came from an independent response."""
    return sorted(check.id for check in db.heads("checks") if check.body["role"] == "independent")


def commit_count(db):
    return db.conn.execute("SELECT COUNT(*) FROM commits").fetchone()[0]


class RaceCase(support.TempCase):
    """A staged fixture plus the refusal and conflict readers every race test shares."""

    def build(self, stage, name="paper"):
        fixture = self.fixture(name)
        getattr(fixture, stage)()
        db = fixture.open()
        self.addCleanup(db.close)
        return fixture, db

    def guards(self, packet):
        """The packet's membership guards as sorted (relation, collection, id) triples."""
        return sorted((guard["relation"], guard["key"]["collection"], guard["key"]["id"])
                      for guard in packet["membership_guards"])

    def refuse(self, db, code, call, request_id=None):
        """Assert ``call`` raises ``code`` and that the refused batch left no trace of itself."""
        before, commits = db.max_revision(), commit_count(db)
        with self.assertRaises(CoreError) as caught:
            call()
        error = caught.exception
        self.assertEqual(error.code, code, error.records)
        self.assertEqual(db.max_revision(), before, "a refused batch must write nothing")
        self.assertEqual(commit_count(db), commits, "a refused batch must not write a commit row")
        if request_id is not None:
            self.assertIsNone(db.commit_by_request(request_id), "a refused batch must not be recorded")
        return error

    def conflict(self, error):
        """The one conflict record, after pinning the documented conflict envelope around it."""
        self.assertIsInstance(error, ConflictError)
        self.assertEqual(error.message, CONFLICT_MESSAGE)
        self.assertEqual(error.exit_code, 3)
        self.assertEqual(len(error.records), 1, error.records)
        record = error.records[0]
        self.assertIs(record["source_context_changed"], False)
        return record

    def changed_relations(self, error):
        """The (relation, key) pairs a conflict names, after asserting each digest really moved."""
        record = self.conflict(error)
        for change in record["changed_relations"]:
            self.assertNotEqual(change["expected_digest"], change["actual_digest"], change)
        return [(c["relation"], (c["key"]["collection"], c["key"]["id"])) for c in record["changed_relations"]]


class UnrelatedUpdateTests(RaceCase):
    """Handoff 4.4, clause 1: "unrelated draft updates both commit"."""

    def test_two_packets_from_one_revision_commit_unrelated_updates(self):
        """Clause 1: packets issued at one revision for different results both commit, twice in all."""
        fixture, db = self.build("structure")
        base = db.max_revision()
        commits = commit_count(db)
        lemma_packet = fixture.packet(db, "items:itm_lem")
        theorem_packet = fixture.packet(db, "items:itm_thm")
        self.assertNotEqual(lemma_packet["packet_id"], theorem_packet["packet_id"])
        # issuing a packet never commits, so both packets really are pinned to the same revision
        self.assertEqual([lemma_packet["base_revision"], theorem_packet["base_revision"]], [base, base])
        self.assertEqual(db.max_revision(), base)
        lemma_batch = fixture.batch([relabel(db, "arguments", "arg_lem", "Proof of the lemma, revised")],
                                    lemma_packet["packet_id"])
        theorem_batch = fixture.batch([relabel(db, "arguments", "arg_thm", "Proof of the theorem, revised")],
                                      theorem_packet["packet_id"])

        first = acceptance.apply_batch(db, lemma_batch)
        second = acceptance.apply_batch(db, theorem_batch)

        self.assertEqual(first, {"request_id": lemma_batch["request_id"], "revision": base + 1,
                                 "rebased_from": None, "warnings": [],
                                 "changed": [{"collection": "arguments", "id": "arg_lem", "version": 2,
                                              "op": "replace"}]})
        # rebased_from names the second packet's base revision: it was issued before the first commit
        self.assertEqual(second, {"request_id": theorem_batch["request_id"], "revision": base + 2,
                                  "rebased_from": base, "warnings": [],
                                  "changed": [{"collection": "arguments", "id": "arg_thm", "version": 2,
                                               "op": "replace"}]})
        self.assertEqual(db.max_revision(), base + 2, "the revision must advance exactly twice")
        self.assertEqual(commit_count(db), commits + 2, "two accepted batches are two commit rows")
        for id, label in (("arg_lem", "Proof of the lemma, revised"),
                          ("arg_thm", "Proof of the theorem, revised")):
            head = db.head("arguments", id)
            self.assertEqual((head.version, head.retired, head.body["label"]), (2, False, label))
        for receipt in (first, second):
            self.assertEqual(db.commit_by_request(receipt["request_id"])["revision"], receipt["revision"])

    def test_a_newer_global_revision_alone_does_not_stale_a_packet(self):
        """Handoff 4.3: an unrelated theorem draft commits while a worker is checking the lemma."""
        fixture, db = self.build("audit")
        base = db.max_revision()
        lemma_packet = fixture.packet(db, "items:itm_lem", mode="primary")
        self.assertEqual(lemma_packet["base_revision"], base)
        # the packet does carry guards, so surviving below is not the absence of guards
        self.assertEqual(self.guards(lemma_packet), LEMMA_GUARDS)

        draft = fixture.apply(db, [relabel(db, "arguments", "arg_thm", "Proof of the theorem, draft two")],
                              "items:itm_thm")

        self.assertEqual(draft["changed"], [{"collection": "arguments", "id": "arg_thm", "version": 2,
                                             "op": "replace"}])
        self.assertEqual(db.max_revision(), base + 1, "the unrelated draft really did move the revision")
        commits = commit_count(db)

        receipt = acceptance.apply_batch(db, fixture.batch(
            [fixture.check_edit("chk_comp_lem", R("arguments", "arg_lem"), "composition",
                                evidence=["anc_lem_proof"])],
            lemma_packet["packet_id"]))

        self.assertEqual(receipt["changed"], [{"collection": "checks", "id": "chk_comp_lem", "version": 1,
                                               "op": "create"}])
        self.assertEqual((receipt["revision"], receipt["rebased_from"]), (base + 2, base))
        self.assertEqual(commit_count(db), commits + 1)
        check = db.head("checks", "chk_comp_lem")
        self.assertEqual((check.version, check.retired, check.body["role"], check.body["kind"],
                          check.body["target"], check.body["state"]),
                         (1, False, "primary", "composition", R("arguments", "arg_lem"), "complete"))
        snapshot = assessment.Snapshot(db, db.max_revision())
        self.assertEqual(assessment.judgment_freshness(snapshot, check, superseded=False), FRESH)

    def test_a_packet_for_one_result_may_not_write_the_other_result(self):
        """Handoff 4.3: the write scope is what keeps two workers on two results out of each other's way."""
        fixture, db = self.build("audit")
        packet = fixture.packet(db, "items:itm_lem", mode="primary")
        scope = sorted((entry["collection"], entry["id"]) for entry in packet["write_scope"])
        self.assertEqual([entry for entry in scope if entry[0] != "sources"], LEMMA_WRITE_SCOPE)
        self.assertEqual([entry[0] for entry in scope if entry[0] == "sources"], ["sources"])
        poach = fixture.batch([relabel(db, "arguments", "arg_thm", "poached by the lemma's worker")],
                              packet["packet_id"])

        error = self.refuse(db, "WRITE_SCOPE", lambda: acceptance.apply_batch(db, poach), poach["request_id"])

        self.assertIsInstance(error, InvalidRequest)
        self.assertEqual(error.message, "writes outside the packet's write scope")
        self.assertEqual(error.records, ["edits/0: arguments:arg_thm is not in the packet's write scope"])
        self.assertEqual(error.exit_code, 2)
        head = db.head("arguments", "arg_thm")
        self.assertEqual((head.version, head.body["label"]), (1, "Proof of itm_thm"))
        # the same edit through the theorem's own packet commits, so the refusal is about scope alone
        receipt = fixture.apply(db, [relabel(db, "arguments", "arg_thm", "poached by the lemma's worker")],
                                "items:itm_thm")
        self.assertEqual(receipt["changed"], [{"collection": "arguments", "id": "arg_thm", "version": 2,
                                               "op": "replace"}])


class SameRecordUpdateTests(RaceCase):
    """Handoff 4.4, clause 2: "same-record updates conflict"."""

    def test_two_packets_from_one_revision_cannot_both_update_one_record(self):
        """Clause 2: the second batch is refused, writes nothing, and leaves the winner's write intact."""
        fixture, db = self.build("structure")
        base = db.max_revision()
        winner_packet = fixture.packet(db, "items:itm_lem")
        loser_packet = fixture.packet(db, "items:itm_lem")
        self.assertNotEqual(winner_packet["packet_id"], loser_packet["packet_id"])
        self.assertEqual([winner_packet["base_revision"], loser_packet["base_revision"]], [base, base])
        winner_batch = fixture.batch([relabel(db, "arguments", "arg_lem", "winner")], winner_packet["packet_id"])
        loser_batch = fixture.batch([relabel(db, "arguments", "arg_lem", "loser")], loser_packet["packet_id"])
        winner_body = copy.deepcopy(winner_batch["edits"][0]["body"])

        receipt = acceptance.apply_batch(db, winner_batch)
        error = self.refuse(db, "CONFLICT", lambda: acceptance.apply_batch(db, loser_batch),
                            loser_batch["request_id"])

        self.assertEqual(self.conflict(error)["changed"],
                         [{"ref": R("arguments", "arg_lem"), "expected_version": 1, "actual_version": 2,
                           "retired": False}])
        self.assertEqual(self.changed_relations(error), [("arguments_for_target", ("items", "itm_lem"))])
        self.assertEqual(error.retry, {"command": "get DB --target items:itm_lem --mode author --out PACKET.json",
                                       "targets": [R("items", "itm_lem")], "mode": "author"})
        # the loser wrote nothing at all
        self.assertIsNone(db.version("arguments", "arg_lem", 3))
        self.assertEqual([record.version for record in db.versions_of("arguments", "arg_lem")], [1, 2])
        # and the winner's write survives byte for byte
        head = db.head("arguments", "arg_lem")
        self.assertEqual((head.version, head.revision, head.body), (2, receipt["revision"], winner_body))
        # the loser's edit is refused for the race alone: a replacement packet accepts it
        rebased = fixture.apply(db, [relabel(db, "arguments", "arg_lem", "loser")], "items:itm_lem")
        self.assertEqual(rebased["changed"], [{"collection": "arguments", "id": "arg_lem", "version": 3,
                                               "op": "replace"}])
        self.assertEqual(db.head("arguments", "arg_lem").body["label"], "loser")


class CosmeticEditTests(RaceCase):
    """Handoff 4.3: "A cosmetic label edit may conflict with a packet's record replacement while leaving
    its mathematical evidence current"."""

    def test_a_label_edit_conflicts_with_a_replacement_but_leaves_the_judgment_current(self):
        """Optimistic concurrency and mathematical freshness are different questions about one edit."""
        fixture, db = self.build("primary")
        original = copy.deepcopy(db.head("arguments", "arg_lem").body)
        packet = fixture.packet(db, "items:itm_lem")
        check = db.head("checks", "chk_comp_lem")
        self.assertEqual(assessment.judgment_freshness(assessment.Snapshot(db, db.max_revision()), check,
                                                       superseded=False), FRESH)

        cosmetic = fixture.apply(db, [edit("replace", "arguments", "arg_lem",
                                           dict(original, label="Proof of the lemma, retitled"), 1)],
                                 "items:itm_lem")

        self.assertEqual(cosmetic["changed"], [{"collection": "arguments", "id": "arg_lem", "version": 2,
                                                "op": "replace"}])
        # the label edit stales the packet: version 1 is no longer the live version of arguments:arg_lem
        mathematical = dict(original, evidence_refs=["anc_lem_proof", "anc_lem"])
        stale = fixture.batch([edit("replace", "arguments", "arg_lem", mathematical, 1)], packet["packet_id"])
        error = self.refuse(db, "CONFLICT", lambda: acceptance.apply_batch(db, stale), stale["request_id"])
        self.assertEqual(self.conflict(error)["changed"],
                         [{"ref": R("arguments", "arg_lem"), "expected_version": 1, "actual_version": 2,
                           "retired": False}])
        self.assertEqual(self.changed_relations(error), [("arguments_for_target", ("items", "itm_lem"))])
        self.assertEqual(error.retry, {"command": "get DB --target items:itm_lem --mode author --out PACKET.json",
                                       "targets": [R("items", "itm_lem")], "mode": "author"})
        self.assertIsNone(db.version("arguments", "arg_lem", 3))
        self.assertEqual(db.head("arguments", "arg_lem").body["label"], "Proof of the lemma, retitled")
        # yet the label is not part of the argument's proof facet, so the judgment is still current
        self.assertEqual(assessment.judgment_freshness(assessment.Snapshot(db, db.max_revision()), check,
                                                       superseded=False), FRESH)

        # the contrast: replacing the evidence really does move the same judgment off current
        live = db.head("arguments", "arg_lem")
        fixture.apply(db, [edit("replace", "arguments", "arg_lem",
                                dict(live.body, evidence_refs=["anc_lem_proof", "anc_lem"]), live.version)],
                      "items:itm_lem")
        moved = assessment.judgment_freshness(assessment.Snapshot(db, db.max_revision()), check, superseded=False)
        self.assertEqual(moved["freshness"], "historical")
        self.assertEqual(moved["changes"]["relations"], [])
        self.assertEqual([(c["ref"], c["facet"], c["live_version"]) for c in moved["changes"]["records"]],
                         [({"collection": "arguments", "id": "arg_lem", "version": 1}, "proof", 3)])


class IncomingPremiseTests(RaceCase):
    """Handoff 4.4, clause 3: "adding an incoming premise conflicts with final-composition submission"."""

    def test_new_premise_refuses_a_composition_submitted_from_the_older_packet(self):
        """Clause 3: a use landing on the theorem stales a primary packet issued for that result."""
        fixture, db = self.build("audit")
        packet = fixture.packet(db, "items:itm_thm", mode="primary")
        self.assertEqual(self.guards(packet), THEOREM_GUARDS)
        fixture.apply(db, [premise_edit()], "items:itm_thm", mode="author")
        premise = db.head("uses", "use_extra_premise")
        self.assertEqual((premise.version, premise.retired, premise.body["to"]), (1, False, R("items", "itm_thm")))
        composition = fixture.check_edit("chk_comp_thm", R("arguments", "arg_thm"), "composition",
                                         evidence=["anc_thm_proof"])
        stale_batch = fixture.batch([copy.deepcopy(composition)], packet["packet_id"])

        error = self.refuse(db, "CONFLICT", lambda: acceptance.apply_batch(db, stale_batch),
                            stale_batch["request_id"])

        self.assertEqual(self.conflict(error)["changed"], [])
        self.assertEqual(self.changed_relations(error), [("incoming_uses", ("items", "itm_thm"))])
        self.assertEqual(error.retry, {"command": "get DB --target items:itm_thm --mode primary --out PACKET.json",
                                       "targets": [R("items", "itm_thm")], "mode": "primary"})
        # the final composition must be absent afterwards
        self.assertIsNone(db.head("checks", "chk_comp_thm"))
        self.assertEqual(db.heads("checks"), [])
        # the refusal is about the race, not about the batch: a replacement packet accepts the same edit
        receipt = fixture.apply(db, [composition], "items:itm_thm", mode="primary")
        self.assertEqual(receipt["changed"], [{"collection": "checks", "id": "chk_comp_thm", "version": 1,
                                               "op": "create"}])
        stored = db.head("checks", "chk_comp_thm")
        self.assertEqual((stored.version, stored.body["kind"], stored.body["target"]),
                         (1, "composition", R("arguments", "arg_thm")))

    def test_a_conflict_names_every_relation_that_moved(self):
        """Clauses 3 and 5 together: a premise and a part land in one batch and both guards are reported."""
        fixture, db = self.build("audit")
        packet = fixture.packet(db, "items:itm_thm", mode="primary")
        self.assertEqual(self.guards(packet), THEOREM_GUARDS)
        fixture.apply(db, [premise_edit(), part_edit()], "items:itm_thm", mode="author")
        self.assertEqual((db.head("uses", "use_extra_premise").version,
                          db.head("parts", "prt_thm_case_b").version), (1, 1))
        stale = fixture.batch([fixture.check_edit("chk_comp_thm", R("arguments", "arg_thm"), "composition",
                                                  evidence=["anc_thm_proof"])], packet["packet_id"])

        error = self.refuse(db, "CONFLICT", lambda: acceptance.apply_batch(db, stale), stale["request_id"])

        self.assertEqual(self.conflict(error)["changed"], [])
        # both guards are reported: the worker learns everything that moved, not the first thing that did
        self.assertEqual(self.changed_relations(error),
                         [("incoming_uses", ("items", "itm_thm")), ("parts_of_item", ("items", "itm_thm"))])
        self.assertEqual(db.heads("checks"), [])


class OutgoingConsumerTests(RaceCase):
    """Handoff 4.4, clause 4: "adding an outgoing consumer does not stale the supplier"."""

    def test_a_new_consumer_stales_the_consumer_packet_and_not_the_supplier_packet(self):
        """Clause 4: one use, two packets from one revision; only the consumer's packet is staled."""
        fixture, db = self.build("audit")
        base = db.max_revision()
        supplier_packet = fixture.packet(db, "items:itm_lem", mode="primary")
        consumer_packet = fixture.packet(db, "items:itm_thm", mode="primary")
        self.assertEqual([supplier_packet["base_revision"], consumer_packet["base_revision"]], [base, base])
        # the supplier's packet guards incoming_uses of the SUPPLIER; nothing in it is keyed on the consumer
        self.assertEqual(self.guards(supplier_packet), LEMMA_GUARDS)
        self.assertEqual(self.guards(consumer_packet), THEOREM_GUARDS)

        fixture.apply(db, [consumer_edit()], "items:itm_thm", mode="author")

        consumer = db.head("uses", "use_lem_thm_b")
        self.assertEqual((consumer.version, consumer.retired, consumer.body["from"], consumer.body["to"]),
                         (1, False, R("items", "itm_lem"), R("items", "itm_thm")))
        self.assertGreater(db.max_revision(), base)
        commits = commit_count(db)

        receipt = acceptance.apply_batch(db, fixture.batch(
            [fixture.check_edit("chk_comp_lem", R("arguments", "arg_lem"), "composition",
                                evidence=["anc_lem_proof"])],
            supplier_packet["packet_id"]))

        self.assertEqual(receipt["changed"], [{"collection": "checks", "id": "chk_comp_lem", "version": 1,
                                               "op": "create"}])
        self.assertEqual(receipt["warnings"], [])
        # the packet really was issued before the consumer's commit, and still committed
        self.assertEqual(receipt["rebased_from"], supplier_packet["base_revision"])
        self.assertEqual(commit_count(db), commits + 1)
        supplier_check = db.head("checks", "chk_comp_lem")
        self.assertEqual((supplier_check.version, supplier_check.body["target"], supplier_check.body["state"]),
                         (1, R("arguments", "arg_lem"), "complete"))
        snapshot = assessment.Snapshot(db, db.max_revision())
        self.assertEqual(assessment.judgment_freshness(snapshot, supplier_check, superseded=False), FRESH)

        # the same use DOES stale the consumer's packet, so the survival above is not a dead guard
        stale = fixture.batch([fixture.check_edit("chk_comp_thm", R("arguments", "arg_thm"), "composition",
                                                  evidence=["anc_thm_proof"])],
                              consumer_packet["packet_id"])
        error = self.refuse(db, "CONFLICT", lambda: acceptance.apply_batch(db, stale), stale["request_id"])
        self.assertEqual(self.conflict(error)["changed"], [])
        self.assertEqual(self.changed_relations(error), [("incoming_uses", ("items", "itm_thm"))])
        self.assertEqual(error.retry, {"command": "get DB --target items:itm_thm --mode primary --out PACKET.json",
                                       "targets": [R("items", "itm_thm")], "mode": "primary"})
        self.assertEqual([record.id for record in db.heads("checks")], ["chk_comp_lem"])

    def test_consumer_leaves_the_supplier_binding_and_freshness_untouched(self):
        """Clause 4: the supplier's stored binding names only supplier-side records and relations."""
        fixture, db = self.build("primary")
        supplier_check = db.head("checks", "chk_comp_lem")
        consumer_check = db.head("checks", "chk_comp_thm")
        binding_before = db.binding("checks", "chk_comp_lem", supplier_check.version)
        before = assessment.Snapshot(db, db.max_revision())
        self.assertEqual(assessment.judgment_freshness(before, supplier_check, superseded=False), FRESH)
        self.assertEqual(assessment.judgment_freshness(before, consumer_check, superseded=False), FRESH)
        # the binding is exactly the supplier's own closure: no relation and no record names the consumer
        self.assertEqual(sorted((entry["relation"], entry["key"]["collection"], entry["key"]["id"])
                                for entry in binding_before["bindings"]["relations"]),
                         LEMMA_CHECK_BINDING_RELATIONS)
        self.assertEqual(sorted((entry["ref"]["collection"], entry["ref"]["id"], entry["ref"]["version"],
                                 entry["facet"]) for entry in binding_before["bindings"]["records"]
                         if entry["ref"]["collection"] != "sources"),
                         LEMMA_CHECK_BINDING_RECORDS)
        source_bindings = [entry for entry in binding_before["bindings"]["records"]
                           if entry["ref"]["collection"] == "sources"]
        self.assertEqual([(entry["ref"], entry["facet"]) for entry in source_bindings],
                         [(dict(db.heads("sources")[0].ref, version=1), "source")])
        self.assertEqual(relation_members(db.conn, "incoming_uses", R("items", "itm_lem")), [])
        self.assertEqual(relation_members(db.conn, "incoming_uses", R("items", "itm_thm")),
                         [("uses", "use_lem_thm", 1)])

        fixture.apply(db, [consumer_edit()], "items:itm_thm", mode="author")

        # the consumer really was added, and only the consumer's side of the relation moved
        consumer = db.head("uses", "use_lem_thm_b")
        self.assertEqual((consumer.version, consumer.retired, consumer.body["from"], consumer.body["to"]),
                         (1, False, R("items", "itm_lem"), R("items", "itm_thm")))
        self.assertEqual(sorted(relation_members(db.conn, "incoming_uses", R("items", "itm_thm"))),
                         [("uses", "use_lem_thm", 1), ("uses", "use_lem_thm_b", 1)])
        self.assertEqual(relation_members(db.conn, "incoming_uses", R("items", "itm_lem")), [])
        # nothing in the supplier's binding moved, by the core's own comparison of it against the new state
        after = assessment.Snapshot(db, db.max_revision())
        self.assertEqual(binding_changes(after, binding_before["bindings"]), {"records": [], "relations": []})
        self.assertEqual(assessment.judgment_freshness(after, supplier_check, superseded=False), FRESH)
        # the contrast that keeps the assertions above from passing vacuously: the consumer's own
        # judgment does move, and it moves precisely on incoming_uses of the consumer's result
        moved = assessment.judgment_freshness(after, consumer_check, superseded=False)
        self.assertEqual(moved["freshness"], "needs_review")
        self.assertEqual(moved["changes"]["records"], [])
        self.assertEqual([(c["relation"], c["key"]) for c in moved["changes"]["relations"]],
                         [("incoming_uses", R("items", "itm_thm"))])


class TheoremPartTests(RaceCase):
    """Handoff 4.4, clause 5: "adding a theorem part conflicts with whole-result completion"."""

    def test_new_part_refuses_a_whole_result_submission_from_the_older_packet(self):
        """Clause 5: the blind-safe parts_of_item guard fires when a part lands under a submitted result."""
        fixture, db = self.build("primary")
        packet = packets.get_packet(db, targets=[R("items", "itm_thm")], mode="independent")
        # an independent packet hides its contents, so parts_of_item is the one guard it may carry
        self.assertEqual([(guard["relation"], guard["key"]) for guard in packet["membership_guards"]],
                         [("parts_of_item", R("items", "itm_thm"))])
        self.assertEqual(packet["write_scope"], [], "a blinded packet may not write records")
        fixture.apply(db, [part_edit()], "items:itm_thm", mode="author")
        part = db.head("parts", "prt_thm_case_b")
        self.assertEqual((part.version, part.retired, part.body["item_id"]), (1, False, "itm_thm"))
        stale = submission(packet["packet_id"], fixture.request_id())
        response = worker_response(packet["packet_id"], "itm_thm",
                                   {"source_anchor_id": "anc_thm_proof", "description": "the theorem's proof"},
                                   "composition", "anc_thm_proof")

        error = self.refuse(db, "CONFLICT", lambda: review.submit_review(
            db, submission=stale, response_bytes=json.dumps(response).encode("utf-8")), stale["request_id"])

        self.assertEqual(self.conflict(error)["changed"], [])
        self.assertEqual(self.changed_relations(error), [("parts_of_item", ("items", "itm_thm"))])
        self.assertEqual(error.retry,
                         {"command": "get DB --target items:itm_thm --mode independent --out PACKET.json",
                          "targets": [R("items", "itm_thm")], "mode": "independent"})
        # the completion did not land: no response and no independent judgment
        self.assertEqual(db.heads("responses"), [])
        self.assertEqual(independent_checks(db), [])

        # a replacement packet accepts the same submission, and the completion really does land through it
        fresh = packets.get_packet(db, targets=[R("items", "itm_thm")], mode="independent")
        body = json.dumps(worker_response(
            fresh["packet_id"], "itm_thm",
            {"source_anchor_id": "anc_thm_proof", "description": "the theorem's proof"},
            "composition", "anc_thm_proof")).encode("utf-8")
        accepted = review.submit_review(db, submission=submission(fresh["packet_id"], fixture.request_id()),
                                        response_bytes=body)
        self.assertEqual(accepted["state"], "needs_revision", accepted)
        self.assertEqual(accepted["pending"], [{"judgment_index": 0, "reason": (
            "SourceTarget on anchor anc_thm_proof awaits mapping: the theorem's proof")}])
        self.assertEqual(accepted["checks"], [])
        stored = db.head("responses", accepted["response_id"])
        self.assertEqual([record.id for record in db.heads("responses")], [accepted["response_id"]])
        self.assertEqual((stored.version, stored.body["state"]), (1, "needs_revision"))
        self.assertEqual(db.get_blob(stored.body["original_blob"]), body, "the worker's bytes are preserved")

        mapping_packet = fixture.packet(db, *support.Fixture.ITEMS, mode="primary")
        mapped = review.map_response(db, mapping={
            "contract_version": 3, "request_id": fixture.request_id(), "packet_id": mapping_packet["packet_id"],
            "response_id": accepted["response_id"],
            "entries": [{"judgment_index": 0, "target": R("arguments", "arg_thm"),
                         "rationale": "the proof passage is this argument"}], "reviewer": "coord"})
        self.assertEqual(mapped["state"], "accepted")
        self.assertEqual(independent_checks(db), [mapped["checks"][0]["check_id"]])
        judgment = db.head("checks", mapped["checks"][0]["check_id"])
        self.assertEqual((judgment.version, judgment.body["role"], judgment.body["target"],
                          judgment.body["kind"], judgment.body["response_id"]),
                         (1, "independent", R("arguments", "arg_thm"), "composition", accepted["response_id"]))
        self.assertEqual(db.head("responses", accepted["response_id"]).version, 2)

    def test_a_part_of_the_other_result_leaves_the_blinded_packet_usable(self):
        """Clause 5: parts_of_item is keyed on the submitted result, not on every result in the paper."""
        fixture, db = self.build("primary")
        packet = packets.get_packet(db, targets=[R("items", "itm_thm")], mode="independent")
        base = packet["base_revision"]

        fixture.apply(db, [part_edit("prt_lem_case_b", item="itm_lem", label="Lemma 1(b)", anchor="anc_lem")],
                      "items:itm_lem", mode="author")

        part = db.head("parts", "prt_lem_case_b")
        self.assertEqual((part.version, part.retired, part.body["item_id"]), (1, False, "itm_lem"))
        self.assertIsNone(db.head("parts", "prt_thm_case_b"))
        self.assertGreater(db.max_revision(), base)
        commits = commit_count(db)

        accepted = review.submit_review(
            db, submission=submission(packet["packet_id"], fixture.request_id()),
            response_bytes=json.dumps(worker_response(packet["packet_id"], "itm_thm", R("items", "itm_thm"),
                                                      "external_source", "anc_thm")).encode("utf-8"))

        self.assertEqual(accepted["state"], "accepted")
        self.assertEqual(accepted["receipt"]["rebased_from"], base, "the packet predates the lemma's part")
        self.assertEqual(commit_count(db), commits + 1)
        self.assertEqual(independent_checks(db), [accepted["checks"][0]["check_id"]])
        judgment = db.head("checks", accepted["checks"][0]["check_id"])
        self.assertEqual((judgment.version, judgment.body["role"], judgment.body["target"],
                          judgment.body["kind"], judgment.body["state"]),
                         (1, "independent", R("items", "itm_thm"), "external_source", "complete"))


class ResponseVersusReconciliationTests(RaceCase):
    """Handoff 4.4, clause 6: "response submission racing reconciliation cannot silently omit the response"."""

    def arrange(self):
        """An independent-stage fixture, a reconcile packet, and a second response for the lemma."""
        fixture, db = self.build("independent")
        packet = fixture.packet(db, *support.Fixture.ITEMS, mode="reconcile")
        self.assertEqual(self.guards(packet), RECONCILE_GUARDS)
        late_check, mapped = fixture.independent_round(
            db, "itm_lem", "arg_lem", "anc_lem_proof",
            judgment_target={"source_anchor_id": "anc_lem_proof", "description": "a second independent reading"})
        response = db.head("responses", mapped["response_id"])
        # the coordinator's mapping replaced the submitted response, so the accepted response is version 2
        self.assertEqual((response.version, response.body["state"]), (2, "accepted"))
        self.assertEqual(db.head("checks", late_check).body["response_id"], response.id)
        self.assertEqual(db.head("checks", late_check).body["target"], R("arguments", "arg_lem"))
        return fixture, db, packet, late_check, response

    def assert_response_survives(self, db, response, late_check):
        """The response is still present at the version it had, retrievable, and its check still lives."""
        stored = db.head("responses", response.id)
        self.assertEqual((stored.version, stored.retired, stored.body["state"]),
                         (response.version, False, "accepted"))
        self.assertEqual(json.loads(db.get_blob(stored.body["original_blob"]).decode("utf-8"))["covered_targets"],
                         [R("items", "itm_lem")])
        self.assertIn(late_check, independent_checks(db))
        self.assertIs(db.head("checks", late_check).retired, False)

    def test_reconciling_through_the_packet_the_response_overtook_is_refused(self):
        """Clause 6, submission first: the reconcile packet is stale and the response is still there."""
        fixture, db, packet, late_check, response = self.arrange()
        omission = fixture.batch([fixture.reconciliation_edit(db, "rec_lem", "arg_lem", "chk_comp_lem",
                                                              fixture.independent_checks["itm_lem"])],
                                 packet["packet_id"])

        error = self.refuse(db, "CONFLICT", lambda: review.reconcile(db, batch=omission),
                            omission["request_id"])

        self.assertEqual(self.conflict(error)["changed"], [])
        self.assertEqual(self.changed_relations(error),
                         [("checks_or_findings_for_target", ("arguments", "arg_lem"))])
        self.assertEqual(error.retry, {"command": ("get DB --target items:itm_lem --target items:itm_thm "
                                                   "--mode reconcile --out PACKET.json"),
                                       "targets": [R("items", "itm_lem"), R("items", "itm_thm")],
                                       "mode": "reconcile"})
        self.assertIsNone(db.head("reconciliations", "rec_lem"))
        self.assert_response_survives(db, response, late_check)

    def test_a_replacement_packet_still_refuses_to_drop_the_response(self):
        """Clause 6, submission first: rebasing cannot omit the late check; listing it commits."""
        fixture, db, _packet, late_check, response = self.arrange()
        first_check = fixture.independent_checks["itm_lem"]
        replacement = fixture.packet(db, *support.Fixture.ITEMS, mode="reconcile")
        omission = fixture.batch(
            [fixture.reconciliation_edit(db, "rec_lem", "arg_lem", "chk_comp_lem", first_check)],
            replacement["packet_id"])

        error = self.refuse(db, "INVALID_BATCH", lambda: review.reconcile(db, batch=omission),
                            omission["request_id"])

        self.assertIsInstance(error, InvalidRequest)
        self.assertEqual(error.message, "batch failed validation")
        self.assertEqual(error.records, [f"edits/0 reconciliations:rec_lem: independent check {late_check} "
                                         f"from response {response.id} is not listed"])
        self.assertEqual(error.exit_code, 2)
        self.assertIsNone(db.head("reconciliations", "rec_lem"))
        self.assert_response_survives(db, response, late_check)
        # the only reconciliation the core accepts is the one that counts the raced response
        listed = fixture.reconciliation_edit(db, "rec_lem", "arg_lem", "chk_comp_lem", first_check)
        listed["body"]["independent_checks"].append(fixture.pin(db, "checks", late_check))
        receipt = review.reconcile(db, batch=fixture.batch(
            [listed], fixture.packet(db, *support.Fixture.ITEMS, mode="reconcile")["packet_id"]))
        self.assertEqual(receipt["changed"], [{"collection": "reconciliations", "id": "rec_lem", "version": 1,
                                               "op": "create"}])
        self.assertEqual([pin["id"] for pin in db.head("reconciliations", "rec_lem").body["independent_checks"]],
                         [first_check, late_check])

    def test_a_response_arriving_after_reconciliation_is_counted(self):
        """Clause 6, reconciliation first: the late response reopens the obligation it answers."""
        fixture, db = self.build("complete")
        before = assessment.derive_assessment(db, audit_id="aud_1")
        self.assertEqual(before["independent"], {"items:itm_lem": "complete", "items:itm_thm": "complete"})
        self.assertEqual(before["progress"], COMPLETE_PROGRESS)
        base = db.max_revision()

        late_check, mapped = fixture.independent_round(
            db, "itm_lem", "arg_lem", "anc_lem_proof",
            judgment_target={"source_anchor_id": "anc_lem_proof", "description": "a late second reading"})

        self.assertGreater(db.max_revision(), base)
        response = db.head("responses", mapped["response_id"])
        self.assertEqual((response.version, response.body["state"]), (2, "accepted"))
        self.assert_response_survives(db, response, late_check)
        # the reconciliation that went first is untouched, and the late response is counted against it
        reconciliation = db.head("reconciliations", "rec_lem")
        self.assertEqual(reconciliation.version, 1)
        self.assertNotIn(late_check, [pin["id"] for pin in reconciliation.body["independent_checks"]])
        after = assessment.derive_assessment(db, audit_id="aud_1")
        self.assertEqual(after["independent"], {"items:itm_lem": "pending", "items:itm_thm": "complete"})
        self.assertEqual(after["progress"], REOPENED_PROGRESS)

    def test_a_draft_response_arriving_after_reconciliation_does_not_reopen_the_obligation(self):
        """Clause 6: an unfinished reading is stored and counted as a draft, but is not a second opinion."""
        fixture, db = self.build("complete")
        self.assertEqual(assessment.derive_assessment(db, audit_id="aud_1")["progress"], COMPLETE_PROGRESS)
        packet = packets.get_packet(db, targets=[R("items", "itm_lem")], mode="independent")
        response = worker_response(packet["packet_id"], "itm_lem", R("items", "itm_lem"),
                                   "external_source", "anc_lem")
        response["judgments"][0].update({"state": "draft", "outcome": "inconclusive",
                                         "next_action": "finish reading the proof"})

        accepted = review.submit_review(
            db, submission=submission(packet["packet_id"], fixture.request_id()),
            response_bytes=json.dumps(response).encode("utf-8"))

        self.assertEqual(accepted["state"], "accepted")
        draft = db.head("checks", accepted["checks"][0]["check_id"])
        self.assertEqual((draft.version, draft.body["role"], draft.body["state"], draft.body["target"]),
                         (1, "independent", "draft", R("items", "itm_lem")))
        after = assessment.derive_assessment(db, audit_id="aud_1")
        self.assertEqual(after["independent"], {"items:itm_lem": "complete", "items:itm_thm": "complete"})
        self.assertEqual(after["progress"], DRAFT_PROGRESS)


class RepeatedRequestTests(RaceCase):
    """Handoff 4.4, clause 7: "repeating a successful request returns one commit, not duplicate findings"."""

    def test_replaying_an_accepted_batch_returns_the_stored_receipt(self):
        """Clause 7: the same request id and bytes twice leave one commit and one finding."""
        fixture, db = self.build("primary")
        packet = fixture.packet(db, "items:itm_thm", mode="primary")
        batch = {"contract_version": 3, "request_id": "req_race_once", "packet_id": packet["packet_id"],
                 "edits": [finding_edit()]}
        commits = commit_count(db)

        first = acceptance.apply_batch(db, copy.deepcopy(batch))
        revision = db.max_revision()
        second = acceptance.apply_batch(db, copy.deepcopy(batch))

        self.assertEqual(first["changed"], [{"collection": "findings", "id": "fnd_gap", "version": 1,
                                             "op": "create"}])
        self.assertEqual(second, first, "a replay returns the stored receipt")
        self.assertEqual(db.max_revision(), revision, "a replay must not advance the revision")
        self.assertEqual(commit_count(db), commits + 1, "a replay must not write a second commit")
        self.assertEqual([(record.id, record.version) for record in db.heads("findings")], [("fnd_gap", 1)])
        self.assertEqual([record.version for record in db.versions_of("findings", "fnd_gap")], [1])
        self.assertIsNone(db.version("findings", "fnd_gap", 2))
        self.assertEqual(db.commit_by_request("req_race_once")["revision"], first["revision"])

    def test_reusing_a_request_id_for_different_edits_is_refused(self):
        """Clause 7: the one-commit rule is by request id and digest, so different bytes are refused."""
        fixture, db = self.build("primary")
        packet = fixture.packet(db, "items:itm_thm", mode="primary")
        receipt = acceptance.apply_batch(db, {"contract_version": 3, "request_id": "req_race_once",
                                              "packet_id": packet["packet_id"], "edits": [finding_edit()]})
        other = {"contract_version": 3, "request_id": "req_race_once", "packet_id": packet["packet_id"],
                 "edits": [finding_edit("fnd_other")]}

        error = self.refuse(db, "REQUEST_ID_REUSED", lambda: acceptance.apply_batch(db, other))

        self.assertIsInstance(error, InvalidRequest)
        self.assertEqual(error.message, "request id req_race_once was already used for a different batch")
        self.assertEqual(error.records, [{"request_id": "req_race_once", "revision": receipt["revision"]}])
        self.assertEqual(error.exit_code, 2)
        self.assertIsNone(db.head("findings", "fnd_other"))
        self.assertEqual([(record.id, record.version) for record in db.heads("findings")], [("fnd_gap", 1)])
        self.assertEqual(db.commit_by_request("req_race_once")["revision"], receipt["revision"])

    def test_retrying_the_same_edits_through_a_replacement_packet_is_refused(self):
        """Clause 7: the realistic retry - re-request a packet, resend - cannot duplicate the finding."""
        fixture, db = self.build("primary")
        packet = fixture.packet(db, "items:itm_thm", mode="primary")
        receipt = acceptance.apply_batch(db, {"contract_version": 3, "request_id": "req_race_once",
                                              "packet_id": packet["packet_id"],
                                              "edits": [copy.deepcopy(finding_edit())]})
        replacement = fixture.packet(db, "items:itm_thm", mode="primary")
        self.assertNotEqual(replacement["packet_id"], packet["packet_id"])
        retry = {"contract_version": 3, "request_id": "req_race_once", "packet_id": replacement["packet_id"],
                 "edits": [copy.deepcopy(finding_edit())]}

        error = self.refuse(db, "REQUEST_ID_REUSED", lambda: acceptance.apply_batch(db, retry))

        self.assertIsInstance(error, InvalidRequest)
        self.assertEqual(error.records, [{"request_id": "req_race_once", "revision": receipt["revision"]}])
        self.assertEqual([(record.id, record.version) for record in db.heads("findings")], [("fnd_gap", 1)])
        self.assertEqual([record.version for record in db.versions_of("findings", "fnd_gap")], [1])
        # and the batch the retry meant to send is accepted under its own request id
        accepted = acceptance.apply_batch(db, {"contract_version": 3, "request_id": "req_race_twice",
                                               "packet_id": replacement["packet_id"],
                                               "edits": [finding_edit("fnd_second")]})
        self.assertEqual(accepted["changed"], [{"collection": "findings", "id": "fnd_second", "version": 1,
                                                "op": "create"}])

    def test_replaying_a_review_submission_returns_one_judgment(self):
        """Clause 7: a repeated submission returns one receipt, one response and one independent check."""
        fixture, db = self.build("primary")
        packet = packets.get_packet(db, targets=[R("items", "itm_thm")], mode="independent")
        request = submission(packet["packet_id"], "req_race_submit_once")
        body = json.dumps(worker_response(packet["packet_id"], "itm_thm", R("items", "itm_thm"),
                                          "external_source", "anc_thm")).encode("utf-8")
        commits = commit_count(db)

        first = review.submit_review(db, submission=copy.deepcopy(request), response_bytes=body)
        revision = db.max_revision()
        second = review.submit_review(db, submission=copy.deepcopy(request), response_bytes=body)

        self.assertEqual(first["state"], "accepted")
        self.assertEqual(second, first, "a replayed submission returns the stored result")
        self.assertEqual(db.max_revision(), revision, "a replayed submission must not advance the revision")
        self.assertEqual(commit_count(db), commits + 1)
        self.assertEqual([record.id for record in db.heads("responses")], [first["response_id"]])
        self.assertEqual([record.version for record in db.versions_of("responses", first["response_id"])], [1])
        self.assertEqual(independent_checks(db), [first["checks"][0]["check_id"]])
        self.assertEqual(db.head("checks", first["checks"][0]["check_id"]).version, 1)


class PublicationVersusEditTests(RaceCase):
    """Handoff 4.3: "A report build or usage receipt never conflicts with a mathematical edit"."""

    def test_publishing_a_report_and_recording_a_usage_event_do_not_stale_a_packet(self):
        """Neither a publication row nor a run event allocates a revision, so no packet is disturbed."""
        fixture, db = self.build("complete")
        base = db.max_revision()
        packet = fixture.packet(db, "items:itm_lem")
        self.assertEqual(packet["base_revision"], base)
        commits = commit_count(db)

        report = publish.publish_report(
            db, projection=projection.build_projection(db, revision=base, audit_id="aud_1"),
            output=self.path("report.html"))
        event = telemetry.record_event(db, run_id="run_race", stage="report", elapsed_ms=7,
                                       details={"note": "report build"})

        self.assertEqual((report["state"], report["revision"]), ("published", base))
        self.assertTrue(self.path("report.html").exists())
        self.assertEqual([(row["revision"], row["state"]) for row in db.publications()], [(base, "published")])
        self.assertEqual([record["event_id"] for record in telemetry.events(db, run_id="run_race")],
                         [event["event_id"]])
        self.assertEqual(db.max_revision(), base, "a report build allocates no revision")
        self.assertEqual(commit_count(db), commits, "a report build writes no commit")

        receipt = acceptance.apply_batch(db, fixture.batch(
            [relabel(db, "arguments", "arg_lem", "Proof of the lemma, after the report")],
            packet["packet_id"]))

        self.assertEqual(receipt["changed"], [{"collection": "arguments", "id": "arg_lem", "version": 2,
                                               "op": "replace"}])
        # rebased_from is null: nothing at all landed between the packet's base and this commit's parent
        self.assertEqual((receipt["revision"], receipt["rebased_from"]), (base + 1, None))
        self.assertEqual(commit_count(db), commits + 1)
        head = db.head("arguments", "arg_lem")
        self.assertEqual((head.version, head.body["label"]), (2, "Proof of the lemma, after the report"))


if __name__ == "__main__":
    unittest.main()
