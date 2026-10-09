"""Explicit corrections retain completed work, saved opinions, and comparison history."""
from copy import deepcopy
import json

from support import R, TempCase, edit, locator, run_cli, write_json
from paper_core import controller, packets, sources, stage1, stage2
from paper_core.errors import InvalidRequest
from paper_core.work import derive_work, select_assignment


class IntegrationCorrectionTests(TempCase):
    @staticmethod
    def tasks(db, fixture):
        return {task["target"]["id"]: task["id"]
                for task in derive_work(db, audit_id=fixture.audit_id)["tasks"]
                if task["role"] == "coordinator"}

    @staticmethod
    def records(db):
        return {collection: {row.id: (row.pinned, deepcopy(row.body),
                    db.get_blob(row.body["original_blob"]) if collection == "responses" else None)
                for row in db.heads(collection)}
                for collection in ("checks", "responses", "reconciliations", "findings")}

    @staticmethod
    def comparisons(db, target):
        return sorted((row for row in db.heads("reconciliations") if row.body["target"] == target),
                      key=lambda row: (row.revision, row.id))

    @staticmethod
    def response(prepared, decision="unresolved"):
        response = deepcopy(prepared["scaffold"])
        for row in response["integrations"]:
            row.update(decision=decision, rationale="Synthetic correction of the saved comparison; retain the original opinions.")
        return response

    @staticmethod
    def submit(db, fixture, prepared, response):
        envelope = dict(prepared["submission_envelope_template"],
                        request_id=fixture.request_id(), reviewer="coordinator")
        return controller.submit_work(db, envelope_bytes=json.dumps(envelope).encode(),
                                      response_bytes=json.dumps(response).encode())

    @staticmethod
    def prepare(db, fixture, task_ids):
        return stage2.prepare(db, audit_id=fixture.audit_id, mode="reconcile",
                              task_ids=task_ids, correct=True)

    def test_cli_correction_replay_and_current_successor_preserve_completed_work(self):
        fixture = self.fixture().complete()
        target = R("arguments", "arg_thm")
        with fixture.open() as db:
            original = self.records(db)
            task_id = self.tasks(db, fixture)["arg_thm"]
            predecessor = self.comparisons(db, target)[-1]
            self.assertFalse(stage2.prepare(db, audit_id=fixture.audit_id, mode="reconcile")["prepared"])
            prepared = self.prepare(db, fixture, [task_id])
            repeated = self.prepare(db, fixture, [task_id])
            self.assertTrue(repeated["reused"])
            self.assertEqual(prepared["packet_id"], repeated["packet_id"])
            self.assertEqual(original, self.records(db))
        cli_prepared, _ = run_cli("stage2", "prepare", fixture.path, "--audit", fixture.audit_id,
            "--mode", "integration", "--correct", "--task", task_id)
        self.assertTrue(cli_prepared["correction"])
        self.assertEqual(prepared["packet_id"], cli_prepared["packet_id"])
        response_path = write_json(self.path("correction.json"), self.response(prepared))
        args = ("stage2", "integrate", fixture.path, "--packet", prepared["packet_id"],
                "--reviewer", "coordinator", "--response", response_path)
        accepted, _ = run_cli(*args)
        self.assertEqual("accepted", accepted["state"], accepted)
        self.assertFalse(accepted["replayed"])
        with fixture.open() as db:
            current = self.comparisons(db, target)[-1]
            self.assertEqual(predecessor.pinned, current.body["supersedes"])
            saved = self.records(db)
            revision = db.max_revision()
        replay, _ = run_cli(*args)
        self.assertTrue(replay["replayed"])
        self.assertEqual(accepted["request_id"], replay["request_id"])
        with fixture.open() as db:
            self.assertEqual(saved, self.records(db))
            self.assertEqual(revision, db.max_revision())
            stale = self.submit(db, fixture, repeated, self.response(repeated, "agree"))
            self.assertIn(stale["state"], ("needs_revision", "conflict"), stale)
            self.assertEqual(saved, self.records(db))
            self.assertEqual(revision, db.max_revision())
            fresh = self.prepare(db, fixture, [task_id])
            self.assertNotEqual(prepared["packet_id"], fresh["packet_id"])
            second = self.submit(db, fixture, fresh, self.response(fresh, "agree"))
            self.assertEqual("accepted", second["state"], second)
            latest = self.comparisons(db, target)[-1]
            self.assertEqual(current.pinned, latest.body["supersedes"])
            self.assertEqual("agree", latest.body["decision"])
            for collection in ("checks", "responses", "findings"):
                self.assertEqual(original[collection], self.records(db)[collection])
            for identity, record in original["reconciliations"].items():
                self.assertEqual(record, self.records(db)["reconciliations"][identity])
            self.assertFalse(stage2.prepare(db, audit_id=fixture.audit_id, mode="reconcile")["prepared"])
            self.assertTrue(all(task["state"] == "satisfied" for task in
                                derive_work(db, audit_id=fixture.audit_id)["tasks"]))

    def test_requested_list_uses_bounded_selection_and_preserves_other_decisions(self):
        fixture = self.fixture().complete()
        with fixture.open() as db:
            task_ids = set(self.tasks(db, fixture).values())
            original = self.records(db)
            prepared = self.prepare(db, fixture, sorted(task_ids))
            self.assertEqual(1, len(prepared["assigned_task_ids"]))
            self.assertTrue(set(prepared["assigned_task_ids"]) < task_ids)
            self.assertTrue(prepared["deferred"])
            other = (task_ids - set(prepared["assigned_task_ids"])).pop()
            other_target = next(task["target"] for task in derive_work(db, audit_id=fixture.audit_id)["tasks"]
                                if task["id"] == other)
            prior_other = self.comparisons(db, other_target)[-1].pinned
            # Disjoint corrections prepared together retain their own current context.
            remaining = self.prepare(db, fixture, [other])
            accepted = self.submit(db, fixture, prepared, self.response(prepared))
            self.assertEqual("accepted", accepted["state"], accepted)
            self.assertEqual(prior_other, self.comparisons(db, other_target)[-1].pinned)
            self.assertEqual([], accepted["remaining_task_ids"])
            accepted = self.submit(db, fixture, remaining, self.response(remaining))
            self.assertEqual("accepted", accepted["state"], accepted)
            self.assertEqual(len(original["reconciliations"]) + 2, len(db.heads("reconciliations")))
            for collection in ("checks", "responses", "findings"):
                self.assertEqual(original[collection], self.records(db)[collection])

    def test_partial_return_leaves_omitted_completed_comparison_unchanged(self):
        fixture = self.fixture().complete()
        with fixture.open() as db:
            view = derive_work(db, audit_id=fixture.audit_id)
            task_ids = sorted(self.tasks(db, fixture).values())
            for unit in view["units"]:
                unit["pending_obligation_ids"] = [tid for tid in unit["obligation_ids"] if tid in task_ids]
            parts = [select_assignment(view, {"mode": "reconcile", "task_ids": [tid]}) for tid in task_ids]
            # A caller may combine the existing selections using the public packet API.
            selection = dict(parts[0], units=parts[0]["units"] + parts[1]["units"],
                tasks=parts[0]["tasks"] + parts[1]["tasks"], context={"owner": None, "argument": None},
                assigned_task_ids=task_ids,
                selected_unit_ids=parts[0]["selected_unit_ids"] + parts[1]["selected_unit_ids"])
            prepared = packets.prepare_assignment(db, audit_id=fixture.audit_id, mode="reconcile", selection=selection)
            prepared = controller._assignment_assistance(db, prepared)
            response = self.response(prepared)
            response["integrations"] = response["integrations"][:1]
            omitted = (set(task_ids) - {response["integrations"][0]["task_id"]}).pop()
            target = next(task["target"] for task in view["tasks"] if task["id"] == omitted)
            prior = self.comparisons(db, target)[-1].pinned
            count = len(db.heads("reconciliations"))
            accepted = self.submit(db, fixture, prepared, response)
            self.assertEqual("accepted", accepted["state"], accepted)
            self.assertEqual(count + 1, len(db.heads("reconciliations")))
            self.assertEqual(prior, self.comparisons(db, target)[-1].pinned)
            # Ordinary completion does not count unreturned optional corrections.
            self.assertEqual([], accepted["remaining_task_ids"])

    def test_unrelated_scientific_change_leaves_selected_correction_current(self):
        fixture = self.fixture().complete()
        with fixture.open() as db:
            task_id = self.tasks(db, fixture)["arg_lem"]
            prepared = self.prepare(db, fixture, [task_id])
            item = db.head("items", "itm_thm")
            body = deepcopy(item.body)
            body["statement"]["text"] = "A different unrelated theorem conclusion."
            fixture.apply(db, [edit("replace", "items", item.id, body, item.version)],
                          *fixture.ITEMS, mode="primary")
            saved = self.records(db)
            pending = {task["id"] for task in derive_work(db, audit_id=fixture.audit_id)["tasks"]
                       if task["state"] != "satisfied"}
            self.assertTrue(pending)
            current = self.prepare(db, fixture, [task_id])
            self.assertEqual(prepared["packet_id"], current["packet_id"])
            self.assertEqual([task_id], current["assigned_task_ids"])
            accepted = self.submit(db, fixture, prepared, self.response(prepared))
            self.assertEqual("accepted", accepted["state"], accepted)
            after = self.records(db)
            for collection in ("checks", "responses", "findings"):
                self.assertEqual(saved[collection], after[collection])
            for identity, record in saved["reconciliations"].items():
                self.assertEqual(record, after["reconciliations"][identity])
            self.assertEqual(pending, {task["id"] for task in derive_work(db, audit_id=fixture.audit_id)["tasks"]
                                      if task["state"] != "satisfied"})

    def test_materially_changed_selected_inputs_reject_old_correction(self):
        for kind in ("statement", "opinion", "evidence"):
            with self.subTest(kind=kind):
                fixture = self.fixture(kind).complete()
                with fixture.open() as db:
                    task_id = self.tasks(db, fixture)["arg_thm"]
                    prepared = self.prepare(db, fixture, [task_id])
                    if kind == "statement":
                        item = db.head("items", "itm_thm")
                        body = deepcopy(item.body)
                        body["statement"]["text"] = "A materially changed target conclusion."
                        fixture.apply(db, [edit("replace", "items", item.id, body, item.version)],
                                      *fixture.ITEMS, mode="primary")
                    elif kind == "opinion":
                        prior = db.head("checks", "chk_comp_thm")
                        fixture.apply(db, [fixture.check_edit("chk_changed", R("arguments", "arg_thm"),
                            "composition", outcome="gap", evidence=["anc_thm_proof"], supersedes=prior.pinned)],
                            *fixture.ITEMS, mode="primary")
                    else:
                        packet = fixture.packet(db, *fixture.ITEMS, mode="primary")
                        sources.anchor_sources(db, request={"contract_version": 4,
                            "request_id": fixture.request_id(), "packet_id": packet["packet_id"],
                            "anchors": [{"id": "anc_thm_proof", "expected_version": 1,
                                "source_id": fixture.source_id, "locator": locator(start=6, end=6)}]})
                    saved = self.records(db)
                    revision = db.max_revision()
                    rejected = self.submit(db, fixture, prepared, self.response(prepared, "agree"))
                    self.assertIn(rejected["state"], ("needs_revision", "conflict"), rejected)
                    self.assertEqual(saved, self.records(db))
                    self.assertEqual(revision, db.max_revision())
                    with self.assertRaises(InvalidRequest) as caught:
                        self.prepare(db, fixture, [task_id])
                    self.assertEqual("WORK_CORRECTION", caught.exception.code)

    def test_invalid_correction_selection_fails_without_scientific_mutation(self):
        fixture = self.fixture().complete()
        with fixture.open() as db:
            task_id = self.tasks(db, fixture)["arg_thm"]
            primary = next(task["id"] for task in derive_work(db, audit_id=fixture.audit_id)["tasks"]
                           if task["role"] == "primary")
            saved = self.records(db)
            revision = db.max_revision()
            for stage, mode, selected in ((1, "primary", [task_id]), (2, "independent", [task_id]),
                    (2, "primary", [task_id]), (2, "reconcile", ["unknown_task"]),
                    (2, "reconcile", []), (2, "reconcile", None), (2, "reconcile", [primary])):
                with self.subTest(stage=stage, mode=mode, selected=selected):
                    with self.assertRaises(InvalidRequest) as caught:
                        stage1.prepare_stage(db, audit_id=fixture.audit_id, stage=stage,
                                             mode=mode, task_ids=selected, correct=True)
                    self.assertEqual("WORK_CORRECTION", caught.exception.code)
                    self.assertEqual(saved, self.records(db))
                    self.assertEqual(revision, db.max_revision())
        pending = self.fixture("pending").independent()
        with pending.open() as db:
            saved = self.records(db)
            revision = db.max_revision()
            with self.assertRaises(InvalidRequest) as caught:
                self.prepare(db, pending, [self.tasks(db, pending)["arg_thm"]])
            self.assertEqual("WORK_CORRECTION", caught.exception.code)
            self.assertEqual(saved, self.records(db))
            self.assertEqual(revision, db.max_revision())
