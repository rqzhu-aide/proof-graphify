"""A source-only judgment keeps the setup actually delivered to its reviewer."""
from unittest import mock

from support import R, TempCase, edit, locator
from test_review import entry, judgment, mapping_request, source_target, worker_response
from test_work_packets import intermediate_edits, selection, task
from paper_core import assessment, controller, packets, review, sources
from paper_core.canonical import canonical_bytes, digest
from paper_core.errors import ConflictError, InvalidRequest
from paper_core.bindings import binding_changes
from paper_core.validation import State


class NeutralFreshnessTests(TempCase):
    def setUp(self):
        super().setUp()
        self.fx = self.fixture().primary()
        self.db = self.fx.open()
        self.addCleanup(self.db.close)

    def prepare(self, target="itm_lem"):
        result = controller.prepare_work(self.db, audit_id="aud_1", mode="independent", focus=R("items", target))
        self.assertTrue(result["prepared"], result)
        return result

    def submit(self, prepared, name="lem"):
        worker = worker_response(prepared["packet_id"], [judgment(source_target(f"anc_{name}_proof", "The written argument"),
                                                               evidence=(f"anc_{name}_proof",))])
        envelope = {"contract_version": 4, "request_id": self.fx.request_id(), "packet_id": prepared["packet_id"],
            "rebase_packet_id": None, "reviewer": "checker-A", "qualification_id": "qua_r1",
            "exposure": "source_only", "exposure_note": "Fresh source-only reviewer."}
        return controller.submit_work(self.db, envelope_bytes=canonical_bytes(envelope), response_bytes=canonical_bytes(worker))

    def mapping(self, result, name="lem"):
        private = self.fx.packet(self.db, f"items:itm_{name}", mode="reconcile")
        return mapping_request(self.fx, private["packet_id"], result["response_id"], [entry(0, R("arguments", f"arg_{name}"))])

    def change_setup(self):
        scope = self.db.head("scopes", "scp_plain")
        self.fx.apply(self.db, [self.fx.item_edit("itm_setup", "assumption", "Previously uninspected setup", "anc_thm", "anc_thm_proof"),
            edit("replace", "scopes", scope.id, dict(scope.body, assumptions=[R("items", "itm_setup")]), scope.version)])

    def freshness(self, check):
        snapshot = assessment.Snapshot(self.db, self.db.max_revision())
        return assessment.judgment_freshness(snapshot, self.db.head("checks", check), superseded=False)

    def test_setup_change_between_prepare_and_submit_is_not_accepted(self):
        original = self.prepare()
        self.change_setup()
        result = self.submit(original)
        self.assertEqual("conflict", result["state"], result)
        self.assertNotIn("response_id", result, result)
        self.assertIn("setup", result["error"]["message"])

    def test_pending_response_cannot_be_mapped_against_changed_setup(self):
        original = self.prepare()
        result = self.submit(original)
        self.assertIn("response_id", result, result)
        self.change_setup()
        before = self.db.max_revision()
        with self.assertRaises(ConflictError):
            review.map_response(self.db, mapping=self.mapping(result))
        self.assertEqual(before, self.db.max_revision())
        self.assertEqual("needs_revision", self.db.head("responses", result["response_id"]).body["state"])

    def test_primary_rationale_change_does_not_invalidate_source_review_before_mapping(self):
        original = self.prepare()
        group = self.db.head("groups", "grp_lem")
        self.fx.apply(self.db, [edit("replace", "groups", group.id,
            dict(group.body, rationale="Different coordinator exposition of the same source argument"), group.version)])
        result = self.submit(original)
        self.assertIn("response_id", result, result)
        mapped = review.map_response(self.db, mapping=self.mapping(result))
        self.assertEqual("accepted", mapped["state"])
        self.assertEqual("current", self.freshness(mapped["checks"][0]["check_id"])["freshness"])

    def reassign_setup(self, collection, identity):
        record = self.db.head(collection, identity)
        self.fx.apply(self.db, [edit("replace", collection, identity,
                                   dict(record.body, scope_id="scp_new"), record.version)])

    def test_setup_attachments_are_checked_at_submission_and_mapping(self):
        cases = (("groups", "grp_lem", "lem"), ("arguments", "arg_lem", "lem"),
                 ("application_details", "use_lem_thm", "thm"), ("target_specs", "tgt_lem", "lem"))
        for stage in ("submit", "map"):
            for collection, identity, name in cases:
                with self.subTest(stage=stage, collection=collection):
                    self.fx = self.fixture(stage + collection).audit()
                    self.db = self.fx.open()
                    self.addCleanup(self.db.close)
                    self.fx.apply(self.db, [edit("create", "scopes", "scp_new", {
                        "argument_id": "arg_thm" if collection == "application_details" else None,
                        "parent_id": "scp_plain", "assumptions": [], "binders": [],
                        "conditions": ["Additional applicable condition"], "evidence_refs": ["anc_thm"]})])
                    if collection == "application_details":
                        group = self.db.head("groups", "grp_thm")
                        self.fx.apply(self.db, [edit("replace", "groups", group.id,
                            dict(group.body, scope_id="scp_new"), group.version)])
                    self.fx.primary()
                    original = self.prepare("itm_" + name)
                    if name == "lem":
                        self.assertNotIn("anc_thm", [ref["id"] for ref in original["manifest"]["read_set"]])
                    pending = self.submit(original, name) if stage == "map" else None
                    self.reassign_setup(collection, identity)
                    if stage == "submit":
                        result = self.submit(original, name)
                        self.assertEqual("conflict", result["state"], result)
                        self.assertNotIn("response_id", result)
                    else:
                        before = self.db.max_revision()
                        with self.assertRaises(ConflictError):
                            review.map_response(self.db, mapping=self.mapping(pending, name))
                        self.assertEqual(before, self.db.max_revision())

    def test_added_equivalent_inference_keeps_pending_source_review_usable(self):
        original = self.prepare()
        pending = self.submit(original)
        group = self.db.head("groups", "grp_lem")
        self.fx.apply(self.db, [edit("create", "groups", "grp_added", dict(group.body))])
        changes = packets.independent_context_changes(State(self.db, []), original["manifest"])
        self.assertEqual({"records": [], "relations": []}, changes)
        mapped = review.map_response(self.db, mapping=self.mapping(pending))
        self.assertEqual("accepted", mapped["state"])
        check_id = mapped["checks"][0]["check_id"]
        self.fx.apply(self.db, [edit("create", "groups", "grp_later", dict(group.body))])
        self.assertEqual("needs_review", self.freshness(check_id)["freshness"])

    def test_added_inference_with_new_setup_invalidates_pending_source_review(self):
        original = self.prepare()
        pending = self.submit(original)
        group = self.db.head("groups", "grp_lem")
        self.fx.apply(self.db, [edit("create", "scopes", "scp_new", {
            "argument_id": None, "parent_id": None, "assumptions": [], "binders": [],
            "conditions": ["Additional applicable condition"], "evidence_refs": ["anc_thm"]}),
            edit("create", "groups", "grp_added", dict(group.body, scope_id="scp_new"))])
        changes = packets.independent_context_changes(State(self.db, []), original["manifest"])
        self.assertTrue(any(row["relation"] == "groups_in_argument" for row in changes["relations"]))
        with self.assertRaises(ConflictError):
            review.map_response(self.db, mapping=self.mapping(pending))

    def test_historical_selector_entries_keep_recognized_broad_digests(self):
        original = self.prepare()
        for row in original["manifest"]["work"]["source_context_inputs"]:
            row.pop("setup_digest", None)
        binding = packets.independent_context_binding(State(self.db, []), original["manifest"])
        selector = next(row for row in binding["records"] if row["ref"]["id"] == "grp_lem")
        self.assertIn("setup_digest", selector)
        self.assertEqual("inference", selector["facet"])
        group = self.db.head("groups", "grp_lem")
        self.fx.apply(self.db, [edit("replace", "groups", group.id,
            dict(group.body, rationale="Same source, revised coordinator wording"), group.version)])
        self.assertEqual({"records": [], "relations": []}, binding_changes(State(self.db, []), binding))
        broad = dict(selector)
        broad.pop("setup_digest")
        self.assertTrue(binding_changes(State(self.db, []), {"records": [broad], "relations": []})["records"])

    def test_saved_major_source_selectors_keep_their_original_setup_projection(self):
        original = self.prepare()
        binding = packets.independent_context_binding(State(self.db, []), original["manifest"])
        selected = [row for row in binding["records"] if row["ref"]["id"] in ("arg_lem", "grp_lem")]
        self.assertEqual(2, len(selected))
        legacy_fields = {"arguments": ("target", "scope_id"),
                         "groups": ("argument_id", "scope_id", "case_scope_ids", "discharges")}
        for row in selected:
            pin = row["ref"]
            record = self.db.version(pin["collection"], pin["id"], pin["version"])
            saved = dict(row, setup_digest=digest({key: record.body[key] for key in legacy_fields[pin["collection"]]}))
            self.assertNotIn("source_passage_selection", saved)
            self.assertEqual({"records": [], "relations": []},
                             binding_changes(State(self.db, []), {"records": [saved], "relations": []}))

    def prepare_old_selector_packet(self, *, omitted_scope=None):
        build, members, scope = packets._assignment_packet, packets._neutral_members, packets._neutral_scope

        def old_build(*args, **kwargs):
            manifest, packet = build(*args, **kwargs)
            manifest["work"].pop("neutral_setup_selection")
            for row in manifest["work"]["source_context_inputs"]:
                row.pop("setup_digest", None)
            return manifest, packet

        def old_members(closure, relation, ref):
            return [] if relation == "target_specs_for_target" else members(closure, relation, ref)

        def old_scope(closure, scope_id):
            return None if scope_id == omitted_scope else scope(closure, scope_id)

        with mock.patch.object(packets, "_assignment_packet", side_effect=old_build), \
                mock.patch.object(packets, "_neutral_members", side_effect=old_members), \
                mock.patch.object(packets, "_neutral_scope", side_effect=old_scope):
            return self.prepare()

    def test_existing_packet_without_missing_exact_setup_remains_usable(self):
        original = self.prepare_old_selector_packet()
        pending = self.submit(original)
        self.assertIn("response_id", pending, pending)
        mapped = review.map_response(self.db, mapping=self.mapping(pending))
        self.assertEqual("accepted", mapped["state"])
        check_id = mapped["checks"][0]["check_id"]
        self.assertEqual(1, self.db.binding("checks", check_id, 1)["bindings"]["neutral_setup_validated"])
        with mock.patch.object(packets, "independent_context_changes", side_effect=AssertionError("already validated")):
            self.assertEqual("current", self.freshness(check_id)["freshness"])

    def assert_legacy_omission_is_rejected(self, original):
        self.assertNotIn("anc_thm", [ref["id"] for ref in original["manifest"]["read_set"]])
        rejected = self.submit(original)
        self.assertEqual("conflict", rejected["state"], rejected)
        self.assertIn("omitted applicable source or setup", rejected["error"]["message"])
        # Emulate a response preserved and later mapped by the previous writer.
        with mock.patch.object(packets, "independent_context_binding", return_value=None):
            pending = self.submit(original)
        self.assertIn("response_id", pending, pending)
        with self.assertRaisesRegex(ConflictError, "omitted applicable source or setup"):
            review.map_response(self.db, mapping=self.mapping(pending))
        with mock.patch.object(packets, "independent_context_binding", return_value=None):
            mapped = review.map_response(self.db, mapping=self.mapping(pending))
        check_id = mapped["checks"][0]["check_id"]
        self.assertNotIn("neutral_setup_validated", self.db.binding("checks", check_id, 1)["bindings"])
        before = self.db.max_revision()
        snapshot = assessment.Snapshot(self.db, before)
        reuse = mock.Mock()
        reuse.get.side_effect = AssertionError("missing independent context cannot use generic source reuse")
        changed = assessment.judgment_freshness(snapshot, self.db.head("checks", check_id),
                                               superseded=False, reuse_index=reuse)
        self.assertEqual("needs_review", changed["freshness"])
        self.assertFalse(changed["reused"])
        self.assertIn("omitted applicable source or setup", str(changed["changes"]))
        self.assertEqual(before, self.db.max_revision())

    def test_existing_packet_with_omitted_exact_setup_requires_new_review(self):
        self.fx = self.fixture("legacy_exact").audit()
        self.db = self.fx.open()
        self.addCleanup(self.db.close)
        spec = self.db.head("target_specs", "tgt_lem")
        self.fx.apply(self.db, [edit("create", "scopes", "scp_exact", {
            "argument_id": None, "parent_id": None, "assumptions": [], "binders": [],
            "conditions": ["Exact setup omitted by the earlier selector"], "evidence_refs": ["anc_thm"]}),
            edit("replace", "target_specs", spec.id, dict(spec.body, scope_id="scp_exact"), spec.version)])
        self.fx.primary()
        original = self.prepare_old_selector_packet()
        self.assert_legacy_omission_is_rejected(original)

    def test_existing_packet_with_omitted_discharged_setup_requires_new_review(self):
        group = self.db.head("groups", "grp_lem")
        self.fx.apply(self.db, [edit("create", "scopes", "scp_discharged", {
            "argument_id": "arg_lem", "parent_id": None, "assumptions": [], "binders": [],
            "conditions": ["An additional premise must be discharged"], "evidence_refs": ["anc_thm"]}),
            edit("replace", "groups", group.id, dict(group.body, discharges=["scp_discharged"]), group.version)])
        # Preparation now requires current Stage 1 evidence. Renew the changed
        # primary inference while preserving the legacy packet omission below.
        coverage = self.db.head("coverage", "cov_lem")
        self.fx.apply(self.db, [
            self.fx.check_edit("chk_der_discharged", R("groups", "grp_lem"), "derivation",
                evidence=["anc_lem_proof"], supersedes=self.fx.pin(self.db, "checks", "chk_der_lem")),
            self.fx.check_edit("chk_comp_discharged", R("arguments", "arg_lem"), "composition",
                evidence=["anc_lem_proof"], supersedes=self.fx.pin(self.db, "checks", "chk_comp_lem")),
            self.fx.check_edit("chk_scope_discharged", R("groups", "grp_lem"), "scope_discharge",
                evidence=["anc_lem_proof"]),
            edit("replace", "coverage", coverage.id, dict(coverage.body,
                check_ids=["chk_der_discharged"]), coverage.version)], *self.fx.ITEMS, mode="primary")
        original = self.prepare_old_selector_packet(omitted_scope="scp_discharged")
        self.assert_legacy_omission_is_rejected(original)

    def test_existing_mapped_check_keeps_valid_delivered_context_current(self):
        original = self.prepare_old_selector_packet()
        with mock.patch.object(packets, "independent_context_binding", return_value=None):
            pending = self.submit(original)
            mapped = review.map_response(self.db, mapping=self.mapping(pending))
        self.assertEqual("current", self.freshness(mapped["checks"][0]["check_id"])["freshness"])

    def test_existing_mapped_check_rechecks_original_setup_attachment(self):
        original = self.prepare_old_selector_packet()
        self.fx.apply(self.db, [edit("create", "scopes", "scp_new", {
            "argument_id": None, "parent_id": None, "assumptions": [], "binders": [],
            "conditions": ["Additional setup never delivered"], "evidence_refs": ["anc_thm"]})])
        self.reassign_setup("groups", "grp_lem")
        with mock.patch.object(packets, "independent_context_binding", return_value=None):
            pending = self.submit(original)
            mapped = review.map_response(self.db, mapping=self.mapping(pending))
        changed = self.freshness(mapped["checks"][0]["check_id"])
        self.assertEqual("needs_review", changed["freshness"])
        self.assertTrue(any(row["ref"]["id"] == "grp_lem" for row in changed["changes"]["records"]))

    def extra_context(self, original):
        self.fx.apply(self.db, [edit("create", "scopes", "scp_extra", {"argument_id": None, "parent_id": None,
            "assumptions": [], "binders": [], "conditions": [], "evidence_refs": ["anc_thm"]}),
            {**self.fx.item_edit("itm_extra_context", "definition", "Auxiliary definition", "anc_thm", "anc_thm_proof"),
             "body": {**self.fx.item_edit("itm_extra_context", "definition", "Auxiliary definition", "anc_thm", "anc_thm_proof")["body"],
                      "scope_id": "scp_extra"}}])
        return controller.extend_work(self.db, packet_id=original["packet_id"], request={
            "source_refs": [self.db.head("items", "itm_extra_context").pinned], "reason": "Auxiliary definition is needed."})

    def change_extra_setup(self):
        scope = self.db.head("scopes", "scp_extra")
        self.fx.apply(self.db, [edit("replace", "scopes", scope.id, dict(scope.body, conditions=["different regime"]), scope.version)])

    def test_mapped_check_keeps_context_only_setup_binding(self):
        extended = self.extra_context(self.prepare())
        result = self.submit(extended)
        mapped = review.map_response(self.db, mapping=self.mapping(result))
        check_id = mapped["checks"][0]["check_id"]
        bound = self.db.binding("checks", check_id, 1)["bindings"]
        self.assertTrue(any(row["ref"]["id"] == "scp_extra" for row in bound["records"]))
        self.change_extra_setup()
        changed = self.freshness(check_id)
        self.assertEqual("needs_review", changed["freshness"])
        self.assertTrue(any(row["ref"]["id"] == "scp_extra" for row in changed["changes"]["records"]))

    def test_mapped_check_keeps_context_only_exact_setup_selection(self):
        original = self.prepare()
        extended = self.extra_context(original)
        context = self.db.head("items", "itm_extra_context")
        self.fx.apply(self.db, [edit("create", "target_specs", "tgt_extra", {
            "target": context.ref, "statement_ref": context.pinned, "statement": None, "scope_id": "scp_extra",
            "evidence_refs": ["anc_thm"], "state": "draft", "fidelity_ref": None})])
        # An exact specification that adds no source/setup does not demand a new
        # source reading solely because its private record acquired an ID.
        result = self.submit(extended)
        self.assertIn("response_id", result, result)
        renewed = controller.extend_work(self.db, packet_id=self.prepare()["packet_id"], request={
            "source_refs": [context.pinned], "reason": "Auxiliary definition is needed."})
        submitted = self.submit(renewed)
        mapped = review.map_response(self.db, mapping=self.mapping(submitted))
        check_id = mapped["checks"][0]["check_id"]
        bound = self.db.binding("checks", check_id, 1)["bindings"]
        self.assertTrue(any(row["ref"]["id"] == "tgt_extra" and "setup_digest" in row for row in bound["records"]))
        self.fx.apply(self.db, [edit("create", "scopes", "scp_new", {
            "argument_id": None, "parent_id": None, "assumptions": [], "binders": [],
            "conditions": ["Different applicable setup"], "evidence_refs": ["anc_lem"]})])
        self.reassign_setup("target_specs", "tgt_extra")
        changed = self.freshness(check_id)
        self.assertEqual("needs_review", changed["freshness"])
        self.assertTrue(any(row["ref"]["id"] == "tgt_extra" for row in changed["changes"]["records"]))

    def test_context_only_setup_race_is_rechecked_inside_mapping_transaction(self):
        extended = self.extra_context(self.prepare())
        result = self.submit(extended)
        mapping = self.mapping(result)
        authority = self.db.packet(mapping["packet_id"])["manifest"]
        self.assertNotIn("scp_extra", [ref["id"] for ref in authority["read_set"]])
        accept = review.accept
        changed_revision = []

        def interleave(*args, **kwargs):
            self.change_extra_setup()
            changed_revision.append(self.db.max_revision())
            return accept(*args, **kwargs)

        with mock.patch.object(review, "accept", side_effect=interleave):
            with self.assertRaises(ConflictError):
                review.map_response(self.db, mapping=mapping)
        self.assertEqual(changed_revision[0], self.db.max_revision())
        self.assertEqual("needs_revision", self.db.head("responses", result["response_id"]).body["state"])


class IntermediateNeutralFreshnessTests(TempCase):
    def boundary_context(self, fx, db, *, attach=True):
        (fx.source_root / "supplement.tex").write_text("Unseen supporting passage.\nAdditional source setup.\n", encoding="utf-8")
        source_id = sources.capture_sources(db, files=["supplement.tex"])["sources"][0]["id"]
        authority = fx.packet(db)
        sources.anchor_sources(db, request={"contract_version": 4, "request_id": fx.request_id(),
            "packet_id": authority["packet_id"], "anchors": [{"id": "anc_supp", "expected_version": None,
                "source_id": source_id, "locator": locator(start=1, end=2)}]})
        authority = fx.packet(db)
        sources.review_sources(db, batch=fx.batch([edit("create", "source_reviews", "srv_step", {
            "source_refs": [db.head("sources", source_id).pinned, db.head("sources", fx.source_id).pinned],
            "anchor_refs": [db.head("anchors", "anc_lem_proof").pinned, db.head("anchors", "anc_supp").pinned],
            "purpose": "proof_boundary", "decision": "accepted", "rationale": "Captured local source context.",
            "reviewer": "fixture"})], authority["packet_id"]))
        boundary = edit("create", "proof_boundaries", "bnd_step", {
            "target": R("items", "itm_step"), "argument_ids": ["arg_step"],
            "anchor_refs": [db.head("anchors", "anc_lem_proof").pinned],
            "source_review_ref": db.head("source_reviews", "srv_step").pinned, "state": "complete"})
        if attach:
            fx.apply(db, [boundary])
        return boundary

    def prepare(self, db):
        local = task("private_step", R("arguments", "arg_step"), "composition", role="independent")
        return packets.prepare_assignment(db, audit_id="aud_1", mode="independent", selection=selection((local,)))

    def submit(self, fx, db, prepared):
        worker = worker_response(prepared["packet_id"],
            [judgment(source_target("anc_lem_proof", "The captured local argument"))],
            covered=[R("items", "itm_thm")])
        envelope = {"contract_version": 4, "request_id": fx.request_id(), "packet_id": prepared["packet_id"],
            "rebase_packet_id": None, "reviewer": "checker-A", "qualification_id": "qua_r1",
            "exposure": "source_only", "exposure_note": "Fresh source-only reviewer."}
        return controller.submit_work(db, envelope_bytes=canonical_bytes(envelope), response_bytes=canonical_bytes(worker))

    def mapping(self, fx, db, pending):
        private = fx.packet(db, "items:itm_thm", mode="reconcile")
        return mapping_request(fx, private["packet_id"], pending["response_id"], [entry(0, R("arguments", "arg_step"))])

    def change_selection(self, fx, db, change):
        intermediate = db.head("items", "itm_step")
        if change == "owner":
            edits = [edit("replace", "items", intermediate.id, dict(intermediate.body, owner_id="itm_lem"), intermediate.version)]
        elif change == "passages":
            edits = [edit("replace", "items", intermediate.id, dict(intermediate.body,
                passages=[{"role": "evidence", "anchor_id": "anc_thm_proof"}]), intermediate.version)]
        elif change == "item_scope":
            edits = [edit("create", "scopes", "scp_new", {"argument_id": "arg_step", "parent_id": "scp_plain",
                "assumptions": [], "binders": [], "conditions": ["Additional condition"], "evidence_refs": ["anc_thm"]}),
                edit("replace", "items", intermediate.id, dict(intermediate.body, scope_id="scp_new"), intermediate.version)]
        elif change == "scope_condition":
            scope = db.head("scopes", "scp_step")
            edits = [edit("replace", "scopes", scope.id, dict(scope.body, conditions=["Changed applicable setup"]), scope.version)]
        else:
            collection, identity = {"argument_passage": ("arguments", "arg_step"),
                "group_passage": ("groups", "grp_step"), "use_passage": ("uses", "use_step_dep")}[change]
            record = db.head(collection, identity)
            edits = [edit("replace", collection, record.id,
                dict(record.body, evidence_refs=["anc_thm_proof"]), record.version)]
        fx.apply(db, edits)

    def test_changed_intermediate_source_selection_is_rejected_at_submission_and_mapping(self):
        for stage in ("submit", "map"):
            for change in ("owner", "passages", "item_scope", "scope_condition", "argument_passage", "group_passage", "use_passage"):
                with self.subTest(stage=stage, change=change):
                    fx = self.fixture(stage + change).audit()
                    with fx.open() as db:
                        fx.apply(db, intermediate_edits(fx, origin="reconstruction"))
                        fx.apply(db, [edit("create", "uses", "use_step_dep", {
                            "from": R("items", "itm_lem"), "to": R("items", "itm_step"), "type": "dependency",
                            "reason": "PRIVATE USE REASON", "evidence_refs": ["anc_lem_proof"],
                            "regime": None, "uncertainty": None})])
                        prepared = self.prepare(db)
                        pending = self.submit(fx, db, prepared) if stage == "map" else None
                        self.change_selection(fx, db, change)
                        if stage == "submit":
                            rejected = self.submit(fx, db, prepared)
                            self.assertEqual("conflict", rejected["state"], rejected)
                            self.assertNotIn("response_id", rejected)
                        else:
                            mapping = self.mapping(fx, db, pending)
                            before = db.max_revision()
                            with self.assertRaises(ConflictError):
                                review.map_response(db, mapping=mapping)
                            self.assertEqual(before, db.max_revision())
                            self.assertEqual("needs_revision", db.head("responses", pending["response_id"]).body["state"])

    def test_private_caption_outline_and_rationale_changes_do_not_stale_delivered_source(self):
        fx = self.fixture().audit()
        with fx.open() as db:
            fx.apply(db, intermediate_edits(fx, origin="reconstruction"))
            prepared = self.prepare(db)
            intermediate, argument, group = (db.head(c, i) for c, i in
                (("items", "itm_step"), ("arguments", "arg_step"), ("groups", "grp_step")))
            fx.apply(db, [edit("replace", "items", intermediate.id,
                dict(intermediate.body, caption="Reworded caption", proof_idea="Reworded private outline"), intermediate.version),
                edit("replace", "arguments", argument.id, dict(argument.body, label="Reworded label"), argument.version),
                edit("replace", "groups", group.id, dict(group.body, rationale="Reworded private reasoning"), group.version)])
            self.assertEqual({"records": [], "relations": []}, packets.independent_context_changes(State(db, []), prepared["manifest"]))
            pending = self.submit(fx, db, prepared)
            mapped = review.map_response(db, mapping=self.mapping(fx, db, pending))
            self.assertEqual("accepted", mapped["state"])
            check_id = mapped["checks"][0]["check_id"]
            fresh = assessment.judgment_freshness(assessment.Snapshot(db, db.max_revision()), db.head("checks", check_id), superseded=False)
            self.assertEqual("current", fresh["freshness"])
            self.change_selection(fx, db, "scope_condition")
            changed = assessment.judgment_freshness(assessment.Snapshot(db, db.max_revision()), db.head("checks", check_id), superseded=False)
            self.assertEqual("needs_review", changed["freshness"])

    def test_intermediate_boundary_attach_change_and_detach_require_new_review(self):
        for stage in ("submit", "map"):
            for change in ("attach", "change", "detach"):
                with self.subTest(stage=stage, change=change):
                    fx = self.fixture(stage + change).audit()
                    with fx.open() as db:
                        fx.apply(db, intermediate_edits(fx, origin="reconstruction"))
                        boundary = self.boundary_context(fx, db, attach=change != "attach")
                        prepared = self.prepare(db)
                        self.assertNotIn("anc_supp", [row["ref"]["id"] for row in prepared["packet"]["records"]])
                        self.assertNotIn("bnd_step", canonical_bytes(prepared["packet"]).decode("utf-8"))
                        pending = self.submit(fx, db, prepared) if stage == "map" else None
                        if change == "attach":
                            boundary["body"]["anchor_refs"] = [db.head("anchors", "anc_supp").pinned]
                            fx.apply(db, [boundary])
                        elif change == "change":
                            current = db.head("proof_boundaries", "bnd_step")
                            fx.apply(db, [edit("replace", "proof_boundaries", current.id,
                                dict(current.body, anchor_refs=[db.head("anchors", "anc_supp").pinned]), current.version)])
                        else:
                            current = db.head("proof_boundaries", "bnd_step")
                            fx.apply(db, [{"op": "retire", "collection": "proof_boundaries", "id": current.id,
                                "expected_version": current.version, "reason": "Local source boundary withdrawn."}])
                        changes = packets.independent_context_changes(State(db, []), prepared["manifest"])
                        self.assertTrue(changes["records"] or changes["relations"], changes)
                        if stage == "submit":
                            rejected = self.submit(fx, db, prepared)
                            self.assertEqual("conflict", rejected["state"], rejected)
                            self.assertNotIn("response_id", rejected)
                        else:
                            mapping = self.mapping(fx, db, pending)
                            before = db.max_revision()
                            with self.assertRaises(ConflictError):
                                review.map_response(db, mapping=mapping)
                            self.assertEqual(before, db.max_revision())

    def test_intermediate_boundary_source_review_metadata_does_not_change_delivered_context(self):
        fx = self.fixture().audit()
        with fx.open() as db:
            fx.apply(db, intermediate_edits(fx, origin="reconstruction"))
            self.boundary_context(fx, db)
            prepared = self.prepare(db)
            prior = db.head("source_reviews", "srv_step")
            authority = fx.packet(db)
            sources.review_sources(db, batch=fx.batch([edit("create", "source_reviews", "srv_step_reworded",
                dict(prior.body, rationale="Reworded source-selection explanation."))], authority["packet_id"]))
            boundary = db.head("proof_boundaries", "bnd_step")
            fx.apply(db, [edit("replace", "proof_boundaries", boundary.id,
                dict(boundary.body, source_review_ref=db.head("source_reviews", "srv_step_reworded").pinned), boundary.version)])
            self.assertEqual({"records": [], "relations": []}, packets.independent_context_changes(State(db, []), prepared["manifest"]))
            pending = self.submit(fx, db, prepared)
            mapped = review.map_response(db, mapping=self.mapping(fx, db, pending))
            self.assertEqual("accepted", mapped["state"])

    def test_intermediate_assumption_delivers_captured_setup_and_preserves_scope(self):
        fx = self.fixture().audit()
        with fx.open() as db:
            fx.apply(db, intermediate_edits(fx, origin="reconstruction"))
            self.boundary_context(fx, db, attach=False)
            assumption = fx.item_edit("itm_aux", "equation", "PRIVATE AUXILIARY CAPTION", "anc_supp", "anc_supp")
            assumption["body"].update(owner_id="itm_thm", origin="reconstruction", proof_idea="PRIVATE AUXILIARY OUTLINE")
            scope = db.head("scopes", "scp_step")
            fx.apply(db, [assumption, edit("replace", "scopes", scope.id,
                dict(scope.body, assumptions=scope.body["assumptions"] + [R("items", "itm_aux")]), scope.version)])
            prepared = self.prepare(db)
            self.assertEqual([R("items", "itm_thm")], prepared["packet"]["targets"])
            raw = canonical_bytes(prepared["packet"]).decode("utf-8")
            self.assertIn("anc_supp", raw)
            for hidden in ("itm_aux", "PRIVATE AUXILIARY", "scp_step"):
                self.assertNotIn(hidden, raw)
            self.assertEqual([], packets.blinding_violations(prepared["packet"]))
            self.assertTrue(any(row["ref"]["id"] == "itm_aux" for row in prepared["manifest"]["work"]["source_context_inputs"]))
            pending = self.submit(fx, db, prepared)
            auxiliary = db.head("items", "itm_aux")
            fx.apply(db, [edit("replace", "items", auxiliary.id,
                dict(auxiliary.body, passages=[{"role": "evidence", "anchor_id": "anc_thm_proof"}]), auxiliary.version)])
            with self.assertRaises(ConflictError):
                review.map_response(db, mapping=self.mapping(fx, db, pending))

    def test_intermediate_assumption_without_source_context_stays_unprepared(self):
        fx = self.fixture().audit()
        with fx.open() as db:
            fx.apply(db, intermediate_edits(fx, origin="reconstruction"))
            assumption = fx.item_edit("itm_aux", "equation", "Private assumption", "anc_lem_proof", "anc_lem_proof")
            assumption["body"].update(owner_id="itm_thm", origin="reconstruction", passages=[])
            scope = db.head("scopes", "scp_step")
            fx.apply(db, [assumption, edit("replace", "scopes", scope.id,
                dict(scope.body, assumptions=[R("items", "itm_aux")]), scope.version)])
            before = db.conn.execute("SELECT COUNT(*) FROM packets").fetchone()[0]
            with self.assertRaisesRegex(InvalidRequest, "no captured local source passage"):
                self.prepare(db)
            self.assertEqual(before, db.conn.execute("SELECT COUNT(*) FROM packets").fetchone()[0])
