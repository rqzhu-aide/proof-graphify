from __future__ import annotations

import importlib.util
import copy
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "evals" / "release_eval.py"
SPEC = importlib.util.spec_from_file_location("proofcheck_release_eval", SCRIPT)
evaluation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(evaluation)


class ReleaseEvaluationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.run = self.base / "release run"
        self.configuration = {
            "role": "current", "configuration_id": "test-configuration",
            "checker_id": "checker-context", "description": "Synthetic harness test, not measured checker performance.",
        }

    def tearDown(self) -> None:
        self.temp.cleanup()

    def prepare(self, cases: list[str] | None = None) -> dict:
        evaluation.prepare(self.run, self.configuration, "development", 20260904, cases or ["q-7b42"])
        return evaluation.read_json(self.run / "run.json")

    def submission(self, binding: dict, *, rationale: int = 2) -> tuple[Path, Path]:
        packet = evaluation.read_json(self.run / binding["path"])
        response = {
            "packet_id": packet["packet_id"],
            "conclusions": [{
                "conclusion_id": row["conclusion_id"], "argument_status": "valid",
                "statement_status": "established", "defect_lines": [],
                "justification": "The fixed finite union has finitely many vanishing terms, so its probability bound tends to zero.",
                "counterexample": None, "repair": None,
            } for row in packet["conclusions"]],
        }
        response_path = self.base / f"{packet['packet_id']}.response.json"
        assessment_path = self.base / f"{packet['packet_id']}.assessment.json"
        evaluation.write_new(response_path, response)
        evaluation.assessment_template(response_path, assessment_path)
        assessment = evaluation.read_json(assessment_path)
        assessment["assessor"] = {"assessor_id": "independent-review-context", "independence": "different_model"}
        for row in assessment["conclusions"]:
            row.update(rationale_score=rationale, reason="Independent synthetic assessment for the harness regression.")
        assessment_path.write_bytes(evaluation.encoded(assessment))
        return response_path, assessment_path

    def test_corpus_has_eight_intact_pairs_two_chains_and_provisional_keys(self) -> None:
        cases = evaluation.load_corpus()
        self.assertEqual(18, len(cases))
        self.assertEqual(20, sum(len(row["problem"]["conclusions"]) for row in cases.values()))
        families = {}
        for case in cases.values():
            self.assertEqual("pending", case["key"]["expert_review"]["status"])
            families.setdefault(case["pair_id"], []).append(case)
        pairs = [rows for rows in families.values() if len(rows) == 2]
        chains = [rows for rows in families.values() if len(rows) == 1]
        self.assertEqual(8, len(pairs))
        self.assertEqual(2, len(chains))
        for rows in pairs:
            self.assertEqual({"correct", "flawed"}, {row["variant"] for row in rows})
            self.assertEqual(1, len({row["split"] for row in rows}))
        self.assertEqual({"development", "heldout"}, {rows[0]["split"] for rows in chains})

    def test_packets_are_neutral_complete_and_reproducible(self) -> None:
        manifest = self.prepare(["q-7b42", "q-d190"])
        other = self.base / "other run"
        evaluation.prepare(other, {**self.configuration, "role": "baseline"}, "development", 20260904, ["q-7b42", "q-d190"])
        for binding in manifest["packets"]:
            packet = evaluation.read_json(self.run / binding["path"])
            self.assertRegex(Path(binding["path"]).name, r"^[a-f0-9]{16}\.json$")
            self.assertEqual({"packet_version", "packet_id", "instructions", "source_lines", "conclusions", "response_format"}, set(packet))
            self.assertEqual((self.run / binding["path"]).read_bytes(), (other / binding["path"]).read_bytes())
            serialized = json.dumps(packet)
            for forbidden in ("pair_id", "expert_review", "statement_truth", "key_sha256", "rationale_score", "configuration_id"):
                self.assertNotIn(forbidden, serialized)
            source = evaluation.load_corpus()[binding["case_id"]]["problem"]["source"]
            self.assertEqual(source.splitlines(), [row["text"] for row in packet["source_lines"]])
        with self.assertRaisesRegex(ValueError, "already exists"):
            evaluation.prepare(self.run, self.configuration, "development", 1)

    def test_heldout_selection_cannot_silently_cross_split(self) -> None:
        with self.assertRaisesRegex(ValueError, "crosses"):
            evaluation.prepare(self.run, self.configuration, "development", 1, ["q-ec61"])
        self.assertFalse(self.run.exists())

    def test_correct_labels_with_false_mathematics_are_not_supported(self) -> None:
        manifest = self.prepare()
        response_path, assessment_path = self.submission(manifest["packets"][0], rationale=0)
        response = evaluation.read_json(response_path)
        response["conclusions"][0]["justification"] = (
            "Pointwise convergence controls the maximum over any growing number of indices without any uniform condition."
        )
        response_path.write_bytes(evaluation.encoded(response))
        assessment = evaluation.read_json(assessment_path)
        assessment["response_sha256"] = evaluation.digest_file(response_path)
        assessment["conclusions"][0]["reason"] = "The label is correct for a finite maximum, but the stated growing-maximum principle is false."
        assessment_path.write_bytes(evaluation.encoded(assessment))
        evaluation.record(self.run, response_path, assessment_path, [], None)
        summary = evaluation.summarize(self.run)
        self.assertEqual({"numerator": 1, "denominator": 1}, summary["metrics"]["label_match"])
        self.assertEqual({"numerator": 0, "denominator": 1}, summary["metrics"]["supported_label_match"])
        self.assertEqual(1, len(summary["correct_labels_with_unsupported_rationale"]))
        self.assertEqual(1, summary["expert_review_pending_packets"])

    def test_assessment_requires_a_separate_declared_context_and_exact_response(self) -> None:
        manifest = self.prepare()
        response_path, assessment_path = self.submission(manifest["packets"][0])
        assessment = evaluation.read_json(assessment_path)
        assessment["assessor"]["assessor_id"] = self.configuration["checker_id"]
        assessment_path.write_bytes(evaluation.encoded(assessment))
        with self.assertRaisesRegex(ValueError, "separate declared assessor"):
            evaluation.record(self.run, response_path, assessment_path, [], None)
        assessment["assessor"]["assessor_id"] = "different-context"
        assessment["response_sha256"] = "0" * 64
        assessment_path.write_bytes(evaluation.encoded(assessment))
        with self.assertRaisesRegex(ValueError, "exact response bytes"):
            evaluation.record(self.run, response_path, assessment_path, [], None)
        self.assertFalse((self.run / "records").exists())

    def test_serious_errors_remain_visible_separately_from_average_scores(self) -> None:
        cases = evaluation.load_corpus()
        key = cases["q-d190"]["key"]["conclusions"][0]
        response = {"conclusion_id": "C001", "argument_status": "valid", "statement_status": "established", "defect_lines": []}
        score = evaluation.score_conclusion(response, {"rationale_score": 0}, key)
        self.assertTrue(score["serious_false_verification"])
        key = cases["q-c812"]["key"]["conclusions"][0]
        response.update(argument_status="invalid", statement_status="refuted", defect_lines=[4])
        score = evaluation.score_conclusion(response, {"rationale_score": 0}, key)
        self.assertTrue(score["serious_false_refutation"])

    def test_false_establishment_is_reported_even_when_argument_is_gap(self) -> None:
        key = evaluation.load_corpus()["q-d190"]["key"]["conclusions"][0]
        response = {"conclusion_id": "C001", "argument_status": "gap", "statement_status": "established", "defect_lines": [6]}
        score = evaluation.score_conclusion(response, {"rationale_score": 0}, key)
        self.assertTrue(score["serious_false_establishment"])
        self.assertTrue(score["inconsistent_establishment"])
        self.assertFalse(score["serious_false_verification"])
        response["statement_status"] = "not_established"
        score = evaluation.score_conclusion(response, {"rationale_score": 2}, key)
        self.assertFalse(score["serious_false_establishment"])
        self.assertFalse(score["inconsistent_establishment"])

    def test_historical_scores_are_read_without_silent_v2_upgrade(self) -> None:
        manifest = self.prepare()
        manifest.pop("scorer_version")
        manifest["run_version"] = 1
        (self.run / "run.json").write_bytes(evaluation.encoded(manifest))
        response, assessment = self.submission(manifest["packets"][0])
        evaluation.record(self.run, response, assessment, [], None)
        path = self.run / "records" / f"{manifest['packets'][0]['packet_id']}.json"
        stored = evaluation.read_json(path)
        stored.pop("scorer_version")
        stored["record_version"] = 1
        path.write_bytes(evaluation.encoded(stored))
        before = path.read_bytes()
        self.assertNotIn("serious_false_establishment", stored["scores"][0])
        summary = evaluation.summarize(self.run)
        self.assertEqual(1, summary["scorer_version"])
        self.assertIsNone(summary["serious_false_establishment"])
        self.assertEqual(before, path.read_bytes())

    def test_false_establishment_reaches_the_recorded_summary(self) -> None:
        manifest = self.prepare(["q-d190"])
        response_path, assessment_path = self.submission(manifest["packets"][0], rationale=0)
        response = evaluation.read_json(response_path)
        response["conclusions"][0]["argument_status"] = "gap"
        response_path.write_bytes(evaluation.encoded(response))
        assessment = evaluation.read_json(assessment_path)
        assessment["response_sha256"] = evaluation.digest_file(response_path)
        assessment_path.write_bytes(evaluation.encoded(assessment))
        evaluation.record(self.run, response_path, assessment_path, [], None)
        summary = evaluation.summarize(self.run)
        self.assertEqual(1, len(summary["serious_false_establishment"]))
        self.assertEqual([], summary["serious_false_verification"])
        self.assertEqual(1, len(summary["inconsistent_establishment"]))

    def test_new_preparation_records_exposure_without_changing_historical_split(self) -> None:
        historical = (evaluation.ROOT / "catalog.json").read_bytes()
        manifest = self.prepare(["q-52fd"])
        self.assertEqual("heldout", evaluation.load_corpus()["q-52fd"]["split"])
        self.assertEqual("development", manifest["allocation"]["effective_splits"]["q-52fd"])
        with self.assertRaisesRegex(ValueError, "crosses"):
            evaluation.prepare(self.base / "heldout", self.configuration, "heldout", 1, ["q-52fd"])
        self.assertEqual(historical, (evaluation.ROOT / "catalog.json").read_bytes())

    def test_fingerprint_covers_role_instructions_helpers_and_supplied_prompt(self) -> None:
        implementation = self.base / "implementation"
        for relative in ("SKILL.md", "scripts/proofcheck.py", "scripts/proofcheck_report.py",
                         "references/challenge-protocol.md", "assets/templates/CHALLENGE_ARTIFACT.md"):
            path = implementation / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"Synthetic fixture {relative}", encoding="utf-8")
        prompt = self.base / "actual-prompt.txt"
        prompt.write_text("Actual supplied synthetic test prompt", encoding="utf-8")
        self.configuration.update(implementation_path=str(implementation), supplied_files=[str(prompt)])
        manifest = self.prepare()
        identities = manifest["configuration"]["implementation_files"]
        self.assertEqual(5, len(identities))
        self.assertEqual(evaluation.digest_file(prompt), manifest["configuration"]["supplied_file_identities"][0]["sha256"])
        response, assessment = self.submission(manifest["packets"][0])
        (implementation / "references/challenge-protocol.md").write_text("Changed role instructions", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Prepared implementation"):
            evaluation.record(self.run, response, assessment, [], None)

    def test_location_counts_penalize_shotgun_flags(self) -> None:
        key = evaluation.load_corpus()["q-d190"]["key"]["conclusions"][0]
        response = {"conclusion_id": "C001", "argument_status": "invalid", "statement_status": "refuted", "defect_lines": [1, 2, 3, 4, 5, 6, 7]}
        score = evaluation.score_conclusion(response, {"rationale_score": 2}, key)
        self.assertEqual({"true_positive_lines": 1, "predicted_lines": 7, "gold_lines": 1}, score["localization"])

    def test_partial_run_and_missing_telemetry_remain_explicit(self) -> None:
        manifest = self.prepare(["q-7b42", "q-a057"])
        response_path, assessment_path = self.submission(manifest["packets"][0])
        evaluation.record(self.run, response_path, assessment_path, [], None)
        summary = evaluation.summarize(self.run)
        self.assertEqual(2, summary["prepared_conclusions"])
        self.assertEqual(1, summary["scored_conclusions"])
        self.assertEqual(1, summary["unrecorded_packets"])
        self.assertIsNone(summary["usage"]["tokens"]["input"]["observed_sum"])
        self.assertIsNone(summary["usage"]["sum_of_observed_case_wall_seconds"])
        self.assertIsNone(summary["usage"]["financial_cost"])
        self.assertEqual(1, summary["usage"]["records_without_usage_files"])
        self.assertEqual(1, summary["metrics"]["repair_score"]["unassessed"])

    def test_usage_links_are_deduplicated_and_missing_token_fields_stay_unknown(self) -> None:
        manifest = self.prepare(["q-7b42", "q-a057"])
        usage_path = self.base / "RUN_USAGE.json"
        evaluation.write_new(usage_path, {
            "schema_version": 1, "kind": "stat-paper-proofcheck-usage", "observational_only": True,
            "events": [{"event_id": "test-only-event", "stage": "primary", "recorded_utc": "2026-09-04T12:00:00Z",
                        "work_packets": 2, "unit_ids": ["C001"], "cache_outcome": "not_used",
                        "tokens": {"source": "reported", "input": 100, "cached_input": None, "output": 20, "reasoning": None},
                        "notes": "Synthetic unit-test telemetry; not a real checker measurement."}],
        })
        for index, binding in enumerate(manifest["packets"]):
            response, assessment = self.submission(binding)
            evaluation.record(self.run, response, assessment, [usage_path], 1.25 if index == 0 else None)
        summary = evaluation.summarize(self.run)
        self.assertEqual(1, len(summary["usage"]["files"]))
        self.assertEqual(100, summary["usage"]["tokens"]["input"]["observed_sum"])
        self.assertIsNone(summary["usage"]["tokens"]["cached_input"]["observed_sum"])
        self.assertEqual(1.25, summary["usage"]["sum_of_observed_case_wall_seconds"])
        self.assertEqual(1, summary["usage"]["cases_without_wall_time"])

    def usage_fixture(self, name: str, events: list[dict] | None = None) -> Path:
        event = {"event_id": "run-one:call-one", "stage": "primary", "recorded_utc": "2026-09-04T12:00:00Z",
                 "work_packets": 1, "unit_ids": ["C001"], "cache_outcome": "not_used",
                 "tokens": {"source": "reported", "input": 100, "cached_input": None, "output": 20, "reasoning": None}}
        path = self.base / name
        evaluation.write_new(path, {"schema_version": 1, "kind": "stat-paper-proofcheck-usage",
                                   "observational_only": True, "events": events if events is not None else [event]})
        return path

    def test_copied_usage_and_cumulative_snapshots_count_each_event_once(self) -> None:
        first = self.usage_fixture("first.json")
        copied = self.base / "copy.json"
        copied.write_bytes(first.read_bytes())
        original = evaluation.read_usage(first)
        events = copy.deepcopy(original["events"])
        second_event = copy.deepcopy(events[0])
        second_event["event_id"] = "run-one:call-two"
        second_event["tokens"]["input"] = 50
        events.append(second_event)
        cumulative = self.usage_fixture("cumulative.json", events)
        observations = [original, evaluation.read_usage(copied), evaluation.read_usage(cumulative)]
        files, unique, unavailable = evaluation.collect_usage(observations)
        self.assertEqual(2, len(files))
        self.assertEqual(2, len(unique))
        self.assertEqual(150, sum(event["tokens"]["input"] for event in unique))
        self.assertEqual([], unavailable)

    def test_changed_captured_usage_and_conflicting_event_copies_are_rejected(self) -> None:
        observed = evaluation.read_usage(self.usage_fixture("usage.json"))
        altered = copy.deepcopy(observed)
        altered["events"][0]["tokens"]["input"] = 999
        with self.assertRaisesRegex(ValueError, "disagree with their source"):
            evaluation.collect_usage([altered])
        altered = copy.deepcopy(observed)
        altered["source_utf8"] += " "
        with self.assertRaisesRegex(ValueError, "source content changed"):
            evaluation.collect_usage([altered])
        conflicting_events = copy.deepcopy(observed["events"])
        conflicting_events[0]["tokens"]["input"] = 999
        conflicting = evaluation.read_usage(self.usage_fixture("conflicting.json", conflicting_events))
        with self.assertRaisesRegex(ValueError, "Conflicting usage observations"):
            evaluation.collect_usage([observed, conflicting])

    def test_unavailable_legacy_usage_is_unknown_and_not_summed(self) -> None:
        path = self.usage_fixture("legacy.json")
        observed = evaluation.read_usage(path)
        observed.pop("source_utf8")
        self.assertEqual(1, len(evaluation.collect_usage([observed])[1]))
        path.unlink()
        files, events, unavailable = evaluation.collect_usage([observed])
        self.assertEqual(([], []), (files, events))
        self.assertEqual(1, len(unavailable))

    def test_conflicting_usage_is_rejected_before_second_record_is_written(self) -> None:
        manifest = self.prepare(["q-7b42", "q-a057"])
        path = self.usage_fixture("original.json")
        response, assessment = self.submission(manifest["packets"][0])
        evaluation.record(self.run, response, assessment, [path], None)
        events = evaluation.read_usage(path)["events"]
        events[0]["tokens"]["output"] = 999
        conflicting = self.usage_fixture("conflict.json", events)
        response, assessment = self.submission(manifest["packets"][1])
        with self.assertRaisesRegex(ValueError, "Conflicting usage observations"):
            evaluation.record(self.run, response, assessment, [conflicting], None)
        self.assertEqual(1, len(list((self.run / "records").glob("*.json"))))

    def test_summary_rejects_event_mutation_and_keeps_captured_source_when_file_moves(self) -> None:
        manifest = self.prepare()
        binding = manifest["packets"][0]
        response, assessment = self.submission(binding)
        usage = self.usage_fixture("source.json")
        workflow = self.base / "execution.txt"
        workflow.write_text("Synthetic test execution evidence, not a real audit.", encoding="utf-8")
        evaluation.record(self.run, response, assessment, [usage], None, [workflow])
        usage.unlink()
        summary = evaluation.summarize(self.run)
        self.assertEqual(100, summary["usage"]["tokens"]["input"]["observed_sum"])
        self.assertEqual(1, summary["workflow_evidence"]["records_with_attachments"])
        path = self.run / "records" / f"{binding['packet_id']}.json"
        row = evaluation.read_json(path)
        row["usage_files"][0]["events"][0]["tokens"]["input"] = 900
        path.write_bytes(evaluation.encoded(row))
        with self.assertRaisesRegex(ValueError, "disagree with their source"):
            evaluation.summarize(self.run)

    def test_record_is_no_overwrite_and_changed_payload_is_rejected(self) -> None:
        manifest = self.prepare()
        binding = manifest["packets"][0]
        response, assessment = self.submission(binding)
        evaluation.record(self.run, response, assessment, [], None)
        with self.assertRaises(FileExistsError):
            evaluation.record(self.run, response, assessment, [], None)
        record_path = self.run / "records" / f"{binding['packet_id']}.json"
        stored = evaluation.read_json(record_path)
        stored["response"]["conclusions"][0]["justification"] = "A different justification was substituted after scoring."
        record_path.write_bytes(evaluation.encoded(stored))
        with self.assertRaisesRegex(ValueError, "stored response"):
            evaluation.summarize(self.run)

    def test_mutated_packet_and_unassessed_rationale_cannot_be_recorded(self) -> None:
        manifest = self.prepare()
        binding = manifest["packets"][0]
        response, assessment = self.submission(binding)
        original = (self.run / binding["path"]).read_bytes()
        (self.run / binding["path"]).write_bytes(original + b" ")
        with self.assertRaisesRegex(ValueError, "packet changed"):
            evaluation.record(self.run, response, assessment, [], None)
        (self.run / binding["path"]).write_bytes(original)
        unassessed = evaluation.read_json(assessment)
        unassessed["conclusions"][0]["rationale_score"] = None
        assessment.write_bytes(evaluation.encoded(unassessed))
        with self.assertRaisesRegex(ValueError, "independently assigned"):
            evaluation.record(self.run, response, assessment, [], None)

    def test_comparison_retains_configuration_and_incomplete_overlap(self) -> None:
        manifest = self.prepare(["q-7b42", "q-a057"])
        response, assessment = self.submission(manifest["packets"][0])
        evaluation.record(self.run, response, assessment, [], None)
        other = self.base / "baseline"
        evaluation.prepare(other, {**self.configuration, "role": "baseline", "configuration_id": "baseline-config"},
                           "development", 20260904, ["q-7b42", "q-a057"])
        result = evaluation.compare([other, self.run])
        self.assertTrue(result["same_prepared_cases"])
        self.assertEqual([], result["common_recorded_cases"])
        self.assertEqual(2, len(result["common_prepared_cases"]))
        self.assertEqual(["baseline", "current"], [row["configuration"]["role"] for row in result["configurations"]])
        self.assertIsNone(result["configurations"][0]["usage"]["tokens"]["input"]["observed_sum"])
        with self.assertRaisesRegex(ValueError, "distinct"):
            evaluation.compare([self.run, self.run])


if __name__ == "__main__":
    unittest.main()
