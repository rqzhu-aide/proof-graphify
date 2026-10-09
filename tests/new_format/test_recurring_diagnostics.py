"""Targeted recovery and one-snapshot facts, without changing scientific gates."""
import copy
import json
import re
import shutil
import subprocess
from unittest.mock import patch

from support import CORE, Fixture, R, TempCase, edit
from test_sql_support import Graph
from paper_core import assessment, projection, publish, queries, sources, work


class RecoveryDiagnosticsTests(TempCase):
    def task(self, result, target, kind):
        return next(row for row in result["tasks"] if row["target"] == target
                    and row["kind"] == kind and row["role"] == "primary")

    def test_changed_span_names_affected_composition_and_preserved_local_check(self):
        fixture = self.fixture().primary()
        with fixture.open() as db:
            before = db.max_revision()
            coverage = db.head("coverage", "cov_lem")
            fixture.apply(db, [edit("replace", "coverage", coverage.id,
                dict(coverage.body, end_offset=coverage.body["end_offset"] - 1), coverage.version)], mode="primary")
            result = work.derive_work(db, audit_id=fixture.audit_id)
            old = work.derive_work(db, audit_id=fixture.audit_id, revision=before)
        task = self.task(result, R("arguments", "arg_lem"), "composition")
        recovery = task["recovery"]
        self.assertTrue(any(row["label"] == "proof coverage for Lemma 1" and "end_offset" in row["fields"]
                            for row in recovery["changes"]))
        self.assertEqual(recovery["preserved_local_count"], 1)
        self.assertEqual(recovery["preserved_local_sample"][0]["ref"]["id"], "chk_der_lem")
        self.assertEqual(self.task(result, R("groups", "grp_lem"), "derivation")["state"], "satisfied")
        self.assertNotIn("recovery", self.task(old, R("arguments", "arg_lem"), "composition"))

    def test_repeated_draft_advisory_is_reviewer_specific_and_new_reasoning_clears_it(self):
        fixture = self.fixture().audit(independent_required=False)
        with fixture.open() as db:
            def save(identity, reviewer="primary-1", reasoning="Need the missing supplier statement"):
                row = fixture.check_edit(identity, R("groups", "grp_lem"), "derivation",
                                         state="draft", outcome=None, reviewer=reviewer)
                row["body"].update(reasoning=reasoning, next_action="Acquire its exact source statement.")
                fixture.apply(db, [row], *fixture.ITEMS, mode="primary")
            save("chk_wait_a")
            save("chk_wait_other", reviewer="another-reviewer")
            view = work.derive_work(db, audit_id=fixture.audit_id)
            self.assertFalse(any(a["code"] == "repeated_unchanged_draft" for a in view["coordinator_actions"]))
            save("chk_wait_b")
            view = work.derive_work(db, audit_id=fixture.audit_id)
            advisory = next(a for a in view["coordinator_actions"] if a["code"] == "repeated_unchanged_draft")
            self.assertFalse(advisory["required"])
            self.assertFalse(view["progress"]["process_complete"])
            save("chk_progress", reasoning="Checked the bounded case; the uniform regime still needs its source.")
            view = work.derive_work(db, audit_id=fixture.audit_id)
            self.assertFalse(any(a["code"] == "repeated_unchanged_draft" for a in view["coordinator_actions"]))

    def test_support_explanation_identifies_private_scope_without_changing_support(self):
        graph = Graph()
        graph.scope("private", conditions=["x > 0"])
        graph.item("supplier", scope="private")
        graph.route("supplier", "supplier", scope="private")
        graph.item("consumer")
        graph.route("consumer", "consumer")
        graph.use("application", "supplier", "g_consumer")
        before = graph.closure.value(("use", "application"))
        explanation = graph.closure.explain(("use", "application"))
        self.assertEqual(before, "unavailable")
        self.assertEqual(explanation["code"], "scope_unavailable")
        self.assertEqual(explanation["blocking_scope_id"], "private")
        self.assertEqual(explanation["target"], R("items", "supplier"))
        self.assertEqual(graph.closure.value(("use", "application")), before)

    def test_founded_supplier_needs_no_blocking_explanation(self):
        graph = Graph()
        for identity in ("supplier", "consumer"):
            graph.item(identity)
            graph.route(identity, identity)
        graph.use("application", "supplier", "g_consumer")
        self.assertIsNone(graph.closure.explain(("use", "application")))


class FactualReportingTests(TempCase):
    def groups(self, factual):
        rows = factual["work"]["obligation_groups"]
        self.assertIsInstance(rows, list)
        self.assertEqual(sum(row["required"] for row in rows), factual["work"]["required_obligations"])
        self.assertEqual(sum(row["completed"] for row in rows), factual["work"]["completed_current_obligations"])
        for row in rows:
            self.assertEqual(row["required"], row["completed"] + row["unfinished"])
        self.assertEqual(len(rows), len({(row["role"], row["kind"]) for row in rows}))
        self.assertEqual(rows, sorted(rows, key=lambda row: (assessment.ROLES.index(row["role"]), row["kind"])))
        return {(row["role"], row["kind"]): row for row in rows}

    def test_required_global_work_without_check_records_is_visible(self):
        fixture = self.fixture().primary()
        with fixture.open() as db:
            baseline = queries.status(db, audit_id=fixture.audit_id)["factual_summary"]
            self.assertFalse(any(kind in ("global_consistency", "adversarial", "method_interface")
                                 for role, kind in self.groups(baseline)))
            audit = db.head("audits", fixture.audit_id)
            fixture.apply(db, [edit("replace", "audits", audit.id, dict(audit.body,
                global_tasks=[dict(task, applicability="required", reason="Required by this audit")
                              for task in audit.body["global_tasks"]]), audit.version)], mode="primary")
            current = queries.status(db, audit_id=fixture.audit_id)["factual_summary"]
        rows = self.groups(current)
        for kind in ("global_consistency", "adversarial", "method_interface"):
            self.assertEqual(rows[("primary", kind)],
                {"role": "primary", "kind": kind, "required": 1, "completed": 0, "unfinished": 1})

    def test_primary_completion_is_separate_from_review_and_reconciliation(self):
        fixture = self.fixture().primary()
        with fixture.open() as db:
            factual = queries.status(db, audit_id=fixture.audit_id)["factual_summary"]
        rows = self.groups(factual)
        self.assertTrue(all(row["unfinished"] == 0 for (role, kind), row in rows.items() if role == "primary"))
        self.assertGreater(rows[("independent", "composition")]["unfinished"], 0)
        self.assertGreater(rows[("coordinator", "reconciliation")]["unfinished"], 0)
        self.assertFalse(factual["process_complete"])

    def test_completed_rows_do_not_bypass_missing_coverage(self):
        with patch.object(Fixture, "coverage_edits", return_value=[]):
            fixture = self.fixture().audit(independent_required=False).primary()
        with fixture.open() as db:
            factual = queries.status(db, audit_id=fixture.audit_id)["factual_summary"]
        self.assertTrue(all(row["unfinished"] == 0 for row in self.groups(factual).values()))
        self.assertFalse(factual["process_complete"])

    def test_unavailable_assessment_or_absent_audit_has_no_completion_counts(self):
        fixture = self.fixture().structure()
        with fixture.open() as db:
            self.assertIsNone(queries.status(db)["factual_summary"]["work"]["obligation_groups"])
        fixture.primary()
        with fixture.open() as db:
            derivation, result = assessment.derive_full(db, audit_id=fixture.audit_id)
            unavailable = projection.factual_summary(derivation, dict(result, analysis_complete=False))
            self.assertIsNone(unavailable["work"]["obligation_groups"])

    def test_exact_exclusions_and_named_source_limits_survive_the_summary(self):
        fixture = self.fixture().primary()
        with fixture.open() as db:
            audit = db.head("audits", fixture.audit_id)
            exclusion = {"target": R("items", "itm_lem"), "source_anchor_ids": [],
                         "reason": "The requested audit excludes the supplier proof.",
                         "consequence": "The theorem depends on this unexamined supplier."}
            fixture.apply(db, [edit("replace", "audits", audit.id,
                dict(audit.body, targets=[R("items", "itm_thm")], exclusions=[exclusion]), audit.version)], mode="primary")
            packet = fixture.packet(db, *fixture.ITEMS, mode="primary")
            sources.review_sources(db, batch=fixture.batch([edit("create", "source_issues", "sis_unreadable", {
                    "source_id": fixture.source_id, "anchor_id": "anc_thm_proof", "category": "locator_limit",
                    "description": "A consequential formula could not be compared with its original page.",
                    "lifecycle": "open", "resolution": None, "reviewer": "primary-1"})], packet["packet_id"]))
            factual = queries.status(db, audit_id=fixture.audit_id)["factual_summary"]
        self.assertEqual(factual["scope"]["requested"], [{"ref": R("items", "itm_thm"), "label": "Theorem 1"}])
        self.assertEqual(factual["scope"]["exclusions"], [{**exclusion, "label": "Lemma 1"}])
        self.assertEqual(factual["source_limits"][0]["source_path"], "paper.tex")
        self.assertIn("consequential formula", factual["source_limits"][0]["description"])
        self.assertFalse(factual["process_complete"])

    def test_status_and_html_use_the_same_snapshot_facts_after_a_change(self):
        fixture = self.fixture().complete()
        with fixture.open() as db:
            completed_revision = db.max_revision()
            old = queries.status(db, audit_id=fixture.audit_id)["factual_summary"]
            coverage = db.head("coverage", "cov_lem")
            fixture.apply(db, [edit("replace", "coverage", coverage.id,
                dict(coverage.body, end_offset=coverage.body["end_offset"] - 1), coverage.version)], mode="primary")
            current = queries.status(db, audit_id=fixture.audit_id)
            dataset = projection.build_projection(db, audit_id=fixture.audit_id)
            past = queries.status(db, audit_id=fixture.audit_id, revision=completed_revision)["factual_summary"]
        self.assertEqual(old, past)
        self.assertEqual(current["factual_summary"], dataset["summary"]["factual"])
        self.assertTrue(old["process_complete"])
        self.assertFalse(current["factual_summary"]["process_complete"])
        self.assertGreater(current["factual_summary"]["work"]["checks"]["needs_review"], 0)
        self.assertTrue(all(row["unfinished"] == 0 for row in self.groups(old).values()))
        self.assertGreater(sum(row["unfinished"] for row in self.groups(current["factual_summary"]).values()), 0)

    def test_completed_negative_examination_is_not_rewritten_as_incomplete(self):
        for outcome in ("gap", "inconclusive"):
            with self.subTest(outcome=outcome):
                fixture = self.fixture(outcome).audit(independent_required=False).primary()
                with fixture.open() as db:
                    fixture.apply(db, [fixture.check_edit("chk_new", R("groups", "grp_lem"), "derivation",
                        outcome=outcome, supersedes=fixture.pin(db, "checks", "chk_der_lem"))], *fixture.ITEMS, mode="primary")
                    factual = queries.status(db, audit_id=fixture.audit_id)["factual_summary"]
                self.assertTrue(factual["process_complete"])
                self.assertEqual(factual["work"]["current_primary_outcomes"][outcome], 1)
                self.assertEqual(factual["work"]["checks"]["superseded"], 1)
                self.assertTrue(all(row["unfinished"] == 0 for row in self.groups(factual).values()))
                if outcome == "gap":
                    self.assertGreater(factual["statement_support"]["counts"]["unavailable"], 0)

    def test_renderer_keeps_facts_visible_and_detects_tampering(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("user-wide Node is unavailable")
        fixture = self.fixture().audit()
        with fixture.open() as db:
            scope = db.head("scopes", "scp_plain")
            fixture.apply(db, [
                fixture.item_edit("itm_setup", "assumption", "Declared setup", "anc_lem", "anc_lem_proof"),
                edit("replace", "scopes", scope.id,
                     dict(scope.body, assumptions=[R("items", "itm_setup")]), scope.version)])
        fixture.primary()
        with fixture.open() as db:
            dataset = projection.build_projection(db, audit_id=fixture.audit_id)
            envelope = publish.render_input(db, dataset, release=False, source_identity="diagnostic-test")
        premise = next(row for row in dataset["summary"]["factual"]["statement_support"]["unresolved"]
                       if row["ref"]["id"] == "itm_setup")
        self.assertEqual((premise["kind"], premise["availability"], premise["scope_id"]),
                         ("assumption", "conditional", None))
        source, output = self.path("input.json"), self.path("report.html")
        source.write_text(json.dumps(envelope), encoding="utf-8")
        result = subprocess.run([node, str(CORE / "renderer" / "render_projection.mjs"), str(source), str(output)],
                                capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        page = output.read_bytes()
        self.assertIn(b"Current scientific status", page)
        self.assertIn(b"Independent review: pending", page)
        self.assertIn(b"Declared setup: conditional (declared assumption; scope-dependent premise)", page)
        self.assertEqual(publish.mechanical_acceptance(page, dataset)["status"], "pass")
        changed = page.replace(b"Independent review: pending", b"Independent review: complete", 1)
        self.assertEqual(publish.mechanical_acceptance(changed, dataset)["status"], "fail")
        changed = page.replace(b"Declared setup: conditional", b"Declared setup: available", 1)
        self.assertEqual(publish.mechanical_acceptance(changed, dataset)["status"], "fail")
        cell = re.search(rb'<span data-proof-fact="obligations\.0\.unfinished">\d+</span>', page)
        self.assertIsNotNone(cell)
        changed = page.replace(cell[0], b'<span data-proof-fact="obligations.0.unfinished">999</span>', 1)
        self.assertEqual(publish.mechanical_acceptance(changed, dataset)["status"], "fail")
        self.assertEqual(publish.mechanical_acceptance(page.replace(cell[0], b"", 1), dataset)["status"], "fail")
        self.assertIn(b"Completed examinations do not mean verified statements", page)
        for field in ("role", "kind", "required", "completed", "unfinished", "caption"):
            with self.subTest(completion_label=field):
                fact = "obligations.caption" if field == "caption" else f"obligations.header.{field}"
                label = re.search(rb'<span data-proof-fact="' + re.escape(fact.encode()) + rb'">[^<]+</span>', page)
                self.assertIsNotNone(label)
                changed = re.sub(rb'>[^<]+</span>', b'>Verified</span>', label[0])
                self.assertEqual(publish.mechanical_acceptance(page.replace(label[0], changed, 1), dataset)["status"], "fail")
                self.assertEqual(publish.mechanical_acceptance(page.replace(label[0], b"", 1), dataset)["status"], "fail")
        for row, tag in ((b"header", b"th"), (b"0", b"td")):
            with self.subTest(reordered_completion_cells=row):
                cells = re.findall(rb'<' + tag + rb'(?: scope="col")?><span data-proof-fact="obligations\.' + row
                                   + rb'\.(?:completed|unfinished)">[^<]+</span></' + tag + rb'>', page)
                self.assertEqual(len(cells), 2)
                self.assertIn(cells[0] + cells[1], page)
                changed = page.replace(cells[0] + cells[1], cells[1] + cells[0], 1)
                self.assertEqual(publish.mechanical_acceptance(changed, dataset)["status"], "fail")

    def test_older_and_unavailable_breakdowns_render_without_invented_counts(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("user-wide Node is unavailable")
        fixture = self.fixture().primary()
        with fixture.open() as db:
            original = projection.build_projection(db, audit_id=fixture.audit_id)
            for variant in ("older", "unavailable"):
                dataset = copy.deepcopy(original)
                if variant == "older":
                    del dataset["summary"]["factual"]["work"]["obligation_groups"]
                else:
                    dataset["summary"]["factual"]["work"]["obligation_groups"] = None
                envelope = publish.render_input(db, dataset, release=False, source_identity="compatibility-test")
                source, output = self.path(variant + ".json"), self.path(variant + ".html")
                source.write_text(json.dumps(envelope), encoding="utf-8")
                rendered = subprocess.run([node, str(CORE / "renderer" / "render_projection.mjs"), str(source), str(output)],
                                          capture_output=True, text=True, encoding="utf-8")
                self.assertEqual(rendered.returncode, 0, rendered.stderr)
                page = output.read_bytes()
                self.assertNotIn(b'data-proof-fact="obligations.', page)
                self.assertIn(b"breakdown unavailable", page)
                self.assertEqual(publish.mechanical_acceptance(page, dataset)["status"], "pass")
