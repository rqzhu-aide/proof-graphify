"""Observational timing telemetry: events, summaries, ``timed``, and command instrumentation.

The two-hour pilot of implementation-handoff 10 is measured entirely through these calls, so the
tests below pin the event vocabulary, the exact aggregates, the rejection codes, and the promise that
telemetry stays observational: it never writes a commit and never changes a command's outcome.

Durations are asserted as types and bounds, never as exact milliseconds; wherever ordering or a run
window has to be exact, the events carry explicit ``started_at`` stamps from ``at`` so the assertion
does not race the clock.
"""
from __future__ import annotations

import argparse
import json
import re
import time
import unittest

import support
from paper_core import CORE_VERSION, cli, storage, telemetry
from paper_core.errors import InvalidRequest

# The measurement categories implementation-handoff 10 asks the pilot to separate, in that order.
HANDOFF_STAGES = ("reading_reasoning", "authoring", "retry", "renewal", "command", "waiting", "report",
                  "combined")
EMPTY_BUCKET = {"events": 0, "elapsed_ms": 0, "unknown_elapsed": 0}
ISO_MS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
# The details a command event carries; a failed command adds "error_code" and nothing else.
COMMAND_DETAIL_KEYS = ["command", "core_version", "exit_code", "outcome", "subcommand"]
FAILED_COMMAND_DETAIL_KEYS = sorted(COMMAND_DETAIL_KEYS + ["error_code"])
# Every command that takes the database as its positional argument; each one must offer --run-id.
DB_COMMANDS = frozenset({
    "apply", "attach", "backup", "changes", "checkpoint", "compare", "export", "get", "init",
    "migrate-overview", "qualification record", "release", "review map", "review reconcile",
    "review submit", "source anchor", "source capture", "source review", "source diagnostics", "status", "telemetry record",
    "telemetry summary", "validate", "migrate", "work list", "work prepare", "work submit", "work inspect",
    "template", "review mapping-template", "work extend", "stage1 status", "stage1 prepare",
    "stage2 status", "stage2 prepare", "stage2 finalize"})
NO_DB_COMMANDS = frozenset({"ids", "import-legacy", "version", "stage3 build"})


def at(millisecond: int) -> str:
    """A fixed, ordered start stamp, so ordering and windows are asserted without racing the clock."""
    return f"2026-09-14T00:00:00.{millisecond:03d}Z"


def bucket(events: int, elapsed_ms: int, unknown: int = 0) -> dict:
    return {"events": events, "elapsed_ms": elapsed_ms, "unknown_elapsed": unknown}


def stored_events(path, run_id=None) -> list:
    """Read the events back through a fresh read-only connection."""
    with storage.Database(path) as db:
        return telemetry.events(db, run_id=run_id)


def command_leaves(parser, prefix=()) -> list:
    """Every leaf command of the CLI parser with its positionals, options and telemetry marking."""
    groups = [action for action in parser._actions if isinstance(action, argparse._SubParsersAction)]
    if not groups:
        return [{"name": " ".join(prefix),
                 "positionals": [a.dest for a in parser._actions if not a.option_strings],
                 "options": {s for a in parser._actions for s in a.option_strings},
                 "telemetry_own": bool(parser.get_default("telemetry_own"))}]
    leaves = []
    for group in groups:
        for name, sub in sorted(group.choices.items()):
            leaves.extend(command_leaves(sub, prefix + (name,)))
    return leaves


class RecordEventTests(support.TempCase):
    """``record_event`` appends one flat row and validates every field before touching the database."""

    def setUp(self):
        super().setUp()
        self.fx = self.fixture()

    def test_receipt_echoes_the_identity_and_omits_the_details(self):
        """record_event returns exactly the stored identity (id, run, stage, start, duration), not details."""
        with self.fx.open() as db:
            receipt = telemetry.record_event(db, run_id="run_a", stage="authoring", elapsed_ms=1200,
                                             details={"note": "typed the structure batch"},
                                             started_at=at(1))
        self.assertEqual(sorted(receipt), ["elapsed_ms", "event_id", "run_id", "stage", "started_at"])
        self.assertEqual({key: receipt[key] for key in ("run_id", "stage", "elapsed_ms", "started_at")},
                         {"run_id": "run_a", "stage": "authoring", "elapsed_ms": 1200, "started_at": at(1)})
        self.assertTrue(receipt["event_id"].startswith("evt_"), receipt["event_id"])
        self.assertEqual(len(receipt["event_id"]), 36)
        self.assertEqual(stored_events(self.fx.path)[0]["event_id"], receipt["event_id"])

    def test_the_stored_row_is_flat_and_canonical(self):
        """The identity fields are columns; details_json is the caller's object, canonical and unescaped."""
        details = {"note": "ünïcode", "nested": {"a": [1, 2]}}
        with self.fx.open() as db:
            receipt = telemetry.record_event(db, run_id="run_flat", stage="report", elapsed_ms=7,
                                             details=details, started_at=at(3))
            row = dict(db.conn.execute("SELECT * FROM run_events").fetchone())
        self.assertEqual(sorted(row), ["details_json", "elapsed_ms", "id", "run_id", "stage", "started_at"])
        self.assertEqual([row["id"], row["run_id"], row["stage"], row["started_at"], row["elapsed_ms"]],
                         [receipt["event_id"], "run_flat", "report", at(3), 7])
        self.assertEqual(row["details_json"], '{"nested":{"a":[1,2]},"note":"ünïcode"}')

    def test_readback_is_flat_and_keeps_nested_details_verbatim(self):
        """events() rows carry six top-level keys; only the caller's own details nest."""
        details = {"a": {"b": [1, 2, {"c": None}]}, "z": "ünïcode"}
        with self.fx.open() as db:
            telemetry.record_event(db, run_id="run_flat", stage="combined", elapsed_ms=5, details=details,
                                   started_at=at(4))
        event = stored_events(self.fx.path)[0]
        self.assertEqual(sorted(event),
                         ["details", "elapsed_ms", "event_id", "run_id", "stage", "started_at"])
        self.assertEqual(event["details"], details)
        self.assertEqual(event["elapsed_ms"], 5)

    def test_an_unknown_duration_is_stored_as_null_with_empty_details(self):
        """Omitting elapsed_ms and details records a null duration and {}, and stamps the start itself."""
        before = storage.now_iso()
        with self.fx.open() as db:
            receipt = telemetry.record_event(db, run_id="run_unknown", stage="waiting")
        after = storage.now_iso()
        event = stored_events(self.fx.path)[0]
        self.assertIsNone(receipt["elapsed_ms"])
        self.assertIsNone(event["elapsed_ms"])
        self.assertEqual(event["details"], {})
        self.assertRegex(receipt["started_at"], ISO_MS)
        self.assertLessEqual(before, receipt["started_at"])
        self.assertLessEqual(receipt["started_at"], after)
        self.assertEqual(event["started_at"], receipt["started_at"])

    def test_every_stage_of_the_handoff_vocabulary_is_accepted(self):
        """STAGES is the pilot's measurement vocabulary and the schema accepts each of its members."""
        self.assertEqual(telemetry.STAGES, HANDOFF_STAGES)
        with self.fx.open() as db:
            for index, stage in enumerate(telemetry.STAGES):
                telemetry.record_event(db, run_id="run_all", stage=stage, elapsed_ms=index,
                                       started_at=at(index))
            summary = telemetry.summarize(db, run_id="run_all")
        self.assertEqual(summary["events"], len(HANDOFF_STAGES))
        self.assertEqual({stage: summary["stages"][stage]["events"] for stage in HANDOFF_STAGES},
                         {stage: 1 for stage in HANDOFF_STAGES})
        self.assertEqual([event["stage"] for event in stored_events(self.fx.path)], list(HANDOFF_STAGES))

    def test_a_run_id_at_the_length_limit_is_accepted(self):
        """128 characters is the last accepted run id; 129 is refused, so the boundary itself is pinned."""
        longest = "r" * 128
        with self.fx.open() as db:
            telemetry.record_event(db, run_id=longest, stage="command", elapsed_ms=0, started_at=at(1))
            with self.assertRaises(InvalidRequest) as caught:
                telemetry.record_event(db, run_id=longest + "r", stage="command", elapsed_ms=0)
        self.assertEqual(caught.exception.code, "INVALID_EVENT")
        self.assertEqual([event["run_id"] for event in stored_events(self.fx.path)], [longest])

    def test_each_invalid_field_is_refused_with_its_own_reason(self):
        """Bad run_id, stage, elapsed_ms or details raise INVALID_EVENT (exit 2) and write nothing."""
        cases = [("run_id", {"run_id": "1bad", "stage": "authoring"}),
                 ("run_id", {"run_id": "run a", "stage": "authoring"}),
                 ("run_id", {"run_id": "", "stage": "authoring"}),
                 ("run_id", {"run_id": None, "stage": "authoring"}),
                 ("run_id", {"run_id": "r" * 129, "stage": "authoring"}),
                 ("stage", {"run_id": "run_a", "stage": "daydreaming"}),
                 ("stage", {"run_id": "run_a", "stage": None}),
                 ("elapsed_ms", {"run_id": "run_a", "stage": "authoring", "elapsed_ms": -1}),
                 ("elapsed_ms", {"run_id": "run_a", "stage": "authoring", "elapsed_ms": 1.5}),
                 ("elapsed_ms", {"run_id": "run_a", "stage": "authoring", "elapsed_ms": True}),
                 ("details", {"run_id": "run_a", "stage": "authoring", "details": ["a"]}),
                 ("details", {"run_id": "run_a", "stage": "authoring", "details": "note"})]
        with self.fx.open() as db:
            for field, kwargs in cases:
                with self.subTest(field=field, kwargs=kwargs):
                    with self.assertRaises(InvalidRequest) as caught:
                        telemetry.record_event(db, **kwargs)
                    self.assertEqual(caught.exception.code, "INVALID_EVENT")
                    self.assertEqual(caught.exception.exit_code, 2)
                    self.assertEqual([reason.split()[0] for reason in caught.exception.records], [field])
        self.assertEqual(stored_events(self.fx.path), [])

    def test_all_reasons_are_reported_together(self):
        """One rejected event lists every failing field, in field order, rather than the first alone."""
        with self.fx.open() as db:
            with self.assertRaises(InvalidRequest) as caught:
                telemetry.record_event(db, run_id="1bad", stage="nope", elapsed_ms=-2, details=3)
        self.assertEqual([reason.split()[0] for reason in caught.exception.records],
                         ["run_id", "stage", "elapsed_ms", "details"])
        self.assertIn("reading_reasoning", caught.exception.records[1])
        self.assertEqual(stored_events(self.fx.path), [])

    def test_a_read_only_database_refuses_to_record(self):
        """Recording needs a writable database; the refusal is INVALID_REQUEST and writes nothing."""
        with self.fx.open(write=False) as db:
            with self.assertRaises(InvalidRequest) as caught:
                telemetry.record_event(db, run_id="run_ro", stage="command", elapsed_ms=3)
            self.assertEqual(caught.exception.code, "INVALID_REQUEST")
            self.assertEqual(caught.exception.exit_code, 2)
            self.assertIn("writable", caught.exception.message)
            self.assertEqual(telemetry.events(db), [])
            # The field validation runs first, so a bad event is a bad event whatever the connection is.
            with self.assertRaises(InvalidRequest) as bad_field:
                telemetry.record_event(db, run_id="run_ro", stage="daydreaming")
            self.assertEqual(bad_field.exception.code, "INVALID_EVENT")

    def test_unserializable_details_leave_the_database_usable(self):
        """A details object that is not JSON rolls back: no row, no open transaction, later events work."""
        with self.fx.open() as db:
            with self.assertRaises(TypeError):
                telemetry.record_event(db, run_id="run_bad", stage="authoring", details={"set": {1, 2}})
            self.assertFalse(db.conn.in_transaction)
            self.assertEqual(telemetry.events(db), [])
            telemetry.record_event(db, run_id="run_bad", stage="authoring", elapsed_ms=1, started_at=at(9))
            self.assertEqual([event["run_id"] for event in telemetry.events(db)], ["run_bad"])

    def test_events_never_commit_a_revision(self):
        """Telemetry is observational: recording events adds no commit and no record version."""
        with self.fx.open() as db:
            revision = db.max_revision()
            versions = db.conn.execute("SELECT COUNT(*) FROM record_versions").fetchone()[0]
            for index, stage in enumerate(("command", "authoring", "report")):
                telemetry.record_event(db, run_id="run_obs", stage=stage, elapsed_ms=index, started_at=at(index))
            self.assertEqual(db.max_revision(), revision)
            self.assertEqual(db.conn.execute("SELECT COUNT(*) FROM record_versions").fetchone()[0], versions)
            self.assertEqual(db.conn.execute("SELECT COUNT(*) FROM run_events").fetchone()[0], 3)


class EventQueryTests(support.TempCase):
    """``events`` and ``summarize`` over a known, deterministic set of recorded events."""

    def setUp(self):
        super().setUp()
        self.fx = self.fixture()

    def record(self, rows):
        with self.fx.open() as db:
            for run_id, stage, elapsed, started in rows:
                telemetry.record_event(db, run_id=run_id, stage=stage, elapsed_ms=elapsed,
                                       details={"row": started}, started_at=started)

    def test_events_of_an_untouched_database_is_an_empty_list(self):
        """A database with no telemetry answers with [] rather than failing or inventing rows."""
        self.assertEqual(stored_events(self.fx.path), [])
        self.assertEqual(stored_events(self.fx.path, run_id="run_missing"), [])

    def test_events_are_ordered_by_start_time_whatever_the_write_order(self):
        """events() sorts by started_at, so a late-written earlier measurement still reads in order."""
        self.record([("run_a", "authoring", 10, at(30)), ("run_a", "retry", 20, at(10)),
                     ("run_a", "waiting", None, at(20))])
        self.assertEqual([event["started_at"] for event in stored_events(self.fx.path)],
                         [at(10), at(20), at(30)])
        self.assertEqual([event["stage"] for event in stored_events(self.fx.path)],
                         ["retry", "waiting", "authoring"])

    def test_events_sharing_a_start_stamp_break_ties_by_event_id(self):
        """Ties on started_at order by event id, not by write order, so a read is reproducible."""
        self.record([("run_tie", "waiting", index, at(7)) for index in range(10)])
        events = stored_events(self.fx.path)
        ids = [event["event_id"] for event in events]
        self.assertEqual(len(ids), 10)
        self.assertEqual([event["started_at"] for event in events], [at(7)] * 10)
        # The ids are random, so write order is uncorrelated with id order: this fails without the tiebreak.
        self.assertEqual(ids, sorted(ids))
        self.assertEqual([event["event_id"] for event in stored_events(self.fx.path)], ids)

    def test_events_filter_by_run_id(self):
        """A run_id filter returns that run's events only, and the unfiltered call returns all of them."""
        self.record([("run_a", "authoring", 1, at(1)), ("run_b", "retry", 2, at(2)),
                     ("run_a", "report", 3, at(3))])
        self.assertEqual([event["started_at"] for event in stored_events(self.fx.path, run_id="run_a")],
                         [at(1), at(3)])
        self.assertEqual({event["run_id"] for event in stored_events(self.fx.path, run_id="run_b")}, {"run_b"})
        self.assertEqual(len(stored_events(self.fx.path)), 3)

    def test_summary_counts_events_as_an_integer(self):
        """summarize()["events"] is a live integer count of the events, never the events themselves."""
        self.record([("run_a", "authoring", 1, at(1)), ("run_a", "retry", 2, at(2))])
        with self.fx.open(write=False) as db:
            summary = telemetry.summarize(db)
        self.assertEqual(sorted(summary), ["events", "observational_only", "run_id", "runs", "stages"])
        self.assertEqual(summary["events"], 2)
        self.assertIsInstance(summary["events"], int)
        self.assertIs(summary["observational_only"], True)
        self.assertIsNone(summary["run_id"])
        self.record([("run_a", "report", 3, at(3))])
        with self.fx.open(write=False) as db:
            self.assertEqual(telemetry.summarize(db)["events"], 3)

    def test_summary_totals_each_stage_exactly(self):
        """Per-stage totals add the known durations, count unknown durations apart, and list every stage."""
        self.record([("run_sum", "authoring", 120, at(1)), ("run_sum", "authoring", 380, at(2)),
                     ("run_sum", "retry", 45, at(3)), ("run_sum", "waiting", None, at(4)),
                     ("run_sum", "report", 0, at(5))])
        with self.fx.open(write=False) as db:
            stages = telemetry.summarize(db)["stages"]
        self.assertEqual(sorted(stages), sorted(HANDOFF_STAGES))
        self.assertEqual(stages["authoring"], bucket(2, 500))
        self.assertEqual(stages["retry"], bucket(1, 45))
        self.assertEqual(stages["waiting"], bucket(1, 0, 1))
        self.assertEqual(stages["report"], bucket(1, 0))
        for stage in ("reading_reasoning", "renewal", "command", "combined"):
            self.assertEqual(stages[stage], EMPTY_BUCKET, stage)

    def test_summary_rolls_each_run_up_with_its_window(self):
        """Runs are listed in run_id order with their event count, totals and first/last start stamps."""
        # run_a's events are written newest-first, so first/last_started_at must be a min/max, not the
        # first and last row seen.
        self.record([("run_b", "command", 30, at(40)), ("run_a", "authoring", 120, at(30)),
                     ("run_a", "waiting", None, at(20)), ("run_a", "authoring", 80, at(10))])
        with self.fx.open(write=False) as db:
            runs = telemetry.summarize(db)["runs"]
        window = ("run_id", "events", "elapsed_ms", "unknown_elapsed", "first_started_at", "last_started_at")
        self.assertEqual([run["run_id"] for run in runs], ["run_a", "run_b"])
        self.assertEqual({key: runs[0][key] for key in window},
                         {"run_id": "run_a", "events": 3, "elapsed_ms": 200, "unknown_elapsed": 1,
                          "first_started_at": at(10), "last_started_at": at(30)})
        self.assertEqual({key: runs[1][key] for key in window},
                         {"run_id": "run_b", "events": 1, "elapsed_ms": 30, "unknown_elapsed": 0,
                          "first_started_at": at(40), "last_started_at": at(40)})
        self.assertEqual(runs[0]["stages"], {"authoring": bucket(2, 200), "waiting": bucket(1, 0, 1)})
        self.assertEqual(runs[1]["stages"], {"command": bucket(1, 30)})

    def test_summary_for_one_run_restricts_every_aggregate(self):
        """A run_id narrows the event count, the run list and the per-stage totals to that run alone."""
        self.record([("run_a", "authoring", 120, at(1)), ("run_b", "authoring", 900, at(2)),
                     ("run_b", "command", 15, at(3))])
        with self.fx.open(write=False) as db:
            summary = telemetry.summarize(db, run_id="run_b")
        self.assertEqual(summary["run_id"], "run_b")
        self.assertEqual(summary["events"], 2)
        self.assertEqual([run["run_id"] for run in summary["runs"]], ["run_b"])
        self.assertEqual(summary["runs"][0]["events"], 2)
        self.assertEqual(summary["stages"]["authoring"], bucket(1, 900))
        self.assertEqual(summary["stages"]["command"], bucket(1, 15))

    def test_summary_for_an_unknown_run_is_empty_but_well_formed(self):
        """An unmeasured run reports zero events with every stage bucket present and zeroed."""
        self.record([("run_a", "authoring", 120, at(1))])
        with self.fx.open(write=False) as db:
            summary = telemetry.summarize(db, run_id="run_never")
        self.assertEqual(summary["events"], 0)
        self.assertEqual(summary["runs"], [])
        self.assertEqual(summary["stages"], {stage: dict(EMPTY_BUCKET) for stage in HANDOFF_STAGES})
        self.assertIs(summary["observational_only"], True)


class TimedTests(support.TempCase):
    """The ``timed`` context manager measures a block and records it whatever the block does."""

    def setUp(self):
        super().setUp()
        self.fx = self.fixture()

    def only_event(self):
        events = stored_events(self.fx.path)
        self.assertEqual(len(events), 1, events)
        return events[0]

    def test_timed_records_the_stage_the_details_and_a_plausible_duration(self):
        """A completed block records its stage, the details passed and yielded, and outcome "ok"."""
        with self.fx.open() as db:
            with telemetry.timed(db, run_id="run_t", stage="reading_reasoning",
                                 details={"item": "itm_lem"}) as info:
                info["pages"] = 2
        event = self.only_event()
        self.assertEqual(event["run_id"], "run_t")
        self.assertEqual(event["stage"], "reading_reasoning")
        self.assertEqual(event["details"], {"item": "itm_lem", "pages": 2, "outcome": "ok"})
        self.assertIsInstance(event["elapsed_ms"], int)
        self.assertNotIsInstance(event["elapsed_ms"], bool)
        self.assertGreaterEqual(event["elapsed_ms"], 0)
        self.assertLess(event["elapsed_ms"], 60000)

    def test_timed_does_not_mutate_the_details_it_was_given(self):
        """The caller's details dict is copied, so "outcome" and block additions stay inside the event."""
        passed = {"item": "itm_thm"}
        with self.fx.open() as db:
            with telemetry.timed(db, run_id="run_t", stage="authoring", details=passed) as info:
                info["added"] = True
        self.assertEqual(passed, {"item": "itm_thm"})
        self.assertEqual(self.only_event()["details"], {"item": "itm_thm", "added": True, "outcome": "ok"})

    def test_timed_measures_the_block_in_milliseconds(self):
        """The recorded duration covers the block's elapsed time and is milliseconds, bounded not exact."""
        with self.fx.open() as db:
            with telemetry.timed(db, run_id="run_t", stage="waiting"):
                time.sleep(0.05)
        elapsed = self.only_event()["elapsed_ms"]
        self.assertGreaterEqual(elapsed, 30)
        # A seconds- or microseconds-scaled duration would land far outside this window.
        self.assertLess(elapsed, 5000)

    def test_timed_stamps_the_start_of_the_block_not_its_end(self):
        """started_at marks when the block began, so a slow block's stamp precedes a stamp taken inside it."""
        with self.fx.open() as db:
            with telemetry.timed(db, run_id="run_t", stage="report"):
                time.sleep(0.05)
                midpoint = storage.now_iso()
        event = self.only_event()
        self.assertRegex(event["started_at"], ISO_MS)
        self.assertLess(event["started_at"], midpoint)

    def test_timed_records_and_reraises_when_the_block_fails(self):
        """A failing block still records its event, marked outcome "error", and the exception propagates."""
        with self.fx.open() as db:
            with self.assertRaises(ValueError) as caught:
                with telemetry.timed(db, run_id="run_t", stage="retry", details={"attempt": 2}) as info:
                    info["where"] = "schema conflict"
                    raise ValueError("boom")
        self.assertEqual(str(caught.exception), "boom")
        event = self.only_event()
        self.assertEqual(event["stage"], "retry")
        self.assertEqual(event["details"], {"attempt": 2, "where": "schema conflict", "outcome": "error"})
        self.assertGreaterEqual(event["elapsed_ms"], 0)

    def test_timed_records_an_interrupted_block(self):
        """An interruption is a measured outcome too: the event is written and the interrupt propagates."""
        with self.fx.open() as db:
            with self.assertRaises(KeyboardInterrupt):
                with telemetry.timed(db, run_id="run_t", stage="combined") as info:
                    info["phase"] = "reading"
                    raise KeyboardInterrupt
        self.assertEqual(self.only_event()["details"], {"phase": "reading", "outcome": "error"})

    def test_timed_keeps_an_outcome_the_block_set_itself(self):
        """An outcome chosen by the caller survives; timed only fills one in when none was set."""
        with self.fx.open() as db:
            with telemetry.timed(db, run_id="run_t", stage="renewal", details={"outcome": "partial"}):
                pass
        self.assertEqual(self.only_event()["details"], {"outcome": "partial"})


class CommandInstrumentationTests(support.TempCase):
    """``--run-id`` attributes a command event to a run without ever changing the command's outcome."""

    def setUp(self):
        super().setUp()
        self.fx = self.fixture()
        self.db = self.fx.path

    def test_every_database_command_offers_run_id(self):
        """The db-taking commands are exactly the known set and each accepts --run-id."""
        leaves = {leaf["name"]: leaf for leaf in command_leaves(cli.build_parser())}
        with_db = {name for name, leaf in leaves.items() if "db" in leaf["positionals"]}
        self.assertEqual(with_db, DB_COMMANDS)
        self.assertEqual(set(leaves) - with_db, NO_DB_COMMANDS)
        for name in sorted(with_db):
            with self.subTest(command=name):
                self.assertIn("--run-id", leaves[name]["options"])
        for name in sorted(NO_DB_COMMANDS):
            with self.subTest(command=name):
                self.assertNotIn("--run-id", leaves[name]["options"])
        self.assertEqual({name for name, leaf in leaves.items() if leaf["telemetry_own"]},
                         {"telemetry record", "telemetry summary"})

    def test_commands_attribute_their_events_to_the_run(self):
        """Four commands under one --run-id record four "command" events; a fifth run stays separate."""
        support.run_cli("status", self.db, "--run-id", "run_pilot")
        support.run_cli("changes", self.db, "--since", 0, "--run-id", "run_pilot")
        support.run_cli("validate", self.db, "--run-id", "run_pilot")
        support.run_cli("export", self.db, "--out", self.path("out", "export.json"), "--run-id", "run_pilot")
        support.run_cli("status", self.db, "--run-id", "run_other")
        summary, _ = support.run_cli("telemetry", "summary", self.db, "--run-id", "run_pilot", "--events")
        self.assertEqual(summary["events"], 4)
        self.assertEqual([event["details"]["command"] for event in summary["event_list"]],
                         ["status", "changes", "validate", "export"])
        for event in summary["event_list"]:
            with self.subTest(command=event["details"]["command"]):
                self.assertEqual(event["run_id"], "run_pilot")
                self.assertEqual(event["stage"], "command")
                self.assertEqual(sorted(event["details"]), COMMAND_DETAIL_KEYS)
                self.assertEqual(event["details"]["exit_code"], 0)
                self.assertEqual(event["details"]["outcome"], "ok")
                self.assertEqual(event["details"]["core_version"], CORE_VERSION)
                self.assertIsNone(event["details"]["subcommand"])
                self.assertIsInstance(event["elapsed_ms"], int)
                self.assertGreaterEqual(event["elapsed_ms"], 0)
                self.assertLess(event["elapsed_ms"], 600000)
        self.assertEqual(summary["stages"]["command"]["events"], 4)
        self.assertEqual(summary["stages"]["authoring"], EMPTY_BUCKET)
        whole, _ = support.run_cli("telemetry", "summary", self.db)
        self.assertEqual(whole["events"], 5)
        self.assertEqual([(run["run_id"], run["events"]) for run in whole["runs"]],
                         [("run_other", 1), ("run_pilot", 4)])

    def test_a_command_without_run_id_records_nothing(self):
        """Instrumentation is opt-in: an uninstrumented command leaves the event log empty."""
        support.run_cli("status", self.db)
        self.assertEqual(stored_events(self.db), [])

    def test_a_failed_command_records_its_error_code(self):
        """A refused command is still measured, with its exit code and the CoreError code in the details."""
        failure, _ = support.run_cli("status", self.db, "--snapshot", "999", "--run-id", "run_pilot", expect=2)
        self.assertEqual(failure["error"]["code"], "REVISION_RANGE")
        events = stored_events(self.db, run_id="run_pilot")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["stage"], "command")
        self.assertEqual(sorted(events[0]["details"]), FAILED_COMMAND_DETAIL_KEYS)
        self.assertEqual(events[0]["details"]["error_code"], "REVISION_RANGE")
        self.assertEqual(events[0]["details"]["exit_code"], 2)
        self.assertEqual(events[0]["details"]["outcome"], "error")
        self.assertEqual(events[0]["details"]["command"], "status")

    def test_a_failed_subcommand_records_both_halves_of_its_name(self):
        """A two-word command records the group as "command" and the action as "subcommand"."""
        failure, _ = support.run_cli("source", "capture", self.db, "--files", self.path("missing.json"),
                                     "--run-id", "run_pilot", expect=2)
        self.assertEqual(failure["error"]["code"], "FILE_UNREADABLE")
        details = stored_events(self.db, run_id="run_pilot")[0]["details"]
        self.assertEqual([details["command"], details["subcommand"]], ["source", "capture"])
        self.assertEqual(details["error_code"], "FILE_UNREADABLE")

    def test_a_usage_error_is_not_measured(self):
        """Arguments that never parse cannot be attributed to a run, so nothing is recorded for them."""
        failure, _ = support.run_cli("changes", self.db, "--since", 0, "--limit", "later",
                                     "--run-id", "run_pilot", expect=2)
        self.assertEqual(failure["error"]["code"], "USAGE")
        self.assertEqual(stored_events(self.db), [])

    def test_an_unusable_run_id_never_changes_the_command_outcome(self):
        """A run id the event validator rejects is reported on stderr; the command still succeeds."""
        payload, stderr = support.run_cli("status", self.db, "--run-id", "1 bad")
        self.assertEqual(payload["command"], "status")
        self.assertEqual(payload["paper"]["id"], self.fx.paper_id)
        self.assertIn("telemetry: could not record command event", stderr)
        self.assertIn("invalid run event", stderr)
        self.assertEqual(stored_events(self.db), [])

    def test_telemetry_commands_do_not_measure_themselves(self):
        """telemetry record and summary record only what they are asked to, never a command event."""
        support.run_cli("telemetry", "record", self.db, "--run-id", "run_pilot", "--stage", "authoring",
                        "--elapsed-ms", "1200", "--details", '{"note": "typed the structure batch"}')
        support.run_cli("telemetry", "summary", self.db, "--run-id", "run_pilot")
        events = stored_events(self.db)
        self.assertEqual([(event["stage"], event["elapsed_ms"]) for event in events], [("authoring", 1200)])
        self.assertEqual(events[0]["details"], {"note": "typed the structure batch"})

    def test_summary_lists_individual_events_only_when_asked(self):
        """--events adds event_list; the plain summary reports the same count without the events."""
        support.run_cli("telemetry", "record", self.db, "--run-id", "run_pilot", "--stage", "report",
                        "--elapsed-ms", "50")
        support.run_cli("telemetry", "record", self.db, "--run-id", "run_other", "--stage", "waiting")
        listed, _ = support.run_cli("telemetry", "summary", self.db, "--events")
        plain, _ = support.run_cli("telemetry", "summary", self.db)
        self.assertEqual(listed["events"], 2)
        self.assertEqual(len(listed["event_list"]), 2)
        self.assertEqual({event["stage"] for event in listed["event_list"]}, {"report", "waiting"})
        self.assertNotIn("event_list", plain)
        self.assertEqual(plain["events"], 2)
        self.assertEqual(plain["stages"], listed["stages"])
        self.assertEqual(plain["stages"]["report"], {"events": 1, "elapsed_ms": 50, "unknown_elapsed": 0})
        self.assertEqual(plain["stages"]["waiting"], {"events": 1, "elapsed_ms": 0, "unknown_elapsed": 1})

    def test_summary_events_honour_the_run_filter(self):
        """--events with --run-id lists that run's events only."""
        support.run_cli("telemetry", "record", self.db, "--run-id", "run_pilot", "--stage", "report",
                        "--elapsed-ms", "50")
        support.run_cli("telemetry", "record", self.db, "--run-id", "run_other", "--stage", "waiting")
        listed, _ = support.run_cli("telemetry", "summary", self.db, "--run-id", "run_other", "--events")
        self.assertEqual([event["run_id"] for event in listed["event_list"]], ["run_other"])
        self.assertEqual(listed["events"], 1)
        self.assertIsNone(listed["event_list"][0]["elapsed_ms"])
        self.assertEqual(listed["stages"]["report"], EMPTY_BUCKET)

    def test_record_takes_details_inline_or_from_a_file(self):
        """--details accepts a JSON object as text or the path of a file holding one."""
        path = support.write_json(self.path("details.json"), {"from": "file"})
        support.run_cli("telemetry", "record", self.db, "--run-id", "run_pilot", "--stage", "authoring",
                        "--details", '{"from": "text"}')
        support.run_cli("telemetry", "record", self.db, "--run-id", "run_pilot", "--stage", "report",
                        "--details", path)
        self.assertEqual([event["details"] for event in stored_events(self.db, run_id="run_pilot")],
                         [{"from": "text"}, {"from": "file"}])

    def test_record_stores_the_started_at_it_was_given(self):
        """--started-at fixes the event's start stamp, and the stored order follows those stamps."""
        support.run_cli("telemetry", "record", self.db, "--run-id", "run_pilot", "--stage", "waiting",
                        "--started-at", at(42))
        receipt, _ = support.run_cli("telemetry", "record", self.db, "--run-id", "run_pilot",
                                     "--stage", "report", "--elapsed-ms", "9", "--started-at", at(11))
        self.assertEqual(receipt["started_at"], at(11))
        self.assertEqual([(event["stage"], event["started_at"])
                          for event in stored_events(self.db, run_id="run_pilot")],
                         [("report", at(11)), ("waiting", at(42))])

    def test_record_refuses_a_bad_event_and_writes_nothing(self):
        """An unknown stage, a negative duration and non-object details are all refused at exit 2."""
        for args, code in ((("--stage", "daydreaming"), "INVALID_EVENT"),
                           (("--stage", "authoring", "--elapsed-ms", "-5"), "INVALID_EVENT"),
                           (("--stage", "authoring", "--details", "[1,2]"), "INVALID_EVENT"),
                           (("--stage", "authoring", "--details", "not json"), "USAGE")):
            with self.subTest(args=args):
                failure, _ = support.run_cli("telemetry", "record", self.db, "--run-id", "run_pilot",
                                             *args, expect=2)
                self.assertEqual(failure["error"]["code"], code)
        self.assertEqual(stored_events(self.db), [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
