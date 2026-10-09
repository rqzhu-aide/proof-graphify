"""Packets: the mode allowlist, blinding, context extension, and packet staleness.

Covers ``shared/paper_core/packets.py`` and the blinding rules of
the independent review contract: an independent worker receives source
material only, a primary worker receives the assessment, an extension widens what may be read
without widening what may be written, and a packet pins the revision it was cut at.
"""
from __future__ import annotations

import json
import unittest
from unittest import mock

import support
from support import GLOBAL_TASKS, R, TempCase, edit, locator, run_cli

from paper_core import acceptance, packets, sources
from paper_core.errors import ConflictError, InvalidRequest
from paper_core.refs import membership_digest

# The collections a packet may carry, written out here so that widening an allowlist in the core
# cannot silently widen the expectation too.
STRUCTURAL_COLLECTIONS = ("papers", "items", "parts", "scopes", "arguments", "groups", "uses", "coverage",
                          "anchors", "sources", "source_issues", "source_reviews", "target_specs",
                          "application_details", "proof_boundaries", "connection_refinements", "overview_selections")
ASSESSMENT_COLLECTIONS = ("audits", "checks", "findings", "identity_maps", "observations", "qualifications",
                          "reconciliations", "repairs", "responses", "reuse_decisions")
# What each mode actually assembles for one item of the standard fixture at the complete() stage.
MODE_COLLECTIONS = {
    "author": ["anchors", "arguments", "coverage", "groups", "items", "proof_boundaries", "scopes",
               "source_reviews", "sources", "target_specs"],
    "primary": ["anchors", "arguments", "audits", "checks", "coverage", "groups", "items", "observations",
                "proof_boundaries", "qualifications", "reconciliations", "scopes", "source_reviews", "sources", "target_specs"],
    "reconcile": ["anchors", "arguments", "audits", "checks", "coverage", "groups", "identity_maps", "items", "observations",
                  "proof_boundaries", "qualifications", "reconciliations", "responses", "scopes", "source_reviews",
                  "sources", "target_specs"],
    "independent": ["anchors", "items", "sources"],
}


# -- helpers ---------------------------------------------------------------------------------------
def collections_of(packet) -> list:
    """Sorted distinct collections carried by a packet payload."""
    return sorted({entry["ref"]["collection"] for entry in packet["records"]})


def ids_in(packet, collection) -> list:
    return sorted(entry["ref"]["id"] for entry in packet["records"] if entry["ref"]["collection"] == collection)


def refs_in(packet) -> set:
    return {(entry["ref"]["collection"], entry["ref"]["id"]) for entry in packet["records"]}


def scope_of(packet) -> set:
    return {(ref["collection"], ref["id"]) for ref in packet["write_scope"]}


def stored_packets(db) -> int:
    return db.conn.execute("SELECT COUNT(*) FROM packets").fetchone()[0]


def extension_request(*, targets=(), anchors=(), paths=(), reason="the proof cites an outside statement") -> dict:
    return {"targets": [dict(t) for t in targets], "source_anchor_ids": list(anchors),
            "source_paths": list(paths), "reason": reason}


def item_edit(iid, kind, label, anchor, *, origin="source", owner_id=None) -> dict:
    return edit("create", "items", iid, {
        "kind": kind, "label": label, "caption": label,
        "statement": {"form": "verbatim", "text": label + " text"},
        "passages": [{"role": "statement", "anchor_id": anchor}],
        "aliases": [], "uncertainty": None, "origin": origin, "owner_id": owner_id, "scope_id": None})


def part_edit(pid, item_id, label, anchor, *, origin="source") -> dict:
    form = "verbatim" if origin == "source" else "synopsis"
    return edit("create", "parts", pid, {
        "item_id": item_id, "label": label, "statement": {"form": form, "text": label + " text"},
        "passages": [{"role": "statement", "anchor_id": anchor}], "scope_id": None, "origin": origin})


def audit_edit(aid, paper_id, targets, report_path) -> dict:
    return edit("create", "audits", aid, {
        "paper_id": paper_id, "mode": "focused", "targets": [dict(t) for t in targets], "exclusions": [],
        "protocol_version": "item-audit/1", "independent_required": True, "qualification_id": "qua_r1",
        "report_path": report_path, "global_tasks": [dict(task) for task in GLOBAL_TASKS]})


class PacketAllowlistTests(TempCase):
    """The mode and target allowlists of implementation-handoff 4.2."""

    def setUp(self):
        super().setUp()
        self.fx = self.fixture().audit()

    def test_modes_are_exactly_the_four_documented_roles(self):
        """MODES is author|primary|independent|reconcile and every mode has a read and a write allowlist."""
        self.assertEqual(("author", "primary", "independent", "reconcile"), packets.MODES)
        self.assertEqual(sorted(packets.MODES), sorted(packets.READ_COLLECTIONS))
        self.assertEqual(sorted(packets.MODES), sorted(packets.WRITE_COLLECTIONS))
        with self.fx.open() as db:
            for mode in packets.MODES:
                packet = packets.get_packet(db, targets=[R("items", "itm_lem")], mode=mode)
                self.assertEqual(mode, packet["mode"])
                self.assertEqual([R("items", "itm_lem")], packet["targets"])
                self.assertEqual(mode, db.packet(packet["packet_id"])["mode"])

    def test_the_read_allowlists_separate_source_material_from_assessment(self):
        """Independent reads five source collections; only primary and reconcile read judgments."""
        self.assertEqual(("items", "parts", "anchors", "sources", "source_issues"),
                         packets.READ_COLLECTIONS["independent"])
        judged = {"audits", "checks", "findings", "repairs", "observations", "reconciliations",
                  "reuse_decisions", "qualifications"}
        self.assertEqual(judged,
                         set(packets.READ_COLLECTIONS["primary"]) - set(packets.READ_COLLECTIONS["author"]))
        self.assertEqual({"responses", "identity_maps"},
                         set(packets.READ_COLLECTIONS["reconcile"]) - set(packets.READ_COLLECTIONS["primary"]))
        self.assertEqual(set(), judged & set(packets.READ_COLLECTIONS["author"]))
        self.assertEqual(set(), (judged | {"papers", "arguments", "groups", "uses", "scopes", "coverage"})
                         & set(packets.READ_COLLECTIONS["independent"]))

    def test_only_the_authoring_modes_may_write_the_structure(self):
        """A reviewer's packet edits evidence, never the paper: independent writes nothing, reconcile no structure."""
        self.assertEqual((), packets.WRITE_COLLECTIONS["independent"])
        self.assertEqual(("anchors", "sources", "source_issues", "source_reviews", "checks", "findings", "responses"),
                         packets.WRITE_COLLECTIONS["reconcile"])
        self.assertEqual(packets.READ_COLLECTIONS["author"], packets.WRITE_COLLECTIONS["author"])
        self.assertNotIn("papers", packets.WRITE_COLLECTIONS["primary"])
        for structural in ("items", "parts", "arguments", "groups", "uses", "scopes"):
            self.assertNotIn(structural, packets.WRITE_COLLECTIONS["reconcile"], structural)
            self.assertIn(structural, packets.WRITE_COLLECTIONS["primary"], structural)
        for mode in packets.MODES:
            self.assertEqual(set(), set(packets.WRITE_COLLECTIONS[mode]) - set(packets.READ_COLLECTIONS[mode]), mode)

    def test_each_mode_assembles_exactly_the_collections_its_role_needs(self):
        """One item of a completed audit yields four different, exactly specified views."""
        self.fx.complete()
        with self.fx.open() as db:
            for mode, expected in MODE_COLLECTIONS.items():
                with self.subTest(mode=mode):
                    packet = packets.get_packet(db, targets=[R("items", "itm_lem")], mode=mode)
                    self.assertEqual(expected, collections_of(packet))

    def test_an_unknown_mode_is_refused_and_stores_no_packet(self):
        """get_packet rejects a mode outside MODES and writes no packets row."""
        with self.fx.open() as db:
            before = stored_packets(db)
            with self.assertRaises(InvalidRequest) as caught:
                packets.get_packet(db, targets=[R("items", "itm_lem")], mode="challenge")
            self.assertEqual("INVALID_REQUEST", caught.exception.code)
            self.assertIn("unknown packet mode 'challenge'", caught.exception.message)
            self.assertIn("['author', 'primary', 'independent', 'reconcile']", caught.exception.message)
            self.assertEqual(before, stored_packets(db))

    def test_target_collections_are_exactly_papers_items_parts_audits(self):
        """TARGET_COLLECTIONS is the four documented collections and each one reaches its own statements."""
        self.assertEqual(("papers", "items", "parts", "audits"), packets.TARGET_COLLECTIONS)
        with self.fx.open() as db:
            self.fx.apply(db, [part_edit("prt_a", "itm_lem", "Part (a)", "anc_lem")])
            for target, items in ((R("papers", self.fx.paper_id), ["itm_lem", "itm_thm"]),
                                  (R("items", "itm_lem"), ["itm_lem"]),
                                  (R("parts", "prt_a"), ["itm_lem"]),
                                  (R("audits", "aud_1"), ["itm_lem", "itm_thm"])):
                with self.subTest(target=target):
                    packet = packets.get_packet(db, targets=[target], mode="primary")
                    self.assertEqual([target], packet["targets"])
                    self.assertEqual(items, ids_in(packet, "items"))
                    self.assertEqual(["prt_a"], ids_in(packet, "parts"))

    def test_a_target_outside_the_allowlist_is_refused_and_stores_no_packet(self):
        """Only papers, items, parts and audits may be packet targets; a malformed ref is refused too."""
        with self.fx.open() as db:
            before = stored_packets(db)
            for target in (R("arguments", "arg_lem"), R("groups", "grp_lem"), R("uses", "use_lem_thm"),
                           R("anchors", "anc_lem"), {"collection": "items"},
                           {"collection": "items", "id": "itm_lem", "version": 1}):
                with self.subTest(target=target):
                    with self.assertRaises(InvalidRequest) as caught:
                        packets.get_packet(db, targets=[target], mode="primary")
                    self.assertEqual("INVALID_REQUEST", caught.exception.code)
                    self.assertIn("packet targets are ['papers', 'items', 'parts', 'audits'] references",
                                  caught.exception.message)
            self.assertEqual(before, stored_packets(db))

    def test_a_packet_needs_at_least_one_live_target(self):
        """get_packet() with no targets is refused, and so is a missing or repeated target."""
        with self.fx.open() as db:
            before = stored_packets(db)
            with self.assertRaises(InvalidRequest) as empty:
                packets.get_packet(db)
            self.assertEqual("a packet needs at least one target", empty.exception.message)
            with self.assertRaises(InvalidRequest) as missing:
                packets.get_packet(db, targets=[R("items", "itm_absent")], mode="primary")
            self.assertEqual("target items:itm_absent is not a live record", missing.exception.message)
            with self.assertRaises(InvalidRequest) as twice:
                packets.get_packet(db, targets=[R("items", "itm_lem"), R("items", "itm_lem")], mode="primary")
            self.assertIn("duplicate packet target", twice.exception.message)
            self.assertEqual(before, stored_packets(db))

    def test_the_cli_has_no_default_target(self):
        """There is no implicit paper target: get needs --target, and --extend takes its targets from the request."""
        payload, _ = run_cli("get", self.fx.path, expect=2)
        self.assertEqual("USAGE", payload["error"]["code"])
        self.assertEqual("get needs at least one --target COLLECTION:ID (or --extend PACKET_ID)",
                         payload["error"]["message"])
        payload, _ = run_cli("get", self.fx.path, "--extend", "pkt_x", "--target", "items:itm_lem", expect=2)
        self.assertEqual("get --extend takes the added targets from the context request, not --target",
                         payload["error"]["message"])
        payload, _ = run_cli("get", self.fx.path, "--target", "arguments:arg_lem", expect=2)
        self.assertEqual("INVALID_REQUEST", payload["error"]["code"])
        self.assertIn("packet targets are ['papers', 'items', 'parts', 'audits'] references",
                      payload["error"]["message"])

    def test_an_author_packet_cannot_target_an_audit(self):
        """Audits are assessment scope: author mode targets papers, items or parts only."""
        with self.fx.open() as db:
            before = stored_packets(db)
            with self.assertRaises(InvalidRequest) as caught:
                packets.get_packet(db, targets=[R("audits", "aud_1")], mode="author")
            self.assertEqual("author packets target papers, items or parts", caught.exception.message)
            self.assertEqual(before, stored_packets(db))
            self.assertEqual("primary", packets.get_packet(
                db, targets=[R("audits", "aud_1")], mode="primary")["mode"])

    def test_a_paper_target_reads_the_whole_live_structure_without_assessment(self):
        """A paper-wide author packet carries every live structural record and no assessment record."""
        self.fx.complete()
        with self.fx.open() as db:
            packet = packets.get_packet(db, targets=[R("papers", self.fx.paper_id)], mode="author")
            self.assertEqual(["anchors", "application_details", "arguments", "coverage", "groups", "items", "papers",
                              "proof_boundaries", "scopes", "source_reviews", "sources", "target_specs", "uses"],
                             collections_of(packet))
            self.assertEqual(["itm_lem", "itm_thm"], ids_in(packet, "items"))
            self.assertEqual(["arg_lem", "arg_thm"], ids_in(packet, "arguments"))
            self.assertEqual(["grp_lem", "grp_thm"], ids_in(packet, "groups"))
            self.assertEqual(["use_lem_thm"], ids_in(packet, "uses"))
            self.assertEqual(refs_in(packet), scope_of(packet))
            live = {(record.collection, record.id) for record in db.heads()
                    if record.collection in STRUCTURAL_COLLECTIONS}
            self.assertEqual(live, refs_in(packet))
            self.assertTrue(db.heads("checks"), "the fixture really does hold checks")
            self.assertEqual(set(), refs_in(packet) & {(r.collection, r.id) for r in db.heads("checks")})

    def test_an_author_packet_reads_a_supplier_statement_but_not_its_proof(self):
        """A consumed lemma arrives as a statement and its passages; its own argument stays out of the packet."""
        with self.fx.open() as db:
            packet = packets.get_packet(db, targets=[R("items", "itm_thm")], mode="author")
            self.assertEqual(["itm_lem", "itm_thm"], ids_in(packet, "items"))
            self.assertEqual(["arg_thm"], ids_in(packet, "arguments"))
            self.assertEqual(["grp_thm"], ids_in(packet, "groups"))
            self.assertEqual(["use_lem_thm"], ids_in(packet, "uses"))
            self.assertTrue(db.head("arguments", "arg_lem"), "the lemma really does have its own argument")

    def test_a_read_only_database_cannot_issue_a_packet(self):
        """Packets are recorded rows, so assembling one needs a writable database."""
        with self.fx.open(write=False) as db:
            with self.assertRaises(InvalidRequest) as caught:
                packets.get_packet(db, targets=[R("items", "itm_lem")], mode="primary")
            self.assertEqual("packets are recorded in the database; open it for writing", caught.exception.message)
            self.assertEqual("INVALID_REQUEST", caught.exception.code)


class BlindingTests(TempCase):
    """Independent packets carry source material only (independent-checker.md)."""

    def setUp(self):
        super().setUp()
        self.fx = self.fixture()

    def test_an_independent_packet_carries_no_assessment_and_no_write_scope(self):
        """The blinded packet is the target statement, its passages and its source; nothing judged."""
        self.fx.complete()
        with self.fx.open() as db:
            packet = packets.get_packet(db, targets=[R("items", "itm_lem")], mode="independent")
            self.assertEqual(["anchors", "items", "sources"], collections_of(packet))
            self.assertEqual(["itm_lem"], ids_in(packet, "items"))
            self.assertEqual(["anc_lem", "anc_lem_proof"], ids_in(packet, "anchors"))
            for collection in ASSESSMENT_COLLECTIONS + ("arguments", "groups", "uses", "papers", "scopes"):
                self.assertNotIn(collection, collections_of(packet))
            self.assertEqual([], packet["write_scope"])
            self.assertEqual({"audit_id": "aud_1", "mode": "focused", "targets": [R("items", "itm_lem")],
                              "exclusions": [], "protocol_version": "item-audit/1"}, packet["declared_scope"])
            self.assertEqual([{"relation": "parts_of_item", "key": R("items", "itm_lem"),
                               "digest": membership_digest([])}], packet["membership_guards"])

    def test_a_primary_packet_carries_the_assessment_the_blinded_packet_hides(self):
        """The same target in primary mode does carry checks, observations, audit and qualification."""
        self.fx.complete()
        with self.fx.open() as db:
            primary = packets.get_packet(db, targets=[R("items", "itm_lem")], mode="primary")
            blinded = packets.get_packet(db, targets=[R("items", "itm_lem")], mode="independent")
            for collection in ("audits", "checks", "observations", "qualifications", "reconciliations"):
                self.assertIn(collection, collections_of(primary))
                self.assertNotIn(collection, collections_of(blinded))
            roles = sorted({entry["body"]["role"] for entry in primary["records"]
                            if entry["ref"]["collection"] == "checks"})
            self.assertEqual(["independent", "primary"], roles)
            self.assertIn("chk_comp_lem", ids_in(primary, "checks"))
            self.assertIn(self.fx.independent_checks["itm_lem"], ids_in(primary, "checks"))
            self.assertTrue(refs_in(blinded) < refs_in(primary))
            violations = set(packets.blinding_violations(primary))
            self.assertIn("checks:chk_comp_lem is not source material", violations)
            self.assertIn("observations:obs_lem is not source material", violations)
            self.assertIn("reconciliations:rec_lem is not source material", violations)
            self.assertIn("membership guard arguments_for_target exposes primary work", violations)
            self.assertIn("independent packets carry no write scope", violations)

    def test_a_reconcile_packet_adds_the_responses_but_may_not_edit_the_structure(self):
        """Reconciliation reads what primary reads plus the preserved responses, and writes only evidence."""
        self.fx.complete()
        with self.fx.open() as db:
            primary = packets.get_packet(db, targets=[R("items", "itm_lem")], mode="primary")
            reconcile = packets.get_packet(db, targets=[R("items", "itm_lem")], mode="reconcile")
            self.assertTrue(refs_in(primary) < refs_in(reconcile))
            self.assertEqual({"responses", "identity_maps"},
                             {collection for collection, _ in refs_in(reconcile) - refs_in(primary)})
            self.assertEqual(2, len(ids_in(reconcile, "responses")), "one preserved response per independent round")
            self.assertEqual({"anchors", "sources", "responses", "source_reviews"},
                             {collection for collection, _ in scope_of(reconcile)})
            self.assertEqual({"anchors", "sources", "items", "arguments", "coverage", "groups", "scopes", "audits",
                              "proof_boundaries", "target_specs", "source_reviews"},
                             {collection for collection, _ in scope_of(primary)})

    def test_a_completed_or_independent_check_is_outside_the_primary_write_scope(self):
        """Only a worker's own draft primary checks may be replaced through a packet."""
        self.fx.complete()
        with self.fx.open() as db:
            before = packets.get_packet(db, targets=[R("items", "itm_lem")], mode="primary")
            self.assertIn("chk_comp_lem", ids_in(before, "checks"))
            self.assertEqual([], sorted(i for c, i in scope_of(before) if c == "checks"))
            self.fx.apply(db, [self.fx.check_edit("chk_draft", R("groups", "grp_lem"), "derivation",
                                                  state="draft", outcome=None)],
                          "items:itm_lem", mode="primary")
            after = packets.get_packet(db, targets=[R("items", "itm_lem")], mode="primary")
            self.assertEqual(["chk_draft"], sorted(i for c, i in scope_of(after) if c == "checks"))

    def test_a_blinded_packet_keeps_source_definitions_and_drops_reconstructed_parts(self):
        """Applicable source setup is included; non-source parts are listed as omitted."""
        self.fx.audit()
        with self.fx.open() as db:
            self.fx.apply(db, [item_edit("itm_def", "definition", "Definition 1", "anc_lem"),
                               part_edit("prt_src", "itm_lem", "Part (a)", "anc_lem"),
                               part_edit("prt_recon", "itm_lem", "Part (b)", "anc_lem", origin="reconstruction")])
            scope = db.head("scopes", "scp_plain")
            self.fx.apply(db, [edit("replace", "scopes", scope.id,
                dict(scope.body, assumptions=[R("items", "itm_def")]), scope.version)])
            packet = packets.get_packet(db, targets=[R("items", "itm_lem")], mode="independent")
            self.assertEqual(["itm_def", "itm_lem"], ids_in(packet, "items"))
            self.assertEqual(["prt_src"], ids_in(packet, "parts"))
            self.assertEqual([{"collection": "parts", "id": "prt_recon", "reason": "not source-origin"}],
                             packet["omitted"])
            primary = packets.get_packet(db, targets=[R("items", "itm_lem")], mode="primary")
            self.assertEqual(["prt_recon", "prt_src"], ids_in(primary, "parts"))

    def test_a_blinded_packet_names_the_anchors_whose_source_moved(self):
        """A recapture under the packet is disclosed in omitted rather than passed off as current material."""
        self.fx.audit()
        with self.fx.open() as db:
            paper = self.fx.source_root / "paper.tex"
            paper.write_text(paper.read_text(encoding="utf-8") + "% a trailing comment\n", encoding="utf-8")
            self.assertEqual(2, sources.capture_sources(db, files=["paper.tex"])["sources"][0]["version"])
            packet = packets.get_packet(db, targets=[R("items", "itm_lem")], mode="independent")
            self.assertEqual([{"collection": "anchors", "id": "anc_lem",
                               "reason": "anchor pins source version 1; current version is 2"},
                              {"collection": "anchors", "id": "anc_lem_proof",
                               "reason": "anchor pins source version 1; current version is 2"}],
                             sorted(packet["omitted"], key=lambda entry: entry["id"]))
            self.assertEqual(["anc_lem", "anc_lem_proof"], ids_in(packet, "anchors"))

    def test_a_blinded_packet_cannot_be_used_to_write(self):
        """Acceptance refuses an independent packet, extended or not, with PACKET_MODE and writes nothing."""
        self.fx.audit()
        with self.fx.open() as db:
            blinded = packets.get_packet(db, targets=[R("items", "itm_lem")], mode="independent")
            extended = packets.get_packet(db, extend=blinded["packet_id"],
                                          request=extension_request(anchors=["anc_thm"], reason="cited statement"))
            item = db.head("items", "itm_lem")
            renamed = dict(json.loads(json.dumps(item.body)), caption="hijacked")
            revision = db.max_revision()
            for packet in (blinded, extended):
                with self.subTest(packet=packet["packet_id"]):
                    with self.assertRaises(InvalidRequest) as caught:
                        acceptance.apply_batch(db, self.fx.batch(
                            [edit("replace", "items", "itm_lem", renamed, expected=item.version)],
                            packet["packet_id"]))
                    self.assertEqual("PACKET_MODE", caught.exception.code)
                    self.assertIn("needs a packet in mode ['author', 'primary']", caught.exception.message)
            self.assertEqual("Lemma 1", db.head("items", "itm_lem").body["caption"])
            self.assertEqual(item.version, db.head("items", "itm_lem").version)
            self.assertEqual(revision, db.max_revision())

    def test_blinding_violations_reports_a_leaked_check(self):
        """A payload carrying a check is reported as not source material, naming the record."""
        self.fx.complete()
        with self.fx.open() as db:
            packet = packets.get_packet(db, targets=[R("items", "itm_lem")], mode="independent")
            check = db.head("checks", "chk_comp_lem")
            leaked = json.loads(json.dumps(packet))
            leaked["records"].append({"ref": check.pinned, "body": check.body})
            self.assertEqual(["checks:chk_comp_lem is not source material"], packets.blinding_violations(leaked))

    def test_blinding_violations_reports_a_write_scope(self):
        """An independent packet that could edit anything at all is a violation by itself."""
        self.fx.audit()
        with self.fx.open() as db:
            packet = packets.get_packet(db, targets=[R("items", "itm_lem")], mode="independent")
        scoped = json.loads(json.dumps(packet))
        scoped["write_scope"] = [R("items", "itm_lem")]
        self.assertEqual(["independent packets carry no write scope"], packets.blinding_violations(scoped))

    def test_blinding_violations_reports_a_guard_over_primary_work(self):
        """Only source-derived membership (parts_of_item) may be guarded; an argument guard leaks primary work."""
        self.fx.audit()
        with self.fx.open() as db:
            packet = packets.get_packet(db, targets=[R("items", "itm_lem")], mode="independent")
        self.assertEqual(("parts_of_item",), packets.BLIND_SAFE_GUARDS)
        for relation in ("arguments_for_target", "checks_or_findings_for_target", "incoming_uses"):
            with self.subTest(relation=relation):
                guarded = json.loads(json.dumps(packet))
                guarded["membership_guards"] = [{"relation": relation, "key": R("items", "itm_lem"),
                                                 "digest": "0" * 64}]
                self.assertEqual([f"membership guard {relation} exposes primary work"],
                                 packets.blinding_violations(guarded))

    def test_blinding_violations_reports_a_report_path(self):
        """A report path on any carried record would point the worker at the primary database."""
        self.fx.audit()
        with self.fx.open() as db:
            packet = packets.get_packet(db, targets=[R("items", "itm_lem")], mode="independent")
        reported = json.loads(json.dumps(packet))
        for entry in reported["records"]:
            if entry["ref"]["collection"] == "items":
                entry["body"]["report_path"] = "reports/audit.html"
        self.assertEqual(["items:itm_lem carries a report path"], packets.blinding_violations(reported))

    def test_blinding_violations_reports_a_reconstructed_or_intermediate_statement(self):
        """Primary-authored statements are reported by origin and by kind, each on its own line."""
        self.fx.audit()
        with self.fx.open() as db:
            packet = packets.get_packet(db, targets=[R("items", "itm_lem")], mode="independent")
        authored = json.loads(json.dumps(packet))
        for entry in authored["records"]:
            if entry["ref"]["collection"] == "items":
                entry["body"]["origin"] = "reconstruction"
        self.assertEqual(["items:itm_lem has origin reconstruction"], packets.blinding_violations(authored))
        authored = json.loads(json.dumps(packet))
        for entry in authored["records"]:
            if entry["ref"]["collection"] == "items":
                entry["body"]["kind"] = "intermediate_result"
        self.assertEqual(["items:itm_lem is an intermediate result"], packets.blinding_violations(authored))

    def test_get_packet_refuses_to_issue_a_packet_that_would_leak(self):
        """The blinding check runs before the packet is stored: an intermediate target is refused."""
        self.fx.audit()
        with self.fx.open() as db:
            self.fx.apply(db, [item_edit("itm_mid", "intermediate_result", "Step 1", "anc_lem_proof",
                                         owner_id="itm_lem")])
            self.fx.apply(db, [audit_edit("aud_mid", self.fx.paper_id, [R("items", "itm_mid")],
                                          "reports/mid.html")], "items:itm_lem", mode="primary")
            before = stored_packets(db)
            with self.assertRaises(InvalidRequest) as caught:
                packets.get_packet(db, targets=[R("items", "itm_mid")], mode="independent")
            self.assertEqual("independent packet failed blinding check", caught.exception.message)
            self.assertEqual(["items:itm_mid is an intermediate result"], caught.exception.records)
            self.assertEqual(before, stored_packets(db))

    def test_an_independent_target_must_be_a_live_source_statement(self):
        """Papers and audits are not independent targets, and a reconstructed statement is not reviewable."""
        self.fx.audit()
        with self.fx.open() as db:
            self.fx.apply(db, [part_edit("prt_recon", "itm_lem", "Part (b)", "anc_lem", origin="reconstruction")])
            before = stored_packets(db)
            with self.assertRaises(InvalidRequest) as paper:
                packets.get_packet(db, targets=[R("papers", self.fx.paper_id)], mode="independent")
            self.assertIn("independent targets must be live items or parts", paper.exception.message)
            with self.assertRaises(InvalidRequest) as audit:
                packets.get_packet(db, targets=[R("audits", "aud_1")], mode="independent")
            self.assertIn("independent targets must be live items or parts", audit.exception.message)
            with self.assertRaises(InvalidRequest) as origin:
                packets.get_packet(db, targets=[R("parts", "prt_recon")], mode="independent")
            self.assertEqual("independent review requires a source-origin target; parts:prt_recon has origin "
                             "reconstruction", origin.exception.message)
            self.assertEqual(before, stored_packets(db))

    def test_an_independent_packet_needs_a_registered_audit(self):
        """Blinded review is dispatched from a registered audit; without one no packet is issued."""
        self.fx.structure()
        with self.fx.open() as db:
            before = stored_packets(db)
            with self.assertRaises(InvalidRequest) as caught:
                packets.get_packet(db, targets=[R("items", "itm_lem")], mode="independent")
            self.assertEqual("independent packets need a registered audit covering the target",
                             caught.exception.message)
            self.assertEqual(before, stored_packets(db))

    def test_an_independent_packet_needs_an_audit_that_covers_its_own_target(self):
        """An audit over other targets is not a dispatch; the covering audit becomes the declared scope."""
        self.fx.audit()
        with self.fx.open() as db:
            self.fx.apply(db, [part_edit("prt_a", "itm_lem", "Part (a)", "anc_lem")])
            before = stored_packets(db)
            with self.assertRaises(InvalidRequest) as caught:
                packets.get_packet(db, targets=[R("parts", "prt_a")], mode="independent")
            self.assertEqual("independent packets need a registered audit covering the target",
                             caught.exception.message)
            self.assertEqual(before, stored_packets(db))
            self.fx.apply(db, [audit_edit("aud_part", self.fx.paper_id, [R("parts", "prt_a")], "reports/part.html")],
                          "items:itm_lem", mode="primary")
            packet = packets.get_packet(db, targets=[R("parts", "prt_a")], mode="independent")
            self.assertEqual("aud_part", packet["declared_scope"]["audit_id"])
            self.assertEqual([R("parts", "prt_a")], packet["declared_scope"]["targets"])
            self.assertEqual(["prt_a"], ids_in(packet, "parts"))
            self.assertEqual(["itm_lem"], ids_in(packet, "items"))

    def test_the_declared_scope_picks_one_covering_audit_deterministically(self):
        """Two audits cover the target; the packet always declares the first by id, so it stays reproducible."""
        self.fx.audit()
        with self.fx.open() as db:
            self.assertEqual("aud_1", packets.get_packet(
                db, targets=[R("items", "itm_lem")], mode="independent")["declared_scope"]["audit_id"])
            self.fx.apply(db, [audit_edit("aud_0", self.fx.paper_id, [R("items", "itm_lem")], "reports/zero.html")],
                          "items:itm_lem", mode="primary")
            packet = packets.get_packet(db, targets=[R("items", "itm_lem")], mode="independent")
            self.assertEqual("aud_0", packet["declared_scope"]["audit_id"])
            self.assertEqual("reports/zero.html", db.head("audits", "aud_0").body["report_path"])
            self.assertNotIn("report_path", json.dumps(packet["declared_scope"]))


class ContextExtensionTests(TempCase):
    """``get --extend`` widens the readable context under the original packet's mode (handoff 4.2)."""

    def setUp(self):
        super().setUp()
        self.fx = self.fixture().audit()

    def test_an_extension_widens_the_read_context_but_not_the_write_scope(self):
        """An extended independent packet adds source records, keeps its mode, base revision and empty scope."""
        with self.fx.open() as db:
            base = packets.get_packet(db, targets=[R("items", "itm_lem")], mode="independent")
            extended = packets.get_packet(db, extend=base["packet_id"], request=extension_request(
                targets=[R("items", "itm_thm")], anchors=["anc_thm_proof"], paths=["paper.tex"],
                reason="the lemma proof cites the theorem statement"))
            self.assertTrue(refs_in(base) < refs_in(extended))
            self.assertEqual(["anc_lem", "anc_lem_proof", "anc_thm", "anc_thm_proof"], ids_in(extended, "anchors"))
            self.assertEqual(["itm_lem", "itm_thm"], ids_in(extended, "items"))
            self.assertEqual(["anchors", "items", "sources"], collections_of(extended))
            self.assertEqual([], extended["write_scope"])
            self.assertEqual("independent", extended["mode"])
            self.assertEqual(base["base_revision"], extended["base_revision"])
            self.assertEqual(base["packet_id"], extended["extends"])
            self.assertNotEqual(base["packet_id"], extended["packet_id"])
            self.assertEqual("the lemma proof cites the theorem statement", extended["extension_reason"])
            self.assertEqual([R("items", "itm_lem"), R("items", "itm_thm")], extended["targets"])
            self.assertEqual([R("items", "itm_lem"), R("items", "itm_thm")],
                             extended["declared_scope"]["targets"])

    def test_an_extension_cannot_escalate_the_mode_or_add_unrequested_targets(self):
        """mode= and targets= passed beside extend= are ignored: a blinded packet cannot be widened into a primary."""
        with self.fx.open() as db:
            base = packets.get_packet(db, targets=[R("items", "itm_lem")], mode="independent")
            extended = packets.get_packet(db, targets=[R("papers", self.fx.paper_id)], mode="primary",
                                          extend=base["packet_id"],
                                          request=extension_request(reason="one more look at the source"))
            self.assertEqual("independent", extended["mode"])
            self.assertEqual([R("items", "itm_lem")], extended["targets"])
            self.assertEqual([], extended["write_scope"])
            self.assertEqual(["anchors", "items", "sources"], collections_of(extended))
            self.assertEqual("independent", db.packet(extended["packet_id"])["mode"])

    def test_a_source_only_extension_adds_only_the_named_source_records(self):
        """Naming an anchor widens reading by that anchor alone; no structure or judgment rides along."""
        self.fx.primary()
        with self.fx.open() as db:
            base = packets.get_packet(db, targets=[R("items", "itm_lem")], mode="primary")
            extended = packets.get_packet(db, extend=base["packet_id"], request=extension_request(
                anchors=["anc_thm"], reason="the theorem statement is cited"))
            self.assertEqual({("anchors", "anc_thm")}, refs_in(extended) - refs_in(base))
            self.assertEqual(set(), refs_in(base) - refs_in(extended))
            self.assertEqual({("anchors", "anc_thm")}, scope_of(extended) - scope_of(base))
            self.assertEqual([R("items", "itm_lem")], extended["targets"])
            self.assertEqual("primary", extended["mode"])
            self.assertNotIn("itm_thm", ids_in(extended, "items"))

    def test_an_extension_keeps_the_original_packet_reproducible(self):
        """Extending stores a second packet; the original payload is untouched."""
        with self.fx.open() as db:
            base = packets.get_packet(db, targets=[R("items", "itm_lem")], mode="independent")
            before = json.loads(json.dumps(packets.load_packet(db, base["packet_id"])))
            rows = stored_packets(db)
            packets.get_packet(db, extend=base["packet_id"],
                               request=extension_request(anchors=["anc_thm"], reason="one more statement"))
            self.assertEqual(rows + 1, stored_packets(db))
            self.assertEqual(before, packets.load_packet(db, base["packet_id"]))

    def test_repeated_extensions_keep_all_previous_anchors_and_paths(self):
        """The worker keeps the evidence requested in every earlier extension, in either mode."""
        with self.fx.open() as db:
            for name in ("appendix.tex", "supplement.tex"):
                (self.fx.source_root / name).write_text("Additional source context.\n", encoding="utf-8")
            sources.capture_sources(db, files=["appendix.tex", "supplement.tex"])
            for mode in ("primary", "independent"):
                with self.subTest(mode=mode):
                    base = self.fx.packet(db, "items:itm_lem", mode=mode)
                    original = packets.load_packet(db, base["packet_id"])
                    first = packets.get_packet(db, extend=base["packet_id"], request=extension_request(
                        anchors=["anc_thm"], paths=["appendix.tex"]))
                    second = packets.get_packet(db, extend=first["packet_id"], request=extension_request(
                        anchors=["anc_thm_proof"], paths=["supplement.tex"]))
                    third = packets.get_packet(db, extend=second["packet_id"], request=extension_request())
                    self.assertTrue(refs_in(base) < refs_in(first) < refs_in(second))
                    self.assertEqual(refs_in(second), refs_in(third))
                    self.assertEqual(["anc_lem", "anc_lem_proof", "anc_thm", "anc_thm_proof"],
                                     ids_in(third, "anchors"))
                    self.assertEqual(["appendix.tex", "paper.tex", "supplement.tex"], sorted(
                        entry["body"]["path"] for entry in third["records"]
                        if entry["ref"]["collection"] == "sources"))
                    self.assertEqual(base["targets"], third["targets"])
                    self.assertEqual(original, packets.load_packet(db, base["packet_id"]))
                    if mode == "independent":
                        self.assertEqual([], packets.blinding_violations(third))
                        self.assertEqual([], third["write_scope"])

    def test_extension_rejects_source_change_between_context_check_and_build(self):
        """The original captured context remains authoritative across the whole extension."""
        with self.fx.open() as db, self.fx.open() as concurrent:
            base = self.fx.packet(db, "items:itm_lem", mode="independent")
            original_build = packets._build
            def change_source_then_build(*args, **kwargs):
                path = self.fx.source_root / "paper.tex"
                path.write_text(path.read_text(encoding="utf-8") + "% changed\n", encoding="utf-8")
                sources.capture_sources(concurrent, files=["paper.tex"])
                return original_build(*args, **kwargs)
            before = stored_packets(db)
            with mock.patch.object(packets, "_build", side_effect=change_source_then_build):
                with self.assertRaises(ConflictError) as caught:
                    packets.get_packet(db, extend=base["packet_id"], request=extension_request())
            self.assertIn("captured sources changed since the packet was issued", caught.exception.message)
            self.assertEqual(before, stored_packets(db))

    def test_an_extension_target_must_also_be_an_allowed_target_collection(self):
        """The merged target list goes through the same allowlist; a schema-invalid ref is refused earlier."""
        with self.fx.open() as db:
            base = packets.get_packet(db, targets=[R("items", "itm_lem")], mode="primary")
            before = stored_packets(db)
            with self.assertRaises(InvalidRequest) as outside:
                packets.get_packet(db, extend=base["packet_id"],
                                   request=extension_request(targets=[R("arguments", "arg_thm")]))
            self.assertIn("packet targets are ['papers', 'items', 'parts', 'audits'] references",
                          outside.exception.message)
            with self.assertRaises(InvalidRequest) as unknown:
                packets.get_packet(db, extend=base["packet_id"],
                                   request=extension_request(targets=[{"collection": "widgets", "id": "w1"}]))
            self.assertEqual("invalid context extension request", unknown.exception.message)
            self.assertTrue(any("/targets/0/collection" in error for error in unknown.exception.records),
                            unknown.exception.records)
            self.assertEqual(before, stored_packets(db))

    def test_an_extension_needs_a_known_packet_and_a_complete_request(self):
        """--extend requires an existing packet id and a well-formed context request."""
        with self.fx.open() as db:
            base = packets.get_packet(db, targets=[R("items", "itm_lem")], mode="independent")
            before = stored_packets(db)
            with self.assertRaises(InvalidRequest) as no_request:
                packets.get_packet(db, extend=base["packet_id"])
            self.assertIn("get --extend needs a context request", no_request.exception.message)
            with self.assertRaises(InvalidRequest) as no_packet:
                packets.get_packet(db, extend="pkt_absent", request=extension_request())
            self.assertEqual("unknown packet pkt_absent", no_packet.exception.message)
            for request, field in ((extension_request(reason=""), "/reason"),
                                   ({"targets": [], "source_anchor_ids": [], "reason": "why"}, "/source_paths")):
                with self.subTest(field=field):
                    with self.assertRaises(InvalidRequest) as caught:
                        packets.get_packet(db, extend=base["packet_id"], request=request)
                    self.assertEqual("invalid context extension request", caught.exception.message)
                    self.assertTrue(any(error.startswith(field) for error in caught.exception.records),
                                    caught.exception.records)
            self.assertEqual(before, stored_packets(db))

    def test_an_extension_refuses_source_material_that_does_not_exist(self):
        """A source-only extension must name a live anchor and a captured path."""
        with self.fx.open() as db:
            base = packets.get_packet(db, targets=[R("items", "itm_lem")], mode="independent")
            before = stored_packets(db)
            with self.assertRaises(InvalidRequest) as anchor:
                packets.get_packet(db, extend=base["packet_id"], request=extension_request(anchors=["anc_absent"]))
            self.assertEqual("requested anchor anc_absent is not a live record", anchor.exception.message)
            with self.assertRaises(InvalidRequest) as path:
                packets.get_packet(db, extend=base["packet_id"], request=extension_request(paths=["missing.tex"]))
            self.assertEqual("requested source path missing.tex is not captured", path.exception.message)
            self.assertEqual(before, stored_packets(db))

    def test_an_extension_after_a_source_change_conflicts(self):
        """Captured sources moved under the packet, so the worker must take a fresh one."""
        with self.fx.open() as db:
            base = packets.get_packet(db, targets=[R("items", "itm_lem")], mode="independent")
            paper = self.fx.source_root / "paper.tex"
            paper.write_text(paper.read_text(encoding="utf-8").replace("By induction", "By strong induction"),
                             encoding="utf-8")
            self.assertTrue(sources.capture_sources(db, files=["paper.tex"])["changed"])
            before = stored_packets(db)
            with self.assertRaises(ConflictError) as caught:
                packets.get_packet(db, extend=base["packet_id"], request=extension_request(anchors=["anc_thm"]))
            self.assertEqual("CONFLICT", caught.exception.code)
            self.assertIn("captured sources changed since the packet was issued", caught.exception.message)
            self.assertEqual([{"kind": "source_context", "packet_id": base["packet_id"]}],
                             caught.exception.records)
            self.assertEqual(before, stored_packets(db))


class SourceContextDigestTests(TempCase):
    """``source_context_digest`` tracks captured sources and nothing else."""

    def setUp(self):
        super().setUp()
        self.fx = self.fixture().audit()

    def test_the_digest_is_stable_while_the_sources_are_unchanged(self):
        """Repeated calls agree; a record edit and a no-op recapture both leave the digest alone."""
        with self.fx.open() as db:
            first = packets.source_context_digest(db)
            self.assertEqual(64, len(first))
            self.assertEqual(first, packets.source_context_digest(db))
            self.assertEqual(first, packets.get_packet(
                db, targets=[R("items", "itm_lem")], mode="primary")["source_context_digest"])
            self.fx.apply(db, [item_edit("itm_def", "definition", "Definition 1", "anc_lem")])
            self.assertEqual(first, packets.source_context_digest(db))
            recaptured = sources.capture_sources(db, files=["paper.tex"])
            self.assertFalse(recaptured["changed"])
            self.assertEqual(1, recaptured["sources"][0]["version"])
            self.assertEqual(first, packets.source_context_digest(db))

    def test_the_digest_changes_when_a_captured_source_changes(self):
        """A recaptured file gives a new source version and a new digest."""
        with self.fx.open() as db:
            before = packets.source_context_digest(db)
            paper = self.fx.source_root / "paper.tex"
            paper.write_text(paper.read_text(encoding="utf-8") + "% a trailing comment\n", encoding="utf-8")
            captured = sources.capture_sources(db, files=["paper.tex"])
            self.assertEqual(2, captured["sources"][0]["version"])
            self.assertNotEqual(before, packets.source_context_digest(db))

    def test_the_digest_covers_the_whole_captured_set(self):
        """Capturing a second file changes the digest even though no existing source moved."""
        with self.fx.open() as db:
            before = packets.source_context_digest(db)
            (self.fx.source_root / "appendix.tex").write_text("% an appendix\n", encoding="utf-8")
            captured = sources.capture_sources(db, files=["appendix.tex"])
            self.assertEqual(["appendix.tex"], [source["path"] for source in captured["sources"]])
            self.assertNotEqual(before, packets.source_context_digest(db))

    def test_a_packet_cut_before_a_source_change_cannot_be_written_through(self):
        """Acceptance compares the packet's source digest with the database and rejects the batch whole."""
        self.fx.primary()
        with self.fx.open() as db:
            stale = packets.get_packet(db, targets=[R("items", "itm_lem")], mode="primary")
            paper = self.fx.source_root / "paper.tex"
            paper.write_text(paper.read_text(encoding="utf-8").replace("converges", "converges fast"),
                             encoding="utf-8")
            sources.capture_sources(db, files=["paper.tex"])
            revision = db.max_revision()
            with self.assertRaises(ConflictError) as caught:
                acceptance.apply_batch(db, self.fx.batch(
                    [self.fx.check_edit("chk_new", R("groups", "grp_lem"), "derivation")], stale["packet_id"]))
            self.assertEqual("CONFLICT", caught.exception.code)
            self.assertTrue(caught.exception.records[0]["source_context_changed"])
            self.assertIsNone(db.head("checks", "chk_new"))
            self.assertEqual(revision, db.max_revision())


class StoredPacketTests(TempCase):
    """A packet is an immutable stored row plus a content-addressed payload."""

    def setUp(self):
        super().setUp()
        self.fx = self.fixture().primary()

    def test_load_packet_round_trips_the_stored_payload(self):
        """What the worker received is exactly what the database can hand back later."""
        with self.fx.open() as db:
            rows = stored_packets(db)
            issued = packets.get_packet(db, targets=[R("items", "itm_lem")], mode="primary")
            self.assertEqual(rows + 1, stored_packets(db))
            loaded = packets.load_packet(db, issued["packet_id"])
            manifest = loaded.pop("_manifest")
            self.assertEqual(issued, loaded)
            self.assertEqual(["base_revision", "membership_guards", "mode", "packet_id", "packet_version",
                              "read_set", "source_context_digest", "targets", "write_scope"], sorted(manifest))
            self.assertEqual({key: issued[key] for key in manifest}, manifest)
            row = db.packet(issued["packet_id"])
            self.assertEqual("primary", row["mode"])
            self.assertEqual(issued["base_revision"], row["base_revision"])
            self.assertEqual(issued["packet_version"], row["packet_version"])
            self.assertEqual(support.sha(db.get_blob(row["payload_sha256"])), row["payload_sha256"])

    def test_load_packet_refuses_an_unknown_packet_id(self):
        """An id that was never issued is an invalid request, not an empty packet."""
        with self.fx.open() as db:
            with self.assertRaises(InvalidRequest) as caught:
                packets.load_packet(db, "pkt_never_issued")
            self.assertEqual("unknown packet pkt_never_issued", caught.exception.message)
            self.assertEqual("INVALID_REQUEST", caught.exception.code)

    def test_two_packets_from_one_revision_differ_only_in_identity(self):
        """The same request against an unchanged database yields the same view under a new packet id."""
        with self.fx.open() as db:
            first = packets.get_packet(db, targets=[R("items", "itm_lem")], mode="primary")
            second = packets.get_packet(db, targets=[R("items", "itm_lem")], mode="primary")
            self.assertNotEqual(first["packet_id"], second["packet_id"])
            self.assertTrue(second["packet_id"].startswith("pkt_"))
            self.assertEqual([key for key in first if first[key] != second[key]], ["packet_id"])

    def test_a_non_independent_packet_declares_no_scope_and_omits_nothing(self):
        """declared_scope, extends, omitted and truncated carry the documented defaults outside blinded review."""
        with self.fx.open() as db:
            for mode in ("author", "primary", "reconcile"):
                with self.subTest(mode=mode):
                    packet = packets.get_packet(db, targets=[R("items", "itm_lem")], mode=mode)
                    self.assertIsNone(packet["declared_scope"])
                    self.assertIsNone(packet["extends"])
                    self.assertEqual([], packet["omitted"])
                    self.assertIs(False, packet["truncated"])
                    self.assertNotIn("extension_reason", packet)


class PacketRevisionTests(TempCase):
    """A packet pins the revision it was cut at; later edits stale it (implementation-handoff 4.3)."""

    def setUp(self):
        super().setUp()
        self.fx = self.fixture().primary()

    def test_a_packet_pins_the_revision_and_head_versions_it_was_cut_at(self):
        """base_revision is the database revision, the read set pins every carried record, no revision is spent."""
        with self.fx.open() as db:
            revision = db.max_revision()
            self.assertGreater(revision, 0)
            packet = packets.get_packet(db, targets=[R("items", "itm_lem")], mode="primary")
            self.assertEqual(revision, packet["base_revision"])
            self.assertEqual(revision, db.max_revision())
            self.assertEqual([entry["ref"] for entry in packet["records"]], packet["read_set"])
            self.assertIn(R("items", "itm_lem"), [{"collection": p["collection"], "id": p["id"]}
                                                  for p in packet["read_set"]])
            for pinned in packet["read_set"]:
                head = db.head(pinned["collection"], pinned["id"])
                self.assertEqual(head.version, pinned["version"])
            self.assertEqual(revision, db.packet(packet["packet_id"])["base_revision"])

    def test_interleaved_membership_commit_cannot_issue_a_mixed_packet(self):
        """A new premise between closure and guard reads cannot be hidden behind a newer guard."""
        with self.fx.open() as db, self.fx.open() as concurrent:
            author = self.fx.packet(concurrent, "items:itm_thm")
            body = dict(concurrent.head("uses", "use_lem_thm").body,
                        substitutions=[{"symbol": "n", "value": "n + 1"}])
            batch = self.fx.batch([edit("create", "uses", "use_unseen", body)], author["packet_id"])
            original_finish = packets._Closure.finish
            inserted = []
            def finish_then_commit(closure):
                original_finish(closure)
                if closure.db is db and not inserted:
                    inserted.append(acceptance.apply_batch(concurrent, batch))
            before = stored_packets(db)
            with mock.patch.object(packets._Closure, "finish", new=finish_then_commit):
                with self.assertRaises(ConflictError) as caught:
                    self.fx.packet(db, "items:itm_thm", mode="primary")
            self.assertIn("database changed while the packet was being assembled", caught.exception.message)
            self.assertEqual(1, len(inserted))
            self.assertIsNotNone(db.head("uses", "use_unseen"))
            self.assertEqual(before, stored_packets(db))
            fresh = self.fx.packet(db, "items:itm_thm", mode="primary")
            self.assertIn(("uses", "use_unseen"), refs_in(fresh))
            self.assertEqual(db.max_revision(), fresh["base_revision"])

    def test_an_edit_to_a_read_set_record_makes_the_packet_stale(self):
        """A batch against the old packet is rejected whole with the changed versions and a retry command."""
        with self.fx.open() as db:
            stale = packets.get_packet(db, targets=[R("items", "itm_lem")], mode="primary")
            item = db.head("items", "itm_lem")
            renamed = dict(json.loads(json.dumps(item.body)), caption="Lemma 1 (renamed)")
            self.fx.apply(db, [edit("replace", "items", "itm_lem", renamed, expected=item.version)],
                          "items:itm_lem", mode="author")
            revision = db.max_revision()
            with self.assertRaises(ConflictError) as caught:
                acceptance.apply_batch(db, self.fx.batch(
                    [self.fx.check_edit("chk_new", R("groups", "grp_lem"), "derivation")], stale["packet_id"]))
            self.assertEqual("CONFLICT", caught.exception.code)
            record = caught.exception.records[0]
            self.assertIn({"ref": R("items", "itm_lem"), "expected_version": item.version,
                           "actual_version": item.version + 1, "retired": False}, record["changed"])
            self.assertEqual([], record["changed_relations"])
            self.assertFalse(record["source_context_changed"])
            self.assertEqual({"command": "get DB --target items:itm_lem --mode primary --out PACKET.json",
                              "targets": [R("items", "itm_lem")], "mode": "primary"}, caught.exception.retry)
            self.assertIsNone(db.head("checks", "chk_new"))
            self.assertEqual(revision, db.max_revision())

    def test_a_commit_outside_the_read_set_leaves_the_packet_usable(self):
        """An unrelated commit only rebases the batch; the receipt records the packet's older base revision."""
        with self.fx.open() as db:
            packet = packets.get_packet(db, targets=[R("items", "itm_lem")], mode="primary")
            author = packets.get_packet(db, targets=[R("papers", self.fx.paper_id)], mode="author")
            sources.anchor_sources(db, request={
                "contract_version": 3, "request_id": self.fx.request_id(), "packet_id": author["packet_id"],
                "anchors": [{"id": "anc_extra", "expected_version": None, "source_id": self.fx.source_id,
                             "locator": locator(start=5, end=6)}]})
            self.assertGreater(db.max_revision(), packet["base_revision"])
            item = db.head("items", "itm_lem")
            renamed = dict(json.loads(json.dumps(item.body)), caption="Lemma 1 (revised)")
            receipt = acceptance.apply_batch(db, self.fx.batch(
                [edit("replace", "items", "itm_lem", renamed, expected=item.version)], packet["packet_id"]))
            self.assertEqual(packet["base_revision"], receipt["rebased_from"])
            self.assertEqual(db.max_revision(), receipt["revision"])
            self.assertEqual(item.version + 1, db.head("items", "itm_lem").version)
            self.assertEqual("Lemma 1 (revised)", db.head("items", "itm_lem").body["caption"])


if __name__ == "__main__":
    unittest.main()
