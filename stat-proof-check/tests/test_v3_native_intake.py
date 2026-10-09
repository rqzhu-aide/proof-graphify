"""Native primary splitting preserves authored work and normal acceptance rules."""
from copy import deepcopy
import json
from types import SimpleNamespace

from support import R, TempCase, edit, sha
from paper_core import controller, stage1
from paper_core.contract import WORK_PRIMARY_RESPONSE, validate_shape
from paper_core.errors import InvalidRequest
from paper_core.intake import intake_response


class NativeIntakeTests(TempCase):
    def prepare(self, name="paper"):
        fixture = self.fixture(name).audit(independent_required=False)
        with fixture.open() as db:
            prepared = stage1.prepare_stage(db, audit_id=fixture.audit_id, focus=R("items", "itm_lem"))
        self.assertTrue(prepared["prepared"], prepared)
        return fixture, prepared

    def authored_response(self, prepared):
        response = deepcopy(prepared["scaffold"])
        for row in response["results"]:
            if row["type"] == "source_fidelity":
                row.update(result="matched", note="Fixture author compared the supplied statement.",
                           evidence_refs=["anc_lem"])
            else:
                row.update(state="complete", outcome="gap",
                           reasoning="The induction step lacks a premise, α remains unspecified.",
                           evidence_refs=["anc_lem_proof"])
        return response

    def raw(self, response):
        return (json.dumps(response, indent=2, ensure_ascii=False) + "\n").encode("utf-8")

    def submit(self, db, fixture, prepared, response):
        raw = response if isinstance(response, bytes) else self.raw(response)
        envelope = dict(prepared["submission_envelope_template"], request_id=fixture.request_id(),
                        reviewer="synthetic primary examiner")
        return controller.submit_work(db, envelope_bytes=self.raw(envelope), response_bytes=raw)

    def scientific_snapshot(self, db):
        return {field: [(row.pinned, deepcopy(row.body)) for row in db.heads(field)]
                for field in ("checks", "observations", "coverage", "findings", "responses", "reconciliations")}

    def finding(self, task_ids=(), *, description="Retain this missing premise concern."):
        return {"target": R("arguments", "arg_lem"), "category": "proof_gap",
                "description": description, "evidence_refs": ["anc_lem_proof"],
                "related_task_ids": list(task_ids), "existing_check_refs": [], "affected_uses": [],
                "impact_reason": "The missing premise affects the assigned argument."}

    def coverage(self, task_ids):
        return {"argument_id": "arg_lem", "anchor_id": "anc_lem_proof", "start_offset": 0, "end_offset": 1,
                "classification": "substantive", "claim_refs": [R("items", "itm_lem")],
                "check_task_ids": list(task_ids), "existing_check_refs": [], "replaces": None,
                "note": "Authored coverage record."}

    def test_normal_response_is_unchanged_read_only_and_accepted(self):
        fixture, prepared = self.prepare()
        response = self.authored_response(prepared)
        original = deepcopy(response)
        raw = self.raw(response)
        database_bytes = fixture.path.read_bytes()
        with fixture.open(write=False) as db:
            result = intake_response(db, packet_id=prepared["packet_id"], response_bytes=raw)
        self.assertEqual(database_bytes, fixture.path.read_bytes())
        self.assertEqual(original, response)
        self.assertEqual(raw, self.raw(response))
        self.assertEqual(response, result["response"])
        self.assertEqual([], result["diagnostics"])
        self.assertEqual([], result["deferred"])
        self.assertEqual([row["task_id"] for row in response["results"]], result["selected_task_ids"])
        self.assertEqual(sha(raw), result["source_sha256"])
        self.assertEqual(len(raw), result["source_size"])
        # Candidates and deferred objects are independent copies of caller input.
        result["response"]["results"][0]["note"] = "Caller edit after intake."
        self.assertEqual(original, response)
        with fixture.open() as db:
            receipt = self.submit(db, fixture, prepared, response)
            self.assertEqual("accepted", receipt["state"], receipt)
            self.assertEqual(1, len(db.heads("checks")))
            check = db.heads("checks")[0]
            self.assertEqual("gap", check.body["outcome"])
            self.assertEqual(next(row["reasoning"] for row in response["results"] if row["type"] == "check"),
                             check.body["reasoning"])

    def test_malformed_rows_leave_adverse_work_and_original_bytes_intact(self):
        fixture, prepared = self.prepare()
        response = self.authored_response(prepared)
        valid_rows = deepcopy(response["results"])
        malformed = [None, 17, "bad row", {"type": "check", "outcome": "gap"},
                     {"task_id": []}, {"task_id": "unassigned", "reasoning": "Keep this adverse concern."}]
        response["results"].extend(malformed)
        raw = self.raw(response)
        with fixture.open() as db:
            before = self.scientific_snapshot(db)
            rejected = self.submit(db, fixture, prepared, raw)
            self.assertEqual("needs_revision", rejected["state"], rejected)
            self.assertEqual(before, self.scientific_snapshot(db))
            result = intake_response(db, packet_id=prepared["packet_id"], response_bytes=raw)
            self.assertEqual(valid_rows, result["response"]["results"])
            self.assertEqual([f"/results/{len(valid_rows) + i}" for i in range(len(malformed))],
                             [row["path"] for row in result["deferred"]])
            self.assertEqual(malformed, [row["original"] for row in result["deferred"]])
            receipt = self.submit(db, fixture, prepared, result["response"])
            self.assertEqual("accepted", receipt["state"], receipt)
            self.assertEqual(1, len(db.heads("checks")))
            self.assertEqual("gap", db.heads("checks")[0].body["outcome"])
            self.assertEqual([], db.heads("findings"))
            saved = db.work_submission(rejected["request_id"])
            self.assertEqual(raw, db.get_blob(saved["response_sha256"]))
        self.assertEqual(raw, self.raw(response))

    def test_ambiguous_check_and_explicitly_linked_concern_are_deferred(self):
        fixture, prepared = self.prepare()
        response = self.authored_response(prepared)
        check = next(row for row in response["results"] if row["type"] == "check")
        competitor = deepcopy(check)
        competitor.update(outcome="supported", reasoning="A competing authored judgment.")
        response["results"].append(competitor)
        response["findings"] = [self.finding([check["task_id"]])]
        response["coverage"] = [self.coverage([check["task_id"]])]
        original = deepcopy(response)
        with fixture.open() as db:
            result = intake_response(db, packet_id=prepared["packet_id"], response=response)
            self.assertEqual(original, response)
            check_paths = {f"/results/{i}" for i, row in enumerate(response["results"]) if row["type"] == "check"}
            self.assertEqual(check_paths | {"/findings/0", "/coverage/0"},
                             {row["path"] for row in result["deferred"]})
            self.assertEqual(response["findings"][0], next(row["original"] for row in result["deferred"]
                                                         if row["path"] == "/findings/0"))
            self.assertEqual([], result["response"]["findings"])
            self.assertEqual([], result["response"]["coverage"])
            receipt = self.submit(db, fixture, prepared, result["response"])
            self.assertEqual("accepted", receipt["state"], receipt)
            self.assertIn(check["task_id"], receipt["remaining_task_ids"])
            self.assertEqual([], db.heads("checks"))
            self.assertEqual([], db.heads("findings"))
            self.assertEqual(2, len(db.heads("observations")))

    def test_duplicate_source_claims_defer_both_without_selecting_a_judgment(self):
        fixture, prepared = self.prepare()
        response = self.authored_response(prepared)
        source = next(row for row in response["results"] if row["type"] == "source_fidelity")
        duplicate = {"task_id": source["task_id"], "type": "check", "outcome": "refuted"}
        check = next(row for row in response["results"] if row["type"] == "check")
        response["results"] = [source, check, duplicate]
        with fixture.open() as db:
            result = intake_response(db, packet_id=prepared["packet_id"], response=response)
            self.assertEqual([check], result["response"]["results"])
            self.assertEqual(["ambiguous_same_task", "ambiguous_same_task"],
                             [row["reason"] for row in result["diagnostics"]])
            self.assertEqual([source, duplicate], [row["original"] for row in result["deferred"]])
            receipt = self.submit(db, fixture, prepared, result["response"])
            self.assertEqual("accepted", receipt["state"], receipt)
            self.assertIn(source["task_id"], receipt["remaining_task_ids"])
            self.assertEqual(1, len(db.heads("checks")))
            self.assertEqual([], db.heads("observations"))

    def test_source_comparison_cannot_supply_ancillary_check_links(self):
        fixture, prepared = self.prepare()
        response = self.authored_response(prepared)
        response["results"] = [row for row in response["results"] if row["type"] == "source_fidelity"]
        source_id = response["results"][0]["task_id"]
        response["findings"] = [self.finding([source_id]), self.finding(description="Unlinked concern remains open.")]
        response["coverage"] = [self.coverage([source_id])]
        with fixture.open() as db:
            result = intake_response(db, packet_id=prepared["packet_id"], response=response)
            self.assertIn(source_id, result["selected_task_ids"])
            self.assertEqual({"/findings/0", "/coverage/0"}, {row["path"] for row in result["deferred"]})
            self.assertEqual([response["findings"][1]], result["response"]["findings"])
            receipt = self.submit(db, fixture, prepared, result["response"])
            self.assertEqual("accepted", receipt["state"], receipt)
            self.assertEqual([], db.heads("checks"))
            self.assertEqual(1, len(db.heads("findings")))
            finding = db.heads("findings")[0]
            self.assertEqual("Unlinked concern remains open.", finding.body["description"])
            self.assertEqual("open", finding.body["lifecycle"])
            self.assertIsNone(finding.body["resolution"])

    def test_shape_valid_scientific_defect_is_left_for_atomic_acceptance(self):
        fixture, prepared = self.prepare()
        response = self.authored_response(prepared)
        next(row for row in response["results"] if row["type"] == "check")["reasoning"] = ""
        self.assertEqual([], validate_shape(WORK_PRIMARY_RESPONSE, response))
        with fixture.open() as db:
            result = intake_response(db, packet_id=prepared["packet_id"], response=response)
            self.assertEqual(response, result["response"])
            self.assertEqual([], result["diagnostics"])
            before = self.scientific_snapshot(db)
            receipt = self.submit(db, fixture, prepared, result["response"])
            self.assertEqual("needs_revision", receipt["state"], receipt)
            self.assertEqual(before, self.scientific_snapshot(db))

    def test_old_packet_is_never_rebound_and_staleness_remains_authoritative(self):
        fixture, prepared = self.prepare()
        response = self.authored_response(prepared)
        raw = self.raw(response)
        with fixture.open() as db:
            item = db.head("items", "itm_lem")
            changed = deepcopy(item.body)
            changed["statement"] = {"form": "verbatim", "text": "For every n, a_n <= 0, a stronger assertion."}
            fixture.apply(db, [edit("replace", "items", item.id, changed, item.version)], *fixture.ITEMS)
            current = stage1.prepare_stage(db, audit_id=fixture.audit_id, focus=R("items", "itm_lem"))
            self.assertNotEqual(prepared["packet_id"], current["packet_id"])
            refused = intake_response(db, packet_id=current["packet_id"], response_bytes=raw)
            self.assertIsNone(refused["response"])
            self.assertEqual("original_packet_required", refused["diagnostics"][0]["reason"])
            self.assertEqual(response, refused["deferred"][0]["original"])
            result = intake_response(db, packet_id=prepared["packet_id"], response_bytes=raw)
            self.assertEqual(response, result["response"])
            before = self.scientific_snapshot(db)
            receipt = self.submit(db, fixture, prepared, result["response"])
            self.assertEqual("conflict", receipt["state"], receipt)
            self.assertEqual(before, self.scientific_snapshot(db))

    def test_missing_scientific_fields_are_deferred_without_defaults(self):
        fixture, prepared = self.prepare()
        response = self.authored_response(prepared)
        check = next(row for row in response["results"] if row["type"] == "check")
        del check["reasoning"]
        response["results"] = [check]
        with fixture.open(write=False) as db:
            result = intake_response(db, packet_id=prepared["packet_id"], response=response)
        self.assertIsNone(result["response"])
        self.assertEqual([], result["selected_task_ids"])
        self.assertEqual([{"path": "/results/0", "original": check}], result["deferred"])
        self.assertEqual("no_usable_work", result["diagnostics"][-1]["reason"])
        self.assertNotIn("reasoning", check)

    def test_response_and_ancillary_structure_errors_retain_whole_input(self):
        fixture, prepared = self.prepare()
        response = self.authored_response(prepared)
        variants = [None, [], {**response, "extra": "Preserve this text."},
                    {**response, "results": {}}, {**response, "findings": None},
                    {**response, "findings": [None]}, {**response, "coverage": [{"note": "Keep this remark."}]}]
        with fixture.open(write=False) as db:
            for value in variants:
                with self.subTest(value=value):
                    result = intake_response(db, packet_id=prepared["packet_id"], response=value)
                    self.assertIsNone(result["response"])
                    self.assertEqual([], result["selected_task_ids"])
                    self.assertEqual([{"path": "/", "original": value}], result["deferred"])
                    self.assertTrue(result["diagnostics"])

    def test_bad_bytes_remain_local_with_exact_digest_without_dumping_input(self):
        fixture, prepared = self.prepare()
        invalid = [b"{", b'\xff', b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":1e999}', b'{"a":"\\ud800"}']
        with fixture.open(write=False) as db:
            for raw in invalid:
                with self.subTest(raw=raw[:20]):
                    result = intake_response(db, packet_id=prepared["packet_id"], response_bytes=raw)
                    self.assertIsNone(result["response"])
                    self.assertEqual("json_invalid", result["diagnostics"][0]["reason"])
                    self.assertEqual(sha(raw), result["source_sha256"])
                    self.assertEqual(len(raw), result["source_size"])
                    self.assertEqual([], result["deferred"])
            raw = b"x" * (controller.RESPONSE_LIMIT + 1)
            result = intake_response(db, packet_id=prepared["packet_id"], response_bytes=raw)
            self.assertEqual("input_too_large", result["diagnostics"][0]["reason"])
            self.assertEqual(sha(raw), result["source_sha256"])

    def test_deeply_nested_nonobject_input_is_retained_without_recursive_copy(self):
        fixture, prepared = self.prepare()
        raw = b"[" * 1100 + b"]" * 1100
        with fixture.open(write=False) as db:
            result = intake_response(db, packet_id=prepared["packet_id"], response_bytes=raw)
        self.assertIsNone(result["response"])
        self.assertEqual("response_not_object", result["diagnostics"][0]["reason"])
        self.assertEqual(sha(raw), result["source_sha256"])
        original = result["deferred"][0]["original"]
        for _ in range(1099):
            original = original[0]
        self.assertEqual([], original)

    def test_saved_assignment_and_api_argument_validation(self):
        fixture, prepared = self.prepare()
        response = self.authored_response(prepared)
        with fixture.open(write=False) as db:
            with self.assertRaises(InvalidRequest) as unknown:
                intake_response(db, packet_id="unknown", response=response)
            self.assertEqual("PACKET_UNKNOWN", unknown.exception.code)
            for arguments in ({}, {"response_bytes": "text"},
                              {"response_bytes": self.raw(response), "response": response},
                              {"response": {"numeric_key": {1: "not a JSON object key"}}}):
                with self.subTest(arguments=arguments):
                    with self.assertRaises(InvalidRequest):
                        intake_response(db, packet_id=prepared["packet_id"], **arguments)
            saved = db.packet(prepared["packet_id"])
        for mode in ("nonprimary", "duplicate", "bad_task", "bad_tasks", "wrong_identity"):
            invalid = deepcopy(saved)
            if mode == "nonprimary":
                invalid["manifest"]["work"]["mode"] = "independent"
            elif mode == "duplicate":
                invalid["manifest"]["work"]["tasks"].append(invalid["manifest"]["work"]["tasks"][0])
            elif mode == "bad_task":
                invalid["manifest"]["work"]["tasks"][0]["id"] = []
            elif mode == "bad_tasks":
                invalid["manifest"]["work"]["tasks"] = None
            else:
                invalid["manifest"]["packet_id"] = "another_packet"
            with self.subTest(mode=mode):
                with self.assertRaises(InvalidRequest):
                    intake_response(SimpleNamespace(packet=lambda packet_id: invalid),
                                    packet_id=prepared["packet_id"], response=response)
