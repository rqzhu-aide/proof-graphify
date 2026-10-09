"""Exact reader semantics, lazy canonical bodies, and visible-state integrity."""
import copy
import json
import re
import shutil
import subprocess

from support import CORE, R, TempCase, edit
from paper_core import projection, publish


class SQLProjectionTests(TempCase):
    def test_exact_extensions_and_separate_availability_reach_the_reader(self):
        fixture = self.fixture().primary()
        with fixture.open() as db:
            result = projection.build_projection(db, audit_id=fixture.audit_id)
        identities = [(r["ref"]["collection"], r["ref"]["id"], r["ref"]["version"]) for r in result["records"]]
        self.assertEqual(len(identities), len(set(identities)))
        self.assertIn(("target_specs", "tgt_lem", 1), identities)
        self.assertIn(("application_details", "use_lem_thm", 1), identities)
        self.assertIn(("proof_boundaries", "bnd_lem", 1), identities)
        for node in result["nodes"]:
            self.assertEqual(node["assessment"]["availability"], "available")
            self.assertEqual(node["assessment"]["local_label"], "supported")
        self.assertFalse(result["summary"]["progress"]["process_complete"])

    def test_summary_refinement_links_exact_application_without_extra_proof_credit(self):
        fixture = self.fixture().primary()
        with fixture.open() as db:
            summary = dict(db.head("uses", "use_lem_thm").body, reason="The lemma supplies the convergence bound.")
            fixture.apply(db, [edit("create", "uses", "use_summary", summary),
                               edit("create", "connection_refinements", "ref_summary", {
                                   "summary_use_id": "use_summary", "argument_id": "arg_thm",
                                   "use_ids": ["use_lem_thm"], "state": "registered", "note": "This is the exact use."})], *fixture.ITEMS)
            result = projection.build_projection(db, audit_id=fixture.audit_id)
        self.assertFalse(any(o["target"] == R("uses", "use_summary") for o in result["obligations"]))
        connection = result["connections"][0]
        self.assertEqual(connection["summary_use_ids"], ["use_summary"])
        self.assertEqual([app["use_id"] for app in connection["applications"]], ["use_lem_thm"])
        refs = result["details"][connection["detail_key"]]["record_refs"]
        self.assertIn({"collection": "connection_refinements", "id": "ref_summary", "version": 1}, refs)

    def test_needed_form_math_is_rendered_from_application_extension(self):
        result = {"records": [{"ref": {"collection": "application_details", "id": "use_math", "version": 1},
                                "body": {"needed_form": {"form": "normalized", "text": r"$x^2 \ge 0$"}}}]}
        fragment = publish.display_fragments(result)["application_details:use_math:1"]["needed_form_html"]
        self.assertIn("<math", fragment)

    def test_parallel_applications_keep_opposite_outcomes_visible(self):
        fixture = self.fixture().primary()
        with fixture.open() as db:
            use = dict(db.head("uses", "use_lem_thm").body,
                       reason="A second instantiation under the recorded setup", regime="second application")
            fixture.apply(db, [edit("create", "uses", "use_opposite", use),
                edit("create", "application_details", "use_opposite", {
                    "use_id": "use_opposite", "group_id": "grp_thm", "scope_id": None,
                    "needed_form": db.head("items", "itm_lem").body["statement"],
                    "substitutions": [], "state": "registered"})], *fixture.ITEMS)
            fixture.apply(db, [fixture.check_edit("chk_opposite", R("uses", "use_opposite"), "application", outcome="refuted"),
                               fixture.check_edit("chk_original", R("uses", "use_lem_thm"), "application",
                                                  supersedes=fixture.pin(db, "checks", "chk_app"))],
                          *fixture.ITEMS, mode="primary")
            result = projection.build_projection(db, audit_id=fixture.audit_id)
        applications = {a["use_id"]: a for a in result["connections"][0]["applications"]}
        self.assertEqual(applications["use_lem_thm"]["assessment"]["state"], "green")
        self.assertEqual(applications["use_opposite"]["assessment"]["state"], "red")
        self.assertEqual(applications["use_opposite"]["scope_id"], "scp_plain")

        # A structural return use makes the graph cyclic. Any changed premise
        # availability remains the assessment reducer's decision.
        with fixture.open() as db:
            back = dict(db.head("uses", "use_lem_thm").body,
                        reason="Recorded return dependency", **{"from": R("items", "itm_thm"),
                                                                  "to": R("items", "itm_lem")})
            fixture.apply(db, [edit("create", "uses", "use_return", back)], *fixture.ITEMS)
            cyclic = projection.build_projection(db, audit_id=fixture.audit_id)
        self.assertEqual(cyclic["layout"]["mode"], "cyclic")
        self.assertEqual([(edge["from"], edge["to"]) for edge in cyclic["connections"]],
                         [("itm_lem", "itm_thm"), ("itm_thm", "itm_lem")])
        cyclic_apps = {app["use_id"]: app for app in cyclic["connections"][0]["applications"]}
        self.assertEqual(cyclic_apps["use_lem_thm"]["assessment"]["local_state"], "green")
        self.assertEqual(cyclic_apps["use_opposite"]["assessment"]["local_state"], "red")
        self.assertEqual(cyclic_apps["use_opposite"]["assessment"]["state"], "red")
        self.assertEqual(cyclic["connections"][0]["primary_use_ids"], result["connections"][0]["primary_use_ids"])
        page = self.render(fixture, cyclic)
        acceptance = publish.mechanical_acceptance(page, cyclic)
        self.assertEqual(acceptance["status"], "pass", acceptance)
        self.assertEqual(acceptance["connections"], 2)
        self.assertEqual(acceptance["layout_mode"], "cyclic")
        self.assertIn(b"Layout does not establish mathematical validity or circularity", page)
        for edge in cyclic["connections"]:
            identity = f'data-edge-id="{edge["id"]}"'.encode()
            self.assertEqual(page.count(identity), 1)
        self.assertIn(b'data-application-id="use_lem_thm"', page)
        self.assertIn(b'data-application-id="use_opposite"', page)

    def render(self, fixture, dataset):
        if not shutil.which("node"):
            self.skipTest("user-wide Node is unavailable")
        with fixture.open() as db:
            envelope = publish.render_input(db, dataset, release=False, source_identity="test")
        source = self.path("render-input.json")
        output = self.path("reader.html")
        source.write_text(json.dumps(envelope), encoding="utf-8")
        completed = subprocess.run([shutil.which("node"), str(CORE / "renderer" / "render_projection.mjs"),
                                    str(source), str(output)], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        receipt = json.loads(completed.stdout)
        self.assertEqual(receipt["representation"]["status"], "pass", receipt)
        self.assertEqual(receipt["geometry"]["status"], "pass", receipt)
        return output.read_bytes()

    def test_canonical_record_body_is_not_repeated_for_added_detail_references(self):
        fixture = self.fixture().primary()
        with fixture.open() as db:
            dataset = projection.build_projection(db, audit_id=fixture.audit_id)
        record = next(r for r in dataset["records"] if r["ref"]["id"] == "chk_app")
        marker = "ONE_CANONICAL_ARGUMENT_" + "mathematics " * 3000
        record["body"]["reasoning"] = marker
        baseline = self.render(fixture, dataset)
        for index in range(20):
            dataset["details"][f"additional:{index}"] = {"record_refs": [copy.deepcopy(record["ref"])],
                "sections": [{"key": "applications", "kind": "applications", "title": "Applications",
                              "record_refs": [copy.deepcopy(record["ref"])], "obligation_ids": [], "note": None}]}
        expanded = self.render(fixture, dataset)
        self.assertEqual(expanded.count(b"ONE_CANONICAL_ARGUMENT_"), baseline.count(b"ONE_CANONICAL_ARGUMENT_"))
        self.assertEqual(expanded.count(b'data-record-template="checks:chk_app:1"'), 1)
        self.assertLess(len(expanded) - len(baseline), 40000)
        self.assertIn(b"hydrateDetail(article)", expanded)

    def test_public_acceptance_detects_visible_corruption_with_metadata_unchanged(self):
        fixture = self.fixture().primary()
        with fixture.open() as db:
            dataset = projection.build_projection(db, audit_id=fixture.audit_id)
        page = self.render(fixture, dataset)
        self.assertEqual(publish.mechanical_acceptance(page, dataset)["status"], "pass")
        corruptions = {
            "color": page.replace(b'class="proof-node k-lemma s-green"', b'class="proof-node k-lemma s-red"', 1),
            "glyph": page.replace('font-weight="700">✓'.encode(), 'font-weight="700">✕'.encode(), 1),
            "label": page.replace(b'class="proof-assessment-label">supported', b'class="proof-assessment-label">refuted', 1),
            "scope": page.replace(b'data-proof-scope-mode>focused', b'data-proof-scope-mode>full', 1),
        }
        for kind, changed in corruptions.items():
            with self.subTest(kind=kind):
                self.assertNotEqual(page, changed)
                self.assertEqual(publish.mechanical_acceptance(changed, dataset)["status"], "fail")
