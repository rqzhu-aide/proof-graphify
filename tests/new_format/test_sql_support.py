"""SQL-superset support semantics, independent of graph traversal order.

Small explicit judgments test the reducer, not mathematical checker accuracy.
Public-API tests below additionally exercise source-boundary completion.
"""
from collections import defaultdict
import unittest

from support import R, TempCase, edit
from paper_core.bindings import binding_changes, compute_bindings
from paper_core.assessment import Snapshot, _Derivation, derive_full
from paper_core.authoring import create_unit
from paper_core.storage import Record
from paper_core.support_semantics import SupportClosure


class Graph:
    """Snapshot protocol with authored exact targets and local judgments."""
    def __init__(self):
        self.records = {}
        self.status = {}
        self.findings_by_target = defaultdict(list)
        self.exact = set()
        self.local_basis = None
        self.snap = self
        self.closure = SupportClosure(self)

    def put(self, collection, ident, **body):
        record = Record(collection, ident, 1, 1, False, body)
        self.records[collection, ident] = record
        return record

    def item(self, ident, *, kind="theorem", scope=None, owner=None, exact=True):
        if exact:
            self.exact.add(("items", ident))
        return self.put("items", ident, kind=kind, scope_id=scope, owner_id=owner)

    def scope(self, ident, assumptions=(), *, parent=None, conditions=()):
        return self.put("scopes", ident, parent_id=parent, argument_id=None,
                        assumptions=[R("items", i) for i in assumptions], binders=[], conditions=list(conditions))

    def route(self, ident, target, *, scope=None, outcome="supported", kind="joint", cases=(), discharges=()):
        self.put("arguments", "a_" + ident, target=R("items", target), scope_id=scope,
                 final_group_id="g_" + ident, lifecycle="registered")
        self.group(ident, target, "a_" + ident, scope=scope, outcome=outcome,
                   kind=kind, cases=cases, discharges=discharges)
        self.status["arguments", "a_" + ident, "composition"] = "supported"
        return "g_" + ident

    def group(self, ident, target, argument, *, scope=None, outcome="supported", kind="joint", cases=(), discharges=()):
        self.put("groups", "g_" + ident, argument_id=argument, conclusion=R("items", target),
                 scope_id=scope, kind=kind, case_scope_ids=list(cases), discharges=list(discharges))
        self.status["groups", "g_" + ident, "derivation"] = outcome
        if kind == "cases":
            self.status["groups", "g_" + ident, "case_coverage"] = "supported"
        if discharges:
            self.status["groups", "g_" + ident, "scope_discharge"] = "supported"

    def use(self, ident, supplier, group, *, scope=None, outcome="supported"):
        target = self.live("groups", group).body["conclusion"]
        self.put("uses", ident, **{"from": R("items", supplier), "to": target})
        self.put("application_details", ident, use_id=ident, group_id=group, scope_id=scope, state="registered")
        self.status["uses", ident, "application"] = outcome

    def live(self, collection, ident):
        return self.records.get((collection, ident))

    def get(self, ref):
        return None if ref is None else self.live(ref["collection"], ref["id"])

    def exact_scope(self, ref):
        return self.get(ref).body.get("scope_id") if self.get(ref) else None

    def exact_target_current(self, ref):
        return (ref["collection"], ref["id"]) in self.exact

    def statement_refuted(self, ref):
        return any(f.body["category"] == "statement_refutation" and f.body["lifecycle"] == "open"
                   for f in self.findings_by_target.get(f"{ref['collection']}:{ref['id']}", ()))

    def kind_of(self, ref):
        record = self.get(ref)
        return record.body["kind"] if record else None

    def application(self, use):
        return self.live("application_details", use.id).body

    def scope_assumptions(self, scope_id):
        found, seen = {}, set()
        while scope_id is not None and scope_id not in seen:
            seen.add(scope_id)
            scope = self.live("scopes", scope_id)
            if scope is None:
                break
            found.update((f"{r['collection']}:{r['id']}", r) for r in scope.body["assumptions"])
            scope_id = scope.body["parent_id"]
        return found

    def groups_for_conclusion(self, ref):
        return [r for r in self.records.values() if r.collection == "groups" and r.body["conclusion"] == ref]

    def member_records(self, relation, ref):
        if relation == "arguments_for_target":
            return [r for r in self.records.values() if r.collection == "arguments" and r.body["target"] == ref]
        if relation == "uses_in_group":
            return [self.live("uses", r.id) for r in self.records.values() if r.collection == "application_details"
                    and r.body["group_id"] == ref["id"]]
        raise AssertionError(relation)

    def visit_relations(self, *args):
        pass

    def _obligation_supported(self, ref, kind):
        return self.status.get((ref["collection"], ref["id"], kind), "open")

    def support(self, ident, scope=None):
        return self.closure.value(self.closure.statement_key(R("items", ident), scope))


class FoundedSupportTests(unittest.TestCase):
    def named_hypothesis_graph(self):
        graph = Graph()
        for ident, kind in (("setup", "definition"), ("extra", "assumption")):
            graph.item(ident, kind=kind)
        graph.scope("supplier", ["setup"])
        graph.scope("consumer", ["setup", "extra"])
        for ident in ("supplier", "consumer"):
            graph.item(ident, scope=ident)
            graph.route(ident, ident, scope=ident)
        graph.use("borrow", "supplier", "g_consumer")
        return graph

    def test_named_hypotheses_allow_only_exact_active_inclusion(self):
        cases = ("identical", "subset", "inherited", "neutral_child", "missing_hypothesis",
                 "different_collection", "missing_scope", "missing_ancestor", "argument_id",
                 "binders", "conditions", "restricted_ancestor", "sibling_only", "wrong_application_scope")
        for case in cases:
            with self.subTest(case=case):
                graph = self.named_hypothesis_graph()
                if case == "identical":
                    graph.scope("consumer", ["setup"])
                elif case == "inherited":
                    graph.scope("parent", ["setup"])
                    graph.scope("consumer", ["extra"], parent="parent")
                elif case == "neutral_child":
                    graph.scope("parent", ["setup"])
                    graph.scope("supplier", parent="parent")
                elif case in ("missing_hypothesis", "sibling_only"):
                    graph.scope("consumer", ["extra"])
                    if case == "sibling_only":
                        graph.scope("sibling", ["setup"])
                elif case == "different_collection":
                    graph.records["scopes", "consumer"].body["assumptions"] = [R("parts", "setup")]
                elif case == "missing_scope":
                    del graph.records["scopes", "supplier"]
                elif case == "missing_ancestor":
                    graph.scope("supplier", ["setup"], parent="missing")
                elif case in ("argument_id", "binders", "conditions"):
                    graph.records["scopes", "supplier"].body[case] = {
                        "argument_id": "a_supplier", "binders": [{"symbol": "x", "domain": "real"}],
                        "conditions": ["x > 0"]}[case]
                elif case == "restricted_ancestor":
                    graph.scope("parent", conditions=["x > 0"])
                    graph.scope("supplier", ["setup"], parent="parent")
                elif case == "wrong_application_scope":
                    graph.scope("other", ["setup", "extra"])
                    graph.records["application_details", "borrow"].body["scope_id"] = "other"
                expected = "available" if case in ("identical", "subset", "inherited", "neutral_child") else "unavailable"
                self.assertEqual(graph.support("consumer", "consumer"), expected)

    def test_transport_does_not_supply_or_repair_supplier_proof(self):
        for case, expected in (("gap", "conditional"), ("defect", "unavailable"),
                               ("refuted", "unavailable"), ("stale_target", "conditional"),
                               ("consumer_only_premise", "conditional")):
            with self.subTest(case=case):
                graph = self.named_hypothesis_graph()
                if case in ("gap", "defect"):
                    graph.status["groups", "g_supplier", "derivation"] = "open" if case == "gap" else "defect"
                elif case == "refuted":
                    graph.findings_by_target["items:supplier"].append(graph.put(
                        "findings", "refutation", category="statement_refutation", lifecycle="open"))
                elif case == "stale_target":
                    graph.exact.remove(("items", "supplier"))
                elif case == "consumer_only_premise":
                    graph.item("needed")
                    graph.use("internal", "needed", "g_supplier")
                    graph.records["scopes", "consumer"].body["assumptions"].append(R("items", "needed"))
                self.assertTrue(graph.closure.admissible("supplier", "consumer"))
                self.assertEqual(graph.support("consumer", "consumer"), expected)
                if case == "consumer_only_premise":
                    self.assertEqual(graph.support("needed", "consumer"), "available")
                    self.assertEqual(graph.support("needed", "supplier"), "conditional")

    def test_imported_observations_use_append_order_at_equal_timestamp(self):
        matched = Record("observations", "obs_z", 1, 5, False,
                         {"created_at": "2026-09-21T12:00:00Z", "context_data": {"observation_order": 1}})
        concern = Record("observations", "obs_a", 1, 5, False,
                         {"created_at": "2026-09-21T12:00:00Z", "context_data": {"observation_order": 2}})
        renewed = Record("observations", "obs_b", 1, 6, False, {})
        self.assertEqual(sorted([renewed, concern, matched], key=_Derivation._observation_order),
                         [matched, concern, renewed])

    def test_alternative_routes_are_disjunctive_and_joint_inputs_conjunctive(self):
        for alternative in ("defect", "open"):
            with self.subTest(alternative=alternative):
                graph = Graph()
                graph.item("target")
                graph.route("good", "target")
                graph.route("other", "target", outcome=alternative)
                self.assertEqual(graph.support("target"), "available")
        graph = Graph()
        for ident in ("left", "right", "target"):
            graph.item(ident)
        graph.route("left", "left")
        graph.route("target", "target")
        graph.use("u_left", "left", "g_target")
        graph.use("u_right", "right", "g_target")
        self.assertEqual(graph.support("target"), "conditional")

    def test_founded_and_unfounded_cycles_do_not_depend_on_requested_order(self):
        for foundation in (None, "left", "right"):
            for first in ("left", "right"):
                with self.subTest(foundation=foundation, first=first):
                    graph = Graph()
                    for ident in ("left", "right"):
                        graph.item(ident)
                        graph.route(ident, ident)
                    graph.use("u_left", "right", "g_left")
                    graph.use("u_right", "left", "g_right")
                    if foundation:
                        graph.route("foundation", foundation)
                    graph.support(first)
                    expected = "available" if foundation else "conditional"
                    self.assertEqual([graph.support(i) for i in ("left", "right")], [expected, expected])

    def test_unused_defective_step_does_not_poison_final_backward_closure(self):
        graph = Graph()
        graph.item("target")
        graph.item("unused", kind="equation", owner="target")
        graph.route("final", "target")
        graph.group("unused", "unused", "a_final", outcome="defect")
        self.assertEqual(graph.support("target"), "available")
        self.assertEqual(graph.support("unused"), "unavailable")

    def test_owned_intermediate_survives_owners_false_final_statement(self):
        graph = Graph()
        for ident, kind, owner in (("owner", "theorem", None), ("bound", "equation", "owner"),
                                   ("consumer", "theorem", None)):
            graph.item(ident, kind=kind, owner=owner)
        graph.route("owner", "owner", outcome="defect")
        graph.group("bound", "bound", "a_owner")
        graph.route("consumer", "consumer")
        graph.use("borrow", "bound", "g_consumer")
        self.assertEqual(graph.support("owner"), "unavailable")
        self.assertEqual(graph.support("bound"), "available")
        self.assertEqual(graph.support("consumer"), "available")

    def test_branch_availability_does_not_leak_to_sibling_or_global(self):
        graph = Graph()
        graph.item("hypothesis", kind="assumption")
        graph.scope("positive", ["hypothesis"])
        graph.scope("negative", conditions=["x < 0"])
        graph.item("identity", scope="positive")
        graph.route("identity", "identity", scope="positive")
        self.assertEqual(graph.support("identity", "positive"), "available")
        self.assertEqual(graph.support("identity", "negative"), "unavailable")
        self.assertEqual(graph.support("identity"), "unavailable")
        self.assertEqual(graph.support("hypothesis"), "conditional")
        self.assertEqual(graph.support("hypothesis", "positive"), "available")

    def test_cases_use_separate_contexts_and_require_coverage_and_discharge(self):
        for missing in (None, "scope_discharge", "case_coverage"):
            with self.subTest(missing=missing):
                graph = Graph()
                for branch in ("positive", "negative"):
                    graph.item(branch, kind="assumption")
                    graph.scope(branch, [branch])
                graph.item("target")
                graph.route("cases", "target", kind="cases", cases=("positive", "negative"),
                            discharges=("positive", "negative"))
                for branch in ("positive", "negative"):
                    graph.use("u_" + branch, branch, "g_cases", scope=branch)
                if missing:
                    graph.status["groups", "g_cases", missing] = "open"
                self.assertEqual(graph.support("target"), "conditional" if missing else "available")

    def test_false_supplier_blocks_establishment_but_not_local_implication(self):
        graph = Graph()
        graph.item("false")
        graph.item("consumer")
        graph.route("consumer", "consumer")
        graph.use("use", "false", "g_consumer")
        graph.findings_by_target["items:false"].append(
            graph.put("findings", "refutation", category="statement_refutation", lifecycle="open"))
        self.assertEqual(graph.closure.value(("use", "use")), "unavailable")
        self.assertEqual(graph.status["uses", "use", "application"], "supported")
        self.assertEqual(graph.support("consumer"), "unavailable")

    def test_synopsis_without_exact_target_has_no_mathematical_credit(self):
        graph = Graph()
        graph.item("target", exact=False)
        graph.route("target", "target")
        self.assertEqual(graph.support("target"), "conditional")


class PublicApplicationScopeTests(unittest.TestCase):
    def graph(self):
        graph = Graph()
        graph.local_basis = object()
        for ident in ("public_setup", "local_setup"):
            graph.item(ident, kind="assumption").body["origin"] = "source"
        graph.scope("supplier", ["public_setup"])
        graph.scope("consumer", ["local_setup"])
        for ident in ("supplier", "consumer"):
            graph.item(ident, scope=ident).body["origin"] = "source"
            graph.route(ident, ident, scope=ident)
        graph.use("borrow", "supplier", "g_consumer")
        graph.records["uses", "borrow"].body["type"] = "dependency"
        return graph

    def test_supported_application_uses_public_supplier_in_its_declared_scope(self):
        for kind in ("theorem", "lemma", "proposition", "corollary"):
            with self.subTest(kind=kind):
                graph = self.graph()
                graph.records["items", "supplier"].body["kind"] = kind
                graph.scope("public_parent", ["public_setup"])
                graph.scope("supplier", parent="public_parent")
                self.assertFalse(graph.closure.admissible("supplier", "consumer"))
                self.assertEqual(graph.support("supplier", "consumer"), "unavailable")
                self.assertEqual(graph.support("consumer", "consumer"), "available")
                self.assertEqual(graph.support("public_setup", "consumer"), "conditional")

    def test_only_supported_public_dependency_applications_receive_scope_bridge(self):
        cases = ("open_application", "defective_application", "stale_application", "noncoherent",
                 "proof_argument", "definition_use", "owned_supplier", "reconstructed_supplier",
                 "assumption_supplier", "external_supplier", "private_argument", "binder", "condition",
                 "private_ancestor", "missing_scope", "missing_parent", "cyclic_parent", "missing_premise",
                 "owned_premise", "scoped_premise", "exact_scoped_premise", "definition_premise",
                 "reconstructed_premise", "theorem_premise", "wrong_application_scope")
        for case in cases:
            with self.subTest(case=case):
                graph = self.graph()
                supplier = graph.records["items", "supplier"].body
                premise = graph.records["items", "public_setup"].body
                scope = graph.records["scopes", "supplier"].body
                if case in ("open_application", "defective_application", "stale_application"):
                    graph.status["uses", "borrow", "application"] = {
                        "open_application": "open", "defective_application": "defect", "stale_application": "stale"}[case]
                elif case == "noncoherent":
                    graph.local_basis = None
                elif case in ("proof_argument", "definition_use"):
                    graph.records["uses", "borrow"].body["type"] = "proof_argument" if case == "proof_argument" else "definition"
                elif case == "owned_supplier":
                    supplier["owner_id"] = "consumer"
                elif case == "reconstructed_supplier":
                    supplier["origin"] = "reconstruction"
                elif case in ("assumption_supplier", "external_supplier"):
                    supplier["kind"] = "assumption" if case == "assumption_supplier" else "external_result"
                elif case == "private_argument":
                    scope["argument_id"] = "a_supplier"
                elif case == "binder":
                    scope["binders"] = [{"symbol": "x", "domain": "real"}]
                elif case == "condition":
                    scope["conditions"] = ["x > 0"]
                elif case == "private_ancestor":
                    graph.scope("parent", conditions=["x > 0"])
                    scope["parent_id"] = "parent"
                elif case == "missing_scope":
                    del graph.records["scopes", "supplier"]
                elif case in ("missing_parent", "cyclic_parent"):
                    scope["parent_id"] = "missing" if case == "missing_parent" else "supplier"
                elif case == "missing_premise":
                    del graph.records["items", "public_setup"]
                elif case == "owned_premise":
                    premise["owner_id"] = "supplier"
                elif case == "scoped_premise":
                    premise["scope_id"] = "supplier"
                elif case == "exact_scoped_premise":
                    ordinary_exact_scope = graph.exact_scope
                    graph.exact_scope = lambda ref: "supplier" if ref == R("items", "public_setup") else ordinary_exact_scope(ref)
                elif case in ("definition_premise", "theorem_premise"):
                    premise["kind"] = "definition" if case == "definition_premise" else "theorem"
                elif case == "reconstructed_premise":
                    premise["origin"] = "reconstruction"
                elif case == "wrong_application_scope":
                    graph.scope("other", ["local_setup"])
                    graph.records["application_details", "borrow"].body["scope_id"] = "other"
                self.assertNotEqual(graph.support("consumer", "consumer"), "available")

    def test_application_cannot_supply_a_missing_or_defective_supplier_proof(self):
        for case in ("stale_source", "refuted", "defect", "unproved", "unfounded_cycle"):
            with self.subTest(case=case):
                graph = self.graph()
                if case == "stale_source":
                    graph.exact.remove(("items", "supplier"))
                elif case == "refuted":
                    graph.findings_by_target["items:supplier"].append(graph.put(
                        "findings", "refutation", category="statement_refutation", lifecycle="open"))
                elif case == "defect":
                    graph.status["arguments", "a_supplier", "composition"] = "defect"
                elif case == "unproved":
                    graph.records["arguments", "a_supplier"].body["lifecycle"] = "draft"
                else:
                    graph.use("back", "consumer", "g_supplier")
                    graph.records["uses", "back"].body["type"] = "dependency"
                self.assertEqual(graph.status["uses", "borrow", "application"], "supported")
                expected = "unavailable" if case in ("refuted", "defect") else "conditional"
                self.assertEqual(graph.support("consumer", "consumer"), expected)

    def test_explicit_active_supplier_hypothesis_keeps_ordinary_hypothetical_route(self):
        graph = self.graph()
        graph.records["scopes", "consumer"].body["assumptions"].append(R("items", "supplier"))
        graph.records["arguments", "a_supplier"].body["lifecycle"] = "draft"
        graph.records["scopes", "supplier"].body["conditions"] = ["private condition"]
        self.assertEqual(graph.support("consumer", "consumer"), "available")


class PublicSupportTests(TempCase):
    def test_current_coherent_public_application_and_prerequisite_edit(self):
        fixture = self.fixture().anchors()
        with fixture.open() as db:
            fixture.apply(db, [fixture.item_edit(ident, "assumption", ident, "anc_lem", "anc_lem_proof")
                               for ident in ("hyp_public", "hyp_local")])
            definition = dict(kind="lemma", statement="Under its named setup, x=x.",
                              statement_anchors=["anc_lem"], proof_anchors=["anc_lem_proof"],
                              proof_complete=True, source_matched=True,
                              source_note="Exact statement and complete written proof inspected.")
            create_unit(db, dict(definition, key="supplier", label="Supplier",
                                 assumptions=[R("items", "hyp_public")]))
            create_unit(db, dict(definition, key="consumer", label="Consumer",
                                 assumptions=[R("items", "hyp_local")], suppliers=[{
                                     "target": R("items", "itm_supplier"),
                                     "reason": "The local setup establishes the public theorem's hypotheses.",
                                     "needed_form": {"form": "verbatim", "text": "x=x"}}]))
            targets = [R("items", "itm_" + key) for key in ("supplier", "consumer")]
            fixture.apply(db, [edit("create", "audits", "aud_public", {
                "paper_id": fixture.paper_id, "mode": "focused", "targets": targets, "exclusions": [],
                "protocol_version": "coherent-proof-audit/1", "independent_required": False,
                "qualification_id": None, "report_path": "reports/public.html", "global_tasks": []})])
            checks = []
            for key in ("supplier", "consumer"):
                check = fixture.check_edit("chk_" + key, R("arguments", "arg_" + key), "composition",
                                           audit_id="aud_public", evidence=["anc_lem_proof"])
                check["body"].update(protocol_version="coherent-proof-audit/1", extent="whole_unit", omissions="")
                checks.append(check)
            fixture.apply(db, checks, "items:itm_supplier", "items:itm_consumer", mode="primary")
            revision = db.max_revision()
            before, result = derive_full(db, audit_id="aud_public")
            application = R("uses", "use_consumer_1")
            self.assertIsNotNone(before.local_basis)
            self.assertFalse(before.support_closure.admissible("scp_supplier", "scp_consumer"))
            self.assertEqual(before._obligation_supported(application, "application"), "supported")
            self.assertEqual(result["support"]["items:itm_consumer"], "available")
            self.assertEqual(len(db.records_at(revision, collection="checks")), 2)
            prerequisite = db.head("items", "hyp_public")
            fixture.apply(db, [edit("replace", "items", prerequisite.id, dict(prerequisite.body,
                statement={"form": "verbatim", "text": "A changed prerequisite statement"}), prerequisite.version)],
                "items:itm_supplier", "items:itm_consumer")
            after, changed = derive_full(db, audit_id="aud_public")
            historical, old = derive_full(db, revision=revision, audit_id="aud_public")
            self.assertNotEqual(after._obligation_supported(application, "application"), "supported")
            self.assertNotEqual(changed["support"]["items:itm_consumer"], "available")
            self.assertEqual(historical._obligation_supported(application, "application"), "supported")
            self.assertEqual(old["support"]["items:itm_consumer"], "available")

    def test_create_unit_siblings_share_named_definition_hypotheses(self):
        fixture = self.fixture().anchors()
        with fixture.open() as db:
            fixture.apply(db, [fixture.item_edit(ident, "definition", ident, "anc_lem", "anc_lem_proof")
                               for ident in ("hyp_setup", "hyp_extra")])
            definition = dict(kind="lemma", statement="Under the named setup, x=x.",
                              statement_anchors=["anc_lem"], proof_anchors=["anc_lem_proof"],
                              proof_complete=True, source_matched=True,
                              source_note="Exact claim and written proof inspected for fixture.")
            setup = R("items", "hyp_setup")
            create_unit(db, dict(definition, key="supplier", label="Supplier", assumptions=[setup]))
            for key, assumptions in (("identical", [setup]), ("subset", [setup, R("items", "hyp_extra")])):
                create_unit(db, dict(definition, key=key, label=key, assumptions=assumptions, suppliers=[{
                    "target": R("items", "itm_supplier"), "reason": "Use supplier under the named setup.",
                    "needed_form": {"form": "verbatim", "text": "x=x"}}]))
            derivation = _Derivation(Snapshot(db, db.max_revision()), None)
            for key in ("identical", "subset"):
                with self.subTest(consumer=key):
                    self.assertTrue(derivation.support_closure.admissible("scp_supplier", "scp_" + key))
                    self.assertEqual(derivation.support(R("items", "itm_supplier"), "scp_" + key), "conditional")
            scope = db.head("scopes", "scp_supplier")
            self.assertIsNone(scope.body["argument_id"])
            self.assertEqual(scope.body["assumptions"], [setup])

    def test_named_hypothesis_edit_stales_proof_binding_but_preserves_old_snapshot(self):
        fixture = self.fixture().anchors()
        with fixture.open() as db:
            setup = fixture.item_edit("hyp_setup", "definition", "Setup", "anc_lem", "anc_lem_proof")
            fixture.apply(db, [setup])
            create_unit(db, dict(key="supplier", label="Supplier", kind="lemma", statement="Under setup, x=x.",
                statement_anchors=["anc_lem"], proof_anchors=["anc_lem_proof"], proof_complete=True,
                source_matched=True, source_note="Exact claim and written proof inspected for fixture.",
                assumptions=[R("items", "hyp_setup")]))
            revision = db.max_revision()
            check = fixture.check_edit("chk_supplier", R("groups", "grp_supplier"), "derivation")["body"]
            binding = compute_bindings(Snapshot(db, revision), "checks", check)
            self.assertEqual(binding_changes(Snapshot(db, revision), binding), {"records": [], "relations": []})
            setup = db.head("items", "hyp_setup")
            fixture.apply(db, [edit("replace", "items", setup.id, dict(setup.body,
                statement={"form": "verbatim", "text": "A changed named mathematical hypothesis"}),
                setup.version)], "items:itm_supplier")
            current = binding_changes(Snapshot(db, db.max_revision()), binding)
            historical = binding_changes(Snapshot(db, revision), binding)
        self.assertTrue(any(row["ref"]["id"] == "hyp_setup" and row["facet"] == "statement"
                            for row in current["records"]))
        self.assertEqual(historical, {"records": [], "relations": []})

    def explicit_target_fixture(self):
        fixture = self.fixture().audit(independent_required=False)
        with fixture.open() as db:
            edits = []
            for name in ("lem", "thm"):
                spec = db.head("target_specs", f"tgt_{name}")
                statement = db.head("items", f"itm_{name}").body["statement"]
                edits.append(edit("replace", "target_specs", spec.id,
                                  dict(spec.body, statement_ref=None, statement=statement), spec.version))
            fixture.apply(db, edits, *fixture.ITEMS)
        return fixture.primary()

    def test_explicit_exact_statements_supply_checked_claim_coverage(self):
        fixture = self.explicit_target_fixture()
        with fixture.open() as db:
            binding = db.binding("checks", "chk_der_lem", 1)["bindings"]["records"]
            statement_refs = [entry["ref"]["collection"] for entry in binding if entry["facet"] == "statement"]
            self.assertIn("target_specs", statement_refs)
            self.assertNotIn("items", statement_refs)
            _, result = derive_full(db, audit_id=fixture.audit_id)
        self.assertEqual(result["problems"], [])
        self.assertTrue(result["progress"]["process_complete"])

    def test_changed_exact_statement_reopens_coverage_and_preserves_historical_coverage(self):
        fixture = self.explicit_target_fixture()
        with fixture.open() as db:
            revision = db.max_revision()
            spec = db.head("target_specs", "tgt_lem")
            fixture.apply(db, [edit("replace", "target_specs", spec.id,
                                   dict(spec.body, statement={"form": "verbatim", "text": "A different exact claim"}),
                                   spec.version)], *fixture.ITEMS)
            _, current = derive_full(db, audit_id=fixture.audit_id)
            _, historical = derive_full(db, revision=revision, audit_id=fixture.audit_id)
        self.assertNotEqual(current["judgments"]["checks:chk_der_lem"]["freshness"], "current")
        self.assertTrue(any("anchor anc_lem_proof: uncovered or unchecked" in problem
                            for problem in current["problems"]))
        self.assertEqual(historical["problems"], [])
        self.assertTrue(historical["progress"]["process_complete"])

    def test_exact_statement_check_cannot_cover_a_different_claim(self):
        fixture = self.explicit_target_fixture()
        with fixture.open() as db:
            coverage = db.head("coverage", "cov_lem")
            fixture.apply(db, [edit("replace", "coverage", coverage.id,
                                   dict(coverage.body, claim_refs=[R("items", "itm_thm")]), coverage.version)],
                          *fixture.ITEMS)
            derivation, result = derive_full(db, audit_id=fixture.audit_id)
        self.assertTrue(derivation.obligation_for(R("groups", "grp_lem"), "derivation")["satisfied"])
        self.assertEqual(result["judgments"]["checks:chk_der_lem"]["freshness"], "current")
        self.assertTrue(any("anchor anc_lem_proof: uncovered or unchecked" in problem
                            for problem in result["problems"]))

    def test_caption_edit_preserves_exact_target_but_statement_edit_does_not(self):
        fixture = self.fixture().complete()
        with fixture.open() as db:
            _, before = derive_full(db, audit_id=fixture.audit_id)
            item = db.head("items", "itm_lem")
            fixture.apply(db, [edit("replace", "items", item.id,
                                   dict(item.body, caption="A clearer navigation caption"), item.version)], *fixture.ITEMS)
            _, after = derive_full(db, audit_id=fixture.audit_id)
            self.assertEqual(after["support"], before["support"])
            self.assertEqual(after["assessments"], before["assessments"])
            self.assertTrue(after["progress"]["process_complete"])
            item = db.head("items", "itm_lem")
            fixture.apply(db, [edit("replace", "items", item.id,
                                   dict(item.body, statement={"form": "verbatim", "text": "A changed mathematical claim"}),
                                   item.version)], *fixture.ITEMS)
            _, changed = derive_full(db, audit_id=fixture.audit_id)
        self.assertNotEqual(changed["support"]["items:itm_lem"], "available")
        self.assertFalse(changed["progress"]["process_complete"])

    def test_triage_preserves_checks_without_issuing_correctness_or_completion(self):
        fixture = self.fixture().audit(mode="triage", independent_required=False).primary()
        with fixture.open() as db:
            _, result = derive_full(db, audit_id=fixture.audit_id)
        self.assertTrue(all(j["outcome"] == "supported" for j in result["judgments"].values()))
        self.assertFalse(result["progress"]["process_complete"])
        self.assertTrue(all(s == "conditional" for s in result["support"].values()))
        self.assertTrue(all(a["label"] == "triage" and a["state"] == "gray" for a in result["assessments"].values()))
        self.assertTrue(all(o["assessment"]["label"] == "triage" for o in result["obligations"]))

    def test_checked_excerpts_cannot_complete_audit_without_reviewed_boundary(self):
        fixture = self.fixture().complete()
        with fixture.open() as db:
            _, before = derive_full(db, audit_id=fixture.audit_id)
            self.assertTrue(before["progress"]["process_complete"])
            boundary = db.head("proof_boundaries", "bnd_lem")
            fixture.apply(db, [{"op": "retire", "collection": "proof_boundaries", "id": boundary.id,
                               "expected_version": boundary.version, "reason": "the continuation boundary is unresolved"}],
                          *fixture.ITEMS)
            _, after = derive_full(db, audit_id=fixture.audit_id)
        self.assertTrue(all(o["satisfied"] for o in after["obligations"] if o["kind"] == "derivation"))
        self.assertFalse(after["progress"]["process_complete"])
        self.assertTrue(any("proof boundary for arg_lem" in problem for problem in after["problems"]))

    def test_checked_prefix_cannot_cover_a_reviewed_full_proof_boundary(self):
        fixture = self.fixture().audit(independent_required=False).primary()
        with fixture.open() as db:
            _, before = derive_full(db, audit_id=fixture.audit_id)
            self.assertTrue(before["progress"]["process_complete"])
            coverage = db.head("coverage", "cov_lem")
            end = coverage.body["end_offset"] // 2
            composition = fixture.check_edit("chk_prefix_composition", R("arguments", "arg_lem"), "composition",
                                             supersedes=fixture.pin(db, "checks", "chk_comp_lem"))
            fixture.apply(db, [edit("replace", "coverage", coverage.id,
                                   dict(coverage.body, end_offset=end), coverage.version), composition],
                          *fixture.ITEMS, mode="primary")
            _, after = derive_full(db, audit_id=fixture.audit_id)
        self.assertTrue(all(o["satisfied"] for o in after["obligations"] if o["required"]))
        self.assertEqual(after["judgments"]["checks:chk_prefix_composition"]["freshness"], "current")
        self.assertFalse(after["progress"]["process_complete"])
        self.assertTrue(any(f"anchor anc_lem_proof: uncovered or unchecked spans [{end}," in problem
                            for problem in after["problems"]))

    def test_coverage_note_does_not_reopen_mathematics_or_boundary_review(self):
        fixture = self.fixture().complete()
        with fixture.open() as db:
            coverage = db.head("coverage", "cov_lem")
            fixture.apply(db, [edit("replace", "coverage", coverage.id,
                                   dict(coverage.body, note="bookkeeping clarification"), coverage.version)], *fixture.ITEMS)
            _, result = derive_full(db, audit_id=fixture.audit_id)
        self.assertTrue(result["progress"]["process_complete"])
        self.assertEqual(result["support"]["items:itm_thm"], "available")

    def test_unfinished_alternative_preserves_establishment_and_keeps_audit_open(self):
        fixture = self.fixture().complete()
        with fixture.open() as db:
            fixture.apply(db, [fixture.argument_edit("arg_alt", "itm_lem", "grp_alt", "anc_lem_proof"),
                               fixture.group_edit("grp_alt", "arg_alt", "itm_lem", "anc_lem_proof")], *fixture.ITEMS)
            _, result = derive_full(db, audit_id=fixture.audit_id)
        self.assertEqual(result["support"]["items:itm_lem"], "available")
        self.assertEqual(result["support"]["items:itm_thm"], "available")
        self.assertEqual(result["assessments"]["items:itm_lem"]["state"], "green")
        self.assertFalse(result["progress"]["process_complete"])

    def test_unrepresented_condition_cannot_narrow_the_exact_target(self):
        fixture = self.fixture().primary()
        with fixture.open() as db:
            check = fixture.check_edit("chk_conditional", R("groups", "grp_lem"), "derivation",
                                       supersedes=fixture.pin(db, "checks", "chk_der_lem"))
            check["body"]["conditions"] = ["x is bounded by a new constant"]
            fixture.apply(db, [check], *fixture.ITEMS, mode="primary")
            _, result = derive_full(db, audit_id=fixture.audit_id)
        self.assertEqual(result["judgments"]["checks:chk_conditional"]["outcome"], "supported")
        self.assertEqual(result["support"]["items:itm_lem"], "conditional")
        self.assertNotEqual(result["assessments"]["items:itm_lem"]["state"], "green")


if __name__ == "__main__":
    unittest.main()
