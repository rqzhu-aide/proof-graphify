"""Audit regressions: hidden proof steps, Archify integration and source-safe publication."""
from __future__ import annotations

import copy
import shutil
import subprocess

from support import CORE, R, TempCase, edit
from paper_core import projection, publish
from paper_core.assessment import derive_assessment
from paper_core.errors import InvalidRequest


class HiddenProofTests(TempCase):
    def hidden_paper(self):
        fixture = self.fixture()
        fixture.structure()
        with fixture.open() as db:
            hidden = copy.deepcopy(db.head("items", "itm_thm").body)
            hidden.update(kind="intermediate_result", label="Hidden bound", caption="Hidden bound",
                          owner_id="itm_thm")
            use = copy.deepcopy(db.head("uses", "use_lem_thm").body)
            use.update(to=R("items", "itm_hidden"), group_id="grp_hidden",
                       needed_form=db.head("items", "itm_lem").body["statement"], substitutions=[])
            internal = copy.deepcopy(use)
            internal.update({"from": R("items", "itm_hidden"), "to": R("items", "itm_thm"), "group_id": "grp_thm",
                             "needed_form": hidden["statement"]})
            fixture.apply(db, [edit("create", "items", "itm_hidden", hidden),
                fixture.argument_edit("arg_hidden", "itm_hidden", "grp_hidden", "anc_thm_proof"),
                fixture.group_edit("grp_hidden", "arg_hidden", "itm_hidden", "anc_thm_proof"),
                edit("replace", "uses", "use_lem_thm", use, 1),
                edit("create", "uses", "use_hidden_thm", internal)], *fixture.ITEMS)
        fixture.primary()
        return fixture

    def test_hidden_final_group_gap_changes_edge_and_stays_in_intermediate_reader(self):
        fixture = self.hidden_paper()
        with fixture.open() as db:
            fixture.apply(db, [fixture.check_edit("chk_hidden_gap", R("groups", "grp_hidden"), "derivation",
                outcome="gap", evidence=["anc_thm_proof"])], *fixture.ITEMS, mode="primary")
            result = projection.build_projection(db, audit_id="aud_1")
        edge = result["connections"][0]
        self.assertEqual({"itm_lem", "itm_thm"}, {node["id"] for node in result["nodes"]})
        self.assertEqual("red", edge["assessment"]["state"])
        self.assertIn(R("checks", "chk_hidden_gap"), edge["support_refs"])
        sections = {section["kind"]: section for section in result["details"][edge["detail_key"]]["sections"]}
        self.assertIn("grp_hidden", [ref["id"] for ref in sections["derivations"]["record_refs"]])
        self.assertIn("chk_hidden_gap", [ref["id"] for ref in sections["derivations"]["record_refs"]])
        self.assertIn("use_hidden_thm", [ref["id"] for ref in sections["derivations"]["record_refs"]])
        self.assertNotIn("grp_hidden", [ref["id"] for ref in sections["composition"]["record_refs"]])

    def test_missing_or_failed_hidden_composition_is_an_edge_obligation(self):
        fixture = self.hidden_paper()
        with fixture.open() as db:
            fixture.apply(db, [fixture.check_edit("chk_hidden_der", R("groups", "grp_hidden"), "derivation"),
                fixture.check_edit("chk_hidden_app", R("uses", "use_hidden_thm"), "application")],
                *fixture.ITEMS, mode="primary")
            missing = projection.build_projection(db, audit_id="aud_1")
            edge = missing["connections"][0]
            hidden_obligation = next(o for o in missing["obligations"] if o["target"] == R("arguments", "arg_hidden") and o["kind"] == "composition" and o["role"] == "primary")
            self.assertIn(hidden_obligation["id"], edge["obligation_ids"])
            self.assertNotEqual("green", edge["assessment"]["state"])
            major_obligation = next(o for o in missing["obligations"] if o["target"] == R("arguments", "arg_thm") and o["kind"] == "composition" and o["role"] == "primary")
            self.assertNotIn(major_obligation["id"], edge["obligation_ids"])
            fixture.apply(db, [fixture.check_edit("chk_hidden_comp", R("arguments", "arg_hidden"), "composition",
                outcome="gap", evidence=["anc_thm_proof"])], *fixture.ITEMS, mode="primary")
            failed = projection.build_projection(db, audit_id="aud_1")
            self.assertEqual("red", failed["connections"][0]["assessment"]["state"])
            self.assertIn(R("checks", "chk_hidden_comp"), failed["connections"][0]["support_refs"])

    def test_summary_includes_the_actual_incomplete_coverage_reason(self):
        fixture = self.fixture()
        fixture.audit()
        with fixture.open() as db:
            result = projection.build_projection(db, audit_id="aud_1")
            assessment = derive_assessment(db, audit_id="aud_1")
        self.assertEqual(assessment["problems"], result["summary"]["limitations"])
        self.assertTrue(any("coverage" in note.lower() for note in result["summary"]["limitations"]))


class DestinationTests(TempCase):
    def test_source_database_and_hardlink_alias_are_refused_without_writes(self):
        fixture = self.fixture()
        fixture.primary()
        manuscript = fixture.source_root / "paper.tex"
        alias = self.work / "source-alias.html"
        alias.hardlink_to(manuscript)
        original = manuscript.read_bytes()
        with fixture.open() as db:
            result = projection.build_projection(db, audit_id="aud_1")
            for destination in (manuscript, manuscript.parent / ".." / manuscript.parent.name / manuscript.name,
                                fixture.path, alias):
                with self.subTest(destination=destination):
                    with self.assertRaisesRegex(InvalidRequest, "collides with the database or a registered source"):
                        publish.publish_report(db, projection=result, output=destination)
                    self.assertEqual([], db.publications())
                    self.assertEqual(original, manuscript.read_bytes())
                    self.assertEqual(original, alias.read_bytes())
                    self.assertIsNotNone(db.head("items", "itm_thm"))

    def test_regular_report_can_be_replaced_and_limits_are_actually_visible(self):
        if not shutil.which("node"):
            self.skipTest("Node is unavailable")
        fixture = self.fixture()
        fixture.audit()
        output = self.work / "report.html"
        output.write_text("old report", encoding="utf-8")
        with fixture.open() as db:
            result = projection.build_projection(db, audit_id="aud_1")
            receipt = publish.publish_report(db, projection=result, output=output)
        self.assertEqual("published", receipt["state"])
        page = output.read_bytes()
        self.assertIn(b"data-proof-limitation", page)
        altered = page.replace(b"data-proof-limitation", b"data-other-limitation")
        self.assertIn("listed completion limitations differ from summary.limitations",
                      publish.mechanical_acceptance(altered, result)["failures"])


class ArchifyBridgeTests(TempCase):
    def test_native_shell_and_canonical_reader_interaction_contract(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node is unavailable")
        proc = subprocess.run([node, str(CORE / "renderer" / "interaction_test.mjs")],
                              capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(0, proc.returncode, proc.stdout + proc.stderr)
