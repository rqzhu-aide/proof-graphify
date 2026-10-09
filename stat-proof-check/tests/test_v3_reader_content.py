"""The production frozen publisher preserves scientific content and rejects display loss."""
import html
import json
import re
import unittest
from unittest import mock

from support import R, TempCase, edit, node_available, run_cli
from paper_core import finalization, publish
from paper_core.errors import PublicationError


@unittest.skipUnless(node_available(), "existing global Node.js is unavailable")
class ReaderContentTests(TempCase):
    CONDITION = r"Assume $0 < \eta < 1$ and the sequence is monotone; retain the literal 0xdeadbeef."
    STATEMENT = r"For every $n \ge 1$, $a_n \le 1$ under the stated monotonicity condition."
    REASONING = "Boundedness alone does not imply convergence; the monotonicity condition is essential."

    def frozen(self, name="science", *, extent="whole_unit"):
        fixture = self.fixture(name).structure()
        with fixture.open() as db:
            item = db.head("items", "itm_lem")
            scope = db.head("scopes", "scp_plain")
            application = db.head("application_details", "use_lem_thm")
            fixture.apply(db, [
                edit("replace", "items", item.id, dict(item.body,
                    label=r"Lemma 1 $$a_n$$",
                    statement={"form": "verbatim", "text": self.STATEMENT}, scope_id=scope.id), item.version),
                edit("replace", "scopes", scope.id, dict(scope.body,
                    conditions=[self.CONDITION], binders=[{"symbol": "$n$", "domain": r"$\mathbb{N}$",
                                                          "quantifier": "forall"}]), scope.version),
                edit("replace", "application_details", application.id, dict(application.body,
                    needed_form={"form": "verbatim", "text": self.STATEMENT},
                    substitutions=[{"symbol": "$n$", "value": "$m+1$"}]), application.version),
            ], *fixture.ITEMS, mode="primary")
        fixture.audit(independent_required=False)
        with fixture.open() as db:
            specs = [db.head("target_specs", "tgt_" + name) for name in ("lem", "thm")]
            fixture.apply(db, [edit("replace", "target_specs", spec.id,
                dict(spec.body, scope_id="scp_plain"), spec.version) for spec in specs],
                *fixture.ITEMS, mode="primary")
        fixture.primary()
        with fixture.open() as db:
            check = db.head("checks", "chk_comp_thm")
            fixture.apply(db, [edit("create", "checks", "chk_reader_thm", dict(check.body,
                outcome="gap", reasoning=self.REASONING, conditions=[self.CONDITION], extent=extent,
                supersedes=check.pinned,
                omissions="The final limiting inference is unexamined." if extent == "partial" else ""),
                )], *fixture.ITEMS, mode="primary")
            fixture.apply(db, [edit("create", "findings", "fnd_reader_gap", {
                "audit_id": fixture.audit_id, "target": R("items", "itm_thm"), "category": "proof_gap",
                "lifecycle": "open", "description": self.REASONING, "evidence_refs": ["anc_thm_proof"],
                "check_refs": [fixture.pin(db, "checks", "chk_reader_thm")], "affected_uses": ["use_lem_thm"],
                "impact_reason": "The absent monotonicity premise prevents the claimed inference to convergence.",
                "resolution": None})], *fixture.ITEMS, mode="primary")
        bundle, output = self.path(name + "-frozen"), self.path(name + ".html")
        with fixture.open(write=False) as db:
            finalization.finalize_audit(db, audit_id=fixture.audit_id, output=bundle)
        snapshot, _ = finalization.load_finalization(bundle)
        result = publish.publish_frozen(bundle, output=output)
        return fixture, bundle, output, snapshot, result

    def scan(self, page):
        scan = publish._Scan()
        scan.feed(page)
        scan.close()
        return scan

    def alter(self, page, ref, path, replacement):
        source = re.escape(html.escape(ref, quote=True))
        field = re.escape(html.escape(json.dumps(path, separators=(",", ":")), quote=True))
        pattern = (r'(<(?P<tag>span|div)\b[^>]*data-scientific-ref="' + source +
                   r'"[^>]*data-scientific-path="' + field + r'"[^>]*>)(.*?)(</(?P=tag)>)')
        changed, count = re.subn(pattern, lambda match: match[1] + replacement(match[3]) + match[4], page, count=1,
                                flags=re.S)
        self.assertEqual(1, count, "the control must alter a rendered scientific field")
        self.assertNotEqual(page, changed)
        return changed

    def test_frozen_delivery_keeps_science_without_tracking_interface(self):
        fixture, bundle, output, snapshot, result = self.frozen()
        page = output.read_text(encoding="utf-8")
        scan = self.scan(page)
        self.assertEqual("pass", result["receipt"]["renderer"]["python_acceptance"]["status"])
        records = [row for row in snapshot["projection"]["records"] if row["ref"]["id"] == "chk_reader_thm"]
        current = max(records, key=lambda row: row["ref"]["version"])
        self.assertEqual("gap", current["body"]["outcome"])
        self.assertEqual(self.CONDITION, current["body"]["conditions"][0])
        scientific = [element for element in scan.elements if "data-scientific-path" in element["attrs"]]
        self.assertTrue(any(element["attrs"]["data-scientific-path"] == '["substitutions",0,"value"]'
                            and "".join(element["text"]) == "$m+1$" for element in scientific))
        self.assertTrue(any("0xdeadbeef" in "".join(element["text"]) and
                            "the sequence is monotone" in "".join(element["text"]) for element in scientific))
        self.assertTrue(any(element["tag"] == "annotation" and "a_n \\le 1" in "".join(element["text"])
                            for element in scan.elements))
        self.assertFalse(any("data-proof-count" in element["attrs"] for element in scan.elements))
        visible = " ".join("".join(element["text"]) for element in scan.elements
                           if "data-reader-report-state" in element["attrs"])
        self.assertIn("complete", visible.lower())
        self.assertNotIn("Required obligations", page)
        self.assertNotIn("Technical record index", page)
        self.assertNotIn("Remaining audit work", page)
        frozen_bytes = {path.name: path.read_bytes() for path in bundle.iterdir()}
        fixture.path.rename(fixture.path.with_suffix(".saved"))
        cli, _ = run_cli("stage3", "render", bundle, "--out", self.path("retry.html"))
        self.assertEqual(result["snapshot_sha256"], cli["snapshot_sha256"])
        self.assertEqual(frozen_bytes, {path.name: path.read_bytes() for path in bundle.iterdir()})
        older = publish.frozen_render_input(snapshot, snapshot_sha256=result["snapshot_sha256"])
        older["projection"] = json.loads(json.dumps(snapshot["projection"]))
        older["projection"].update(projection_version=1, worklist=None)
        workdir = self.path("older-render")
        workdir.mkdir()
        _, receipt = publish.render_payload(older, workdir=workdir)
        self.assertEqual("pass", receipt["python_acceptance"]["status"])

    def test_removed_consequential_condition_fails_independent_acceptance(self):
        _, _, output, snapshot, _ = self.frozen()
        projection = snapshot["projection"]
        check = max((row for row in projection["records"] if row["ref"]["id"] == "chk_reader_thm"),
                    key=lambda row: row["ref"]["version"])
        ref = "checks:chk_reader_thm:" + str(check["ref"]["version"])
        altered = self.alter(output.read_text(encoding="utf-8"), ref, ["conditions", 0],
                             lambda value: value.replace(" and the sequence is monotone", ""))
        accepted = publish.mechanical_acceptance(altered.encode("utf-8"), projection)
        self.assertEqual("fail", accepted["status"])
        self.assertTrue(any("scientific evidence differs" in failure for failure in accepted["failures"]))

    def test_changed_actual_outcome_fails_independent_acceptance(self):
        _, _, output, snapshot, _ = self.frozen()
        projection = snapshot["projection"]
        check = max((row for row in projection["records"] if row["ref"]["id"] == "chk_reader_thm"),
                    key=lambda row: row["ref"]["version"])
        altered = self.alter(output.read_text(encoding="utf-8"), "checks:chk_reader_thm:" +
                             str(check["ref"]["version"]), ["outcome"], lambda _: "supported")
        accepted = publish.mechanical_acceptance(altered.encode("utf-8"), projection)
        self.assertEqual("fail", accepted["status"])
        self.assertTrue(any("scientific evidence differs" in failure for failure in accepted["failures"]))

    def test_changed_math_structure_fails_with_original_tex_annotation_intact(self):
        _, _, output, snapshot, _ = self.frozen()
        projection = snapshot["projection"]
        item = next(row for row in projection["records"] if row["ref"]["collection"] == "items" and
                    row["ref"]["id"] == "itm_lem")
        altered = self.alter(output.read_text(encoding="utf-8"), "items:itm_lem:" +
                             str(item["ref"]["version"]), ["statement", "text"],
                             lambda value: value.replace("<msub>", "<msup>").replace("</msub>", "</msup>"))
        accepted = publish.mechanical_acceptance(altered.encode("utf-8"), projection)
        self.assertEqual("fail", accepted["status"])
        self.assertTrue(any("mathematics" in failure for failure in accepted["failures"]))

    def test_partial_saved_gap_keeps_review_limitation_visible(self):
        _, _, output, snapshot, _ = self.frozen(extent="partial")
        self.assertFalse(snapshot["process_complete"])
        scan = self.scan(output.read_text(encoding="utf-8"))
        report = next(element for element in scan.elements if "data-reader-report-state" in element["attrs"])
        self.assertIn("incomplete", "".join(report["text"]).lower())
        self.assertIn("Initial assessment: gap. Examination remains incomplete for the current material.",
                      "".join(report["text"]))
        self.assertTrue(any(element["attrs"].get("data-scientific-path") == '["omissions"]' and
                            "final limiting inference is unexamined" in "".join(element["text"])
                            for element in scan.elements))

    def test_acceptance_failure_preserves_prior_output_and_frozen_input(self):
        _, bundle, output, snapshot, _ = self.frozen()
        original_html, original_receipt = output.read_bytes(), output.with_name(output.name + ".receipt.json").read_bytes()
        frozen_bytes = {path.name: path.read_bytes() for path in bundle.iterdir()}
        original = publish.mechanical_acceptance

        def reject(page, projection, *, build=None):
            check = max((row for row in projection["records"] if row["ref"]["id"] == "chk_reader_thm"),
                        key=lambda row: row["ref"]["version"])
            altered = self.alter(page.decode("utf-8"), "checks:chk_reader_thm:" + str(check["ref"]["version"]),
                                 ["outcome"], lambda _: "supported")
            return original(altered.encode("utf-8"), projection, build=build)

        with mock.patch.object(publish, "mechanical_acceptance", side_effect=reject):
            with self.assertRaisesRegex(PublicationError, "mechanical acceptance failed"):
                publish.publish_frozen(bundle, output=output)
        self.assertEqual(original_html, output.read_bytes())
        self.assertEqual(original_receipt, output.with_name(output.name + ".receipt.json").read_bytes())
        self.assertEqual(frozen_bytes, {path.name: path.read_bytes() for path in bundle.iterdir()})


if __name__ == "__main__":
    unittest.main()
