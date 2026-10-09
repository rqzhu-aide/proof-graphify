"""Blank captured text cannot certify source fidelity or a complete proof boundary."""
from copy import deepcopy
from unittest.mock import patch

from support import R, TempCase, edit, locator
from paper_core import acceptance, assessment, export_import, packets, review, sources
from paper_core.canonical import digest
from paper_core.errors import InvalidRequest


class EmptyEvidenceTests(TempCase):
    TARGETS = (("items", "itm_lem"), ("parts", "prt_lem"),
               ("uses", "use_lem_thm"), ("target_specs", "tgt_lem"))

    def evidence_fixture(self, name):
        fx = self.fixture(name).audit()
        (fx.source_root / "evidence.txt").write_text("\n \t \nA supporting source passage.\n", encoding="utf-8")
        with fx.open() as db:
            captured = sources.capture_sources(db, files=["evidence.txt"])
            source_id = captured["sources"][0]["id"]
            packet = fx.packet(db)
            sources.anchor_sources(db, request={
                "contract_version": 4, "request_id": fx.request_id(), "packet_id": packet["packet_id"],
                "anchors": [{"id": identity, "expected_version": None, "source_id": source_id,
                             "locator": locator(start=line, end=line)}
                            for identity, line in (("anc_empty", 1), ("anc_whitespace", 2), ("anc_good", 3))]})
            fx.apply(db, [edit("create", "parts", "prt_lem", {
                "item_id": "itm_lem", "label": "Lemma part", "origin": "source", "scope_id": None,
                "statement": {"form": "verbatim", "text": "A selected part of the lemma."},
                "passages": [{"role": "statement", "anchor_id": "anc_lem"}]})])
        return fx

    def set_evidence(self, fx, db, collection, identity, anchors):
        row = db.head(collection, identity)
        body = deepcopy(row.body)
        if collection in ("items", "parts"):
            body["passages"] = [{"role": "statement", "anchor_id": anchor} for anchor in anchors]
        else:
            body["evidence_refs"] = list(anchors)
            if collection == "target_specs":
                body["statement_ref"] = fx.pin(db, "items", "itm_lem")
        fx.apply(db, [edit("replace", collection, identity, body, row.version)], *fx.ITEMS, mode="primary")

    @staticmethod
    def observation(identity, target, anchors, result="matched"):
        body = {"target": R(*target), "result": result, "reviewer": "source-reader",
                "note": "Compared the saved content with the cited source evidence.", "evidence_refs": list(anchors)}
        if target[0] == "target_specs":
            body["context_kind"] = "exact_target"
        return edit("create", "observations", identity, body)

    def compare(self, fx, db, edits):
        part_targets = [entry["body"]["target"] for entry in edits if entry["body"]["target"]["collection"] == "parts"]
        packet = packets.get_packet(db, targets=[*fx.ITEM_REFS, *part_targets], mode="primary")
        return review.compare(db, batch=fx.batch(edits, packet["packet_id"]))

    @staticmethod
    def import_history(fx, db, edits):
        # The real import acceptance path preserves judgments made by older
        # versions. Derived assessment must still assess their evidence today.
        return acceptance.accept(db, request_id=fx.request_id(), request_digest=digest(edits),
                                 packet_id=None, edits=edits, command="import")

    def boundary_review(self, fx, db, identity, anchors):
        source_ids = sorted({db.head("anchors", anchor).body["source_id"] for anchor in anchors})
        return edit("create", "source_reviews", identity, {
            "source_refs": [fx.pin(db, "sources", source_id) for source_id in source_ids],
            "anchor_refs": [fx.pin(db, "anchors", anchor) for anchor in anchors],
            "purpose": "proof_boundary", "decision": "accepted", "reviewer": "source-reader",
            "rationale": "These captured passages contain the written proof boundary."})

    @staticmethod
    def fidelity(result, target):
        return next(row for row in result["obligations"]
                    if row["kind"] == "source_fidelity" and row["target"] == R(*target))

    def test_blank_statement_use_and_exact_target_matches_are_rejected_atomically(self):
        for target in self.TARGETS:
            for anchor in ("anc_empty", "anc_whitespace"):
                with self.subTest(target=target, anchor=anchor):
                    fx = self.evidence_fixture(target[0] + anchor)
                    with fx.open() as db:
                        self.set_evidence(fx, db, *target, [anchor])
                        before = export_import.export_snapshot(db, history=True)
                        with self.assertRaises(InvalidRequest):
                            self.compare(fx, db, [
                                self.observation("obs_valid", ("items", "itm_thm"), ["anc_thm"]),
                                self.observation("obs_blank", target, [anchor])])
                        self.assertEqual(export_import.export_snapshot(db, history=True), before)
                        self.compare(fx, db, [self.observation("obs_unresolved", target, [anchor], "needs_attention")])
                        self.assertEqual(db.head("observations", "obs_unresolved").body["result"], "needs_attention")

    def test_blank_review_and_complete_boundary_are_rejected_atomically(self):
        fx = self.evidence_fixture("boundary-guard")
        with fx.open() as db:
            entry = self.boundary_review(fx, db, "srv_blank", ["anc_whitespace"])
            packet = fx.packet(db)
            before = export_import.export_snapshot(db, history=True)
            with self.assertRaises(InvalidRequest):
                sources.review_sources(db, batch=fx.batch([entry], packet["packet_id"]))
            self.assertEqual(export_import.export_snapshot(db, history=True), before)

            self.import_history(fx, db, [entry])
            boundary = db.head("proof_boundaries", "bnd_lem")
            replacement = edit("replace", "proof_boundaries", boundary.id, dict(boundary.body,
                anchor_refs=[fx.pin(db, "anchors", "anc_whitespace")],
                source_review_ref=fx.pin(db, "source_reviews", "srv_blank")), boundary.version)
            before = export_import.export_snapshot(db, history=True)
            with self.assertRaises(InvalidRequest):
                fx.apply(db, [replacement], *fx.ITEMS, mode="primary")
            self.assertEqual(export_import.export_snapshot(db, history=True), before)

    def test_nonempty_secondary_text_and_pdf_without_text_allow_source_matches(self):
        from pypdf import PdfWriter

        for evidence in ("anc_good", "anc_pdf"):
            with self.subTest(evidence=evidence):
                fx = self.evidence_fixture(evidence)
                with fx.open() as db:
                    if evidence == "anc_pdf":
                        # Scanned pages may have no text layer; the recorded
                        # visual comparison must remain available in that case.
                        writer = PdfWriter()
                        writer.add_blank_page(width=200, height=200)
                        with (fx.source_root / "page.pdf").open("wb") as stream:
                            writer.write(stream)
                        captured = sources.capture_sources(db, files=["page.pdf"])
                        packet = fx.packet(db)
                        sources.anchor_sources(db, request={"contract_version": 4, "request_id": fx.request_id(),
                            "packet_id": packet["packet_id"], "anchors": [{"id": "anc_pdf", "expected_version": None,
                                "source_id": captured["sources"][0]["id"], "locator": locator(page=1)}]})
                        self.assertEqual(db.head("anchors", "anc_pdf").body["excerpt"], "")
                    for target in self.TARGETS:
                        self.set_evidence(fx, db, *target, ["anc_empty", evidence])
                        identity = "obs_" + target[0]
                        self.compare(fx, db, [self.observation(identity, target, ["anc_empty", evidence])])
                        self.assertEqual(db.head("observations", identity).body["result"], "matched")

    def test_imported_blank_matches_remain_readable_without_fidelity_credit_and_can_be_repaired(self):
        fx = self.evidence_fixture("historical-fidelity")
        targets = (("items", "itm_lem"), ("target_specs", "tgt_lem"))
        with fx.open() as db:
            for target in targets:
                self.set_evidence(fx, db, *target, ["anc_whitespace"])
            self.import_history(fx, db, [self.observation("old_" + target[0], target, ["anc_whitespace"])
                                        for target in targets])
            imported_revision = db.max_revision()
            packet = fx.packet(db, *fx.ITEMS, mode="primary")
            self.assertTrue(any(row["ref"]["id"] == "itm_lem" for row in packet["records"]))
            exported = export_import.export_snapshot(db, history=True)
            self.assertEqual(sum(row["collection"] == "observations" for row in exported["history"]), 2)
            spec = db.head("target_specs", "tgt_lem")
            with self.assertRaises(InvalidRequest):
                fx.apply(db, [edit("replace", "target_specs", spec.id, dict(spec.body,
                    fidelity_ref=fx.pin(db, "observations", "old_target_specs")), spec.version)],
                    *fx.ITEMS, mode="primary")
            self.assertEqual(export_import.export_snapshot(db, history=True), exported)
            result = assessment.derive_assessment(db, audit_id=fx.audit_id)
            for target in targets:
                fidelity = self.fidelity(result, target)
                self.assertNotEqual(fidelity["outcome"], "supported")
                self.assertFalse(fidelity["satisfied"])
            self.assertFalse(result["progress"]["process_complete"])

            for target in targets:
                self.set_evidence(fx, db, *target, ["anc_good"])
                self.compare(fx, db, [self.observation("repaired_" + target[0], target, ["anc_good"])])
            repaired = assessment.derive_assessment(db, audit_id=fx.audit_id)
            for target in targets:
                self.assertEqual(self.fidelity(repaired, target)["outcome"], "supported")
                self.assertTrue(self.fidelity(repaired, target)["satisfied"])
                self.assertEqual(db.head("observations", "old_" + target[0]).body["result"], "matched")
            historical = assessment.derive_assessment(db, audit_id=fx.audit_id, revision=imported_revision)
            self.assertFalse(self.fidelity(historical, targets[0])["satisfied"])

    def test_exact_target_can_reuse_valid_statement_evidence_but_not_a_blank_statement_match(self):
        for blank in (False, True):
            with self.subTest(blank=blank):
                fx = self.evidence_fixture("pinned-statement-" + str(blank))
                with fx.open() as db:
                    anchor = "anc_empty" if blank else "anc_lem"
                    if blank:
                        self.set_evidence(fx, db, "items", "itm_lem", [anchor])
                    observation = self.observation("obs_statement", ("items", "itm_lem"), [anchor])
                    if blank:
                        self.import_history(fx, db, [observation])
                    else:
                        self.compare(fx, db, [observation])
                    spec = db.head("target_specs", "tgt_lem")
                    replacement = edit("replace", "target_specs", spec.id, dict(spec.body,
                        statement_ref=fx.pin(db, "items", "itm_lem"), evidence_refs=[],
                        fidelity_ref=fx.pin(db, "observations", "obs_statement")), spec.version)
                    before = export_import.export_snapshot(db, history=True)
                    if blank:
                        with self.assertRaises(InvalidRequest):
                            fx.apply(db, [replacement], *fx.ITEMS, mode="primary")
                        self.assertEqual(export_import.export_snapshot(db, history=True), before)
                    else:
                        fx.apply(db, [replacement], *fx.ITEMS, mode="primary")
                        result = assessment.derive_assessment(db, audit_id=fx.audit_id)
                        fidelity = self.fidelity(result, ("target_specs", "tgt_lem"))
                        self.assertEqual(fidelity["outcome"], "supported")
                        self.assertTrue(fidelity["satisfied"])

    def test_imported_blank_boundary_is_readable_but_does_not_certify_completeness(self):
        fx = self.evidence_fixture("historical-boundary")
        with fx.open() as db:
            item, argument, boundary = (db.head(collection, identity) for collection, identity in
                (("items", "itm_lem"), ("arguments", "arg_lem"), ("proof_boundaries", "bnd_lem")))
            self.import_history(fx, db, [self.boundary_review(fx, db, "srv_blank", ["anc_empty"])])
            legacy_edits = [
                edit("replace", "items", item.id, dict(item.body, passages=[
                    {"role": "statement", "anchor_id": "anc_lem"}, {"role": "proof", "anchor_id": "anc_empty"}]), item.version),
                edit("replace", "arguments", argument.id, dict(argument.body, evidence_refs=["anc_empty"]), argument.version),
                edit("replace", "proof_boundaries", boundary.id, dict(boundary.body,
                    anchor_refs=[fx.pin(db, "anchors", "anc_empty")],
                    source_review_ref=fx.pin(db, "source_reviews", "srv_blank")), boundary.version)]
            # Import preserves created historical reviews; simulate an existing
            # pre-fix boundary through the normal edit API with only this new
            # evidence guard disabled. Assessment below uses the real guard.
            with patch("paper_core.validation.has_evidence", return_value=True):
                fx.apply(db, legacy_edits, *fx.ITEMS, mode="primary")
            exported = export_import.export_snapshot(db, history=True)
            self.assertTrue(exported["history"])
            self.assertEqual(db.head("proof_boundaries", "bnd_lem").body["state"], "complete")
            result = assessment.derive_assessment(db, audit_id=fx.audit_id)
            self.assertTrue(any("proof boundary for arg_lem" in problem for problem in result["problems"]), result["problems"])
            self.assertFalse(result["progress"]["process_complete"])

            current_item, current_arg, current_boundary = (db.head(collection, identity) for collection, identity in
                (("items", "itm_lem"), ("arguments", "arg_lem"), ("proof_boundaries", "bnd_lem")))
            fx.apply(db, [
                edit("replace", "items", item.id, item.body, current_item.version),
                edit("replace", "arguments", argument.id, argument.body, current_arg.version),
                edit("replace", "proof_boundaries", boundary.id, boundary.body, current_boundary.version)],
                *fx.ITEMS, mode="primary")
            repaired = assessment.derive_assessment(db, audit_id=fx.audit_id)
            self.assertFalse(any("proof boundary for arg_lem" in problem for problem in repaired["problems"]), repaired["problems"])
