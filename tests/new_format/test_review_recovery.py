"""Typed recovery and current inspection preserve the original independent examination."""
import copy
import unittest

from support import Fixture, R, TempCase, edit, run_cli
from paper_core import controller, packets, review
from paper_core.canonical import canonical_bytes
from paper_core.errors import InvalidRequest
from test_review import entry, judgment, mapping_request, source_target, submission, worker_response


class ReviewRecoveryTests(TempCase):
    def setUp(self):
        super().setUp()
        self.fx = self.fixture().primary()

    def submit(self, db, judgments, *, exposure="none_known"):
        packet = packets.get_packet(db, targets=[R("items", "itm_lem")], mode="independent")
        worker = worker_response(packet["packet_id"], judgments, exposure=exposure,
                                 exposure_note="Read primary work" if exposure != "none_known" else "")
        raw = canonical_bytes(worker)
        envelope = submission(self.fx, packet["packet_id"])
        return review.submit_review(db, submission=envelope, response_bytes=raw), raw, envelope

    def map(self, db, response_id, entries):
        packet = self.fx.packet(db, *Fixture.ITEMS, mode="primary")
        return review.map_response(db, mapping=mapping_request(self.fx, packet["packet_id"], response_id, entries))

    def test_mixed_judgment_causes_are_typed_and_legacy_tuple_is_unchanged(self):
        with self.fx.open() as db:
            packet = packets.get_packet(db, targets=[R("items", "itm_lem")], mode="primary")
            manifest = db.packet(packet["packet_id"])["manifest"]
            worker = worker_response(packet["packet_id"], [judgment(R("groups", "grp_ghost"), evidence=("anc_ghost",))])
            details = review.judgment_diagnostics(manifest, worker, packet)
            self.assertEqual([p["category"] for p in details[0]["problems"]],
                             ["wrong_target_kind", "target_not_in_packet", "missing_neutral_source"])
            self.assertEqual(review.classify_judgments(manifest, worker, packet), ([], [(0,
                "kind composition cannot target groups; target groups:grp_ghost is not in the packet read set; "
                "evidence anchor anc_ghost is not in the packet read set")]))
            actions = review.response_recovery({"judgment_diagnostics": details}, complete=True)
            self.assertEqual({a["operation"] for a in actions},
                             {"author_response_correction", "extend_neutral_source"})

    def test_source_target_absent_from_packet_is_not_described_as_mapping_only(self):
        with self.fx.open() as db:
            saved, _, _ = self.submit(db, [judgment(source_target("anc_absent", "missing proof"))])
            self.assertEqual(saved["state"], "needs_revision")
            self.assertEqual({p["category"] for p in saved["judgment_diagnostics"][0]["problems"]},
                             {"source_target_mapping", "missing_neutral_source"})
            # Additional advice did not change the receipt's existing explanation.
            self.assertEqual(saved["pending"], [{"judgment_index": 0,
                "reason": "SourceTarget on anchor anc_absent awaits mapping: missing proof"}])
            info = review.inspect_response(db, response_id=saved["response_id"])
            self.assertEqual({a["operation"] for a in info["recovery"]}, {"extend_neutral_source"})

    def test_pending_reference_reports_covered_scope_problem_alongside_correspondence(self):
        with self.fx.open() as db:
            saved, _, _ = self.submit(db, [judgment(R("arguments", "arg_thm"))])
            self.assertEqual({p["category"] for p in saved["judgment_diagnostics"][0]["problems"]},
                             {"target_not_in_packet", "judgment_out_of_covered_scope"})
            self.assertEqual(saved["pending"], [{"judgment_index": 0,
                "reason": "target arguments:arg_thm is not in the packet read set"}])

    def test_partial_and_final_mapping_update_live_inventory_without_rewriting_receipts(self):
        with self.fx.open() as db:
            saved, raw, envelope = self.submit(db, [
                judgment(source_target("anc_lem_proof", "route has a gap"), outcome="gap"),
                judgment(source_target("anc_lem_proof", "local inference has a gap"), kind="derivation", outcome="gap")])
            original_receipt = db.commit_by_request(envelope["request_id"])["receipt_json"]
            info = review.inspect_response(db, response_id=saved["response_id"])
            self.assertEqual(info["mapped_judgment_indexes"], [])
            self.assertEqual(info["pending_judgment_indexes"], [0, 1])
            self.assertEqual([a["operation"] for a in info["recovery"]], ["map_saved_response"])
            self.map(db, saved["response_id"], [entry(0, R("arguments", "arg_lem"))])
            partial = review.inspect_response(db, response_id=saved["response_id"])
            self.assertEqual(partial["state"], "needs_revision")
            self.assertEqual(partial["mapped_judgment_indexes"], [0])
            self.assertEqual(partial["pending_judgment_indexes"], [1])
            self.assertEqual(partial["eligible_independent_check_count"], 0)
            self.map(db, saved["response_id"], [entry(1, R("groups", "grp_lem"))])
            final = review.inspect_response(db, response_id=saved["response_id"])
            self.assertEqual(final["state"], "accepted")
            self.assertEqual(final["pending_judgment_indexes"], [])
            self.assertEqual(final["mapped_judgment_indexes"], [0, 1])
            self.assertEqual(final["eligible_independent_check_count"], 2)
            self.assertEqual({c["outcome"] for c in final["checks"]}, {"gap"})
            self.assertEqual([a["operation"] for a in final["recovery"]], ["inspect_reconciliation"])
            self.assertEqual(final["original_request_id"], envelope["request_id"])
            self.assertEqual(final["original_response_ref"]["version"], 1)
            self.assertEqual(final["response_ref"]["version"], 2)
            self.assertEqual(db.get_blob(final["original_blob_sha256"]), raw)
            self.assertEqual(db.commit_by_request(envelope["request_id"])["receipt_json"], original_receipt)
            # Replaying the original direct submission also retains the old receipt.
            replay = review.submit_review(db, submission=envelope, response_bytes=raw)
            self.assertEqual(replay["receipt"], saved["receipt"])
            self.assertEqual(db.commit_by_request(envelope["request_id"])["receipt_json"], original_receipt)

    def test_accepted_compromised_and_draft_work_are_not_current_independent_credit(self):
        with self.fx.open() as db:
            saved, _, _ = self.submit(db, [judgment(source_target("anc_lem_proof", "route"))],
                                      exposure="possible_exposure")
            self.map(db, saved["response_id"], [entry(0, R("arguments", "arg_lem"))])
            info = review.inspect_response(db, response_id=saved["response_id"])
            self.assertEqual(info["state"], "accepted")
            self.assertEqual(info["exposure"], "compromised")
            self.assertEqual(info["eligible_independent_check_count"], 0)
            self.assertIn("obtain_independent_review", [a["operation"] for a in info["recovery"]])
            partial = judgment(R("items", "itm_lem"), kind="external_source", state="draft",
                outcome=None, evidence=("anc_lem",), reasoning="The source states the bound, but its original citation remains unresolved.")
            partial["next_action"] = "Locate the cited source and inspect the exact bound."
            saved, _, _ = self.submit(db, [partial])
            draft = review.inspect_response(db, response_id=saved["response_id"])
            self.assertEqual(draft["state"], "accepted")
            self.assertEqual(draft["eligible_independent_check_count"], 0)

    def test_actual_statement_change_renews_work_instead_of_remapping_it(self):
        with self.fx.open() as db:
            saved, _, _ = self.submit(db, [judgment(source_target("anc_lem_proof", "route"))])
            self.map(db, saved["response_id"], [entry(0, R("arguments", "arg_lem"))])
            item = db.head("items", "itm_lem")
            self.fx.apply(db, [edit("replace", "items", item.id,
                dict(item.body, statement={"form": "transcription", "text": "A genuinely changed conclusion."}), item.version)])
            info = review.inspect_response(db, response_id=saved["response_id"])
            self.assertEqual(info["state"], "accepted")
            self.assertEqual(info["pending_judgment_indexes"], [])
            self.assertEqual(info["eligible_independent_check_count"], 0)
            self.assertGreater(info["stale_check_count"], 0)
            self.assertTrue(info["checks"][0]["changes"]["records"])
            self.assertEqual([a["operation"] for a in info["recovery"]], ["inspect_current_evidence"])

    def test_pending_direct_review_obeys_original_packet_guards(self):
        with self.fx.open() as db:
            saved, _, _ = self.submit(db, [judgment(source_target("anc_lem_proof", "route"))])
            item = db.head("items", "itm_lem")
            self.fx.apply(db, [edit("replace", "items", item.id,
                dict(item.body, statement={"form": "transcription", "text": "A changed conclusion."}), item.version)])
            info = review.inspect_response(db, response_id=saved["response_id"])
            self.assertTrue(info["mapping_input_changes"]["records"])
            self.assertEqual([a["operation"] for a in info["recovery"]], ["inspect_current_evidence"])

    def test_old_pending_or_stale_review_checks_current_replacement_before_renewal(self):
        for mapped in (False, True):
            with self.subTest(original_mapped=mapped):
                self.fx = self.fixture(f"replacement_{mapped}").primary()
                with self.fx.open() as db:
                    prepared = controller.prepare_work(db, audit_id=self.fx.audit_id, mode="independent",
                                                       focus=R("items", "itm_lem"))
                    self.assertTrue(prepared["prepared"])
                    worker = worker_response(prepared["packet_id"], [
                        judgment(source_target("anc_lem_proof", "route with an unresolved gap"), outcome="gap")])
                    raw = canonical_bytes(worker)
                    saved = review.submit_review(db, submission=submission(self.fx, prepared["packet_id"]), response_bytes=raw)
                    if mapped:
                        self.map(db, saved["response_id"], [entry(0, R("arguments", "arg_lem"))])
                    item = db.head("items", "itm_lem")
                    spec = db.head("target_specs", "tgt_lem")
                    self.fx.apply(db, [edit("replace", "items", item.id,
                        dict(item.body, statement={"form": "transcription", "text": "A corrected conclusion."}), item.version),
                        edit("replace", "target_specs", spec.id,
                            dict(spec.body, statement_ref={**item.pinned, "version": item.version + 1}), spec.version)])
                    replacement, _, _ = self.submit(db, [
                        judgment(source_target("anc_lem_proof", "the gap under the corrected conclusion"), outcome="gap")])
                    renewed = self.map(db, replacement["response_id"], [entry(0, R("arguments", "arg_lem"))])
                    revision = db.max_revision()
                    info = review.inspect_response(db, response_id=saved["response_id"])
                    self.assertEqual(info["assigned_task_count"], 1)
                    current = info["assigned_task_statuses"][0]["current"]
                    self.assertTrue(current["required"])
                    self.assertTrue(current["satisfied"], info["assigned_task_statuses"])
                    self.assertEqual(current["freshness"], "current")
                    self.assertEqual(current["outcome"], "gap")
                    self.assertIn(renewed["checks"][0]["check_id"], [r["id"] for r in current["check_refs"]])
                    self.assertEqual(info["recovery"][0]["operation"], "inspect_current_evidence")
                    self.assertNotIn("renew_affected_work", [a["operation"] for a in info["recovery"]])
                    self.assertIn("replacement", info["recovery"][0]["message"])
                    self.assertIn("unresolved concerns", info["recovery"][0]["message"])
                    self.assertEqual(db.max_revision(), revision)
                    self.assertEqual(db.get_blob(info["original_blob_sha256"]), raw)
                    self.assertEqual(info["state"], "accepted" if mapped else "needs_revision")

    def test_bounded_details_do_not_hide_other_recovery_causes(self):
        with self.fx.open() as db:
            saved, raw, _ = self.submit(db, [judgment(source_target("anc_lem_proof", "route gap"), outcome="gap"),
                judgment(source_target("anc_absent", "unavailable second passage"))])
            info = review.inspect_response(db, response_id=saved["response_id"], limit=1)
            self.assertTrue(info["details_truncated"])
            self.assertEqual(info["pending_judgment_count"], 2)
            self.assertEqual(len(info["judgment_diagnostics"]), 1)
            self.assertEqual({a["operation"] for a in info["recovery"]}, {"map_saved_response", "extend_neutral_source"})
            advertised = next(a for a in info["recovery"] if a["operation"] == "map_saved_response")
            self.assertEqual(advertised["judgment_indexes"], [0])
            self.map(db, saved["response_id"], [entry(i, R("arguments", "arg_lem"))
                                             for i in advertised["judgment_indexes"]])
            partial = review.inspect_response(db, response_id=saved["response_id"])
            self.assertEqual(partial["state"], "needs_revision")
            self.assertEqual(partial["checks"][0]["outcome"], "gap")
            self.assertEqual(partial["eligible_independent_check_count"], 0)
            self.assertEqual(db.get_blob(partial["original_blob_sha256"]), raw)

    def test_overlapping_missing_sources_never_become_mapping_advice_after_truncation(self):
        for limit in (1, 20):
            with self.subTest(limit=limit):
                self.fx = self.fixture(f"overlap_{limit}").primary()
                with self.fx.open() as db:
                    judgments = [judgment(source_target("anc_lem_proof", "route"), evidence=(f"anc_missing_{i}",))
                                 for i in range(limit)]
                    judgments.append(judgment(R("arguments", "arg_lem"), evidence=(f"anc_missing_{limit}",)))
                    saved, raw, _ = self.submit(db, judgments)
                    full = review.inspect_response(db, response_id=saved["response_id"])
                    limited = review.inspect_response(db, response_id=saved["response_id"], limit=limit)
                    for info in (full, limited):
                        self.assertEqual([a["operation"] for a in info["recovery"]], ["extend_neutral_source"])
                        self.assertEqual(info["recovery"][0]["judgment_count"], limit + 1)
                    action = limited["recovery"][0]
                    self.assertTrue(action["judgment_indexes_truncated"])
                    self.assertEqual(len(action["judgment_indexes"]), limit)
                    for kwargs in ({}, {"complete": True}):
                        self.assertEqual([a["operation"] for a in review.response_recovery(limited, **kwargs)],
                                         ["inspect_saved_response"])
                    packet = self.fx.packet(db, *Fixture.ITEMS, mode="primary")
                    request = mapping_request(self.fx, packet["packet_id"], saved["response_id"],
                                              [entry(limit, R("arguments", "arg_lem"))])
                    revision = db.max_revision()
                    with self.assertRaises(InvalidRequest) as caught:
                        review.map_response(db, mapping=request)
                    self.assertTrue(any("evidence absent" in reason for reason in caught.exception.records))
                    self.assertEqual(db.max_revision(), revision)
                    self.assertEqual(db.get_blob(full["original_blob_sha256"]), raw)
                if limit == 20:
                    cli_view, _ = run_cli("work", "inspect", self.fx.path, "--response", saved["response_id"])
                    self.assertEqual(cli_view["details_limit"], 20)
                    self.assertEqual(cli_view["recovery"], limited["recovery"])

    def test_bounded_mapping_indexes_are_usable_and_counts_preserve_the_full_action(self):
        for limit in (1, 100):
            with self.subTest(limit=limit):
                self.fx = self.fixture(f"mappable_{limit}").primary()
                with self.fx.open() as db:
                    saved, raw, _ = self.submit(db, [
                        judgment(source_target("anc_lem_proof", f"route gap {i}"), outcome="gap") for i in range(3)])
                    info = review.inspect_response(db, response_id=saved["response_id"], limit=limit)
                    action, = info["recovery"]
                    self.assertEqual(action["operation"], "map_saved_response")
                    self.assertEqual(action["judgment_count"], 3)
                    self.assertEqual(action["judgment_indexes_truncated"], limit < 3)
                    self.assertEqual(action["judgment_indexes"], list(range(3))[:limit])
                    self.map(db, saved["response_id"], [entry(i, R("arguments", "arg_lem"))
                                                     for i in action["judgment_indexes"]])
                    after = review.inspect_response(db, response_id=saved["response_id"])
                    self.assertEqual(after["state"], "needs_revision" if limit == 1 else "accepted")
                    self.assertEqual({c["outcome"] for c in after["checks"]}, {"gap"})
                    self.assertEqual(db.get_blob(after["original_blob_sha256"]), raw)

    def test_overlapping_wrong_kind_and_scope_remain_blockers_beside_usable_mapping(self):
        for problem in ("wrong_kind", "scope"):
            for limit in (1, 20):
                with self.subTest(problem=problem, limit=limit):
                    self.fx = self.fixture(f"{problem}_{limit}").primary()
                    with self.fx.open() as db:
                        if problem == "wrong_kind":
                            target = R("groups", "grp_lem")
                            judgments = [judgment(R("items", "itm_lem")) for _ in range(limit)]
                            judgments.append(judgment(target))
                            packet = packets.get_packet(db, targets=[R("items", "itm_lem")], mode="independent")
                        else:
                            target = R("arguments", "arg_thm")
                            judgments = [judgment(R("items", "itm_thm"), kind="external_source", evidence=("anc_thm",))
                                         for _ in range(limit)]
                            judgments.append(judgment(target, evidence=("anc_thm_proof",)))
                            packet = packets.get_packet(db, targets=[R("items", "itm_lem"), R("items", "itm_thm")],
                                                        mode="independent")
                        judgments.append(judgment(source_target("anc_lem_proof", "route gap"), outcome="gap"))
                        worker = worker_response(packet["packet_id"], judgments)
                        saved = review.submit_review(db, submission=submission(self.fx, packet["packet_id"]),
                                                     response_bytes=canonical_bytes(worker))
                        for display_limit in (limit, 100):
                            info = review.inspect_response(db, response_id=saved["response_id"], limit=display_limit)
                            self.assertEqual({a["operation"] for a in info["recovery"]},
                                             {"map_saved_response", "author_response_correction"})
                            action = next(a for a in info["recovery"] if a["operation"] == "map_saved_response")
                            self.assertEqual(action["judgment_indexes"], [limit + 1])
                            correction = next(a for a in info["recovery"] if a["operation"] == "author_response_correction")
                            self.assertEqual(correction["judgment_count"], limit + 1)
                        packet = self.fx.packet(db, *Fixture.ITEMS, mode="primary")
                        request = mapping_request(self.fx, packet["packet_id"], saved["response_id"], [entry(limit, target)])
                        revision = db.max_revision()
                        with self.assertRaises(InvalidRequest):
                            review.map_response(db, mapping=request)
                        self.assertEqual(db.max_revision(), revision)
                        self.map(db, saved["response_id"], [entry(i, R("arguments", "arg_lem"))
                                                         for i in action["judgment_indexes"]])
                        partial = review.inspect_response(db, response_id=saved["response_id"])
                        self.assertEqual(partial["state"], "needs_revision")
                        self.assertEqual(partial["checks"][0]["outcome"], "gap")

    def test_disjoint_packet_pairing_defers_packet_dependent_repairs_and_preserves_bytes(self):
        with self.fx.open() as db:
            lemma = packets.get_packet(db, targets=[R("items", "itm_lem")], mode="independent")
            theorem = packets.get_packet(db, targets=[R("items", "itm_thm")], mode="independent")
            worker = worker_response(theorem["packet_id"], [judgment(R("items", "itm_thm"),
                kind="external_source", outcome="gap", evidence=("anc_thm",))], covered=[R("items", "itm_thm")])
            raw = canonical_bytes(worker)
            envelope = submission(self.fx, lemma["packet_id"])
            saved = review.submit_review(db, submission=envelope, response_bytes=raw)
            self.assertEqual(saved["state"], "needs_revision")
            self.assertEqual(saved["checks"], [])
            info = review.inspect_response(db, response_id=saved["response_id"])
            self.assertIn("covered_target_out_of_scope", info["diagnostic_categories"])
            self.assertIn("missing_neutral_source", [p["category"] for row in info["judgment_diagnostics"] for p in row["problems"]])
            action, = info["recovery"]
            self.assertEqual(action["operation"], "inspect_assignment")
            self.assertEqual(action["reason_code"], "PACKET_MISMATCH")
            self.assertEqual(action["envelope_packet_id"], lemma["packet_id"])
            self.assertEqual(action["worker_packet_id"], theorem["packet_id"])
            with self.assertRaises(InvalidRequest) as caught:
                self.map(db, saved["response_id"], [entry(0, R("items", "itm_thm"))])
            self.assertEqual(caught.exception.code, "RESPONSE_SCOPE")
            corrected = review.submit_review(db, submission=submission(self.fx, theorem["packet_id"]), response_bytes=raw)
            self.assertEqual(corrected["state"], "accepted")
            self.assertEqual(review.inspect_response(db, response_id=corrected["response_id"])["checks"][0]["outcome"], "gap")
            replay = review.submit_review(db, submission=envelope, response_bytes=raw)
            self.assertEqual(replay["receipt"], saved["receipt"])
            self.assertEqual(replay["state"], "needs_revision")
            self.assertNotIn("recovery", replay)
            self.assertEqual(db.get_blob(info["original_blob_sha256"]), raw)
            item = db.head("items", "itm_lem")
            self.fx.apply(db, [edit("replace", "items", item.id,
                dict(item.body, statement={"form": "transcription", "text": "A changed lemma."}), item.version)])
            changed = review.inspect_response(db, response_id=saved["response_id"])
            self.assertTrue(changed["mapping_input_changes"]["records"])
            self.assertEqual(changed["recovery"], info["recovery"])

    def test_wrong_worker_identity_also_gets_neutral_pairing_until_authored_correction(self):
        with self.fx.open() as db:
            lemma = packets.get_packet(db, targets=[R("items", "itm_lem")], mode="independent")
            theorem = packets.get_packet(db, targets=[R("items", "itm_thm")], mode="independent")
            worker = worker_response(theorem["packet_id"], [judgment(R("items", "itm_lem"),
                kind="external_source", evidence=("anc_lem",))])
            raw = canonical_bytes(worker)
            saved = review.submit_review(db, submission=submission(self.fx, lemma["packet_id"]), response_bytes=raw)
            info = review.inspect_response(db, response_id=saved["response_id"])
            action, = info["recovery"]
            self.assertEqual(action["operation"], "inspect_assignment")
            self.assertEqual((action["envelope_packet_id"], action["worker_packet_id"]),
                             (lemma["packet_id"], theorem["packet_id"]))
            worker["packet_id"] = lemma["packet_id"]
            corrected = review.submit_review(db, submission=submission(self.fx, lemma["packet_id"]),
                                              response_bytes=canonical_bytes(worker))
            self.assertEqual(corrected["state"], "accepted")
            self.assertEqual(db.get_blob(info["original_blob_sha256"]), raw)

    def test_missing_nonobject_and_invalid_identity_remain_authoring_problems(self):
        with self.fx.open() as db:
            packet = packets.get_packet(db, targets=[R("items", "itm_lem")], mode="independent")
            missing = worker_response(packet["packet_id"], [])
            del missing["packet_id"]
            invalid = worker_response("invalid packet identity", [])
            for worker in (missing, [], invalid):
                with self.subTest(worker=worker):
                    saved = review.submit_review(db, submission=submission(self.fx, packet["packet_id"]),
                                                 response_bytes=canonical_bytes(worker))
                    self.assertEqual(saved["state"], "needs_revision")
                    self.assertEqual(saved["checks"], [])
                    info = review.inspect_response(db, response_id=saved["response_id"])
                    self.assertIn("worker_response_invalid_shape", info["diagnostic_categories"])
                    self.assertNotIn("worker_packet_mismatch", info["diagnostic_categories"])
                    self.assertIn("author_response_correction", [a["operation"] for a in info["recovery"]])
                    self.assertNotIn("inspect_assignment", [a["operation"] for a in info["recovery"]])

    def test_pairing_does_not_hide_independent_shape_and_provenance_problems(self):
        with self.fx.open() as db:
            packet = packets.get_packet(db, targets=[R("items", "itm_lem")], mode="independent")
            worker = worker_response("pkt_other", [])
            del worker["coverage_note"]
            saved = review.submit_review(db, submission=submission(self.fx, packet["packet_id"]),
                                         response_bytes=canonical_bytes(worker))
            info = review.inspect_response(db, response_id=saved["response_id"])
            self.assertEqual(set(info["diagnostic_categories"]), {"worker_packet_mismatch", "worker_response_invalid_shape"})
            self.assertEqual({a["operation"] for a in info["recovery"]},
                             {"inspect_assignment", "author_response_correction", "obtain_independent_review"})

    def test_unreadable_worker_has_authored_correction_diagnostic(self):
        with self.fx.open() as db:
            packet = packets.get_packet(db, targets=[R("items", "itm_lem")], mode="independent")
            saved = review.submit_review(db, submission=submission(self.fx, packet["packet_id"]), response_bytes=b"not JSON")
            info = review.inspect_response(db, response_id=saved["response_id"])
            self.assertEqual(info["diagnostic_categories"], ["worker_response_invalid_json"])
            self.assertEqual(info["judgment_count"], 0)
            self.assertIn("author_response_correction", [a["operation"] for a in info["recovery"]])

    def test_current_inspection_is_read_only(self):
        with self.fx.open() as db:
            saved, _, _ = self.submit(db, [judgment(source_target("anc_lem_proof", "route"))])
            self.map(db, saved["response_id"], [entry(0, R("arguments", "arg_lem"))])
            before = {"revision": db.max_revision(), "receipts": list(db.conn.execute("SELECT receipt_json FROM commits")),
                      "blobs": list(db.conn.execute("SELECT sha256, content FROM blobs"))}
        before_bytes = self.fx.path.read_bytes()
        with self.fx.open(write=False) as db:
            info = review.inspect_response(db, response_id=saved["response_id"])
            self.assertEqual(db.max_revision(), before["revision"])
            self.assertEqual(list(db.conn.execute("SELECT receipt_json FROM commits")), before["receipts"])
            self.assertEqual(list(db.conn.execute("SELECT sha256, content FROM blobs")), before["blobs"])
            preserved = copy.deepcopy(info)
            review.response_recovery(info)
            self.assertEqual(info, preserved)
        self.assertEqual(self.fx.path.read_bytes(), before_bytes)


if __name__ == "__main__":
    unittest.main()
