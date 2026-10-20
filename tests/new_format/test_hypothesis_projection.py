"""Recorded target hypotheses are presentation relations, never extra proof work."""
from copy import deepcopy
from unittest.mock import patch

from support import R, TempCase, edit
from test_reader_projection import exact, scope
from paper_core import PROTOCOL_VERSION, assessment, projection


class HypothesisProjectionTests(TempCase):
    def audited(self, name="paper"):
        fixture = self.fixture(name)
        apply = fixture.apply
        def current_protocol(db, edits, *targets, **kwargs):
            edits = [dict(row, body=dict(row["body"], protocol_version=PROTOCOL_VERSION))
                     if row["collection"] == "audits" else row for row in edits]
            # New named major items and shared scopes use a paper author packet.
            return apply(db, edits, **kwargs)
        fixture.apply = current_protocol
        fixture.audit(independent_required=False)
        return fixture

    def named(self, fixture, identity="itm_assumption", kind="assumption"):
        return fixture.item_edit(identity, kind, identity, "anc_lem", "anc_lem_proof")

    def target_scope(self, db, identity, scope_id):
        row = db.head("target_specs", "tgt_" + identity)
        return edit("replace", row.collection, row.id, dict(row.body, scope_id=scope_id), row.version)

    def project(self, fixture):
        with fixture.open(write=False) as db:
            before = db.max_revision()
            result, report = projection.project(db, audit_id=fixture.audit_id)
            self.assertEqual(db.max_revision(), before)
        self.assertEqual(report["problems"], result["summary"]["limitations"])
        pins = {(row["ref"]["collection"], row["ref"]["id"], row["ref"]["version"])
                for row in result["records"]}
        for relation in result["hypothesis_connections"]:
            for ref in [relation[key] for key in ("premise_ref", "target_ref", "spec_ref", "statement_ref")] \
                    + relation["scope_refs"]:
                self.assertIn((ref["collection"], ref["id"], ref["version"]), pins)
            self.assertIn(relation["detail_key"], result["details"])
        return result

    def test_direct_inherited_deduplicated_and_explicit_definition_setup(self):
        fixture = self.audited()
        with fixture.open() as db:
            fixture.apply(db, [self.named(fixture), self.named(fixture, "itm_setup", "definition"),
                self.named(fixture, "itm_explanation", "definition"),
                scope("scp_parent", assumptions=[R("items", "itm_assumption")]),
                scope("scp_target", parent="scp_parent", assumptions=[R("items", "itm_assumption"),
                    R("items", "itm_setup"), R("items", "itm_thm")]),
                self.target_scope(db, "thm", "scp_target")], *fixture.ITEMS)
        result = self.project(fixture)
        relations = {row["from"]: row for row in result["hypothesis_connections"]}
        self.assertEqual(set(relations), {"itm_assumption", "itm_setup"})
        self.assertEqual(relations["itm_assumption"]["kind"], "hypothesis")
        self.assertEqual(relations["itm_setup"]["kind"], "setup")
        self.assertEqual([ref["id"] for ref in relations["itm_assumption"]["scope_refs"]],
                         ["scp_target", "scp_parent"])
        self.assertEqual(relations["itm_assumption"]["id"],
                         "hyp_" + projection.connection_id("itm_assumption", "itm_thm")[5:])
        self.assertIsNone(relations["itm_assumption"]["proof_connection_id"])
        self.assertNotIn("itm_explanation", {node["id"] for node in result["nodes"]})

    def test_context_endpoint_has_no_new_audit_work_or_recursive_expansion(self):
        fixture = self.audited()
        with fixture.open() as db:
            premise = self.named(fixture)
            premise["body"]["scope_id"] = "scp_premise"
            fixture.apply(db, [premise, self.named(fixture, "itm_nested"),
                scope("scp_premise", assumptions=[R("items", "itm_nested")]),
                scope("scp_target", assumptions=[R("items", "itm_assumption")]),
                self.target_scope(db, "thm", "scp_target")], *fixture.ITEMS)
        with fixture.open(write=False) as db:
            derivation, derived = assessment.derive_full(db, audit_id=fixture.audit_id)
            # The full assessment closure already includes named premises. Exercise
            # a bounded projection whose selected statement set omits those endpoints.
            derived["statements"] = [ref for ref in derived["statements"] if ref["id"] in ("itm_lem", "itm_thm")]
            for identity in ("itm_assumption", "itm_nested"):
                derived["assessments"].pop("items:" + identity, None)
            with patch.object(projection._Projector, "hypothesis_connections", return_value=[]):
                before, _ = projection.project(db, derived=(derivation, derived))
            result, report = projection.project(db, derived=(derivation, derived))
        self.assertEqual(report["problems"], result["summary"]["limitations"])
        self.assertEqual(len(result["hypothesis_connections"]), 1)
        nodes = {node["id"]: node for node in result["nodes"]}
        self.assertEqual(set(nodes) - {node["id"] for node in before["nodes"]}, {"itm_assumption"})
        self.assertEqual(nodes["itm_assumption"]["assessment"]["label"], "outside scope")
        self.assertEqual(result["obligations"], before["obligations"])
        self.assertEqual([task["id"] for task in result["worklist"]["tasks"]],
                         [task["id"] for task in before["worklist"]["tasks"]])
        self.assertEqual(result["connections"], before["connections"])

    def test_explicit_null_scope_overrides_item_scope(self):
        fixture = self.audited()
        with fixture.open() as db:
            row = db.head("items", "itm_thm")
            fixture.apply(db, [self.named(fixture),
                scope("scp_fallback", assumptions=[R("items", "itm_assumption")]),
                edit("replace", "items", row.id, dict(row.body, scope_id="scp_fallback"), row.version)],
                *fixture.ITEMS)
        self.assertEqual(self.project(fixture)["hypothesis_connections"], [])

    def test_part_only_audit_does_not_flatten_part_or_owner_conditions(self):
        fixture = self.audited()
        with fixture.open() as db:
            audit = db.head("audits", fixture.audit_id)
            fixture.apply(db, [self.named(fixture),
                scope("scp_part", assumptions=[R("items", "itm_assumption")]),
                edit("create", "parts", "prt_first", {"item_id": "itm_thm", "label": "(i)",
                    "statement": {"form": "transcription", "text": "First assertion"}, "passages": [],
                    "scope_id": "scp_part", "origin": "source"}),
                exact("tgt_part", R("parts", "prt_first"),
                    statement={"form": "transcription", "text": "Exact first assertion"}, scope_id="scp_part"),
                self.target_scope(db, "thm", "scp_part"),
                edit("replace", "audits", audit.id, dict(audit.body, targets=[R("parts", "prt_first")]),
                     audit.version)], *fixture.ITEMS, mode="primary")
        result = self.project(fixture)
        self.assertIn("itm_thm", {node["id"] for node in result["nodes"]})
        self.assertEqual(result["hypothesis_connections"], [])

    def test_local_discharged_and_proposed_repair_contexts_are_excluded(self):
        fixture = self.audited()
        with fixture.open() as db:
            argument = fixture.argument_edit("arg_repair", "itm_thm", "grp_repair", "anc_thm_proof")
            argument["body"].update(origin="proposed_repair", scope_id="scp_local")
            group = fixture.group_edit("grp_repair", "arg_repair", "itm_thm", "anc_thm_proof")
            group["body"].update(kind="cases", case_scope_ids=["scp_local"], discharges=["scp_local"])
            fixture.apply(db, [self.named(fixture), argument, group,
                scope("scp_local", parent="scp_plain", assumptions=[R("items", "itm_assumption")],
                      argument="arg_repair")], *fixture.ITEMS)
        self.assertEqual(self.project(fixture)["hypothesis_connections"], [])
        # A local scope explicitly defining this exact target is authoritative.
        with fixture.open() as db:
            fixture.apply(db, [self.target_scope(db, "thm", "scp_local")], *fixture.ITEMS)
        self.assertEqual(len(self.project(fixture)["hypothesis_connections"]), 1)

    def test_overlapping_proof_pair_retains_one_proof_connection_and_applications(self):
        fixture = self.audited()
        with fixture.open() as db:
            row = db.head("items", "itm_lem")
            fixture.apply(db, [edit("replace", "items", row.id, dict(row.body, kind="assumption"), row.version),
                scope("scp_target", assumptions=[R("items", "itm_lem")])], *fixture.ITEMS)
        before = self.project(fixture)
        with fixture.open() as db:
            fixture.apply(db, [self.target_scope(db, "thm", "scp_target")], *fixture.ITEMS)
        result = self.project(fixture)
        relation, = result["hypothesis_connections"]
        self.assertEqual(relation["proof_connection_id"], result["connections"][0]["id"])
        self.assertEqual(result["connections"], before["connections"])
        self.assertEqual(result["layout"], before["layout"])

    def test_draft_missing_and_historical_scope_do_not_create_relations(self):
        for state in ("draft", "missing", "historical"):
            with self.subTest(state=state):
                fixture = self.audited(state)
                with fixture.open() as db:
                    fixture.apply(db, [self.named(fixture),
                        scope("scp_target", assumptions=[R("items", "itm_assumption")]),
                        self.target_scope(db, "thm", "scp_target")], *fixture.ITEMS)
                    spec = db.head("target_specs", "tgt_thm")
                    if state == "draft":
                        change = edit("replace", spec.collection, spec.id, dict(spec.body, state="draft"), spec.version)
                    elif state == "missing":
                        change = {"op": "retire", "collection": spec.collection, "id": spec.id,
                                  "expected_version": spec.version, "reason": "Missing exact target fixture"}
                    else:
                        row = db.head("scopes", "scp_target")
                        change = edit("replace", row.collection, row.id, dict(row.body, assumptions=[]), row.version)
                    fixture.apply(db, [change], *fixture.ITEMS)
                self.assertEqual(self.project(fixture)["hypothesis_connections"], [])

    def test_pinned_exact_statement_survives_current_item_replacement(self):
        fixture = self.audited()
        with fixture.open() as db:
            item = db.head("items", "itm_thm")
            body = deepcopy(item.body)
            body["statement"] = {"form": "synopsis", "text": "New abbreviated statement"}
            fixture.apply(db, [self.named(fixture),
                scope("scp_target", assumptions=[R("items", "itm_assumption")]),
                self.target_scope(db, "thm", "scp_target"),
                edit("replace", "items", item.id, body, item.version)], *fixture.ITEMS)
        relation, = self.project(fixture)["hypothesis_connections"]
        self.assertEqual(relation["target_ref"]["version"], 2)
        self.assertEqual(relation["statement_ref"], {"collection": "items", "id": "itm_thm", "version": 1})

    def test_combined_presentation_cycle_preserves_scientific_connections(self):
        fixture = self.audited()
        before = self.project(fixture)
        with fixture.open() as db:
            edits = []
            for name in ("lem", "thm"):
                row = db.head("items", "itm_" + name)
                edits.append(edit("replace", "items", row.id, dict(row.body, kind="assumption"), row.version))
            fixture.apply(db, [*edits,
                scope("scp_lem", assumptions=[R("items", "itm_thm")]),
                scope("scp_thm", assumptions=[R("items", "itm_lem")]),
                self.target_scope(db, "lem", "scp_lem"), self.target_scope(db, "thm", "scp_thm")])
        result = self.project(fixture)
        self.assertEqual(len(result["hypothesis_connections"]), 2)
        self.assertEqual(result["layout"]["mode"], "cyclic")
        self.assertEqual([row["id"] for row in result["connections"]],
                         [row["id"] for row in before["connections"]])
        self.assertEqual(result["connections"][0]["primary_use_ids"], ["use_lem_thm"])

    def test_overview_output_has_no_hypothesis_field(self):
        fixture = self.fixture().structure()
        with fixture.open(write=False) as db:
            result, _ = projection.project(db)
        self.assertNotIn("hypothesis_connections", result)
