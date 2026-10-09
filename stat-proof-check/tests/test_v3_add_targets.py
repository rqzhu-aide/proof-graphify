"""Additive scope preserves exact saved questions, not changed mathematics.

All source comparisons and examinations below are synthetic engine fixtures.
"""
from copy import deepcopy
import json

from support import R, TempCase, edit, locator
from paper_core import assessment, authoring, controller, packets, sources, stage1, stage2
from paper_core.audit_compatibility import validate_assignment_audit
from paper_core.errors import ConflictError, InvalidRequest, SourceUnavailable
from paper_core.work import derive_work, select_assignment


class AddTargetsTests(TempCase):
    def fixture_with_claim(self, name="addition", *, stage="complete", route=True):
        fixture = self.fixture(name, tag=name)
        source = fixture.source_root / "paper.tex"
        source.write_text(source.read_text(encoding="utf-8").replace(r"\end{document}", "\n".join([
            r"\paragraph{Additional claim}\label{claim:extra}",
            r"If $b_n=2a_n$, then $b_n\le 2$ for every $n$.",
            r"\begin{proof}", r"Multiply $a_n\le 1$ by two.", r"\end{proof}",
            r"\end{document}"])), encoding="utf-8")
        fixture.audit(mode="full")
        if stage != "audit":
            getattr(fixture, stage)()
        with fixture.open() as db:
            author = fixture.packet(db)
            sources.anchor_sources(db, request={"contract_version": 4, "request_id": fixture.request_id(),
                "packet_id": author["packet_id"], "anchors": [
                    {"id": "anc_extra", "expected_version": None, "source_id": fixture.source_id,
                     "locator": locator(start=18, end=19)},
                    {"id": "anc_extra_proof", "expected_version": None, "source_id": fixture.source_id,
                     "locator": locator(start=20, end=22)}]})
            definition = {"key": "extra", "kind": "claim", "owner_id": "itm_thm", "label": "Additional claim",
                "statement": "If b_n=2a_n, then b_n<=2 for every n.", "statement_anchors": ["anc_extra"],
                "source_matched": True, "source_note": "Synthetic exact source comparison."}
            if route:
                definition.update(proof_anchors=["anc_extra_proof"], proof_complete=True,
                    suppliers=[{"target": R("items", "itm_lem"), "reason": "The supplied bound.",
                                "needed_form": {"form": "transcription", "text": "For every n, a_n <= 1."}}])
                authoring.create_unit(db, definition)
            else:
                authoring.create_record(db, definition)
        return fixture

    def add(self, db, fixture, *targets, version=None):
        return authoring.add_targets(db, audit_id=fixture.audit_id,
            expected_version=db.head("audits", fixture.audit_id).version if version is None else version,
            targets=list(targets or (R("items", "itm_extra"),)))

    def prepare(self, db, fixture, mode, focus=None, **options):
        if mode == "primary":
            return stage1.prepare_stage(db, audit_id=fixture.audit_id, focus=focus, **options)
        return stage2.prepare(db, audit_id=fixture.audit_id, mode=mode, focus=focus, **options)

    def returned_bytes(self, fixture, prepared, *, mode="primary", outcome="supported"):
        response = deepcopy(prepared["scaffold"])
        for row in response.get("results", []):
            if row["type"] == "source_fidelity":
                row.update(result="matched", note="Synthetic exact source comparison.")
            else:
                row.update(state="complete", outcome=outcome, reasoning="Synthetic examination of this exact question.")
        for row in response.get("judgments", []):
            row.update(state="complete", outcome=outcome, reasoning="Synthetic separate source-only examination.")
        for row in response.get("integrations", []):
            row.update(decision="agree", rationale="Synthetic comparison retains the exact saved examinations.")
        envelope = dict(prepared["submission_envelope_template"], request_id=fixture.request_id(),
                        reviewer="synthetic independent" if mode == "independent" else "synthetic coordinator")
        return json.dumps(envelope).encode(), json.dumps(response).encode()

    def submit(self, db, fixture, prepared, *, mode="primary", outcome="supported"):
        envelope, response = self.returned_bytes(fixture, prepared, mode=mode, outcome=outcome)
        result = controller.submit_work(db, envelope_bytes=envelope, response_bytes=response)
        self.assertEqual("accepted", result["state"], result)
        self.assertEqual(response, db.get_blob(db.work_submission(result["request_id"])["response_sha256"]))
        return result

    @staticmethod
    def preserved(db):
        return {collection: {record.id: (record.pinned, deepcopy(record.body),
            deepcopy(db.binding(collection, record.id, record.version)),
            db.get_blob(record.body["original_blob"]) if collection == "responses" else None)
            for record in db.heads(collection)} for collection in ("checks", "responses", "reconciliations", "observations")}

    def replace_audit(self, db, fixture, **changes):
        audit = db.head("audits", fixture.audit_id)
        fixture.apply(db, [edit("replace", "audits", audit.id, dict(audit.body, **changes), audit.version)],
                      "audits:" + audit.id, mode="primary")

    def test_add_after_completion_preserves_records_and_finishes_only_new_question(self):
        fixture = self.fixture_with_claim()
        with fixture.open() as db:
            before = self.preserved(db)
            original = assessment.derive_assessment(db, audit_id=fixture.audit_id)
            old_required = {row["id"]: deepcopy(row) for row in original["obligations"] if row["required"]}
            audit = deepcopy(db.head("audits", fixture.audit_id).body)
            self.add(db, fixture)
            live = db.head("audits", fixture.audit_id)
            self.assertEqual(audit, {**live.body, "targets": audit["targets"]})
            expanded = assessment.derive_assessment(db, audit_id=fixture.audit_id)
            self.assertEqual(old_required, {row["id"]: row for row in expanded["obligations"] if row["id"] in old_required})
            self.assertEqual(before, self.preserved(db))
            for mode in ("primary", "independent", "reconcile"):
                prepared = self.prepare(db, fixture, mode, R("items", "itm_extra"))
                self.assertTrue(prepared["prepared"], prepared)
                self.assertEqual({R("arguments", "arg_extra")["id"]},
                    {task["target"]["id"] for task in prepared["manifest"]["work"]["tasks"]})
                self.submit(db, fixture, prepared, mode=mode)
            final = assessment.derive_assessment(db, audit_id=fixture.audit_id)
            self.assertTrue(final["progress"]["process_complete"], final["problems"])
            for collection, rows in before.items():
                self.assertEqual(rows, {identity: self.preserved(db)[collection][identity] for identity in rows})

    def test_outstanding_returns_for_all_three_roles_accept_and_reuse_original_packet(self):
        for mode, stage in (("primary", "audit"), ("independent", "primary"), ("reconcile", "independent")):
            with self.subTest(mode=mode):
                fixture = self.fixture_with_claim(mode, stage=stage)
                with fixture.open() as db:
                    prepared = self.prepare(db, fixture, mode, R("items", "itm_thm"))
                    envelope, response = self.returned_bytes(fixture, prepared, mode=mode)
                    packet = deepcopy(db.packet(prepared["packet_id"]))
                    payload = db.get_blob(packet["payload_sha256"])
                    self.add(db, fixture)
                    reused = self.prepare(db, fixture, mode, R("items", "itm_thm"))
                    self.assertEqual(prepared["packet_id"], reused["packet_id"])
                    self.assertTrue(reused["reused"])
                    result = controller.submit_work(db, envelope_bytes=envelope, response_bytes=response)
                    self.assertEqual("accepted", result["state"], result)
                    revision = db.max_revision()
                    replay = controller.submit_work(db, envelope_bytes=envelope, response_bytes=response)
                    self.assertEqual(result, replay)
                    self.assertEqual(revision, db.max_revision())
                    self.assertEqual(response, db.get_blob(db.work_submission(result["request_id"])["response_sha256"]))
                    self.assertEqual(packet, db.packet(prepared["packet_id"]))
                    self.assertEqual(payload, db.get_blob(packet["payload_sha256"]))

    def test_addition_replay_current_noop_and_stale_writers(self):
        fixture = self.fixture_with_claim()
        with fixture.open() as db:
            version = db.head("audits", fixture.audit_id).version
            first = self.add(db, fixture, version=version)
            revision = db.max_revision()
            self.assertEqual(first["receipt"], self.add(db, fixture, version=version)["receipt"])
            self.assertEqual(revision, db.max_revision())
            self.assertTrue(self.add(db, fixture)["unchanged"])
            self.assertEqual(revision, db.max_revision())
            authoring.create_record(db, {"key": "later", "kind": "claim", "owner_id": "itm_thm", "label": "Later",
                "statement": "Synthetic later exact claim.", "statement_anchors": ["anc_extra"],
                "source_matched": True, "source_note": "Synthetic source comparison."})
            self.add(db, fixture, R("items", "itm_later"))
            latest = deepcopy(db.head("audits", fixture.audit_id))
            with self.assertRaises(ConflictError):
                self.add(db, fixture, version=version)
            with self.assertRaises(ConflictError):
                self.add(db, fixture, R("items", "itm_later"), version=version)
            self.assertEqual(latest, db.head("audits", fixture.audit_id))

    def test_invalid_retired_and_excluded_requests_preserve_audit(self):
        fixture = self.fixture_with_claim()
        with fixture.open() as db:
            audit = deepcopy(db.head("audits", fixture.audit_id))
            revision = db.max_revision()
            for targets in ([R("items", "itm_other_paper")], [R("parts", "par_missing")],
                            [R("items", "itm_extra"), R("items", "itm_missing")]):
                with self.subTest(targets=targets), self.assertRaises(InvalidRequest):
                    self.add(db, fixture, *targets)
                self.assertEqual(audit, db.head("audits", fixture.audit_id))
                self.assertEqual(revision, db.max_revision())
            for exclusion in ({"target": R("items", "itm_extra"), "source_anchor_ids": [],
                               "reason": "Explicitly excluded claim.", "consequence": "No examination requested."},
                              {"target": None, "source_anchor_ids": ["anc_extra_proof"],
                               "reason": "Excluded supplied passage.", "consequence": "No examination of this passage."}):
                self.replace_audit(db, fixture, exclusions=[exclusion])
                before = deepcopy(db.head("audits", fixture.audit_id))
                revision = db.max_revision()
                result = self.add(db, fixture)
                self.assertTrue(result["unchanged"])
                self.assertEqual(R("items", "itm_extra"), result["ineffective_targets"][0]["target"])
                self.assertEqual(before, db.head("audits", fixture.audit_id))
                self.assertEqual(revision, db.max_revision())
            authoring.create_record(db, {"key": "retired", "kind": "claim", "owner_id": "itm_thm", "label": "Retired",
                "statement": "Synthetic known claim.", "statement_anchors": ["anc_extra"],
                "source_matched": True, "source_note": "Synthetic source comparison."})
            fixture.apply(db, [{"op": "retire", "collection": collection, "id": identity,
                "expected_version": 1, "reason": "Synthetic retirement for live-target validation."}
                for collection, identity in (("target_specs", "tgt_retired"), ("items", "itm_retired"))])
            with self.assertRaises(InvalidRequest):
                self.add(db, fixture, R("items", "itm_retired"))

    def test_excluded_exact_spec_and_selected_group_evidence_leave_scope_and_saved_work_unchanged(self):
        for source in ("spec", "direct_group", "owned_group"):
            with self.subTest(source=source):
                fixture = self.fixture_with_claim(source, route=source == "direct_group")
                with fixture.open() as db:
                    target = R("items", "itm_extra")
                    if source == "owned_group":
                        authoring.create_record(db, {"key": "grouped", "kind": "claim", "owner_id": "itm_thm",
                            "argument_id": "arg_thm", "label": "Grouped claim", "statement": "A grouped source claim.",
                            "statement_anchors": ["anc_extra"], "proof_anchors": ["anc_extra_proof"],
                            "source_matched": True, "source_note": "Synthetic exact source comparison."})
                        target = R("items", "itm_grouped")
                    collection, identity = (("target_specs", "tgt_extra") if source == "spec" else
                        ("groups", "grp_extra" if source == "direct_group" else "grp_grouped"))
                    record = db.head(collection, identity)
                    fixture.apply(db, [edit("replace", collection, identity,
                        dict(record.body, evidence_refs=[*record.body["evidence_refs"], "anc_lem_proof"]), record.version)])
                    self.replace_audit(db, fixture, exclusions=[{"target": None, "source_anchor_ids": ["anc_lem_proof"],
                        "reason": "This exact source passage is excluded.", "consequence": "No examination of it."}])
                    audit = deepcopy(db.head("audits", fixture.audit_id))
                    saved, revision = self.preserved(db), db.max_revision()
                    scope = assessment.derive_assessment(db, audit_id=fixture.audit_id)["scope"]
                    tasks = deepcopy(derive_work(db, audit_id=fixture.audit_id)["tasks"])
                    result = self.add(db, fixture, target)
                    self.assertTrue(result["unchanged"], result)
                    self.assertEqual([{"target": target, "reason": "excluded_source_anchors",
                        "source_anchor_ids": ["anc_lem_proof"]}], result["ineffective_targets"])
                    self.assertEqual(audit, db.head("audits", fixture.audit_id))
                    self.assertEqual(revision, db.max_revision())
                    self.assertEqual(saved, self.preserved(db))
                    self.assertEqual(scope, assessment.derive_assessment(db, audit_id=fixture.audit_id)["scope"])
                    self.assertEqual(tasks, derive_work(db, audit_id=fixture.audit_id)["tasks"])

    def test_unrelated_draft_and_retired_evidence_does_not_block_an_added_claim(self):
        fixture = self.fixture_with_claim()
        with fixture.open() as db:
            spec, argument, group = (db.head(collection, identity) for collection, identity in (
                ("target_specs", "tgt_extra"), ("arguments", "arg_extra"), ("groups", "grp_extra")))
            evidence = {"evidence_refs": ["anc_lem_proof"]}
            fixture.apply(db, [
                edit("replace", "target_specs", spec.id, dict(spec.body, state="draft", **evidence), spec.version),
                edit("create", "arguments", "arg_draft", dict(argument.body, lifecycle="draft", final_group_id=None, **evidence)),
                edit("create", "arguments", "arg_retired", dict(argument.body, lifecycle="draft", final_group_id=None, **evidence)),
                edit("create", "groups", "grp_draft", dict(group.body, argument_id="arg_draft", **evidence)),
                edit("create", "groups", "grp_retired", dict(group.body, **evidence)),
                edit("create", "groups", "grp_unrelated", dict(group.body, argument_id="arg_thm",
                    conclusion=R("items", "itm_thm"), **evidence))])
            fixture.apply(db, [{"op": "retire", "collection": collection, "id": identity, "expected_version": 1,
                "reason": "This evidence registration is retired."} for collection, identity in (
                    ("arguments", "arg_retired"), ("groups", "grp_retired"))])
            self.replace_audit(db, fixture, exclusions=[{"target": None, "source_anchor_ids": ["anc_lem_proof"],
                "reason": "Exclude the nearby passage.", "consequence": "No examination of that passage."}])
            targets = deepcopy(db.head("audits", fixture.audit_id).body["targets"])
            saved = self.preserved(db)
            result = self.add(db, fixture)
            self.assertFalse(result["unchanged"], result)
            self.assertEqual([], result["ineffective_targets"])
            self.assertEqual([*targets, R("items", "itm_extra")], db.head("audits", fixture.audit_id).body["targets"])
            self.assertEqual(saved, self.preserved(db))
            prepared = self.prepare(db, fixture, "primary", R("items", "itm_extra"))
            self.assertTrue(prepared["prepared"], prepared)
            self.assertTrue(all(task["target"] in (R("arguments", "arg_extra"), R("target_specs", "tgt_extra"))
                for task in prepared["manifest"]["work"]["tasks"]), prepared["manifest"]["work"]["tasks"])

    def test_mixed_source_exclusion_adds_only_allowed_claim_and_replay_creates_no_work(self):
        fixture = self.fixture_with_claim(route=False)
        with fixture.open() as db:
            authoring.create_record(db, {"key": "allowed", "kind": "claim", "owner_id": "itm_thm", "label": "Allowed",
                "statement": "A separately allowed source claim.", "statement_anchors": ["anc_extra"],
                "source_matched": True, "source_note": "Synthetic exact source comparison."})
            spec = db.head("target_specs", "tgt_extra")
            fixture.apply(db, [edit("replace", "target_specs", spec.id,
                dict(spec.body, evidence_refs=["anc_extra", "anc_lem_proof"]), spec.version)])
            self.replace_audit(db, fixture, exclusions=[{"target": None, "source_anchor_ids": ["anc_lem_proof"],
                "reason": "Exclude this exact source passage.", "consequence": "No examination of it."}])
            audit = deepcopy(db.head("audits", fixture.audit_id))
            saved = self.preserved(db)
            old_tasks = {task["id"] for task in derive_work(db, audit_id=fixture.audit_id)["tasks"]}
            targets = (R("items", "itm_extra"), R("items", "itm_allowed"))
            first = self.add(db, fixture, *targets, version=audit.version)
            self.assertEqual([{"target": targets[0], "reason": "excluded_source_anchors",
                "source_anchor_ids": ["anc_lem_proof"]}], first["ineffective_targets"])
            self.assertEqual([*audit.body["targets"], targets[1]], db.head("audits", fixture.audit_id).body["targets"])
            work = deepcopy(derive_work(db, audit_id=fixture.audit_id)["tasks"])
            added = [task for task in work if task["id"] not in old_tasks]
            self.assertTrue(added)
            self.assertTrue(all(task["target"] in (targets[1], R("target_specs", "tgt_allowed")) for task in added), added)
            revision = db.max_revision()
            replay = self.add(db, fixture, *targets, version=audit.version)
            self.assertEqual(first["receipt"], replay["receipt"])
            self.assertEqual([targets[0]], [row["target"] for row in replay["ineffective_targets"]])
            self.assertEqual(revision, db.max_revision())
            self.assertEqual(work, derive_work(db, audit_id=fixture.audit_id)["tasks"])
            self.assertEqual(saved, self.preserved(db))

    def test_scope_policy_changes_reject_return_and_skip_stale_packet(self):
        for change in ("removal", "reorder", "exclusions", "independence", "global_tasks"):
            with self.subTest(change=change):
                fixture = self.fixture_with_claim(change, stage="audit")
                with fixture.open() as db:
                    prepared = self.prepare(db, fixture, "primary", R("items", "itm_thm"))
                    envelope, response = self.returned_bytes(fixture, prepared)
                    audit = db.head("audits", fixture.audit_id)
                    values = {"removal": {"targets": [R("items", "itm_thm")]},
                        "reorder": {"targets": list(reversed(audit.body["targets"]))},
                        "exclusions": {"exclusions": [{"target": R("items", "itm_lem"), "source_anchor_ids": [],
                            "reason": "Changed scope.", "consequence": "No lemma examination."}]},
                        "independence": {"independent_required": False},
                        "global_tasks": {"global_tasks": [{"kind": "adversarial", "applicability": "required", "reason": ""}]}}
                    self.replace_audit(db, fixture, **values[change])
                    result = controller.submit_work(db, envelope_bytes=envelope, response_bytes=response)
                    self.assertEqual("conflict", result["state"], result)
                    current = self.prepare(db, fixture, "primary", R("items", "itm_thm"))
                    self.assertTrue(current["prepared"], current)
                    self.assertNotEqual(prepared["packet_id"], current["packet_id"])
                    self.assertEqual(result, controller.submit_work(db, envelope_bytes=envelope, response_bytes=response))

    def test_mathematical_and_setup_changes_still_reject_original_return(self):
        for change in ("statement", "setup", "use", "route", "source"):
            with self.subTest(change=change):
                fixture = self.fixture_with_claim(change, stage="primary")
                with fixture.open() as db:
                    prepared = self.prepare(db, fixture, "independent", R("items", "itm_thm"))
                    envelope, response = self.returned_bytes(fixture, prepared, mode="independent")
                    self.add(db, fixture)
                    if change == "statement":
                        item, spec = db.head("items", "itm_thm"), db.head("target_specs", "tgt_thm")
                        body = deepcopy(item.body)
                        body["statement"]["text"] = "A materially different theorem."
                        fixture.apply(db, [edit("replace", "items", item.id, body, item.version),
                            edit("replace", "target_specs", spec.id, dict(spec.body,
                                statement_ref={**item.ref, "version": item.version + 1}), spec.version)])
                    elif change == "setup":
                        item = db.head("items", "itm_lem")
                        body = deepcopy(item.body)
                        body["statement"]["text"] = "A materially different supplied premise."
                        fixture.apply(db, [edit("replace", "items", item.id, body, item.version)])
                    elif change == "use":
                        use = db.head("uses", "use_lem_thm")
                        fixture.apply(db, [edit("replace", "uses", use.id,
                            dict(use.body, needed_form={"form": "transcription", "text": "An altered required bound."}), use.version)])
                    elif change == "route":
                        argument = db.head("arguments", "arg_thm")
                        fixture.apply(db, [edit("replace", "arguments", argument.id,
                            dict(argument.body, evidence_refs=["anc_thm_proof", "anc_extra_proof"]), argument.version)])
                    else:
                        source = fixture.source_root / "paper.tex"
                        source.write_text(source.read_text(encoding="utf-8").replace("monotonicity gives convergence", "a changed proof gives convergence"), encoding="utf-8")
                        sources.capture_sources(db, files=["paper.tex"])
                    result = controller.submit_work(db, envelope_bytes=envelope, response_bytes=response)
                    self.assertEqual("conflict", result["state"], result)
                    if change == "source":
                        with self.assertRaises(SourceUnavailable):
                            self.prepare(db, fixture, "independent", R("items", "itm_thm"))
                        continue
                    current = self.prepare(db, fixture, "independent", R("items", "itm_thm"))
                    if current["prepared"]:
                        self.assertNotEqual(prepared["packet_id"], current["packet_id"])

    def test_direct_owned_statement_keeps_all_three_stages_without_owner_or_sibling(self):
        fixture = self.fixture_with_claim(route=False)
        with fixture.open() as db:
            authoring.create_record(db, {"key": "sibling", "kind": "claim", "owner_id": "itm_thm", "label": "Sibling",
                "statement": "A separate synthetic owned claim.", "statement_anchors": ["anc_extra"],
                "source_matched": True, "source_note": "Synthetic source comparison."})
            self.add(db, fixture, R("items", "itm_extra"), R("items", "itm_sibling"))
            for mode in ("primary", "independent", "reconcile"):
                prepared = self.prepare(db, fixture, mode, R("items", "itm_extra"))
                self.assertTrue(prepared["prepared"], prepared)
                self.assertEqual([R("items", "itm_extra")], [task["target"] for task in prepared["manifest"]["work"]["tasks"]])
                self.assertIsNone(prepared["manifest"]["work"]["context"]["argument"])
                self.submit(db, fixture, prepared, mode=mode, outcome="inconclusive")
            self.assertIsNone(db.head("arguments", "arg_extra"))
            result = assessment.derive_assessment(db, audit_id=fixture.audit_id)
            self.assertTrue(all(row["satisfied"] for row in result["obligations"]
                if row["target"] == R("items", "itm_extra")))
            self.assertTrue(any(not row["satisfied"] and row["target"] == R("items", "itm_sibling") for row in result["obligations"]))

    def test_global_question_stays_strict_but_local_subset_can_accept(self):
        fixture = self.fixture_with_claim(stage="audit")
        with fixture.open() as db:
            self.replace_audit(db, fixture, global_tasks=[{"kind": "adversarial", "applicability": "required", "reason": ""}])
            global_prepared = self.prepare(db, fixture, "primary", R("audits", fixture.audit_id))
            local_prepared = self.prepare(db, fixture, "primary", R("items", "itm_thm"))
            self.add(db, fixture)
            envelope, response = self.returned_bytes(fixture, global_prepared)
            result = controller.submit_work(db, envelope_bytes=envelope, response_bytes=response)
            self.assertEqual("conflict", result["state"], result)
            fresh = self.prepare(db, fixture, "primary", R("audits", fixture.audit_id))
            self.assertNotEqual(global_prepared["packet_id"], fresh["packet_id"])
            self.submit(db, fixture, local_prepared)
            mixed = deepcopy(local_prepared["manifest"])
            mixed["work"]["tasks"].extend(global_prepared["manifest"]["work"]["tasks"])
            with self.assertRaises(ConflictError):
                validate_assignment_audit(db, mixed)

    def test_independent_supplement_after_addition_requires_new_context_response(self):
        fixture = self.fixture_with_claim(stage="primary")
        with fixture.open() as db:
            extra = fixture.source_root / "supplement.txt"
            extra.write_text("A separately supplied source premise.\n", encoding="utf-8")
            sid = sources.capture_sources(db, files=["supplement.txt"])["sources"][0]["id"]
            author = fixture.packet(db)
            sources.anchor_sources(db, request={"contract_version": 4, "request_id": fixture.request_id(),
                "packet_id": author["packet_id"], "anchors": [{"id": "anc_supplement", "expected_version": None,
                    "source_id": sid, "locator": locator(start=1, end=1)}]})
            prepared = self.prepare(db, fixture, "independent", R("items", "itm_thm"))
            old = deepcopy(db.packet(prepared["packet_id"]))
            old_bytes = db.get_blob(old["payload_sha256"])
            self.add(db, fixture)
            extended = controller.extend_work(db, packet_id=prepared["packet_id"], request={
                "source_refs": [fixture.pin(db, "anchors", "anc_supplement")], "reason": "Additional supplied premise."})
            self.assertTrue(extended["prepared"], extended)
            self.assertEqual(old, db.packet(prepared["packet_id"]))
            self.assertEqual(old_bytes, db.get_blob(old["payload_sha256"]))
            envelope, response = self.returned_bytes(fixture, prepared, mode="independent")
            envelope = json.loads(envelope)
            envelope["rebase_packet_id"] = extended["packet_id"]
            result = controller.submit_work(db, envelope_bytes=json.dumps(envelope).encode(), response_bytes=response)
            self.assertEqual("needs_revision", result["state"], result)
            self.assertEqual("NEW_CONTEXT_RESPONSE_REQUIRED", result["error"]["code"])
            self.submit(db, fixture, extended, mode="independent")

    def test_addition_does_not_authorize_new_task_from_old_assignment(self):
        fixture = self.fixture_with_claim(stage="audit")
        with fixture.open() as db:
            original = self.prepare(db, fixture, "primary", R("items", "itm_thm"))
            self.add(db, fixture)
            fresh = self.prepare(db, fixture, "primary", R("items", "itm_extra"))
            envelope, response = self.returned_bytes(fixture, original)
            worker = json.loads(response)
            worker["results"] = deepcopy(fresh["scaffold"]["results"])
            result = controller.submit_work(db, envelope_bytes=envelope, response_bytes=json.dumps(worker).encode())
            self.assertEqual("needs_revision", result["state"], result)
            self.assertEqual("TASK_SCOPE", result["error"]["code"])
            removed = deepcopy(original["manifest"])
            current = derive_work(db, audit_id=fixture.audit_id)
            with self.assertRaises(ConflictError):
                validate_assignment_audit(db, removed, current_tasks=[task for task in current["tasks"]
                    if task["id"] not in original["assigned_task_ids"]])

    def test_owned_claim_does_not_inherit_owner_exclusion_but_parts_do(self):
        fixture = self.fixture_with_claim(route=False)
        with fixture.open() as db:
            part = R("parts", "par_owned")
            fixture.apply(db, [edit("create", "parts", part["id"], {
                "item_id": "itm_thm", "label": "Part of the owner", "scope_id": "scp_plain", "origin": "source",
                "statement": {"form": "transcription", "text": "The selected part."},
                "passages": [{"role": "statement", "anchor_id": "anc_thm"}]})])
            audit = db.head("audits", fixture.audit_id)
            self.replace_audit(db, fixture, targets=[*audit.body["targets"], part], exclusions=[{
                "target": R("items", "itm_thm"), "source_anchor_ids": [],
                "reason": "Exclude the owner and its parts.", "consequence": "No owner or part proof examination."}])
            self.add(db, fixture)
            result = assessment.derive_assessment(db, audit_id=fixture.audit_id)
            self.assertIn(R("items", "itm_extra"), result["scope"]["target_refs"])
            self.assertFalse(any(row["required"] and row["target"] == part for row in result["obligations"]))
            self.assertIn(part, db.head("audits", fixture.audit_id).body["targets"])
            prepared = self.prepare(db, fixture, "primary", R("items", "itm_extra"))
            self.assertEqual([R("items", "itm_extra")], [task["target"] for task in prepared["manifest"]["work"]["tasks"]])

    def test_owned_item_exact_routes_leave_ambiguity_explicit_and_exclude_owner_siblings(self):
        fixture = self.fixture_with_claim()
        with fixture.open() as db:
            self.add(db, fixture)
            argument, group, boundary = (db.head(collection, identity) for collection, identity in (
                ("arguments", "arg_extra"), ("groups", "grp_extra"), ("proof_boundaries", "bnd_extra")))
            fixture.apply(db, [edit("create", "arguments", "arg_extra_alt", dict(argument.body,
                final_group_id="grp_extra_alt", label="Another explicitly selected source route.")),
                edit("create", "groups", "grp_extra_alt", dict(group.body, argument_id="arg_extra_alt")),
                edit("create", "proof_boundaries", "bnd_extra_alt", dict(boundary.body,
                    argument_ids=["arg_extra_alt"]))])
            with self.assertRaises(InvalidRequest) as caught:
                self.prepare(db, fixture, "primary", R("items", "itm_extra"))
            self.assertEqual("WORK_FOCUS", caught.exception.code)
            self.assertEqual({"arg_extra", "arg_extra_alt"}, {ref["id"] for ref in caught.exception.records})
            exact = self.prepare(db, fixture, "primary", R("arguments", "arg_extra"))
            self.assertEqual([R("arguments", "arg_extra")], [task["target"] for task in exact["manifest"]["work"]["tasks"]])
            selected = self.prepare(db, fixture, "primary", R("items", "itm_extra"),
                task_ids=exact["assigned_task_ids"])
            self.assertEqual(exact["assigned_task_ids"], selected["assigned_task_ids"])

    def test_mixed_excluded_request_replay_reports_saved_omissions_without_source_reevaluation(self):
        fixture = self.fixture_with_claim(route=False)
        with fixture.open() as db:
            authoring.create_record(db, {"key": "allowed", "kind": "claim", "owner_id": "itm_thm", "label": "Allowed",
                "statement": "A synthetic separately allowed claim.", "statement_anchors": ["anc_extra"],
                "source_matched": True, "source_note": "Synthetic source comparison."})
            self.replace_audit(db, fixture, exclusions=[{"target": R("items", "itm_extra"), "source_anchor_ids": [],
                "reason": "Keep this exact claim excluded.", "consequence": "No examination requested."}])
            version = db.head("audits", fixture.audit_id).version
            targets = (R("items", "itm_extra"), R("items", "itm_allowed"))
            first = self.add(db, fixture, *targets, version=version)
            replay = self.add(db, fixture, *targets, version=version)
            self.assertEqual(first["receipt"], replay["receipt"])
            self.assertEqual([row["target"] for row in first["ineffective_targets"]],
                             [row["target"] for row in replay["ineffective_targets"]])
            self.assertEqual("not_added_in_saved_result", replay["ineffective_targets"][0]["reason"])

    def test_actual_mixed_packet_rejects_global_return_but_accepts_unchanged_local_subset(self):
        fixture = self.fixture_with_claim(stage="audit")
        with fixture.open() as db:
            self.replace_audit(db, fixture, global_tasks=[{"kind": "adversarial", "applicability": "required", "reason": ""}])
            view = derive_work(db, audit_id=fixture.audit_id)
            local = select_assignment(view, {"mode": "primary", "focus": R("items", "itm_thm")})
            global_selection = select_assignment(view, {"mode": "primary", "focus": R("audits", fixture.audit_id)})
            combined = dict(local, units=[*local["units"], *global_selection["units"]],
                tasks=[*local["tasks"], *global_selection["tasks"]], max_units=10)
            prepared = controller._assignment_assistance(db, packets.prepare_assignment(db,
                audit_id=fixture.audit_id, mode="primary", selection=combined))
            envelope, all_response = self.returned_bytes(fixture, prepared)
            local_response = json.loads(all_response)
            local_response["results"] = [row for row in local_response["results"]
                if row["task_id"] in local["assigned_task_ids"]]
            local_bytes = json.dumps(local_response).encode()
            local_envelope = dict(json.loads(envelope), request_id=fixture.request_id())
            original = deepcopy(db.packet(prepared["packet_id"]))
            self.add(db, fixture)
            rejected = controller.submit_work(db, envelope_bytes=envelope, response_bytes=all_response)
            self.assertEqual("conflict", rejected["state"], rejected)
            accepted = controller.submit_work(db, envelope_bytes=json.dumps(local_envelope).encode(), response_bytes=local_bytes)
            self.assertEqual("accepted", accepted["state"], accepted)
            self.assertEqual(local_bytes, db.get_blob(db.work_submission(accepted["request_id"])["response_sha256"]))
            self.assertEqual(original, db.packet(prepared["packet_id"]))

    def test_completed_global_becomes_stale_while_completed_local_records_stay_current(self):
        fixture = self.fixture_with_claim()
        with fixture.open() as db:
            self.replace_audit(db, fixture, global_tasks=[{"kind": "adversarial", "applicability": "required", "reason": ""}])
            prepared = self.prepare(db, fixture, "primary", R("audits", fixture.audit_id))
            self.submit(db, fixture, prepared)
            saved = self.preserved(db)
            original = assessment.derive_assessment(db, audit_id=fixture.audit_id)
            self.assertTrue(original["progress"]["process_complete"])
            self.add(db, fixture)
            expanded = assessment.derive_assessment(db, audit_id=fixture.audit_id)
            global_obligation = next(row for row in expanded["obligations"]
                if row["kind"] == "adversarial" and row["target"] == R("audits", fixture.audit_id))
            self.assertFalse(global_obligation["satisfied"])
            self.assertEqual("historical", global_obligation["freshness"])
            self.assertTrue(all(row["satisfied"] for row in expanded["obligations"]
                if row["required"] and row["target"] in (R("arguments", "arg_lem"), R("arguments", "arg_thm"))))
            self.assertEqual(saved, self.preserved(db))
