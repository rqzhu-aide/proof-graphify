"""Explanatory definitions do not become unproved mathematical co-premises."""
import unittest

from support import R, TempCase, edit, locator
from test_sql_support import Graph
from paper_core import PROTOCOL_VERSION, assessment, projection, review, sources
from paper_core.authoring import create_record


class DefinitionContextTests(unittest.TestCase):
    def graph(self, *, scope=None):
        graph = Graph()
        graph.item("notation", kind="definition")
        graph.item("consumer", scope=scope)
        graph.route("consumer", "consumer", scope=scope)
        graph.use("notation_use", "notation", "g_consumer", scope=scope)
        graph.live("uses", "notation_use").body["type"] = "definition"
        return graph

    def test_explanatory_use_preserves_global_and_hypothetical_distinctions(self):
        for first in ("notation", "consumer"):
            with self.subTest(first=first):
                graph = self.graph()
                graph.support(first)
                self.assertEqual(graph.support("consumer"), "available")
                self.assertEqual(graph.closure.value(("use", "notation_use")), "available")
                self.assertEqual(graph.support("notation"), "conditional")
                reason = graph.closure.explain(graph.closure.statement_key(R("items", "notation"), None))
                self.assertEqual(reason["code"], "premise_not_active")

    def test_context_retains_currency_refutation_and_scope_requirements(self):
        cases = (("current", "available", None),
                 ("stale", "conditional", "exact_target_pending"),
                 ("missing", "unavailable", "missing_record"),
                 ("refuted", "unavailable", "statement_refuted"),
                 ("private", "unavailable", "scope_unavailable"),
                 ("missing_scope", "unavailable", "scope_unavailable"))
        for case, expected, code in cases:
            with self.subTest(case=case):
                graph = self.graph()
                if case == "stale":
                    graph.exact.remove(("items", "notation"))
                elif case == "missing":
                    del graph.records["items", "notation"]
                elif case == "refuted":
                    graph.findings_by_target["items:notation"].append(graph.put(
                        "findings", "refutation", category="statement_refutation", lifecycle="open"))
                elif case in ("private", "missing_scope"):
                    graph.live("items", "notation").body["scope_id"] = "private"
                    if case == "private":
                        graph.scope("private", conditions=["x > 0"])
                self.assertEqual(graph.support("consumer"), expected)
                reason = graph.closure.explain(("use", "notation_use"))
                self.assertEqual(reason["code"] if reason else None, code)

    def test_declared_premise_does_not_launder_stale_or_refuted_context(self):
        for case, expected in (("stale", "conditional"), ("refuted", "unavailable")):
            with self.subTest(case=case):
                graph = self.graph(scope="active")
                graph.scope("active", ["notation"])
                if case == "stale":
                    graph.exact.remove(("items", "notation"))
                else:
                    graph.findings_by_target["items:notation"].append(graph.put(
                        "findings", "refutation", category="statement_refutation", lifecycle="open"))
                self.assertEqual(graph.support("notation", "active"), "available")
                self.assertEqual(graph.support("consumer", "active"), expected)

    def test_application_failures_are_not_repaired_by_explanatory_context(self):
        for case, expected in (("open", "conditional"), ("defect", "unavailable"),
                               ("unregistered", "conditional"), ("missing_group", "conditional"),
                               ("wrong_scope", "unavailable")):
            with self.subTest(case=case):
                graph = self.graph()
                app = graph.live("application_details", "notation_use").body
                if case in ("open", "defect"):
                    graph.status["uses", "notation_use", "application"] = case
                elif case == "unregistered":
                    app["state"] = "draft"
                elif case == "missing_group":
                    app["group_id"] = "absent"
                else:
                    graph.scope("other")
                    app["scope_id"] = "other"
                self.assertEqual(graph.closure.value(("use", "notation_use")), expected)
                if case != "missing_group":
                    self.assertEqual(graph.support("consumer"), expected)

    def test_real_co_premises_and_consumer_judgments_remain_required(self):
        for case, expected in (("real_premise", "conditional"), ("active_premise", "available"),
                               ("derivation", "conditional"), ("composition", "unavailable")):
            with self.subTest(case=case):
                graph = self.graph(scope="active")
                graph.scope("active")
                if case in ("real_premise", "active_premise"):
                    graph.item("condition", kind="assumption")
                    graph.use("condition_use", "condition", "g_consumer", scope="active")
                    if case == "active_premise":
                        graph.live("scopes", "active").body["assumptions"] = [R("items", "condition")]
                elif case == "derivation":
                    graph.status["groups", "g_consumer", "derivation"] = "open"
                else:
                    graph.status["arguments", "a_consumer", "composition"] = "defect"
                self.assertEqual(graph.support("consumer", "active"), expected)

    def test_only_actual_definition_items_on_definition_uses_supply_context(self):
        for case in ("dependency", "proof_argument", "assumption", "theorem", "part"):
            with self.subTest(case=case):
                graph = self.graph()
                use = graph.live("uses", "notation_use").body
                if case in ("dependency", "proof_argument"):
                    use["type"] = case
                elif case in ("assumption", "theorem"):
                    graph.live("items", "notation").body["kind"] = case
                else:
                    graph.put("parts", "notation_part", item_id="notation", scope_id=None)
                    graph.exact.add(("parts", "notation_part"))
                    use["from"] = R("parts", "notation_part")
                    ordinary_kind = graph.kind_of
                    graph.kind_of = lambda ref: "definition" if ref["collection"] == "parts" else ordinary_kind(ref)
                self.assertEqual(graph.support("consumer"), "conditional")


class PublicDefinitionContextTests(TempCase):
    def test_completed_application_uses_saved_definition_without_extra_work_or_writes(self):
        fixture = self.fixture()
        source = fixture.source_root / "paper.tex"
        source.write_text(source.read_text(encoding="utf-8").replace(
            r"\end{document}", "Let $b_n$ denote $a_n$.\n" + r"\end{document}"), encoding="utf-8")
        apply = fixture.apply

        def current_protocol(db, edits, *targets, **kwargs):
            edits = [dict(row, body=dict(row["body"], protocol_version=PROTOCOL_VERSION))
                     if row["collection"] in ("audits", "checks") else row for row in edits]
            edits = [dict(row, body=dict(row["body"], extent="whole_unit"))
                     if row["collection"] == "checks" and row["body"]["kind"] == "composition" else row
                     for row in edits]
            return apply(db, edits, **kwargs)

        fixture.apply = current_protocol
        fixture.audit(independent_required=False)
        with fixture.open() as db:
            packet = fixture.packet(db)
            sources.anchor_sources(db, request={"contract_version": 3, "request_id": fixture.request_id(),
                "packet_id": packet["packet_id"], "anchors": [{"id": "anc_notation", "expected_version": None,
                    "source_id": fixture.source_id, "locator": locator(start=17, end=17)}]})
            create_record(db, {"key": "notation", "kind": "definition", "label": "Notation",
                "statement": "Let $b_n$ denote $a_n$.", "statement_anchors": ["anc_notation"],
                "source_matched": True, "source_note": "The passage introduces notation only."})
            use = dict(db.head("uses", "use_lem_thm").body, **{
                "from": R("items", "itm_notation"), "type": "definition",
                "group_id": "grp_thm",
                "reason": "Read the sequence notation in the theorem's proof.",
                "needed_form": {"form": "verbatim", "text": "Let $b_n$ denote $a_n$."}})
            fixture.apply(db, [edit("create", "uses", "use_notation", use)])
            packet = fixture.packet(db, mode="primary")
            review.compare(db, batch=fixture.batch([edit("create", "observations", "obs_exact_notation", {
                "target": R("target_specs", "tgt_notation"), "result": "matched", "reviewer": "primary-1",
                "note": "The exact notation is source matched.", "evidence_refs": ["anc_notation"],
                "context_kind": "exact_target"})], packet["packet_id"]))
        fixture.primary()
        with fixture.open() as db:
            fixture.apply(db, [fixture.check_edit("chk_app_notation", R("uses", "use_notation"), "application")],
                          *fixture.ITEMS, mode="primary")
        with fixture.open(write=False) as db:
            revision = db.max_revision()
            scientific = db.records_at(revision)
            derivation, result = assessment.derive_full(db, audit_id=fixture.audit_id)
            rendered, _ = projection.project(db, audit_id=fixture.audit_id)
            _, repeated = assessment.derive_full(db, audit_id=fixture.audit_id)
            self.assertEqual(db.max_revision(), revision)
            self.assertEqual(db.records_at(db.max_revision()), scientific)
        self.assertEqual(result["problems"], [])
        self.assertTrue(result["progress"]["process_complete"])
        self.assertEqual(result["support"]["items:itm_thm"], "available")
        self.assertEqual(derivation.support(R("items", "itm_notation")), "conditional")
        self.assertEqual(derivation.use_support(derivation.snap.live("uses", "use_notation")), "available")
        self.assertEqual(result["support"], repeated["support"])
        self.assertEqual(result["obligations"], repeated["obligations"])
        self.assertEqual(result["judgments"], repeated["judgments"])
        self.assertEqual(len(rendered["connections"]), 2)
        self.assertEqual(result["judgments"]["checks:chk_app_notation"]["freshness"], "current")


if __name__ == "__main__":
    unittest.main()
