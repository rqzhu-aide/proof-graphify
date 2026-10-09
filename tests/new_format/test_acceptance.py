"""Tests for the database-backed acceptance path (implementation-handoff 9).

Exercises shared/paper_core/acceptance.py (receipts, idempotency, optimistic concurrency, packet
gating, atomicity), shared/paper_core/contract.py (the contract-3 envelope, closed body schemas and
reference extraction) and shared/paper_core/validation.py (command permissions, reference integrity,
scope rules, retire rules and the global-task rules). Every fixture is built through the public API,
so a behaviour that stops being reachable through apply_batch fails here instead of drifting.

Every refusal test goes through ``AcceptanceCase.refuse``, which pins the error code *and* asserts
that the database's head revision did not move, so "nothing was written" is checked on every failure
path rather than only on the ones that name it.
"""
import json
import unittest

import support
from support import GLOBAL_TASKS, HANDOFF, R, edit, sha

from paper_core import acceptance, contract
from paper_core.canonical import digest
from paper_core.errors import ConflictError, CoreError
from paper_core.ids import COLLECTIONS

EXAMPLE_BATCH = HANDOFF / "example-batch.json"

EXAMPLE_RECORDS = [
    ("scopes", "scp_example"),
    ("items", "itm_event_a"), ("items", "itm_event_b"), ("items", "itm_joint"), ("items", "itm_target"),
    ("arguments", "arg_joint"), ("arguments", "arg_target"),
    ("groups", "grp_joint"), ("groups", "grp_target"),
    ("uses", "use_a_joint"), ("uses", "use_b_joint"), ("uses", "use_joint_target"),
    ("application_details", "use_a_joint"), ("application_details", "use_b_joint"), ("application_details", "use_joint_target")]

# The items schema in field order; a body carrying only "kind" must report each of the rest as missing.
ITEM_FIELDS_AFTER_KIND = ("label", "caption", "statement", "passages", "aliases", "uncertainty")


# -- body builders ---------------------------------------------------------------------------------
# support.Fixture.item_edit always pins owner_id and scope_id to None, so these local builders exist
# to construct bodies whose only defect is the one the test is pinning.

def item_body(kind, label, **overrides):
    body = {"kind": kind, "label": label, "caption": label,
            "statement": {"form": "synopsis", "text": label + " statement"},
            "passages": [], "aliases": [], "uncertainty": None, "origin": "reconstruction",
            "owner_id": None, "scope_id": None}
    body.update(overrides)
    return body


def use_body(**overrides):
    body = {"from": R("items", "itm_lem"), "to": R("items", "itm_thm"), "type": "dependency",
            "group_id": "grp_thm", "reason": "applied as stated", "needed_form": {"form":"verbatim","text":"Lemma 1 text"},
            "substitutions": [], "evidence_refs": [], "regime": None, "uncertainty": None}
    body.update(overrides)
    return body


def scope_body(**overrides):
    body = {"argument_id": None, "parent_id": None, "assumptions": [], "binders": [], "conditions": [],
            "evidence_refs": []}
    body.update(overrides)
    return body


def anchor_body(fixture, **overrides):
    body = {"source_id": fixture.source_id, "source_version": 1, "locator": support.locator(label="lem:a"),
            "excerpt": "", "excerpt_sha256": sha(b""), "method": "label_match", "limitation": None}
    body.update(overrides)
    return body


def audit_body(paper_id, **overrides):
    body = {"paper_id": paper_id, "mode": "focused", "targets": list(support.Fixture.ITEM_REFS),
            "exclusions": [], "protocol_version": "item-audit/1", "independent_required": True,
            "qualification_id": "qua_r1", "report_path": "reports/audit.html",
            "global_tasks": [dict(task) for task in GLOBAL_TASKS]}
    body.update(overrides)
    return body


def check_body(**overrides):
    body = {"audit_id": "aud_1", "target": R("arguments", "arg_lem"), "kind": "composition",
            "role": "primary", "reviewer": "primary-1", "protocol_version": "item-audit/1",
            "state": "draft", "outcome": None, "reasoning": "checked against the source",
            "evidence_refs": [], "conditions": [], "next_action": "Finish the remaining source examination", "response_id": None,
            "supersedes": None}
    body.update(overrides)
    return body


def tasks(*kinds, applicability="required", reason=""):
    return [{"kind": kind, "applicability": applicability, "reason": reason} for kind in kinds]


class AcceptanceCase(support.TempCase):
    """A fixture database plus the two assertions every acceptance test needs."""

    def build(self, stage=None, name="paper", **kwargs):
        """Return (fixture, open database) for a fixture advanced to `stage` (None: just initialized)."""
        fixture = self.fixture(name, **kwargs)
        if stage is not None:
            getattr(fixture, stage)()
        db = fixture.open()
        self.addCleanup(db.close)
        return fixture, db

    def refuse(self, db, code, call):
        """Assert `call` raises a CoreError carrying `code` and that the database is untouched."""
        before = db.max_revision()
        with self.assertRaises(CoreError) as caught:
            call()
        error = caught.exception
        self.assertEqual(error.code, code, error.records)
        self.assertEqual(db.max_revision(), before, "a refused batch must write nothing")
        return error

    def refuse_batch(self, fixture, db, code, edits, *targets, mode="author"):
        """Request a packet, apply `edits` through it, and assert the documented refusal."""
        packet = fixture.packet(db, *targets, mode=mode)
        batch = fixture.batch(edits, packet["packet_id"])
        return self.refuse(db, code, lambda: acceptance.apply_batch(db, batch))


class ReceiptTests(AcceptanceCase):
    """apply_batch applies a batch and reports exactly what it wrote."""

    def test_create_batch_returns_a_receipt_naming_every_new_record(self):
        """A create batch commits one revision and reports each created record at version 1."""
        fixture, db = self.build("structure")
        before = db.max_revision()
        receipt = fixture.apply(db, [edit("create", "items", "itm_new",
                                          item_body("intermediate_result", "Step", owner_id="itm_thm"))],
                                *fixture.ITEMS)
        self.assertEqual(sorted(receipt), ["changed", "rebased_from", "request_id", "revision", "warnings"])
        self.assertEqual(receipt["revision"], before + 1)
        self.assertIsNone(receipt["rebased_from"])
        self.assertEqual(receipt["warnings"], [])
        self.assertEqual(receipt["changed"],
                         [{"collection": "items", "id": "itm_new", "version": 1, "op": "create"}])
        self.assertEqual(db.max_revision(), receipt["revision"])

    def test_a_created_record_becomes_a_live_head_at_version_one(self):
        """The record named in the receipt is readable as a live head carrying the submitted body."""
        fixture, db = self.build("structure")
        body = item_body("intermediate_result", "Step", owner_id="itm_thm")
        fixture.apply(db, [edit("create", "items", "itm_new", body)], *fixture.ITEMS)
        head = db.head("items", "itm_new")
        self.assertEqual(head.version, 1)
        self.assertFalse(head.retired)
        self.assertEqual(head.body, body)

    def test_the_commit_row_records_the_request_that_produced_it(self):
        """Each accepted batch leaves one commit row keyed by its request id, digest and base revision."""
        fixture, db = self.build("structure")
        packet = fixture.packet(db)
        batch = fixture.batch([edit("create", "scopes", "scp_extra", scope_body())], packet["packet_id"])
        receipt = acceptance.apply_batch(db, batch)
        commit = db.commit_row(receipt["revision"])
        self.assertEqual(commit["request_id"], batch["request_id"])
        self.assertEqual(commit["request_digest"], digest(batch))
        self.assertEqual(commit["parent_revision"], receipt["revision"] - 1)
        self.assertEqual(commit["base_revision"], packet["base_revision"])
        self.assertEqual(json.loads(commit["receipt_json"]), receipt)

    def test_replaying_the_identical_batch_returns_the_same_receipt(self):
        """Idempotency: the same request id and bytes replay the stored receipt without a new commit."""
        fixture, db = self.build("structure")
        packet = fixture.packet(db)
        batch = fixture.batch([edit("create", "scopes", "scp_extra", scope_body())], packet["packet_id"])
        first = acceptance.apply_batch(db, batch)
        revision = db.max_revision()
        self.assertEqual(acceptance.apply_batch(db, batch), first)
        self.assertEqual(db.max_revision(), revision)
        self.assertEqual(db.head("scopes", "scp_extra").version, 1)

    def test_reusing_a_request_id_for_different_bytes_is_refused(self):
        """A request id may name only one batch; different bytes under it are REQUEST_ID_REUSED."""
        fixture, db = self.build("structure")
        packet = fixture.packet(db)
        batch = fixture.batch([edit("create", "scopes", "scp_extra", scope_body())], packet["packet_id"])
        receipt = acceptance.apply_batch(db, batch)
        replayed = json.loads(json.dumps(batch))
        replayed["edits"][0]["body"]["conditions"] = ["changed"]
        error = self.refuse(db, "REQUEST_ID_REUSED",
                            lambda: acceptance.apply_batch(db, replayed))
        self.assertEqual(error.message, f"request id {batch['request_id']} was already used for a different batch")
        self.assertEqual(error.records, [{"request_id": batch["request_id"], "revision": receipt["revision"]}])
        self.assertEqual(db.head("scopes", "scp_extra").body["conditions"], [])

    def test_a_batch_applied_after_its_packet_base_reports_the_rebase(self):
        """rebased_from names the packet's base revision whenever the head has moved past it."""
        fixture, db = self.build("structure")
        stale_packet = fixture.packet(db)
        fixture.apply(db, [edit("create", "scopes", "scp_meanwhile", scope_body())])
        self.assertGreater(db.max_revision(), stale_packet["base_revision"])
        receipt = acceptance.apply_batch(db, fixture.batch(
            [edit("create", "scopes", "scp_late", scope_body())], stale_packet["packet_id"]))
        self.assertEqual(receipt["rebased_from"], stale_packet["base_revision"])
        self.assertEqual(receipt["revision"], stale_packet["base_revision"] + 2)
        self.assertEqual(db.head("scopes", "scp_late").version, 1)

    def test_accept_threads_warnings_and_annotations_into_the_receipt(self):
        """accept() copies its warnings verbatim and merges per-record annotations into changed."""
        fixture, db = self.build("structure")
        packet = fixture.packet(db)
        receipt = acceptance.accept(
            db, request_id="req_annotated", request_digest="a" * 64, packet_id=packet["packet_id"],
            edits=[edit("create", "scopes", "scp_ann", scope_body())], command="apply",
            warnings=["source context is stale"], annotations={("scopes", "scp_ann"): {"note": "seeded"}})
        self.assertEqual(receipt["warnings"], ["source context is stale"])
        self.assertEqual(receipt["changed"], [{"collection": "scopes", "id": "scp_ann", "version": 1,
                                               "op": "create", "note": "seeded"}])
        self.assertEqual(json.loads(db.commit_row(receipt["revision"])["receipt_json"]), receipt)

    def test_a_read_only_database_refuses_every_batch(self):
        """A batch offered to a read-only connection is refused before the transaction opens."""
        fixture, db = self.build("structure")
        packet = fixture.packet(db)
        batch = fixture.batch([edit("create", "scopes", "scp_ro", scope_body())], packet["packet_id"])
        reader = fixture.open(write=False)
        self.addCleanup(reader.close)
        error = self.refuse(reader, "INVALID_REQUEST", lambda: acceptance.apply_batch(reader, batch))
        self.assertEqual(error.message, "the database is open read-only")
        self.assertIsNone(db.head("scopes", "scp_ro"))


class ExpectedVersionTests(AcceptanceCase):
    """expected_version is the optimistic-concurrency token of every edit."""

    def test_create_requires_a_null_expected_version(self):
        """A create edit carrying a version is refused by the envelope before anything is planned."""
        fixture, db = self.build("structure")
        error = self.refuse_batch(fixture, db, "INVALID_REQUEST",
                                  [edit("create", "scopes", "scp_extra", scope_body(), 1)], *fixture.ITEMS)
        self.assertEqual(error.message, "invalid edit envelope")
        self.assertEqual(error.records, ["/edits/0/expected_version: must be null"])

    def test_replace_requires_a_non_null_expected_version(self):
        """A replace edit without a version is refused by the envelope."""
        fixture, db = self.build("structure")
        body = dict(db.head("items", "itm_lem").body)
        error = self.refuse_batch(fixture, db, "INVALID_REQUEST",
                                  [edit("replace", "items", "itm_lem", body, None)], *fixture.ITEMS)
        self.assertEqual(error.records, ["/edits/0/expected_version: null is not allowed"])

    def test_replace_at_the_current_version_appends_the_next_version(self):
        """A replace pinned at the head version stores version n+1 and leaves version n intact."""
        fixture, db = self.build("structure")
        original = db.head("items", "itm_lem")
        body = dict(original.body)
        body["caption"] = "renamed"
        receipt = fixture.apply(db, [edit("replace", "items", "itm_lem", body, original.version)],
                                *fixture.ITEMS)
        self.assertEqual(receipt["changed"],
                         [{"collection": "items", "id": "itm_lem", "version": original.version + 1,
                           "op": "replace"}])
        self.assertEqual(db.head("items", "itm_lem").body["caption"], "renamed")
        self.assertEqual(db.version("items", "itm_lem", original.version).body, original.body)

    def test_a_stale_expected_version_conflicts_and_writes_nothing(self):
        """A replace pinned at a superseded version raises CONFLICT naming expected and actual versions."""
        fixture, db = self.build("structure")
        original = db.head("items", "itm_lem")
        body = dict(original.body)
        body["caption"] = "renamed"
        fixture.apply(db, [edit("replace", "items", "itm_lem", body, original.version)], *fixture.ITEMS)
        stale = dict(body)
        stale["caption"] = "renamed again"
        error = self.refuse_batch(fixture, db, "CONFLICT",
                                  [edit("replace", "items", "itm_lem", stale, original.version)],
                                  *fixture.ITEMS)
        self.assertIsInstance(error, ConflictError)
        self.assertEqual(error.exit_code, 3)
        self.assertEqual(error.records, [{
            "changed": [{"ref": R("items", "itm_lem"), "expected_version": original.version,
                         "actual_version": original.version + 1, "retired": False}],
            "changed_relations": [], "source_context_changed": False}])
        self.assertEqual(db.head("items", "itm_lem").body["caption"], "renamed")
        self.assertIsNone(db.version("items", "itm_lem", original.version + 2))

    def test_creating_an_id_that_appeared_after_the_packet_base_conflicts(self):
        """A create losing a race reports a conflict with a null expected_version, not "already exists"."""
        fixture, db = self.build("structure")
        stale_packet = fixture.packet(db)
        fixture.apply(db, [edit("create", "scopes", "scp_race", scope_body())])
        error = self.refuse(db, "CONFLICT", lambda: acceptance.apply_batch(db, fixture.batch(
            [edit("create", "scopes", "scp_race", scope_body(conditions=["mine"]))],
            stale_packet["packet_id"])))
        self.assertEqual(error.records, [{
            "changed": [{"ref": R("scopes", "scp_race"), "expected_version": None,
                         "actual_version": 1, "retired": False}],
            "changed_relations": [], "source_context_changed": False}])
        self.assertEqual(db.head("scopes", "scp_race").body["conditions"], [])

    def test_a_conflict_names_the_command_that_rebases_the_batch(self):
        """CONFLICT carries a retry command for the same targets and mode as the exhausted packet."""
        fixture, db = self.build("structure")
        original = db.head("items", "itm_lem")
        body = dict(original.body)
        body["caption"] = "renamed"
        fixture.apply(db, [edit("replace", "items", "itm_lem", body, original.version)], *fixture.ITEMS)
        error = self.refuse_batch(fixture, db, "CONFLICT",
                                  [edit("replace", "items", "itm_lem", body, original.version)],
                                  *fixture.ITEMS)
        self.assertEqual(error.retry, {
            "command": "get DB --target items:itm_lem --target items:itm_thm --mode author --out PACKET.json",
            "targets": list(fixture.ITEM_REFS), "mode": "author"})


class AtomicityTests(AcceptanceCase):
    """A batch is all or nothing: one bad edit discards the whole batch."""

    def test_a_batch_that_fails_validation_writes_nothing(self):
        """A valid edit beside an invalid one leaves no record and no new revision behind."""
        fixture, db = self.build("structure")
        error = self.refuse_batch(fixture, db, "INVALID_BATCH", [
            edit("create", "scopes", "scp_good", scope_body()),
            edit("create", "uses", "use_bad", use_body(**{"from": R("items", "itm_ghost")}))],
            *fixture.ITEMS)
        self.assertEqual(error.records, ["edits/1 uses:use_bad /from: no live items record itm_ghost"])
        self.assertIsNone(db.head("scopes", "scp_good"))
        self.assertIsNone(db.head("uses", "use_bad"))

    def test_a_batch_that_fails_planning_writes_nothing(self):
        """Planning rejects the whole batch when one edit names a record twice."""
        fixture, db = self.build("structure")
        error = self.refuse_batch(fixture, db, "INVALID_REQUEST", [
            edit("create", "scopes", "scp_first", scope_body()),
            edit("create", "scopes", "scp_dup", scope_body()),
            edit("create", "scopes", "scp_dup", scope_body(conditions=["other"]))], *fixture.ITEMS)
        self.assertEqual(error.message, "batch rejected")
        self.assertEqual(error.records, ["edits/2: scopes:scp_dup appears twice in one batch"])
        self.assertIsNone(db.head("scopes", "scp_first"))
        self.assertIsNone(db.head("scopes", "scp_dup"))

    def test_a_batch_with_one_conflicting_edit_writes_nothing(self):
        """A conflict on edit 1 discards the unrelated create on edit 0."""
        fixture, db = self.build("structure")
        original = db.head("items", "itm_lem")
        renamed = dict(original.body, caption="renamed")
        fixture.apply(db, [edit("replace", "items", "itm_lem", renamed, original.version)], *fixture.ITEMS)
        error = self.refuse_batch(fixture, db, "CONFLICT", [
            edit("create", "scopes", "scp_good", scope_body()),
            edit("replace", "items", "itm_lem", dict(original.body, caption="again"), original.version)],
            *fixture.ITEMS)
        self.assertEqual([c["ref"] for c in error.records[0]["changed"]], [R("items", "itm_lem")])
        self.assertIsNone(db.head("scopes", "scp_good"))
        self.assertEqual(db.head("items", "itm_lem").body["caption"], "renamed")


class EnvelopeShapeTests(AcceptanceCase):
    """contract.BATCH is the gate every request passes before the database is touched."""

    def test_an_unknown_collection_is_refused(self):
        """The envelope only admits the twenty-two contract-3 collections, named in the error."""
        fixture, db = self.build("structure")
        self.assertEqual(len(COLLECTIONS), 27)
        error = self.refuse_batch(fixture, db, "INVALID_REQUEST",
                                  [edit("create", "widgets", "wid_1", {})], *fixture.ITEMS)
        self.assertEqual(error.message, "invalid edit envelope")
        self.assertEqual(error.records, [f"/edits/0/collection: must be one of {list(COLLECTIONS)}"])

    def test_a_malformed_identifier_is_refused(self):
        """Identifiers must match the contract id grammar."""
        fixture, db = self.build("structure")
        error = self.refuse_batch(fixture, db, "INVALID_REQUEST",
                                  [edit("create", "items", "9bad!", item_body("lemma", "L"))],
                                  *fixture.ITEMS)
        self.assertEqual(error.records, ["/edits/0/id: invalid identifier"])

    def test_an_unknown_op_is_refused(self):
        """create, replace and retire are the only operations an edit may carry."""
        fixture, db = self.build("structure")
        error = self.refuse_batch(fixture, db, "INVALID_REQUEST",
                                  [edit("delete", "items", "itm_lem", None)], *fixture.ITEMS)
        self.assertEqual(error.records, ["/edits/0/op: must equal 'create'"])

    def test_a_foreign_contract_version_is_refused(self):
        """Only contract_version 3 is accepted."""
        fixture, db = self.build("structure")
        packet = fixture.packet(db, *fixture.ITEMS)
        error = self.refuse(db, "INVALID_REQUEST", lambda: acceptance.apply_batch(db, {
            "contract_version": 2, "request_id": "req_cv", "packet_id": packet["packet_id"], "edits": []}))
        self.assertEqual(error.records, ["/contract_version: supported request contract versions are 3 and 4"])

    def test_a_batch_without_a_packet_id_is_refused(self):
        """packet_id is a required, non-null envelope field."""
        fixture, db = self.build("structure")
        missing = self.refuse(db, "INVALID_REQUEST", lambda: acceptance.apply_batch(db, {
            "contract_version": 3, "request_id": "req_missing", "edits": []}))
        self.assertEqual(missing.records, ["/packet_id: missing required field"])
        null = self.refuse(db, "INVALID_REQUEST", lambda: acceptance.apply_batch(db, {
            "contract_version": 3, "request_id": "req_null", "packet_id": None, "edits": []}))
        self.assertEqual(null.records, ["/packet_id: null is not allowed"])

    def test_a_blank_request_id_is_refused(self):
        """A batch must carry a nonempty request id, since that id is the idempotency key."""
        fixture, db = self.build("structure")
        packet = fixture.packet(db)
        error = self.refuse(db, "INVALID_REQUEST", lambda: acceptance.apply_batch(db, {
            "contract_version": 3, "request_id": "  ", "packet_id": packet["packet_id"], "edits": []}))
        self.assertEqual(error.records, ["/request_id: must be nonempty text"])

    def test_a_retire_edit_may_not_carry_a_body(self):
        """The retire envelope carries a reason, never a body, so a body makes the edit shapeless."""
        fixture, db = self.build("structure")
        error = self.refuse_batch(fixture, db, "INVALID_REQUEST", [
            {"op": "retire", "collection": "uses", "id": "use_lem_thm", "expected_version": 1,
             "body": None}], *fixture.ITEMS)
        self.assertEqual(error.message, "invalid edit envelope")
        self.assertEqual(error.records, ["/edits/0/op: must equal 'create'",
                                         "/edits/0/expected_version: must be null"])

    def test_a_retire_edit_needs_a_nonempty_reason(self):
        """A blank retire reason is refused by the envelope."""
        fixture, db = self.build("structure")
        error = self.refuse_batch(fixture, db, "INVALID_REQUEST", [
            {"op": "retire", "collection": "uses", "id": "use_lem_thm", "expected_version": 1,
             "reason": "  "}], *fixture.ITEMS)
        self.assertEqual(error.records, ["/edits/0/reason: must be nonempty text"])


class BodyShapeTests(AcceptanceCase):
    """Body schemas are closed: every field is listed and nothing else is allowed."""

    def test_a_body_missing_required_fields_reports_each_one(self):
        """Every missing field is reported, pointed at by collection, id and JSON pointer."""
        fixture, db = self.build("structure")
        error = self.refuse_batch(fixture, db, "INVALID_BATCH",
                                  [edit("create", "items", "itm_bad", {"kind": "lemma"})], *fixture.ITEMS)
        self.assertEqual(error.message, "batch failed validation")
        self.assertEqual(error.records,
                         [f"edits/0 items:itm_bad /{field}: missing required field"
                          for field in ITEM_FIELDS_AFTER_KIND])

    def test_an_unknown_body_field_is_refused(self):
        """A field outside the schema is rejected rather than stored and ignored."""
        fixture, db = self.build("structure")
        error = self.refuse_batch(fixture, db, "INVALID_BATCH",
                                  [edit("create", "scopes", "scp_bad", scope_body(extra=1))], *fixture.ITEMS)
        self.assertEqual(error.records, ["edits/0 scopes:scp_bad /extra: unknown field"])

    def test_a_bad_array_element_is_reported_with_its_index(self):
        """Array elements are validated one by one and the pointer carries the offending index."""
        fixture, db = self.build("structure")
        error = self.refuse_batch(fixture, db, "INVALID_BATCH",
                                  [edit("create", "scopes", "scp_bad",
                                        scope_body(conditions=["fine", "  "]))], *fixture.ITEMS)
        self.assertEqual(error.records, ["edits/0 scopes:scp_bad /conditions/1: must be nonempty text"])

    def test_a_non_object_body_is_refused(self):
        """A body that is not a JSON object is rejected with the documented message."""
        fixture, db = self.build("structure")
        error = self.refuse_batch(fixture, db, "INVALID_BATCH",
                                  [edit("create", "scopes", "scp_bad", ["nope"])], *fixture.ITEMS)
        self.assertEqual(error.records, ["edits/0 scopes:scp_bad body must be an object"])

    # REGRESSION: an explicitly null body passes the envelope because contract.EDIT_CREATE declares
    # ``body: Any()``, which is nullable. _shape_errors used to skip it with the guard meant for
    # retires and _semantic then subscripted it, so validate_plan raised a bare TypeError with no
    # code and no records. A null body is now refused as a body that is not an object.
    def test_a_null_body_is_refused_like_any_other_non_object(self):
        """A create edit whose body is null is rejected with INVALID_BATCH, not an unhandled TypeError."""
        fixture, db = self.build("structure")
        error = self.refuse_batch(fixture, db, "INVALID_BATCH",
                                  [edit("create", "items", "itm_null", None)], *fixture.ITEMS)
        self.assertEqual(error.records, ["edits/0 items:itm_null body must be an object"])

    def test_a_refused_null_body_leaves_the_database_untouched(self):
        """The refusal is a CoreError and the transaction rolls back, leaving the handle usable."""
        fixture, db = self.build("structure")
        before = db.max_revision()
        packet = fixture.packet(db, *fixture.ITEMS)
        batch = fixture.batch([edit("create", "items", "itm_null", None)], packet["packet_id"])
        with self.assertRaises(CoreError) as caught:
            acceptance.apply_batch(db, batch)
        self.assertEqual(caught.exception.code, "INVALID_BATCH")
        self.assertEqual(db.max_revision(), before)
        self.assertIsNone(db.head("items", "itm_null"))
        receipt = fixture.apply(db, [edit("create", "scopes", "scp_after", scope_body())])
        self.assertEqual(receipt["revision"], before + 1)


class PacketGateTests(AcceptanceCase):
    """A packet decides which command may run and which records it may write."""

    def test_an_unknown_packet_is_refused(self):
        """A packet id the database never issued is PACKET_UNKNOWN."""
        fixture, db = self.build("structure")
        error = self.refuse(db, "PACKET_UNKNOWN", lambda: acceptance.apply_batch(
            db, fixture.batch([edit("create", "scopes", "scp_extra", scope_body())], "pkt_nope")))
        self.assertEqual(error.message, "unknown packet pkt_nope")

    def test_apply_refuses_an_independent_packet(self):
        """apply runs only under an author or primary packet, and the refusal names the packet."""
        fixture, db = self.build("audit")
        packet = fixture.packet(db, "items:itm_lem", mode="independent")
        batch = fixture.batch([edit("create", "scopes", "scp_extra", scope_body())], packet["packet_id"])
        error = self.refuse(db, "PACKET_MODE", lambda: acceptance.apply_batch(db, batch))
        self.assertEqual(error.message, "command apply needs a packet in mode ['author', 'primary']; "
                                        f"{packet['packet_id']} is a independent packet")
        self.assertIsNone(error.retry)

    def test_apply_refuses_a_reconcile_packet(self):
        """A reconcile packet cannot be spent on an apply batch either."""
        fixture, db = self.build("structure")
        packet = fixture.packet(db, mode="reconcile")
        batch = fixture.batch([edit("create", "scopes", "scp_extra", scope_body())], packet["packet_id"])
        error = self.refuse(db, "PACKET_MODE", lambda: acceptance.apply_batch(db, batch))
        self.assertEqual(error.message, "command apply needs a packet in mode ['author', 'primary']; "
                                        f"{packet['packet_id']} is a reconcile packet")

    def test_apply_without_a_packet_is_refused(self):
        """apply is not a packetless command, so accept() demands a packet id."""
        fixture, db = self.build("structure")
        error = self.refuse(db, "PACKET_REQUIRED", lambda: acceptance.accept(
            db, request_id="req_nopacket", request_digest="0" * 64, packet_id=None,
            edits=[edit("create", "scopes", "scp_extra", scope_body())], command="apply"))
        self.assertEqual(error.message, "command apply requires a packet")
        self.assertIsNone(db.head("scopes", "scp_extra"))

    def test_a_packetless_command_runs_against_the_whole_paper(self):
        """import is in PACKETLESS_COMMANDS, so it accepts a batch with no packet at all."""
        fixture, db = self.build("structure")
        self.assertIn("import", acceptance.PACKETLESS_COMMANDS)
        receipt = acceptance.accept(db, request_id="req_import", request_digest="1" * 64, packet_id=None,
                                    edits=[edit("create", "scopes", "scp_imported", scope_body())],
                                    command="import")
        self.assertEqual(receipt["changed"],
                         [{"collection": "scopes", "id": "scp_imported", "version": 1, "op": "create"}])
        self.assertEqual(db.head("scopes", "scp_imported").version, 1)

    def test_editing_a_record_outside_the_packet_write_scope_is_refused(self):
        """A batch whose edits belong to a different packet than the one it names is WRITE_SCOPE."""
        fixture, db = self.build("structure")
        theorem = db.head("items", "itm_thm")
        body = dict(theorem.body)
        body["caption"] = "changed"
        error = self.refuse_batch(fixture, db, "WRITE_SCOPE",
                                  [edit("replace", "items", "itm_thm", body, theorem.version)],
                                  "items:itm_lem")
        self.assertEqual(error.message, "writes outside the packet's write scope")
        self.assertEqual(error.records, ["edits/0: items:itm_thm is not in the packet's write scope"])
        self.assertEqual(db.head("items", "itm_thm").body["caption"], theorem.body["caption"])

    def test_a_new_record_must_fall_inside_the_packet_target_scope(self):
        """A new record owned by an item outside the packet's targets is refused."""
        fixture, db = self.build("structure")
        error = self.refuse_batch(fixture, db, "INVALID_BATCH", [
            edit("create", "arguments", "arg_alt", {
                "target": R("items", "itm_thm"), "label": "alt", "origin": "reconstruction",
                "scope_id": "scp_plain", "final_group_id": None, "evidence_refs": [],
                "lifecycle": "draft"})], "items:itm_lem")
        self.assertEqual(error.records, [
            "edits/0 arguments:arg_alt: outside the packet's target scope "
            "(owners ['item:itm_thm'], allowed ['item:itm_lem'])"])

    def test_a_new_major_item_needs_a_paper_scoped_packet(self):
        """New majors change the paper's shape, so an item-scoped packet may not create one."""
        fixture, db = self.build("structure")
        error = self.refuse_batch(fixture, db, "INVALID_BATCH",
                                  [edit("create", "items", "itm_extra", item_body("lemma", "Lemma 2"))],
                                  "items:itm_lem")
        self.assertEqual(error.records, ["edits/0 items:itm_extra: new major items need a paper-scoped packet"])
        self.assertIsNone(db.head("items", "itm_extra"))

    def test_a_globally_scoped_record_needs_a_paper_scoped_packet(self):
        """A scope with no argument is owned by the paper: the item packet refuses it, the paper packet takes it."""
        fixture, db = self.build("structure")
        error = self.refuse_batch(fixture, db, "INVALID_BATCH",
                                  [edit("create", "scopes", "scp_global", scope_body())], "items:itm_lem")
        self.assertEqual(error.records, [
            "edits/0 scopes:scp_global: outside the packet's target scope "
            "(owners ['global_scope'], allowed ['item:itm_lem'])"])
        receipt = fixture.apply(db, [edit("create", "scopes", "scp_global", scope_body())])
        self.assertEqual(receipt["changed"],
                         [{"collection": "scopes", "id": "scp_global", "version": 1, "op": "create"}])
        self.assertEqual(db.head("scopes", "scp_global").body, scope_body())


class PlanningTests(AcceptanceCase):
    """Planning resolves each edit against the prospective state before anything is validated."""

    def test_creating_an_existing_id_is_refused(self):
        """create is only for identifiers the database has never seen."""
        fixture, db = self.build("structure")
        error = self.refuse_batch(fixture, db, "INVALID_REQUEST",
                                  [edit("create", "items", "itm_lem", item_body("lemma", "Lemma 1"))],
                                  *fixture.ITEMS)
        self.assertEqual(error.records, ["edits/0: items:itm_lem already exists at version 1"])
        head = db.head("items", "itm_lem")
        self.assertEqual(head.version, 1)
        self.assertEqual(head.body["statement"], {"form": "verbatim", "text": "Lemma 1 text"})

    def test_replacing_a_missing_record_is_refused(self):
        """replace needs a live record to succeed."""
        fixture, db = self.build("structure")
        error = self.refuse_batch(fixture, db, "INVALID_REQUEST",
                                  [edit("replace", "items", "itm_absent", item_body("lemma", "L"), 1)],
                                  *fixture.ITEMS)
        self.assertEqual(error.records, ["edits/0: items:itm_absent does not exist"])
        self.assertIsNone(db.head("items", "itm_absent"))

    def test_an_identifier_that_breaks_the_grammar_never_reaches_the_plan(self):
        """accept() re-checks identifiers, so a caller bypassing the envelope is still refused."""
        fixture, db = self.build("structure")
        packet = fixture.packet(db)
        error = self.refuse(db, "INVALID_REQUEST", lambda: acceptance.accept(
            db, request_id="req_badid", request_digest="2" * 64, packet_id=packet["packet_id"],
            edits=[edit("create", "scopes", "9 bad", scope_body())], command="apply"))
        self.assertEqual(error.message, "batch rejected")
        self.assertEqual(error.records, ["edits/0: invalid identifier '9 bad'"])

    def test_retire_stores_a_tombstone_version(self):
        """Retiring appends a retired version with no body, keeps version 1 readable, and drops its refs."""
        fixture, db = self.build("structure")
        original = db.version("uses", "use_lem_thm", 1)
        receipt = fixture.apply(db, [
            {"op": "retire", "collection": "uses", "id": "use_lem_thm", "expected_version": 1,
             "reason": "restructuring"}], *fixture.ITEMS)
        self.assertEqual(receipt["changed"], [{"collection": c, "id": "use_lem_thm", "version": 2,
                                               "op": "retire", "reason": "restructuring"}
                                              for c in ('uses','application_details')])
        head = db.head("uses", "use_lem_thm")
        self.assertEqual(head.version, 2)
        self.assertTrue(head.retired)
        self.assertIsNone(head.body)
        self.assertEqual(db.version("uses", "use_lem_thm", 1).body, original.body)
        self.assertEqual(db.refs_from("uses", "use_lem_thm", 2), [])
        self.assertNotEqual(db.refs_from("uses", "use_lem_thm", 1), [])

    def test_a_retired_identifier_is_never_reused(self):
        """Neither create nor replace may revive a retired identifier."""
        fixture, db = self.build("structure")
        fixture.apply(db, [{"op": "retire", "collection": "uses", "id": "use_lem_thm",
                            "expected_version": 1, "reason": "restructuring"}], *fixture.ITEMS)
        recreated = self.refuse_batch(fixture, db, "INVALID_REQUEST",
                                      [edit("create", "uses", "use_lem_thm", use_body())], *fixture.ITEMS)
        self.assertIn("edits/0: uses:use_lem_thm was retired; identifiers are never reused", recreated.records)
        replaced = self.refuse_batch(fixture, db, "INVALID_REQUEST",
                                     [edit("replace", "uses", "use_lem_thm", use_body(), 2)], *fixture.ITEMS)
        self.assertIn("edits/0: uses:use_lem_thm is retired", replaced.records)
        self.assertTrue(db.head("uses", "use_lem_thm").retired)

    def test_retiring_a_referenced_record_is_refused(self):
        """A record other live records point at cannot be retired out from under them."""
        fixture, db = self.build("structure")
        error = self.refuse_batch(fixture, db, "INVALID_BATCH", [
            {"op": "retire", "collection": "groups", "id": "grp_thm", "expected_version": 1,
             "reason": "restructuring"}], *fixture.ITEMS)
        self.assertTrue(any('still referenced by live records' in message and
                            'application_details:use_lem_thm/group_id' in message and
                            'arguments:arg_thm/final_group_id' in message for message in error.records))
        self.assertFalse(db.head("groups", "grp_thm").retired)


class ReferenceIntegrityTests(AcceptanceCase):
    """Every reference in a body must resolve to a live record at the pinned version."""

    def test_an_edit_pointing_at_a_missing_record_is_refused(self):
        """A reference to an id that does not exist names the offending JSON pointer."""
        fixture, db = self.build("structure")
        error = self.refuse_batch(fixture, db, "INVALID_BATCH",
                                  [edit("create", "uses", "use_ghost",
                                        use_body(**{"from": R("items", "itm_ghost")}))], *fixture.ITEMS)
        self.assertEqual(error.records, ["edits/0 uses:use_ghost /from: no live items record itm_ghost"])
        self.assertIsNone(db.head("uses", "use_ghost"))

    def test_a_dangling_evidence_anchor_is_refused(self):
        """Evidence references are checked element by element, with the array index in the pointer."""
        fixture, db = self.build("structure")
        error = self.refuse_batch(fixture, db, "INVALID_BATCH",
                                  [edit("create", "scopes", "scp_ev",
                                        scope_body(evidence_refs=["anc_lem", "anc_nope"]))])
        self.assertEqual(error.records, ["edits/0 scopes:scp_ev /evidence_refs/1: no live anchors record anc_nope"])

    def test_a_reference_to_a_retired_record_is_refused(self):
        """A retired record stops being a usable reference target even though its id still exists."""
        fixture, db = self.build("structure")
        fixture.apply(db, [edit("create", "groups", "grp_extra", {
            "argument_id": "arg_thm", "conclusion": R("items", "itm_thm"), "kind": "joint",
            "scope_id": "scp_plain", "case_scope_ids": [], "discharges": [], "rationale": "spare",
            "evidence_refs": []})], *fixture.ITEMS)
        fixture.apply(db, [{"op": "retire", "collection": "groups", "id": "grp_extra",
                            "expected_version": 1, "reason": "not needed"}], *fixture.ITEMS)
        self.assertTrue(db.head("groups", "grp_extra").retired)
        use = db.head("uses", "use_lem_thm")
        error = self.refuse_batch(fixture, db, "INVALID_BATCH", [
            edit("replace", "uses", "use_lem_thm", use_body(group_id="grp_extra"), use.version)],
            *fixture.ITEMS)
        self.assertTrue(any('application_details:use_lem_thm /group_id: no live groups record grp_extra' in message for message in error.records))
        self.assertEqual(db.head("application_details", "use_lem_thm").body["group_id"], "grp_thm")

    def test_a_pinned_reference_at_a_missing_version_is_refused(self):
        """A pinned reference must name a version the target record actually has."""
        fixture, db = self.build("primary")
        error = self.refuse_batch(fixture, db, "INVALID_BATCH", [
            edit("create", "checks", "chk_sup", check_body(
                supersedes={"collection": "checks", "id": "chk_comp_lem", "version": 7}))],
            *fixture.ITEMS, mode="primary")
        self.assertEqual(error.records,
                         ["edits/0 checks:chk_sup /supersedes: checks record chk_comp_lem has no version 7"])
        self.assertIsNone(db.head("checks", "chk_sup"))

    def test_a_second_use_may_not_duplicate_a_live_application_identity(self):
        """Two live uses may not record the same from/to pair in the same group."""
        fixture, db = self.build("structure")
        error = self.refuse_batch(fixture, db, "INVALID_BATCH",
                                  [edit("create", "uses", "use_twin", use_body(reason="same application"))],
                                  *fixture.ITEMS)
        self.assertEqual(error.records,
                         ["edits/0 uses:use_twin: duplicates the application identity of ['use_lem_thm']"])

    def test_retiring_a_use_frees_its_application_identity(self):
        """Once the original use is retired the same application may be recorded again."""
        fixture, db = self.build("structure")
        fixture.apply(db, [{"op": "retire", "collection": "uses", "id": "use_lem_thm",
                            "expected_version": 1, "reason": "restructuring"}], *fixture.ITEMS)
        receipt = fixture.apply(db, [edit("create", "uses", "use_twin", use_body(reason="restated"))],
                                *fixture.ITEMS)
        self.assertEqual(receipt["changed"],
                         [{"collection": c, "id": "use_twin", "version": 1, "op": "create"}
                          for c in ('uses','application_details')])

    def test_an_accepted_batch_indexes_its_references(self):
        """A created record's references become index rows keyed by JSON pointer."""
        fixture, db = self.build("structure")
        fixture.apply(db, [edit("create", "scopes", "scp_assume",
                                scope_body(assumptions=[R("items", "itm_lem")],
                                           evidence_refs=["anc_lem"]))])
        self.assertEqual(db.refs_from("scopes", "scp_assume", 1), [
            {"field_path": "/assumptions/0", "target_collection": "items", "target_id": "itm_lem",
             "target_version": None},
            {"field_path": "/evidence_refs/0", "target_collection": "anchors", "target_id": "anc_lem",
             "target_version": None}])


class CommandPermissionTests(AcceptanceCase):
    """validation.COMMANDS decides which collections a command may create."""

    def test_apply_cannot_create_observations(self):
        """Observations belong to the compare command, not to apply."""
        fixture, db = self.build("structure")
        error = self.refuse_batch(fixture, db, "INVALID_BATCH", [
            edit("create", "observations", "obs_x", {
                "target": R("items", "itm_lem"), "result": "matched", "reviewer": "primary-1",
                "note": "", "evidence_refs": []})], *fixture.ITEMS)
        self.assertEqual(error.records, ["edits/0: command apply cannot create observations records"])

    def test_apply_cannot_create_anchors(self):
        """Anchors enter only through the source-anchor command, which relocates them against the source."""
        fixture, db = self.build("structure")
        error = self.refuse_batch(fixture, db, "INVALID_BATCH",
                                  [edit("create", "anchors", "anc_x", anchor_body(fixture))], *fixture.ITEMS)
        self.assertEqual(error.records, ["edits/0: command apply cannot create anchors records"])
        self.assertIsNone(db.head("anchors", "anc_x"))

    def test_apply_cannot_create_sources(self):
        """Sources enter only through capture, which also stores the content blob."""
        fixture, db = self.build("structure")
        error = self.refuse_batch(fixture, db, "INVALID_BATCH", [
            edit("create", "sources", "src_x", {
                "paper_id": fixture.paper_id, "path": "extra.tex", "media_type": "tex",
                "blob_sha256": "0" * 64, "capture_method": "verbatim", "limitation": None})],
            *fixture.ITEMS)
        self.assertEqual(error.records, ["edits/0: command apply cannot create sources records",
                                         "edits/0 sources:src_x: source content blob is not stored"])

    def test_apply_refuses_an_independent_check(self):
        """Blinded review results may only enter through review submit."""
        fixture, db = self.build("structure")
        error = self.refuse_batch(fixture, db, "INVALID_REQUEST",
                                  [edit("create", "checks", "chk_ind", check_body(role="independent"))],
                                  *fixture.ITEMS, mode="primary")
        self.assertEqual(error.message, "batch rejected")
        self.assertEqual(error.records,
                         ["edits/0: independent checks enter through review submit, not apply"])

    def test_apply_refuses_a_check_carrying_a_response_id(self):
        """A check tied to a review response may not be smuggled in through apply."""
        fixture, db = self.build("structure")
        error = self.refuse_batch(fixture, db, "INVALID_REQUEST",
                                  [edit("create", "checks", "chk_resp", check_body(response_id="rsp_1"))],
                                  *fixture.ITEMS, mode="primary")
        self.assertEqual(error.records,
                         ["edits/0: checks with a response_id enter through review submit"])

    def test_the_command_name_selects_the_permission_row(self):
        """The same envelope accepted as compare creates the observation apply is refused."""
        fixture, db = self.build("structure")
        packet = fixture.packet(db, *fixture.ITEMS)
        batch = fixture.batch([edit("create", "observations", "obs_ok", {
            "target": R("items", "itm_lem"), "result": "matched", "reviewer": "primary-1",
            "note": "statement matches", "evidence_refs": []})], packet["packet_id"])
        receipt = acceptance.apply_batch(db, batch, command="compare")
        self.assertEqual(receipt["changed"],
                         [{"collection": "observations", "id": "obs_ok", "version": 1, "op": "create"}])
        self.assertEqual(db.head("observations", "obs_ok").body["result"], "matched")

    def test_compare_cannot_create_structure(self):
        """compare's permission row admits observations only."""
        fixture, db = self.build("structure")
        packet = fixture.packet(db, *fixture.ITEMS)
        batch = fixture.batch([edit("create", "scopes", "scp_compare", scope_body())], packet["packet_id"])
        error = self.refuse(db, "INVALID_BATCH",
                            lambda: acceptance.apply_batch(db, batch, command="compare"))
        self.assertEqual(error.records, ["edits/0: command compare cannot create scopes records"])
        self.assertIsNone(db.head("scopes", "scp_compare"))


class GlobalTaskTests(AcceptanceCase):
    """A full or focused audit must account for all three global tasks."""

    def audit(self, fixture, db, audit_id, **overrides):
        return fixture.apply(db, [edit("create", "audits", audit_id,
                                       audit_body(fixture.paper_id, **overrides))],
                             *fixture.ITEMS, mode="primary")

    def refuse_audit(self, fixture, db, audit_id, **overrides):
        return self.refuse_batch(fixture, db, "INVALID_BATCH",
                                 [edit("create", "audits", audit_id,
                                       audit_body(fixture.paper_id, **overrides))],
                                 *fixture.ITEMS, mode="primary")

    def test_a_focused_audit_listing_all_three_tasks_is_accepted(self):
        """The three global tasks, each with a kind, applicability and reason, are stored verbatim."""
        fixture, db = self.build("qualification")
        self.audit(fixture, db, "aud_ok")
        stored = db.head("audits", "aud_ok").body["global_tasks"]
        self.assertEqual(stored, [dict(task) for task in GLOBAL_TASKS])
        self.assertEqual([task["kind"] for task in stored],
                         ["global_consistency", "adversarial", "method_interface"])

    def test_a_full_audit_omitting_a_global_task_is_refused(self):
        """Dropping one of the three tasks from a full audit is INVALID_BATCH."""
        fixture, db = self.build("qualification")
        error = self.refuse_audit(fixture, db, "aud_short", mode="full",
                                  global_tasks=tasks("global_consistency", "adversarial"))
        self.assertEqual(error.records,
                         ["edits/0 audits:aud_short /: full/focused audits list exactly the three global tasks"])
        self.assertIsNone(db.head("audits", "aud_short"))

    def test_a_focused_audit_omitting_a_global_task_is_refused(self):
        """The same rule governs focused audits."""
        fixture, db = self.build("qualification")
        error = self.refuse_audit(fixture, db, "aud_short",
                                  global_tasks=tasks("global_consistency", "method_interface"))
        self.assertEqual(error.records,
                         ["edits/0 audits:aud_short /: full/focused audits list exactly the three global tasks"])

    def test_an_audit_listing_no_global_tasks_is_refused(self):
        """An empty global_tasks list does not satisfy the rule either."""
        fixture, db = self.build("qualification")
        error = self.refuse_audit(fixture, db, "aud_none", global_tasks=[])
        self.assertEqual(error.records,
                         ["edits/0 audits:aud_none /: full/focused audits list exactly the three global tasks"])

    def test_duplicate_global_task_kinds_are_refused(self):
        """Three entries of the same kind break both the distinctness rule and the coverage rule."""
        fixture, db = self.build("qualification")
        error = self.refuse_audit(fixture, db, "aud_dup",
                                  global_tasks=tasks("adversarial", "adversarial", "adversarial"))
        self.assertEqual(error.records, [
            "edits/0 audits:aud_dup /: global task kinds must be distinct",
            "edits/0 audits:aud_dup /: full/focused audits list exactly the three global tasks"])

    def test_an_unknown_global_task_kind_is_refused(self):
        """Only the three documented kinds are admitted, and the enum is named in the error."""
        fixture, db = self.build("qualification")
        error = self.refuse_audit(fixture, db, "aud_kind",
                                  global_tasks=tasks("spelling", "adversarial", "method_interface"))
        self.assertEqual(error.records, [
            "edits/0 audits:aud_kind /global_tasks/0/kind: must be one of "
            f"{list(contract.GLOBAL_TASK_KINDS)}"])

    def test_a_not_applicable_task_needs_a_reason(self):
        """Declaring a task not applicable requires saying why."""
        fixture, db = self.build("qualification")
        global_tasks = tasks("global_consistency", "adversarial", "method_interface")
        global_tasks[0]["applicability"] = "not_applicable"
        global_tasks[0]["reason"] = "  "
        error = self.refuse_audit(fixture, db, "aud_reason", global_tasks=global_tasks)
        self.assertEqual(error.records,
                         ["edits/0 audits:aud_reason /global_tasks/0: a not_applicable task needs a nonempty reason"])

    def test_a_required_task_may_leave_the_reason_blank(self):
        """The reason is compulsory only for not_applicable, so the required form is accepted as given."""
        fixture, db = self.build("qualification")
        required = tasks("global_consistency", "adversarial", "method_interface")
        self.audit(fixture, db, "aud_required", global_tasks=required)
        self.assertEqual(db.head("audits", "aud_required").body["global_tasks"], required)

    def test_a_triage_audit_may_list_fewer_tasks(self):
        """The three-task rule is scoped to full and focused audits."""
        fixture, db = self.build("qualification")
        self.audit(fixture, db, "aud_triage", mode="triage", global_tasks=tasks("adversarial"))
        self.assertEqual([task["kind"] for task in db.head("audits", "aud_triage").body["global_tasks"]],
                         ["adversarial"])

    def test_an_audit_naming_an_unknown_qualification_is_refused(self):
        """The qualification reference is checked like any other reference."""
        fixture, db = self.build("qualification")
        error = self.refuse_audit(fixture, db, "aud_q", qualification_id="qua_nope")
        self.assertEqual(error.records,
                         ["edits/0 audits:aud_q /qualification_id: no live qualifications record qua_nope"])


class ContractHelperTests(unittest.TestCase):
    """The pure contract helpers other modules build their error messages from."""

    def test_pointer_escapes_json_pointer_tokens(self):
        """Slashes become ~1 and tildes ~0, and integer tokens are rendered as path segments."""
        self.assertEqual(contract.pointer("a/b", "c~d", 0), "/a~1b/c~0d/0")
        self.assertEqual(contract.pointer(), "")

    def test_validate_body_rejects_an_unknown_collection(self):
        """A collection with no schema is named in the error rather than silently accepted."""
        self.assertEqual(contract.validate_body("widgets", {}), ["unknown collection 'widgets'"])

    def test_validate_body_rejects_a_non_object_body(self):
        """A non-object body is rejected before any field rule runs, whatever the non-object is."""
        for body in ("x", ["x"], 3, None, True):
            self.assertEqual(contract.validate_body("items", body), ["body must be an object"], body)

    def test_an_intermediate_result_names_its_owner_and_a_major_does_not(self):
        """The items local rule ties owner_id to the item kind in both directions."""
        self.assertEqual(contract.validate_body("items", item_body("intermediate_result", "Step")),
                         ["/: an intermediate result needs exactly one owner_id"])
        self.assertEqual(contract.validate_body("items", item_body("lemma", "L", owner_id="itm_thm")),
                         ["/: a major item has owner_id null"])
        self.assertEqual(contract.validate_body("items", item_body("intermediate_result", "Step",
                                                                   owner_id="itm_thm")), [])
        self.assertEqual(contract.validate_body("items", item_body("lemma", "L")), [])

    def test_a_use_may_not_connect_a_statement_to_itself(self):
        """The uses local rule rejects a self-loop and accepts a genuine edge."""
        self.assertEqual(contract.validate_body("uses", use_body(to=R("items", "itm_lem"))),
                         ["/: a use cannot connect a statement to itself"])
        self.assertEqual(contract.validate_body("uses", use_body()), [])

    def test_a_registered_argument_needs_a_final_group(self):
        """lifecycle 'registered' is only legal once the argument names its final group."""
        argument = {"target": R("items", "itm_lem"), "label": "Proof", "origin": "source",
                    "scope_id": "scp_plain", "final_group_id": None, "evidence_refs": [],
                    "lifecycle": "registered"}
        self.assertEqual(contract.validate_body("arguments", argument),
                         ["/: a registered argument needs a final group"])
        self.assertEqual(contract.validate_body("arguments", dict(argument, lifecycle="draft")), [])
        self.assertEqual(contract.validate_body("arguments", dict(argument, final_group_id="grp_lem")), [])

    def test_audit_targets_must_be_distinct(self):
        """The audits local rule refuses a target listed twice."""
        body = audit_body("pap_1", targets=[R("items", "itm_lem"), R("items", "itm_lem")])
        self.assertEqual(contract.validate_body("audits", body), ["/: audit targets must be distinct"])
        self.assertEqual(contract.validate_body("audits", audit_body("pap_1")), [])

    def test_extract_refs_reports_every_reference_with_its_pointer(self):
        """extract_refs walks the body and reports collection, id and JSON pointer for each reference."""
        refs = contract.extract_refs("uses", use_body(**{
            "from": R("items", "a"), "to": R("parts", "b"), "group_id": "g",
            "evidence_refs": ["anc_1", "anc_2"]}))
        self.assertEqual(refs, [
            {"field_path": "/from", "target_collection": "items", "target_id": "a", "target_version": None},
            {"field_path": "/to", "target_collection": "parts", "target_id": "b", "target_version": None},
            {"field_path": "/group_id", "target_collection": "groups", "target_id": "g",
             "target_version": None},
            {"field_path": "/evidence_refs/0", "target_collection": "anchors", "target_id": "anc_1",
             "target_version": None},
            {"field_path": "/evidence_refs/1", "target_collection": "anchors", "target_id": "anc_2",
             "target_version": None}])

    def test_extract_refs_skips_null_optional_references(self):
        """A nullable reference field that is null produces no index row at all."""
        refs = contract.extract_refs("uses", use_body(group_id=None, evidence_refs=[]))
        self.assertEqual([row["field_path"] for row in refs], ["/from", "/to"])

    def test_extract_refs_pairs_an_anchor_with_its_source_version(self):
        """An anchor pins the source version it was cut from, and the reference carries that version."""
        refs = contract.extract_refs("anchors", {
            "source_id": "src_1", "source_version": 3,
            "locator": {"start_line": 1, "end_line": 2, "page": None, "label": None},
            "excerpt": "", "excerpt_sha256": "0" * 64, "method": "exact_lines", "limitation": None})
        self.assertEqual(refs, [{"field_path": "/source_id", "target_collection": "sources",
                                 "target_id": "src_1", "target_version": 3}])

    def test_a_locator_needs_at_least_one_usable_location(self):
        """An empty locator, a half-open line range and a reversed range are each rejected."""
        empty = {"start_line": None, "end_line": None, "page": None, "label": None}
        self.assertEqual(contract.validate_shape(contract.LOCATOR, empty),
                         ["/: at least one location method is required"])
        self.assertEqual(contract.validate_shape(contract.LOCATOR, dict(empty, start_line=3)),
                         ["/: start_line and end_line must appear together"])
        self.assertEqual(contract.validate_shape(contract.LOCATOR, dict(empty, start_line=9, end_line=2)),
                         ["/: start_line must not exceed end_line"])
        self.assertEqual(contract.validate_shape(contract.LOCATOR, dict(empty, label="lem:a")), [])

    def test_booleans_are_not_integers(self):
        """Python's bool must not slip through an integer field."""
        self.assertEqual(contract.validate_shape(contract.LOCATOR, {
            "start_line": True, "end_line": True, "page": None, "label": None}),
            ["/start_line: expected integer", "/end_line: expected integer"])

    def test_an_edit_matching_no_envelope_shape_is_rejected(self):
        """A rejected edit identifies its actual keys and the expected envelope shapes."""
        errors = contract.validate_shape(contract.BATCH, {
            "contract_version": 3, "request_id": "r", "packet_id": "p", "edits": [{"op": "create"}]})
        self.assertEqual(len(errors), 1)
        self.assertTrue(errors[0].startswith("/edits/0: object does not match any allowed shape; expected one of "))
        self.assertIn("'collection', 'expected_version', 'id', 'op'", errors[0])
        self.assertIn("got object keys ['op']", errors[0])
        self.assertIn("keep required nullable fields present", errors[0])

    def test_the_retire_envelope_is_a_recognised_shape(self):
        """op, collection, id, expected_version and reason is the whole retire envelope."""
        self.assertEqual(contract.validate_shape(contract.BATCH, {
            "contract_version": 3, "request_id": "r", "packet_id": "p",
            "edits": [{"op": "retire", "collection": "uses", "id": "use_1", "expected_version": 1,
                       "reason": "restructuring"}]}), [])

    def test_a_check_kind_must_match_its_target_collection(self):
        """The check kind/target table is enforced by the body schema."""
        self.assertEqual(contract.validate_body("checks", check_body(target=R("groups", "grp_lem"))),
                         ["/: check kind composition targets ['arguments'], not groups"])
        self.assertEqual(contract.validate_body("checks", check_body(kind="derivation",
                                                                     target=R("groups", "grp_lem"))), [])


class ExampleBatchReplayTests(AcceptanceCase):
    """The handoff example batch is replayable against a fresh database as written."""

    def load_example(self):
        batch = json.loads(EXAMPLE_BATCH.read_text(encoding="utf-8"))
        self.assertEqual(batch["contract_version"], 3)
        self.assertEqual(batch["packet_id"], "pkt_example")
        self.assertEqual(batch["request_id"], "req_example")
        self.assertEqual([(e["collection"], e["id"]) for e in batch["edits"]], EXAMPLE_RECORDS[:12])
        self.assertEqual({e["op"] for e in batch["edits"]}, {"create"})
        self.assertEqual({e["expected_version"] for e in batch["edits"]}, {None})
        return batch

    def rewrite(self, fixture, db, batch):
        """Point a loaded fixture batch at this database's packet and a fresh request id."""
        batch["packet_id"] = fixture.packet(db)["packet_id"]
        batch["request_id"] = fixture.request_id()
        return batch

    def test_the_example_batch_applies_with_only_its_identities_rewritten(self):
        """Replacing pkt_example and req_example is the only edit the fixture needs to replay."""
        fixture, db = self.build("capture", name="example")
        batch = self.rewrite(fixture, db, self.load_example())
        before = db.max_revision()
        receipt = acceptance.apply_batch(db, batch)
        self.assertEqual(receipt["request_id"], batch["request_id"])
        self.assertEqual(receipt["warnings"], [])
        self.assertIsNone(receipt["rebased_from"])
        self.assertEqual(receipt["revision"], before + 1)
        self.assertEqual(receipt["revision"], db.max_revision())
        self.assertEqual(receipt["changed"],
                         [{"collection": collection, "id": record_id, "version": 1, "op": "create"}
                          for collection, record_id in EXAMPLE_RECORDS])

    def test_the_example_batch_applies_to_a_bare_database(self):
        """The fixture needs no captured source and no anchors: a freshly initialized database takes it."""
        fixture, db = self.build(name="bare")
        batch = self.rewrite(fixture, db, self.load_example())
        receipt = acceptance.apply_batch(db, batch)
        self.assertEqual(len(receipt["changed"]), 15)
        self.assertEqual(db.head("items", "itm_target").body["label"], "Example target")

    def test_every_example_record_lands_under_its_fixture_identifier(self):
        """All twelve records become live heads at version 1 under the ids the fixture names."""
        fixture, db = self.build("capture", name="example")
        acceptance.apply_batch(db, self.rewrite(fixture, db, self.load_example()))
        for collection, record_id in EXAMPLE_RECORDS:
            head = db.head(collection, record_id)
            self.assertIsNotNone(head, f"{collection}:{record_id} was not written")
            self.assertEqual(head.version, 1)
            self.assertFalse(head.retired)
        self.assertEqual(db.head("items", "itm_joint").body["owner_id"], "itm_target")
        self.assertEqual(db.head("items", "itm_target").body["kind"], "theorem")
        self.assertEqual(db.head("arguments", "arg_joint").body["final_group_id"], "grp_joint")
        self.assertEqual(db.head("uses", "use_joint_target").body["to"], R("items", "itm_target"))

    def test_the_example_batch_builds_the_reference_index(self):
        """References inside the batch are indexed by JSON pointer once it lands, in pointer order."""
        fixture, db = self.build("capture", name="example")
        acceptance.apply_batch(db, self.rewrite(fixture, db, self.load_example()))
        self.assertEqual(db.refs_from("scopes", "scp_example", 1), [
            {"field_path": "/assumptions/0", "target_collection": "items", "target_id": "itm_event_a",
             "target_version": None},
            {"field_path": "/assumptions/1", "target_collection": "items", "target_id": "itm_event_b",
             "target_version": None}])
        self.assertEqual(db.refs_from("uses", "use_joint_target", 1), [
            {"field_path": "/from", "target_collection": "items", "target_id": "itm_joint",
             "target_version": None},
            {"field_path": "/to", "target_collection": "items", "target_id": "itm_target",
             "target_version": None}])

    def test_applying_the_example_batch_twice_is_refused_edit_by_edit(self):
        """A fresh packet and request id do not let the same create ids land a second time."""
        fixture, db = self.build("capture", name="example")
        acceptance.apply_batch(db, self.rewrite(fixture, db, self.load_example()))
        again = self.rewrite(fixture, db, self.load_example())
        error = self.refuse(db, "INVALID_REQUEST", lambda: acceptance.apply_batch(db, again))
        self.assertEqual(error.message, "batch rejected")
        self.assertEqual(error.records, [
            f"edits/{index}: {collection}:{record_id} already exists at version 1"
            for index, (collection, record_id) in enumerate(EXAMPLE_RECORDS[:12])])


if __name__ == "__main__":
    unittest.main()
