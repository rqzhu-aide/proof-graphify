"""One stitched mechanical trace; all reviewers and qualifications are synthetic.

This exercises protocol recovery, not the truth of the fixture's mathematical
claims and not a fresh model run. All database mutations use public APIs.
"""
import copy
import json
from unittest.mock import patch

from support import R, TempCase, edit, locator, node_available
from paper_core import assistance, controller, review, sources
from paper_core.assessment import derive_full
from paper_core.canonical import canonical_bytes
from paper_core.errors import InvalidRequest
from paper_core.projection import build_projection
from paper_core.publish import publish_report


class RevisionRecoveryTraceTests(TempCase):
    def envelope(self, packet, *, independent=False, continuation=False):
        return {"contract_version": 4, "request_id": self.fx.request_id(), "packet_id": packet["packet_id"],
            "rebase_packet_id": None, "reviewer": "checker-A" if independent else "primary-1",
            "qualification_id": "qua_r1" if independent else None, "exposure": "source_only" if independent else None,
            "exposure_note": ("Synthetic same-reviewer continuation of its own prior source-only response."
                              if continuation else "Synthetic source-only dispatch; software fixture only.") if independent else ""}

    def submit(self, packet, response, **kwargs):
        return controller.submit_work(self.db, envelope_bytes=canonical_bytes(self.envelope(packet, **kwargs)),
                                      response_bytes=canonical_bytes(response))

    def primary_response(self, prepared, *, draft_task=None, replacements=None, predecessors=None):
        response = copy.deepcopy(prepared["scaffold"])
        tasks = {task["id"]: task for task in prepared["manifest"]["work"]["tasks"]}
        included = []
        for row in response["results"]:
            task = tasks[row["task_id"]]
            record = self.db.head(task["target"]["collection"], task["target"]["id"])
            if record.collection == "target_specs":
                record = self.db.head(record.body["target"]["collection"], record.body["target"]["id"])
            if row["type"] == "source_fidelity":
                anchors = record.body.get("evidence_refs") or [p["anchor_id"] for p in record.body["passages"] if p["role"] == "statement"]
                row.update(result="matched", note="Synthetic fixture comparison against the captured statement.", evidence_refs=anchors)
            else:
                if draft_task and row["task_id"] != draft_task:
                    continue
                anchors = record.body["evidence_refs"]
                row.update(state="draft" if draft_task else "complete", outcome=None if draft_task else "supported",
                    reasoning="Synthetic partial argument recorded." if draft_task else "Synthetic renewed examination of the assigned exact inference.",
                    evidence_refs=anchors, next_action="Finish this derivation." if draft_task else None,
                    replaces=(replacements or {}).get(row["task_id"]), supersedes=(predecessors or {}).get((record.collection, record.id)))
                if task["kind"] == "composition" and not draft_task:
                    name = record.id.removeprefix("arg_")
                    anchor = self.db.head("anchors", "anc_" + name + "_proof")
                    old = next((c for c in self.db.heads("coverage") if c.body["argument_id"] == record.id), None)
                    response["coverage"].append({"argument_id": record.id, "anchor_id": anchor.id,
                        "start_offset": 0, "end_offset": len(anchor.body["excerpt"]), "classification": "substantive",
                        "claim_refs": [record.body["target"]], "check_task_ids": [task["id"]], "existing_check_refs": [],
                        "replaces": None if old is None else old.pinned, "note": "Synthetic composition covers this captured proof."})
            included.append(row)
        response["results"] = included
        return response

    def finish_primary(self, *, predecessors=None):
        completed = []
        for _ in range(8):
            prepared = controller.prepare_work(self.db, audit_id=self.fx.audit_id, mode="primary", max_units=10,
                                                allow_provisional=True)
            if not prepared["prepared"]:
                return completed
            result = self.submit(prepared, self.primary_response(prepared, predecessors=predecessors))
            self.assertEqual("accepted", result["state"], result)
            completed.extend(result["record_map"].values())
        self.fail("synthetic primary trace failed to reach a stable checkpoint")

    def independent(self, prepared, name, *, outcome="supported", predecessor=None, extra=False, recovery_events=None):
        response = {"packet_id": prepared["packet_id"], "covered_targets": [R("items", "itm_" + name)],
            "coverage_note": "Synthetic whole-argument examination; no fresh scientific evaluation.",
            "exposure_report": {"status": "none_known", "note": "Same synthetic reviewer retains only its own prior response." if predecessor else ""},
            "judgments": [{"target": {"source_anchor_id": "anc_" + name + "_proof", "description": "Whole written argument"},
                "kind": "composition", "state": "complete", "outcome": outcome,
                "reasoning": "The auxiliary source statement is missing." if outcome in ("inconclusive", "gap") else
                             "Synthetic renewed examination includes the supplied context and the entire argument.",
                "evidence_refs": ["anc_" + name + "_proof"] + (["anc_aux"] if extra else []),
                "conditions": [], "next_action": None, "supersedes": predecessor}]}
        raw = canonical_bytes(response)
        if recovery_events is None:
            submitted = self.submit(prepared, response, independent=True, continuation=predecessor is not None)
        else:
            # This explicitly known directory has a misleading name. Identity
            # comes from the packet and response, never from the folder label.
            directory = self.path("known-assignments", "independent-theorem")
            revision, response_count = self.db.max_revision(), len(self.db.heads("responses"))
            controller.write_artifacts(self.db, prepared, directory)
            (directory / "response.json").write_bytes(raw)
            envelope = self.envelope(prepared, independent=True)
            envelope_raw = canonical_bytes(envelope)
            (directory / "submission-envelope.json").write_bytes(envelope_raw)
            inspected = controller.inspect_work(self.db, packet_id=prepared["packet_id"])
            self.assertEqual([], inspected["submissions"])
            self.assertIsNone(self.db.work_submission(envelope["request_id"]))
            self.assertEqual(revision, self.db.max_revision())
            self.assertEqual(response_count, len(self.db.heads("responses")))
            self.assertFalse(any(check.body["role"] == "independent" for check in self.db.heads("checks")))
            candidate = json.loads((directory / "response.json").read_bytes())
            self.assertEqual(prepared["packet_id"], candidate["packet_id"])
            self.assertEqual([R("items", "itm_lem")], candidate["covered_targets"])
            recovery_events.append({"step": "unsent_response_found", "folder_label": directory.name,
                "actual_target": "items:itm_lem", "database_credit": False})

            unrelated = controller.prepare_work(self.db, audit_id=self.fx.audit_id,
                mode="independent", focus=R("items", "itm_thm"))
            wrong = self.envelope(unrelated, independent=True)
            rejected = controller.submit_work(self.db, envelope_bytes=canonical_bytes(wrong), response_bytes=raw)
            self.assertEqual("PACKET_MISMATCH", rejected["error"]["code"], rejected)
            self.assertEqual(revision, self.db.max_revision())

            with patch.object(controller, "accept_in_transaction", side_effect=RuntimeError("synthetic interruption")):
                interrupted = controller.submit_work(self.db, envelope_bytes=envelope_raw, response_bytes=raw)
            self.assertEqual("received", interrupted["state"], interrupted)
            self.assertEqual(revision, self.db.max_revision())
            self.db.close()
            self.db = self.fx.open()
            self.addCleanup(self.db.close)
            retained = controller.inspect_work(self.db, request_id=envelope["request_id"])
            self.assertEqual("replay_saved_submission", retained["current"]["recovery"][0]["operation"])
            recovered = self.path("recovered-intake")
            controller.write_artifacts(self.db, retained, recovered)
            self.assertEqual(envelope_raw, (recovered / "submission-envelope.json").read_bytes())
            self.assertEqual(raw, (recovered / "worker-response.json").read_bytes())
            submitted = controller.submit_work(self.db,
                envelope_bytes=(recovered / "submission-envelope.json").read_bytes(),
                response_bytes=(recovered / "worker-response.json").read_bytes())
            self.assertEqual(envelope["request_id"], submitted["request_id"])
            self.assertEqual(raw, (directory / "response.json").read_bytes())
            recovery_events.append({"step": "interrupted_intake_replayed", "same_request": True,
                "exact_bytes_preserved": True, "still_needs_mapping": submitted["state"] == "needs_revision"})
        self.assertEqual("needs_revision", submitted["state"], submitted)
        authority = self.fx.packet(self.db, "items:itm_" + name, mode="reconcile")
        mapping = assistance.mapping_template(source_packet_id=prepared["packet_id"], mapping_packet_id=authority["packet_id"],
            response_id=submitted["response_id"], judgment_indexes=[0])["template"]
        mapping["reviewer"] = "synthetic-coordinator"
        mapping["entries"][0].update(target=R("arguments", "arg_" + name), rationale="Exact source proof overlaps this argument.")
        mapped = review.map_response(self.db, mapping=mapping)
        self.assertEqual("accepted", mapped["state"], mapped)
        check = self.db.head("checks", mapped["checks"][0]["check_id"])
        self.assertEqual(response["judgments"][0]["outcome"], check.body["outcome"])
        self.assertEqual(response["judgments"][0]["reasoning"], check.body["reasoning"])
        saved = self.db.head("responses", submitted["response_id"])
        self.assertEqual(raw, self.db.get_blob(saved.body["original_blob"]))
        return check, saved, raw

    def primary_composition(self, name):
        _, state = derive_full(self.db, audit_id=self.fx.audit_id)
        rows = [j for j in state["judgments"].values() if j["target"] == R("arguments", "arg_" + name)
                and j["role"] == "primary" and j["freshness"] == "current" and not j["superseded"]]
        self.assertEqual(1, len(rows), rows)
        return self.db.head("checks", rows[0]["ref"]["id"])

    def reconcile(self, name, independent, *, predecessor=None):
        packet = self.fx.packet(self.db, "items:itm_" + name, mode="reconcile")
        body = {"audit_id": self.fx.audit_id, "target": R("arguments", "arg_" + name),
            "primary_checks": [self.primary_composition(name).pinned],
            "independent_checks": ([predecessor.pinned] if predecessor else []) + [independent.pinned],
            "decision": "independent_revised" if predecessor else "agree",
            "rationale": "Synthetic exact-target comparison, including the explicitly replaced opinion; mechanical evidence only.",
            "evidence_refs": ["anc_" + name + "_proof"], "successor_checks": [independent.pinned] if predecessor else [], "supersedes": None,
            "adjudicator": "synthetic-coordinator"}
        try:
            review.reconcile(self.db, batch=self.fx.batch([edit("create", "reconciliations", "rec_trace_" + name, body)], packet["packet_id"]))
        except InvalidRequest as exc:
            self.fail(str(exc.records))

    def test_stitched_draft_context_and_statement_recovery(self):
        self.fx = self.fixture().audit()
        self.db = self.fx.open()
        self.addCleanup(self.db.close)
        events = []
        initial = controller.prepare_work(self.db, audit_id=self.fx.audit_id, mode="primary", focus=R("items", "itm_lem"))
        task = next(t for t in initial["manifest"]["work"]["tasks"] if t["kind"] == "derivation")
        saved = self.submit(initial, self.primary_response(initial, draft_task=task["id"]))
        self.assertEqual("accepted", saved["state"], saved)
        draft = self.db.head("checks", saved["record_map"][task["id"]]["id"])
        events.append({"step": "draft_saved", "state": draft.body["state"], "version": draft.version})
        resumed = controller.prepare_work(self.db, audit_id=self.fx.audit_id, mode="primary", focus=R("items", "itm_lem"))
        result = self.submit(resumed, self.primary_response(resumed, replacements={task["id"]: draft.pinned}))
        self.assertEqual("accepted", result["state"], result)
        continued = self.db.head("checks", draft.id)
        self.assertEqual(draft.version + 1, continued.version)
        self.assertEqual("complete", continued.body["state"])
        self.assertEqual(1, len([c for c in self.db.heads("checks") if c.body["target"] == task["target"]
                                 and c.body["reviewer"] == "primary-1" and c.body["kind"] == "derivation"]))
        events.append({"step": "draft_replaced", "state": continued.body["state"], "same_id": continued.id == draft.id,
                       "version": continued.version})
        self.finish_primary()
        blind = controller.prepare_work(self.db, audit_id=self.fx.audit_id, mode="independent", focus=R("items", "itm_lem"))
        first, first_response, first_raw = self.independent(blind, "lem", outcome="gap", recovery_events=events)
        events.append({"step": "missing_context_review", "state": first_response.body["state"], "outcome": first.body["outcome"]})
        (self.fx.source_root / "auxiliary.txt").write_text("Synthetic auxiliary statement for mechanical recovery only.\n", encoding="utf-8")
        source_id = sources.capture_sources(self.db, files=["auxiliary.txt"])["sources"][0]["id"]
        packet = self.fx.packet(self.db)
        sources.anchor_sources(self.db, request={"contract_version": 4, "request_id": self.fx.request_id(), "packet_id": packet["packet_id"],
            "anchors": [{"id": "anc_aux", "expected_version": None, "source_id": source_id, "locator": locator(start=1, end=1)}]})
        extended = controller.extend_work(self.db, packet_id=blind["packet_id"], request={"source_refs": [self.db.head("anchors", "anc_aux").pinned],
            "reason": "The requested neutral auxiliary source has now been captured."})
        self.assertEqual(blind["assigned_task_ids"], extended["assigned_task_ids"])
        successor, _, _ = self.independent(extended, "lem", predecessor=first.pinned, extra=True)
        self.assertEqual(first.pinned, successor.body["supersedes"])
        self.assertEqual(first_raw, self.db.get_blob(first_response.body["original_blob"]))
        self.assertEqual("gap", self.db.version("checks", first.id, first.version).body["outcome"])
        events.append({"step": "extended_successor", "state": "accepted", "outcome": successor.body["outcome"],
                       "same_obligations": True, "historical_bytes_preserved": True})
        self.reconcile("lem", successor, predecessor=first)
        events.append({"step": "lemma_reconciled", "decision": self.db.head("reconciliations", "rec_trace_lem").body["decision"]})
        preserved = self.primary_composition("lem")
        before = derive_full(self.db, audit_id=self.fx.audit_id)[1]
        predecessors = {(j["target"]["collection"], j["target"]["id"]): j["ref"] for j in before["judgments"].values()
                        if j["role"] == "primary" and j["state"] == "complete" and not j["superseded"]}
        theorem, exact = self.db.head("items", "itm_thm"), self.db.head("target_specs", "tgt_thm")
        repaired = dict(theorem.body, statement={"form": "verbatim", "text": self.db.head("anchors", "anc_thm").body["excerpt"]})
        self.fx.apply(self.db, [edit("replace", "items", theorem.id, repaired, theorem.version),
            edit("replace", "target_specs", exact.id, dict(exact.body,
                statement_ref={"collection": "items", "id": theorem.id, "version": theorem.version + 1}), exact.version)],
            "items:itm_thm", mode="primary")
        _, changed = derive_full(self.db, audit_id=self.fx.audit_id)
        stale = [j for j in changed["judgments"].values() if j["role"] == "primary" and j["freshness"] != "current" and not j["superseded"]]
        self.assertTrue(stale)
        kept = next(j for j in changed["judgments"].values() if j["ref"] == preserved.pinned)
        self.assertEqual("current", kept["freshness"])
        events.append({"step": "statement_repaired", "affected_primary_checks": len(stale), "lemma_composition": kept["freshness"]})
        self.finish_primary(predecessors=predecessors)
        renewed = self.primary_composition("thm")
        self.assertEqual(predecessors[("arguments", "arg_thm")], renewed.body["supersedes"])
        final_packet = controller.prepare_work(self.db, audit_id=self.fx.audit_id, mode="independent", focus=R("items", "itm_thm"))
        independent, _, _ = self.independent(final_packet, "thm")
        self.reconcile("thm", independent)
        events.append({"step": "affected_work_renewed", "primary_successor": True, "reconciliation": "agree"})
        projection = build_projection(self.db, audit_id=self.fx.audit_id)
        if node_available():
            report = publish_report(self.db, projection=projection, output=self.path("working.html"), release=False)
            self.assertEqual("published", report["state"])
            events.append({"step": "working_report", "state": report["state"], "release_requested": False})
        else:
            events.append({"step": "working_report", "state": "not_rendered", "reason": "Node unavailable"})
        trace = {"evidence_kind": "mechanical integration only; synthetic qualification and authored judgments",
                 "events": events, "process_complete": projection["summary"]["progress"]["process_complete"]}
        self.path("mechanical-recovery-trace.json").write_text(json.dumps(trace, indent=2) + "\n", encoding="utf-8")
        print("MECHANICAL_RECOVERY_TRACE " + json.dumps(trace, sort_keys=True))
