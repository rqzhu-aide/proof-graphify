"""The coordinator view projects delivered facts, not new scientific judgments."""
import copy
from types import SimpleNamespace
from unittest.mock import patch

from support import R, TempCase, edit
from paper_core import assistance, controller, stage1
from paper_core.assessment import derive_full
from paper_core.canonical import canonical_bytes


def record(collection, identifier, body, version=1):
    return SimpleNamespace(collection=collection, id=identifier, version=version, retired=False,
                           ref=R(collection, identifier), pinned=dict(R(collection, identifier), version=version), body=body)


class DecisionContextTests(TempCase):
    def project(self, target, delivered, *, findings=(), displays=None, tasks=(), constituents=None):
        pins = [row.pinned for row in delivered]
        versions = {(row.collection, row.id, row.version): row for row in delivered}
        calls = []

        def version(*key):
            calls.append(key)
            self.assertIn(key, versions, "projection fetched an undelivered record")
            return versions[key]

        db = SimpleNamespace(version=version)
        index = assistance._decision_context_index(db, pins + pins)
        self.assertEqual(len(versions), len(calls), "delivered versions should be loaded once")
        by_target = {}
        for finding in findings:
            key = f"{finding.body['target']['collection']}:{finding.body['target']['id']}"
            by_target.setdefault(key, []).append(finding)
        derivation = SimpleNamespace(findings_by_target=by_target,
                                     review_display=SimpleNamespace(displays=displays or {}))
        assessment = {"audit_id": "aud_1", "obligations": list(tasks), "constituents": constituents or {}}
        with patch("paper_core.assessment.derive_full", side_effect=AssertionError("no second assessment")), \
             patch("paper_core.packets.neutral_question", side_effect=AssertionError("no unrestricted question")):
            result = assistance._reconciliation_context(target, index, derivation=derivation, assessment=assessment)
        self.assertEqual(len(versions), len(calls))
        return result

    def test_local_part_argument_and_exact_formulation_keep_pins_and_scope_provenance(self):
        parent = record("items", "theorem", {"statement": {"text": "The whole theorem"}})
        part = record("parts", "local", {"statement": {"text": "Local assertion"}, "item_id": "theorem"}, version=2)
        old = record("parts", "local", {"statement": {"text": r"Local $x>0$"}, "item_id": "theorem"})
        argument = record("arguments", "proof", {"target": part.ref, "scope_id": "branch"})
        spec = record("target_specs", "exact", {"target": part.ref, "statement_ref": old.pinned,
            "statement": None, "state": "registered", "scope_id": "root"})
        root = record("scopes", "root", {"parent_id": None, "conditions": ["n >= 1"], "binders": [{"symbol": "n"}], "assumptions": []})
        branch = record("scopes", "branch", {"parent_id": "root", "conditions": ["n >= 1", "x > 0"], "binders": [], "assumptions": [part.ref]})
        # Exact specifications pin an older version of the same target.
        # Multiple delivered base versions remain ambiguous without losing that pin.
        result = self.project(argument.ref, [parent, part, old, argument, spec, root, branch])
        self.assertNotIn("statement", result)
        self.assertNotIn("statement_ref", result)
        self.assertTrue(result["projection_limits"])
        self.assertEqual(old.body["statement"], result["exact_formulation"]["statement"])
        self.assertEqual(old.pinned, result["exact_formulation"]["statement_ref"])
        self.assertEqual(part.ref, result["exact_formulation"]["target"])
        self.assertEqual([branch.pinned, root.pinned], [s["ref"] for s in result["scope_ancestry"]])
        common = next(row for row in result["conditions"] if row["value"] == "n >= 1")
        self.assertEqual([branch.pinned, root.pinned], common["scope_refs"])
        self.assertEqual([branch.pinned], result["assumptions"][0]["scope_refs"])
        self.assertNotIn("The whole theorem", str(result))
        direct = self.project(part.ref, [parent, part])
        self.assertEqual(part.body["statement"], direct["statement"])
        self.assertEqual(parent.pinned, direct["owner_ref"])
        root.body["parent_id"] = "branch"
        cyclic = self.project(argument.ref, [parent, part, old, argument, spec, root, branch])
        self.assertIn("cyclic", str(cyclic["projection_limits"]))

    def test_real_same_target_spec_keeps_exact_old_pin_when_both_versions_are_delivered(self):
        fx = self.fixture(coherent=True).audit(independent_required=False)
        with fx.open() as db:
            old = db.head("items", "itm_lem")
            spec = db.head("target_specs", "tgt_lem")
            scope = db.head("scopes", "scp_plain")
            fx.apply(db, [
                edit("replace", "items", old.id, dict(old.body,
                    statement={"form": "synopsis", "text": "A later displayed synopsis."}), old.version),
                edit("replace", "target_specs", spec.id, dict(spec.body, scope_id=scope.id), spec.version),
                edit("replace", "scopes", scope.id, dict(scope.body, conditions=["n >= 1"]), scope.version),
            ], "items:itm_lem", mode="primary")
            packet = fx.packet(db, "items:itm_lem", mode="reconcile")
            delivered = db.packet(packet["packet_id"])["manifest"]["read_set"]
            self.assertNotIn(old.pinned, delivered)
            derivation, assessment = derive_full(db, audit_id=fx.audit_id)
            before = db.max_revision()
            limited_index = assistance._decision_context_index(db, delivered)
            limited = assistance._reconciliation_context(old.ref, limited_index,
                derivation=derivation, assessment=assessment)
            self.assertEqual("A later displayed synopsis.", limited["statement"]["text"])
            self.assertNotIn("statement", limited["exact_formulation"])
            self.assertIn("exact target formulation is absent", str(limited["projection_limits"]))

            # Simulate delivery of the known exact older version as well. The
            # records themselves were accepted through the real authoring route.
            full_index = assistance._decision_context_index(db, [*delivered, old.pinned])
            with patch("paper_core.assessment.derive_full", side_effect=AssertionError("reuse assessment")), \
                 patch.object(db, "head", side_effect=AssertionError("no live head selection")):
                for target in (old.ref, R("arguments", "arg_lem")):
                    result = assistance._reconciliation_context(target, full_index,
                        derivation=derivation, assessment=assessment)
                    self.assertNotIn("statement", result)
                    self.assertEqual(old.body["statement"], result["exact_formulation"]["statement"])
                    self.assertEqual(old.pinned, result["exact_formulation"]["statement_ref"])
                    self.assertEqual(old.ref, result["exact_formulation"]["target"])
                    self.assertIn("ambiguous delivered versions", str(result["projection_limits"]))
                    self.assertEqual(db.version("scopes", scope.id, scope.version + 1).pinned,
                                     result["conditions"][0]["scope_refs"][0])
            self.assertEqual(before, db.max_revision())

    def test_projection_uses_pinned_body_not_a_later_head_and_reports_local_limits(self):
        item = record("items", "claim", {"statement": {"text": "Pinned claim"}, "scope_id": "missing"})
        newer = record("items", "claim", {"statement": {"text": "Later head"}}, version=2)
        result = self.project(item.ref, [item])
        self.assertEqual(item.body["statement"], result["statement"])
        self.assertNotIn(newer.body["statement"]["text"], str(result))
        self.assertTrue(result["projection_limits"])
        specs = [record("target_specs", name, {"target": item.ref, "statement": {"text": name},
                 "state": "registered", "scope_id": None}) for name in ("one", "two")]
        ambiguous = self.project(item.ref, [item, *specs])
        self.assertNotIn("exact_formulation", ambiguous)
        self.assertIn("ambiguous", str(ambiguous["projection_limits"]))
        self.assertNotIn("task", str(ambiguous["projection_limits"]))

    def test_only_direct_and_explicit_statement_findings_use_existing_display_status(self):
        item = record("items", "claim", {"statement": {"text": "Claim"}})
        argument = record("arguments", "proof", {"target": item.ref})
        findings = [record("findings", identifier, {"audit_id": "aud_1", "target": target,
            "lifecycle": "open", "category": "proof_gap", "description": identifier,
            "impact_reason": "Saved qualification"}) for identifier, target in (
                ("direct", argument.ref), ("linked", item.ref), ("sibling", R("arguments", "other")),
                ("stale", argument.ref), ("unclassified", argument.ref))]
        displays = {"direct": {"status": "unresolved"}, "linked": {"status": "moderate"}, "stale": {"status": "historical"}}
        result = self.project(argument.ref, [item, argument, *findings], findings=findings, displays=displays)
        rows = {row["ref"]["id"]: row for row in result["findings"]}
        self.assertNotIn("sibling", rows)
        self.assertEqual("argument_statement", rows["linked"]["relation"])
        for identifier, status in (("direct", "unresolved"), ("stale", "historical"), ("unclassified", "unavailable")):
            self.assertEqual(status, rows[identifier]["review_display"]["status"])
        omitted = self.project(argument.ref, [item, argument], findings=findings, displays=displays)
        self.assertNotIn("findings", omitted)

    def test_authority_comes_from_selected_current_task_not_newest_saved_reconciliation(self):
        item = record("items", "claim", {"statement": {"text": "Claim"}})
        argument = record("arguments", "proof", {"target": item.ref})
        selected = record("reconciliations", "selected", {"target": item.ref, "decision": "unresolved", "rationale": "Saved uncertainty"})
        newest = record("reconciliations", "newest", {"target": argument.ref, "decision": "agree", "rationale": "Not authoritative"}, version=3)
        task = {"id": "integration", "kind": "reconciliation", "target": argument.ref, "satisfied": True}
        saved = {"integration": {"state": "complete", "freshness": "current", "disputed": True, "check_refs": [selected.pinned]}}
        args = dict(tasks=[task], constituents=saved)
        result = self.project(argument.ref, [item, argument, selected, newest], **args)
        current = result["integrations"][0]["current_reconciliation"]
        self.assertEqual(selected.pinned, current["ref"])
        self.assertEqual("unresolved", current["decision"])
        for change in ({"freshness": "needs_review"}, {"unaccounted": True}):
            changed = copy.deepcopy(saved)
            changed["integration"].update(change)
            result = self.project(argument.ref, [item, argument, selected, newest], tasks=[task], constituents=changed)
            self.assertNotIn("current_reconciliation", result["integrations"][0])
        task["satisfied"] = False
        result = self.project(argument.ref, [item, argument, selected, newest], **args)
        self.assertNotIn("current_reconciliation", result["integrations"][0])

    def test_generated_note_preserves_reconciliation_guidance(self):
        note = assistance._response_guidance("reconcile")["note"]
        self.assertIn("For a disputed printed symbol, use available source evidence", note)
        self.assertIn("Assess disputed reasoning under the exact claim, hypotheses, definitions and regime; agreement and labels are not decisive.", note)
        self.assertIn("decision_context supplies existing records when available, without requiring another packet read.", note)
        self.assertIn("Reuse saved reasoning, preserving surviving grounds, original opinions, history, unresolved consequences and coverage limits.", note)
        self.assertNotIn("Compare saved reasoning and conditions and author the decision and rationale.", note)
        self.assertTrue(note.endswith("Stage 2 generates the submission envelope. If response_dispositions are listed, explain how the preserved extra rows are handled, retaining material unresolved concerns. Do not fabricate an independent examination to repair a peripheral response field."))
        self.assertNotIn("template DB", note)

    def test_group_and_use_compatibility_rows_get_no_whole_theorem_context(self):
        checks = [record("checks", collection, {"target": R(collection, "local"), "kind": "composition",
            "role": "primary", "reviewer": "primary", "state": "complete", "outcome": "supported",
            "reasoning": "Saved opinion", "conditions": [], "evidence_refs": [], "next_action": None,
            "supersedes": None}) for collection in ("groups", "uses")]
        db = SimpleNamespace(version=lambda collection, identifier, version: next(row for row in checks if row.id == identifier),
                             max_revision=lambda: 1)
        derivation = SimpleNamespace(audit=SimpleNamespace(body={"protocol_version": "coherent-proof-audit/1"}),
                                     integration_eligible=lambda info: True)
        judgments = {row.id: {"ref": row.pinned, "target": row.body["target"], "audit_id": "aud_1",
                    "state": "complete", "freshness": "current", "superseded": False, "role": "primary"} for row in checks}
        manifest = {"mode": "reconcile", "packet_id": "packet", "read_set": [row.pinned for row in checks],
                    "work": {"audit_id": "aud_1", "tasks": []}}
        result = assistance.coordinator_guidance(db, manifest, assessed=(derivation,
            {"audit_id": "aud_1", "revision": 1, "judgments": judgments}))
        self.assertEqual(2, len(result["reconciliation_candidates"]))
        self.assertNotIn("decision_context", str(result))

    def test_coherent_view_is_read_only_and_private_without_scaffold_changes(self):
        fx = self.fixture(coherent=True).primary()
        with fx.open() as db:
            independent = stage1.prepare_stage(db, audit_id=fx.audit_id, stage=2,
                mode="independent", focus=R("items", "itm_lem"))
            self.assertTrue(independent["prepared"], independent)
            response = copy.deepcopy(independent["scaffold"])
            response.update(coverage_note="Synthetic complete separate examination.",
                            exposure_report={"status": "none_known", "note": "Synthetic source-only context."})
            for row in response["judgments"]:
                row.update(state="complete", outcome="supported", extent="whole_unit", omissions="",
                           reasoning="Synthetic complete proof examination.", conditions=[])
            raw = canonical_bytes(response)
            envelope = controller.stage_submission_envelope(packet_id=independent["packet_id"],
                reviewer="context-test-independent", response_bytes=raw, exposure="source_only",
                exposure_note="Synthetic separate examination.")
            submitted = controller.submit_work(db, envelope_bytes=canonical_bytes(envelope), response_bytes=raw)
            self.assertEqual("accepted", submitted["state"], submitted)
            prepared = controller.prepare_work(db, audit_id=fx.audit_id, mode="reconcile", focus=R("items", "itm_lem"))
            self.assertTrue(prepared["prepared"], prepared)
            assessed = derive_full(db, audit_id=fx.audit_id)
            before = db.max_revision()
            scaffold = copy.deepcopy(prepared["scaffold"])
            with patch("paper_core.assessment.derive_full", side_effect=AssertionError("reuse assessment")):
                guidance = assistance.coordinator_guidance(db, prepared["manifest"], assessed=assessed)
            rows = guidance["reconciliation_candidates"]
            self.assertTrue(any("decision_context" in row for row in rows))
            self.assertTrue(all("decision_context" not in row for row in rows if row["target"]["collection"] in ("groups", "uses")))
            self.assertEqual(before, db.max_revision())
            self.assertEqual(scaffold, prepared["scaffold"])
            self.assertNotIn("decision_context", prepared["worker_guidance"])
            for value in (prepared["source_navigation"], prepared["packet"], prepared["scaffold"]):
                self.assertNotIn("decision_context", str(value))
            blind = copy.deepcopy(prepared["manifest"])
            blind["mode"] = "independent"
            with patch("paper_core.assessment.derive_full", side_effect=AssertionError("blind guidance does not assess")):
                self.assertNotIn("decision_context", str(assistance.coordinator_guidance(db, blind)))
            with patch.object(assistance, "_decision_context_index", side_effect=AssertionError("validation needs only opinions")):
                opinion_guidance = assistance.coordinator_guidance(db, prepared["manifest"],
                    assessed=assessed, include_context=False)
            expected = copy.deepcopy(guidance)
            for row in expected["reconciliation_candidates"]:
                row.pop("decision_context", None)
            self.assertEqual(expected, opinion_guidance)

            authored = copy.deepcopy(scaffold)
            for row in authored["integrations"]:
                row.update(decision="agree", rationale="The saved examinations agree under the exact supplied premises.",
                           evidence_refs=[])
            raw = canonical_bytes(authored)
            envelope = controller.stage_submission_envelope(packet_id=prepared["packet_id"],
                reviewer="context-test-coordinator", response_bytes=raw)
            with patch.object(assistance, "_decision_context_index", side_effect=AssertionError("submission must omit unused projection")):
                submitted = controller.submit_work(db, envelope_bytes=canonical_bytes(envelope), response_bytes=raw)
            self.assertEqual("accepted", submitted["state"], submitted)
            saved = db.heads("reconciliations")
            self.assertTrue(saved)
            for reconciliation in saved:
                candidate = next(row for row in rows if row["target"] == reconciliation.body["target"])
                self.assertEqual(candidate["primary_checks"], reconciliation.body["primary_checks"])
                self.assertEqual(candidate["independent_checks"], reconciliation.body["independent_checks"])
