"""Scaling guards for ``get``, ``apply``, ``status`` and render input (implementation-handoff 10).

The handoff's early measurement protocol asks for "generated large-record fixtures for ``get``,
``apply``, ``status``, and render input construction to detect accidental whole-store scans" and for
operation count and bytes read/written to be compared alongside wall time. This module is the
regression guard half of that request. It builds the same paper twice, once with a handful of extra
results and once with an order of magnitude more, and compares deterministic sqlite counters between
the two stores.

Wall time is deliberately not asserted. A loaded machine moves it by more than any regression this
module is meant to catch, so the only assertions here are over counters that are a pure function of
the stored records: how many statements the core issued, how many rows those statements actually
delivered, and how many bytes those rows carried. Those numbers reproduce run to run on one machine,
and they are what "accidental whole-store scan" means in practice. (Absolute byte totals are not
portable between machines: the paper record stores its source root, so the length of the temporary
directory path lands in the figures for the operations that read that record, measured here as
``status`` and ``projection``. The constant part cancels out of the ratios and the per-added-record
budgets asserted below, which is why only those are asserted.)

Two opposite shapes are guarded, because the two kinds of operation have opposite obligations.

* ``packets.get_packet`` on one statement and ``acceptance.apply_batch`` of one small edit walk out
  from their own target. Their cost must stay put as unrelated results are added, so they are held to
  a constant factor and to a near-zero budget per record added to the store.
* ``queries.status`` and ``projection.build_projection`` legitimately read the whole live snapshot, so
  a constant bound would be false. They are held to the opposite guard: cost may grow linearly with
  the live snapshot but not faster, because a quadratic snapshot builder is the realistic accident.

Nothing is measured by reading sqlite internals. ``Database`` exposes its connection as the plain
attribute ``db.conn`` and every read in the core goes through it, so the fixtures wrap that connection
in a proxy that counts. The proxy covers both routes sqlite offers, ``conn.execute`` and
``conn.cursor().execute``, because a regression is as likely to be written one way as the other; and
each measured operation runs inside a watcher that fails if the operation opened a connection of its
own, which is the other way work could pass the proxy unseen. ``TestCountingProxy`` proves all of that
is really in the path before any scaling claim is made, and ``TestCalibration`` proves the thresholds
below actually discriminate: the deliberately whole-store paper-scoped closure, measured on the same
two stores, blows through every bounded read threshold this module sets.

Every record in both stores is created through the real public API (``packets`` plus
``acceptance.apply_batch``), never by inserting rows, so a fixture that stops being reachable through
the public interface fails here too.
"""
from __future__ import annotations

import contextlib
import sqlite3
import tempfile
import unittest
from pathlib import Path

from support import Fixture, R, edit, rmtree_force

from paper_core import acceptance, packets, projection, queries

# Extra major results beyond the two that support.Fixture builds. Each one costs four records (an
# item, its argument, its final group and the use that consumes the lemma), so the stores differ by a
# factor of about six in live records while both still build in well under a second.
SMALL_EXTRA = 10
LARGE_EXTRA = 100
# New major items need a paper-scoped packet, and a paper-scoped closure grows with the store, so the
# growth is applied in chunks rather than as one enormous batch.
CHUNK = 20

# -- measured baseline ------------------------------------------------------------------------------
# Counters observed on this exact fixture pair (small: 12 items / 71 live records, large: 102 items /
# 431 live records). Statement, row and write counts are machine independent; the byte column carries
# the temporary source-root path, so it lands within a few bytes of these figures elsewhere.
#
#   operation                   executes        rows          bytes        writes
#   get (statement target)      47 ->    47     32 ->    32    8880 ->   8880   2 -> 2
#   apply (one replace)         32 ->    32     21 ->    21    8546 ->   8546   5 -> 5
#   status                      20 ->    20    228 ->  1308   96693 -> 471726   0 -> 0
#   build_projection            11 ->    11     80 ->   440   38775 -> 163786   0 -> 0
#   get (paper target)         112 ->   742    108 ->   828   21737 -> 154219   2 -> 2
#
# The last row is not a regression: a paper-scoped packet is defined to read the whole paper. It is
# carried through the module as the calibration point that says what a whole-store scan looks like
# here, so the bounded thresholds below can be shown to separate the two.

# A bounded operation may issue a few more statements on a larger store (the closure of the same
# target is not literally byte-identical), but not a multiple of them. Today both bounded operations
# sit at exactly 1.00; the paper-scoped closure sits at 6.62, so 2.0 leaves honest drift a lot of room
# while still failing a per-record query regression.
BOUNDED_EXECUTE_FACTOR = 2.0
BOUNDED_WRITE_FACTOR = 2.0

# What a single pass over the store costs, by definition: reading every live record once delivers one
# row per live record, however narrow the row is. Nothing bounded may reach this.
WHOLE_STORE_ROWS_PER_RECORD = 1.0
# The sharpest guard in the module: how many extra rows the operation delivers for each extra live
# record in the store. A closure that walks out from its target reads a bounded neighbourhood, so this
# number should sit near zero. Measured today: exactly 0.00 rows/record for both get and apply, which
# is what a closure that reaches its neighbours through the reference index rather than by filtering a
# collection costs. The budget is half of a whole-store pass: far above today's cost, and still only half of the
# cheapest scan anyone could write. It is deliberately not set at 1.0, because a scan selecting only
# key columns lands on exactly 1.0 and a budget of 1.0 would admit it.
BOUNDED_ROWS_PER_RECORD = WHOLE_STORE_ROWS_PER_RECORD / 2
# The same budget in bytes. Measured today: 0 bytes/record for get and for apply; the paper-scoped
# closure carries 368. 250 sits between them with roughly a factor of two either side. Bytes are the
# blunter of the two budgets, because a scan over key columns alone carries very little payload; the
# row budget above is what actually catches that shape.
BOUNDED_BYTES_PER_RECORD = 250.0

# Whole-snapshot operations are allowed to grow with the snapshot, so they are measured per live
# record instead. Today status costs 3.21 -> 3.03 rows per record and the projection 1.13 -> 1.02, i.e.
# the per-record cost falls slightly as the store grows. A quadratic builder would multiply it by the
# size ratio (about six here), so requiring that it does not even double is generous to honest linear
# work and fatal to a quadratic one.
SNAPSHOT_PER_RECORD_FACTOR = 2.0
# Statement count for the snapshot operations is constant today (20 and 11). One query per record
# would multiply it by the size ratio, so 3.0 fails that while leaving room for a handful of new
# fixed-cost queries.
SNAPSHOT_EXECUTE_FACTOR = 3.0
# The generous super-linear bound the handoff asks for, expressed as a fraction of the squared size
# ratio: honest linear growth lands near 1.0x the size ratio, a quadratic regression near its square.
SUPER_LINEAR_FRACTION = 0.5

COUNTERS = ("executes", "rows", "bytes", "writes")


# -- counting proxy ---------------------------------------------------------------------------------
class _Counter:
    """Deterministic tally of sqlite work: statements issued, rows delivered, bytes in those rows."""

    WRITE_VERBS = ("INSERT", "UPDATE", "DELETE", "REPLACE")

    def __init__(self):
        self.executes = 0
        self.rows = 0
        self.bytes = 0
        self.writes = 0

    def note(self, sql: str):
        """Record one statement, classified as a read or a write by its leading verb."""
        self.executes += 1
        # The whole first word is compared rather than a fixed-width prefix: "REPLACE" is seven
        # letters, and a six-character slice would silently never match it.
        words = sql.split(None, 1)
        if words and words[0].upper() in self.WRITE_VERBS:
            self.writes += 1

    def note_script(self):
        """A script is many statements at once; in this core it only ever creates schema and rows."""
        self.executes += 1
        self.writes += 1

    def snapshot(self) -> dict:
        return {name: getattr(self, name) for name in COUNTERS}


def _row_bytes(row) -> int:
    """Payload size of one delivered row; text and blobs by length, other values as a flat 8."""
    total = 0
    for value in tuple(row):
        if isinstance(value, str):
            total += len(value.encode("utf-8"))
        elif isinstance(value, (bytes, bytearray)):
            total += len(value)
        elif value is not None:
            total += 8
    return total


class _CountingCursor:
    """A cursor that counts the rows the caller actually takes, however the caller takes them.

    Statements issued on the cursor itself are counted here too, so a read written the ordinary sqlite
    way -- ``conn.cursor()`` and then ``cursor.execute(...)`` -- is as visible as ``conn.execute``.
    """

    def __init__(self, cursor, counter: _Counter):
        self._cursor = cursor
        self._counter = counter

    def __getattr__(self, name):
        return getattr(self._cursor, name)

    def _delivered(self, row):
        if row is not None:
            self._counter.rows += 1
            self._counter.bytes += _row_bytes(row)
        return row

    def __iter__(self):
        for row in self._cursor:
            yield self._delivered(row)

    def execute(self, sql, *args):
        self._counter.note(sql)
        self._cursor.execute(sql, *args)
        return self

    def executemany(self, sql, *args):
        self._counter.note(sql)
        self._cursor.executemany(sql, *args)
        return self

    def executescript(self, script):
        self._counter.note_script()
        self._cursor.executescript(script)
        return self

    def fetchone(self):
        return self._delivered(self._cursor.fetchone())

    def fetchall(self) -> list:
        rows = self._cursor.fetchall()
        for row in rows:
            self._delivered(row)
        return rows

    def fetchmany(self, *args) -> list:
        rows = self._cursor.fetchmany(*args)
        for row in rows:
            self._delivered(row)
        return rows


class _CountingConnection:
    """A stand-in for ``Database.conn`` that tallies every statement and every row it hands back."""

    def __init__(self, conn, counter: _Counter):
        self._conn = conn
        self._counter = counter

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def cursor(self, *args):
        """Hand back a counting cursor, so ``conn.cursor()`` is not a hole in the instrument."""
        return _CountingCursor(self._conn.cursor(*args), self._counter)

    def execute(self, sql, *args):
        self._counter.note(sql)
        # sqlite3 builds the cursor for this statement on the wrapped connection, not through the
        # method above, so the statement is counted here exactly once and never twice.
        return _CountingCursor(self._conn.execute(sql, *args), self._counter)

    def executemany(self, sql, *args):
        self._counter.note(sql)
        return _CountingCursor(self._conn.executemany(sql, *args), self._counter)

    def executescript(self, script):
        self._counter.note_script()
        return _CountingCursor(self._conn.executescript(script), self._counter)


def counted(fixture: Fixture, *, write: bool = False):
    """Open one store with the counting proxy installed; returns ``(database, counter)``."""
    db = fixture.open(write=write)
    counter = _Counter()
    db.conn = _CountingConnection(db.conn, counter)
    return db, counter


@contextlib.contextmanager
def watching_connections():
    """Yield the list of sqlite connections opened while the block runs.

    The proxy above sees only work done on the connection it wraps. Code that opened a second
    connection to the same file -- its own ``Database``, or a bare ``sqlite3.connect`` -- could read
    the whole store without moving a single counter, and every bound in this module would then hold
    for the wrong reason. Swapping ``sqlite3.connect`` for the length of one operation is how that
    escape route is detected. The swap is process wide, so it is only ever wrapped around a single
    synchronous call in this single-threaded module, and it is always restored.
    """
    opened = []
    real_connect = sqlite3.connect

    def spy(*args, **kwargs):
        opened.append(args[0] if args else kwargs.get("database"))
        return real_connect(*args, **kwargs)

    sqlite3.connect = spy
    try:
        yield opened
    finally:
        sqlite3.connect = real_connect


def take(counter: _Counter, operation) -> dict:
    """Run one operation; return the counter movement it caused and the connections it opened."""
    before = counter.snapshot()
    with watching_connections() as opened:
        operation()
    after = counter.snapshot()
    measured = {name: after[name] - before[name] for name in COUNTERS}
    measured["connections"] = len(opened)
    return measured


# -- generated stores -------------------------------------------------------------------------------
def extra_edits(start: int, count: int) -> list:
    """``count`` further major results, each with its own proof route and one consumed premise.

    The extra results reuse the fixture's existing anchors and global scope, and every one of them
    hangs off the lemma rather than the theorem, so none of them belongs to the theorem's closure.
    That is the point: they are exactly the "unrelated items" a bounded operation must not read.
    """
    edits = []
    for index in range(start, start + count):
        item_id, argument_id = f"itm_x{index}", f"arg_x{index}"
        group_id, use_id = f"grp_x{index}", f"use_x{index}"
        edits.append(edit("create", "items", item_id, {
            "kind": "lemma", "label": f"Extra lemma {index}", "caption": f"Extra lemma {index}",
            "statement": {"form": "verbatim", "text": f"Extra lemma {index} text"},
            "passages": [{"role": "statement", "anchor_id": "anc_lem"},
                         {"role": "proof", "anchor_id": "anc_lem_proof"}],
            "aliases": [], "uncertainty": None, "origin": "source", "owner_id": None, "scope_id": None}))
        edits.append(edit("create", "arguments", argument_id, {
            "target": R("items", item_id), "label": f"Proof of {item_id}", "origin": "source",
            "scope_id": "scp_plain", "final_group_id": group_id, "evidence_refs": ["anc_lem_proof"],
            "lifecycle": "registered"}))
        edits.append(edit("create", "groups", group_id, {
            "argument_id": argument_id, "conclusion": R("items", item_id), "kind": "joint",
            "scope_id": "scp_plain", "case_scope_ids": [], "discharges": [], "rationale": "one step",
            "evidence_refs": ["anc_lem_proof"]}))
        edits.append(edit("create", "uses", use_id, {
            "from": R("items", "itm_lem"), "to": R("items", item_id), "type": "dependency",
            "group_id": group_id, "reason": "applied as stated", "needed_form": None, "substitutions": [],
            "evidence_refs": ["anc_lem_proof"], "regime": None, "uncertainty": None}))
    return edits


class Store:
    """One completed paper grown to a chosen size, with every measured counter already taken."""

    def __init__(self, root: Path, extra: int):
        self.extra = extra
        self.fixture = Fixture(root, tag=f"sc{extra}", title=f"Scaling fixture {extra}")
        self.fixture.complete()
        self._grow(extra)
        self.counts = self._counts()
        self.live = sum(self.counts.values())
        self.items = self.counts["items"]
        self.measured = self._measure()

    def _grow(self, extra: int):
        with self.fixture.open() as db:
            for start in range(0, extra, CHUNK):
                self.fixture.apply(db, extra_edits(start, min(CHUNK, extra - start)))

    def _counts(self) -> dict:
        with self.fixture.open(write=False) as db:
            return queries.status(db)["counts"]

    def _measure(self) -> dict:
        """Take every counter once; each operation runs inside its own measured window."""
        measured = {}
        db, counter = counted(self.fixture, write=True)
        with db:
            measured["get"] = take(counter, lambda: packets.get_packet(
                db, targets=[R("items", "itm_thm")], mode="author"))
            measured["get_paper"] = take(counter, lambda: packets.get_packet(
                db, targets=[R("papers", self.fixture.paper_id)], mode="author"))

            # the packet is issued outside the measured window; only the acceptance run is counted
            packet = packets.get_packet(db, targets=[R("items", "itm_thm")], mode="author")
            head = db.head("items", "itm_thm")
            body = dict(head.body, caption="Theorem 1 (edited)")
            measured["apply"] = take(counter, lambda: acceptance.apply_batch(db, {
                "contract_version": 3, "request_id": self.fixture.request_id(),
                "packet_id": packet["packet_id"],
                "edits": [edit("replace", "items", "itm_thm", body, head.version)]}))

        db, counter = counted(self.fixture, write=False)
        with db:
            measured["status"] = take(counter, lambda: queries.status(db))
            measured["projection"] = take(counter, lambda: projection.build_projection(db))
        return measured


SMALL: Store = None
LARGE: Store = None
_ROOT: Path = None


def setUpModule():
    global SMALL, LARGE, _ROOT
    _ROOT = Path(tempfile.mkdtemp(prefix="paper_core_scaling_"))
    try:
        SMALL = Store(_ROOT / "small", SMALL_EXTRA)
        LARGE = Store(_ROOT / "large", LARGE_EXTRA)
    except BaseException:
        # unittest skips tearDownModule when setUpModule raises, so a build that fails partway
        # would strand two sqlite stores and their sources in the system temp directory.
        SMALL = LARGE = None
        rmtree_force(_ROOT)
        _ROOT = None
        raise


def tearDownModule():
    if _ROOT is not None and _ROOT.exists():
        rmtree_force(_ROOT)


# -- comparison helpers -----------------------------------------------------------------------------
def size_ratio() -> float:
    return LARGE.live / SMALL.live


def added_records() -> int:
    return LARGE.live - SMALL.live


def growth(operation: str, name: str) -> float:
    """Large-store counter divided by the small-store one; 1.0 means the operation did not grow."""
    small = SMALL.measured[operation][name]
    return LARGE.measured[operation][name] / small if small else float(LARGE.measured[operation][name])


def per_added_record(operation: str, name: str) -> float:
    """Extra counter units the operation spent for each live record added between the two stores."""
    return (LARGE.measured[operation][name] - SMALL.measured[operation][name]) / added_records()


def per_record(store: Store, operation: str, name: str) -> float:
    return store.measured[operation][name] / store.live


class ScalingCase(unittest.TestCase):
    """Shared reporting for the counter comparisons, so a failure prints both stores' numbers."""

    def report(self, operation: str, name: str) -> str:
        return (f"{operation}.{name}: {SMALL.measured[operation][name]} at {SMALL.live} live records, "
                f"{LARGE.measured[operation][name]} at {LARGE.live}")

    def assert_bounded(self, operation: str):
        """One operation's cost stays put as unrelated results are added to the store."""
        for name in ("executes", "writes"):
            factor = BOUNDED_EXECUTE_FACTOR if name == "executes" else BOUNDED_WRITE_FACTOR
            self.assertLessEqual(growth(operation, name), factor, self.report(operation, name))
        self.assertLessEqual(per_added_record(operation, "rows"), BOUNDED_ROWS_PER_RECORD,
                             self.report(operation, "rows"))
        self.assertLessEqual(per_added_record(operation, "bytes"), BOUNDED_BYTES_PER_RECORD,
                             self.report(operation, "bytes"))


# -- the proxy itself -------------------------------------------------------------------------------
class TestCountingProxy(ScalingCase):
    """The measuring instrument, checked before anything is measured with it.

    If the proxy were not in the read path, every scaling assertion in this module would compare zero
    with zero and pass for the wrong reason. These tests fail if that ever becomes true.
    """

    def test_a_single_read_is_counted_as_one_statement_and_one_row(self):
        """Asking the database for its newest revision costs exactly one statement and one row."""
        db, counter = counted(SMALL.fixture, write=False)
        with db:
            revision = db.max_revision()
        self.assertGreater(revision, 0)
        self.assertEqual(counter.executes, 1)
        self.assertEqual(counter.rows, 1)
        self.assertGreater(counter.bytes, 0)

    def test_the_proxy_counts_the_rows_a_query_really_delivers(self):
        """Listing every live item delivers one counted row per item, not a single opaque result."""
        db, counter = counted(SMALL.fixture, write=False)
        with db:
            heads = db.heads("items")
        self.assertEqual(len(heads), SMALL.items)
        self.assertEqual(counter.executes, 1)
        self.assertEqual(counter.rows, SMALL.items)

    def test_a_read_taken_through_a_cursor_is_counted_as_well(self):
        """The other route sqlite offers, ``conn.cursor()``, is counted just like ``conn.execute``.

        The core reads through ``conn.execute`` today, but ``conn.cursor().execute`` is the more common
        sqlite idiom and a regression is as likely to be written that way. If only one of the two
        routes were counted, a whole-store scan written the other way would satisfy every bound in this
        module without moving a single number.
        """
        db, counter = counted(SMALL.fixture, write=False)
        with db:
            rows = db.conn.cursor().execute("SELECT collection, id FROM record_heads").fetchall()
        self.assertGreaterEqual(len(rows), SMALL.live)
        self.assertEqual(counter.executes, 1)
        self.assertEqual(counter.rows, len(rows))
        self.assertEqual(counter.writes, 0)

    def test_the_proxy_separates_reads_from_writes(self):
        """A read-only statement is not counted as a write, and a stored packet is."""
        self.assertEqual(SMALL.measured["status"]["writes"], 0)
        self.assertEqual(LARGE.measured["status"]["writes"], 0)
        self.assertGreater(SMALL.measured["apply"]["writes"], 0)

    def test_the_connection_watcher_notices_a_second_connection(self):
        """The detector for the proxy's one blind spot can see into that blind spot."""
        real_connect = sqlite3.connect
        with watching_connections() as opened:
            with SMALL.fixture.open(write=False):
                pass
        self.assertEqual(len(opened), 1)
        with watching_connections() as quiet:
            self.assertIsNot(sqlite3.connect, real_connect, "the watcher must install its spy")
        self.assertEqual(quiet, [])
        self.assertIs(sqlite3.connect, real_connect, "the watcher must restore sqlite3.connect")

    def test_no_measured_operation_opened_a_connection_of_its_own(self):
        """Every measured operation read through the proxied connection, so nothing escaped counting."""
        for store in (SMALL, LARGE):
            for operation, counters in store.measured.items():
                with self.subTest(store=store.extra, operation=operation):
                    self.assertEqual(counters["connections"], 0)

    def test_every_measured_operation_moved_the_counters(self):
        """No measured operation recorded zero work, so no comparison below is comparing nothing."""
        for store in (SMALL, LARGE):
            for operation, counters in store.measured.items():
                with self.subTest(store=store.extra, operation=operation):
                    self.assertGreater(counters["executes"], 0)
                    self.assertGreater(counters["rows"], 0)
                    self.assertGreater(counters["bytes"], 0)


# -- the fixtures -----------------------------------------------------------------------------------
class TestGeneratedStores(ScalingCase):
    """The two generated stores, whose difference in size is what makes every ratio mean something."""

    def test_both_stores_are_complete_papers_built_through_the_public_api(self):
        """Growing a store leaves a real audited paper, not a pile of rows with no assessment."""
        for store in (SMALL, LARGE):
            with self.subTest(store=store.extra):
                with store.fixture.open(write=False) as db:
                    status = queries.status(db)
                self.assertTrue(status["process_complete"], f"store {store.extra} is not complete")
                self.assertEqual(status["counts"]["papers"], 1)
                self.assertEqual(status["counts"]["audits"], 1)

    def test_the_large_store_really_is_much_larger(self):
        """The large store holds several times the live records of the small one."""
        self.assertEqual(SMALL.items, SMALL_EXTRA + 2)
        self.assertEqual(LARGE.items, LARGE_EXTRA + 2)
        self.assertGreaterEqual(added_records(), 4 * (LARGE_EXTRA - SMALL_EXTRA))
        self.assertGreaterEqual(size_ratio(), 5.0, f"{SMALL.live} -> {LARGE.live} live records")

    def test_the_extra_results_stay_outside_the_theorem_closure(self):
        """None of the generated results is reachable from the theorem, so they are true noise."""
        with LARGE.fixture.open() as db:
            packet = packets.get_packet(db, targets=[R("items", "itm_thm")], mode="author")
        included = {entry["ref"]["id"] for entry in packet["records"]}
        self.assertIn("itm_thm", included)
        self.assertIn("itm_lem", included)
        noise = sorted(r for r in included if r.startswith(("itm_x", "arg_x", "grp_x", "use_x")))
        self.assertEqual(noise, [], "generated results leaked into the theorem packet")


# -- bounded operations -----------------------------------------------------------------------------
class TestBoundedOperations(ScalingCase):
    """``get`` on one statement and ``apply`` of one small edit must not pay for the whole store."""

    def test_issuing_one_statement_packet_costs_the_same_on_both_stores(self):
        """A packet for one theorem issues the same handful of statements however big the paper is."""
        self.assert_bounded("get")

    def test_the_statement_packet_never_reads_the_store_once_through(self):
        """Even on the large paper the packet walk delivers fewer rows than the store holds records."""
        self.assertLess(per_added_record("get", "rows"), WHOLE_STORE_ROWS_PER_RECORD,
                        self.report("get", "rows"))
        # 32 rows against 431 live records today. One pass over the store would sit at or above the
        # record count by definition, so this fails the moment the closure starts reading everything.
        self.assertLess(LARGE.measured["get"]["rows"], LARGE.live, self.report("get", "rows"))

    def test_the_statement_packet_costs_the_same_on_both_stores(self):
        """The statement closure reads exactly the same rows and bytes in a small and a large paper.

        ``packets._Closure`` reaches a major item's children through the ``record_refs`` index rather
        than by filtering every live item head, so nothing in a statement-scoped packet is a function
        of how many unrelated results the store holds. Asserted as equality rather than as a budget
        because the measured value is identical at 10, 100 and 500 extra results: any movement at all
        means a read started depending on store size, which the looser budgets above would let past
        while it was still small.
        """
        for counter in ("rows", "bytes"):
            self.assertEqual(SMALL.measured["get"][counter], LARGE.measured["get"][counter],
                             self.report("get", counter))
        # The item count is where the old cost showed up first, so it stays named here: this is 0.00
        # rows per added item today, and a reintroduced per-item read would move it to 1.00.
        added_items = LARGE.items - SMALL.items
        rows_per_added_item = (LARGE.measured["get"]["rows"] - SMALL.measured["get"]["rows"]) / added_items
        self.assertEqual(rows_per_added_item, 0.0,
                         f"{rows_per_added_item:.2f} rows per added item; " + self.report("get", "rows"))

    def test_accepting_one_small_edit_costs_the_same_on_both_stores(self):
        """Replacing one item's caption does the same database work in a small and a large paper."""
        self.assert_bounded("apply")

    def test_accepting_one_small_edit_reads_nothing_extra_at_all(self):
        """The acceptance path is bounded by the edit's own packet, so its counters do not move."""
        self.assertEqual(SMALL.measured["apply"], LARGE.measured["apply"])


# -- whole-snapshot operations ----------------------------------------------------------------------
class TestWholeSnapshotOperations(ScalingCase):
    """``status`` and ``build_projection`` read the whole live snapshot; they may grow, but linearly."""

    def test_status_cost_per_live_record_does_not_rise_with_the_store(self):
        """Reporting status on six times the paper costs about six times as much, not thirty-six."""
        self.assertLessEqual(per_record(LARGE, "status", "rows"),
                             SNAPSHOT_PER_RECORD_FACTOR * per_record(SMALL, "status", "rows"),
                             self.report("status", "rows"))
        self.assertLessEqual(per_record(LARGE, "status", "bytes"),
                             SNAPSHOT_PER_RECORD_FACTOR * per_record(SMALL, "status", "bytes"),
                             self.report("status", "bytes"))

    def test_status_stays_under_the_super_linear_bound(self):
        """Status growth stays far below the squared size ratio a quadratic scan would produce."""
        bound = SUPER_LINEAR_FRACTION * size_ratio() ** 2
        self.assertLess(growth("status", "rows"), bound, self.report("status", "rows"))
        self.assertLess(growth("status", "bytes"), bound, self.report("status", "bytes"))

    def test_status_does_not_issue_a_query_per_record(self):
        """The snapshot is read in a fixed set of statements rather than one lookup per record."""
        self.assertLessEqual(growth("status", "executes"), SNAPSHOT_EXECUTE_FACTOR,
                             self.report("status", "executes"))

    def test_render_input_cost_per_live_record_does_not_rise_with_the_store(self):
        """Building the reader's drawing dataset stays linear in the snapshot it draws."""
        self.assertLessEqual(per_record(LARGE, "projection", "rows"),
                             SNAPSHOT_PER_RECORD_FACTOR * per_record(SMALL, "projection", "rows"),
                             self.report("projection", "rows"))
        self.assertLessEqual(per_record(LARGE, "projection", "bytes"),
                             SNAPSHOT_PER_RECORD_FACTOR * per_record(SMALL, "projection", "bytes"),
                             self.report("projection", "bytes"))

    def test_render_input_stays_under_the_super_linear_bound(self):
        """Projection growth stays far below the squared size ratio, so it is not quadratic."""
        bound = SUPER_LINEAR_FRACTION * size_ratio() ** 2
        self.assertLess(growth("projection", "rows"), bound, self.report("projection", "rows"))
        self.assertLess(growth("projection", "bytes"), bound, self.report("projection", "bytes"))

    def test_render_input_does_not_issue_a_query_per_record(self):
        """The projection reads its snapshot in a fixed set of statements, like status does."""
        self.assertLessEqual(growth("projection", "executes"), SNAPSHOT_EXECUTE_FACTOR,
                             self.report("projection", "executes"))


# -- calibration ------------------------------------------------------------------------------------
class TestCalibration(ScalingCase):
    """What a whole-store read looks like here, so the bounded thresholds can be shown to bite.

    A paper-scoped packet is supposed to read the whole paper: ``_Closure.paper_closure`` walks every
    readable collection on purpose. That makes it the honest control for this module. Measured on the
    same two stores it fails every bounded read threshold -- statements, rows and bytes -- which is the
    proof that those thresholds are constraints on the statement-scoped closure rather than numbers no
    implementation could exceed. The write bound is not part of that demonstration: issuing a packet
    stores one packet record whatever the packet contains, so writes do not separate the two shapes.
    """

    def test_the_paper_scoped_closure_grows_with_the_paper(self):
        """The deliberately unbounded operation grows roughly in step with the store, as expected."""
        self.assertGreater(growth("get_paper", "rows"), size_ratio() / 2,
                           self.report("get_paper", "rows"))
        self.assertGreater(growth("get_paper", "executes"), size_ratio() / 2,
                           self.report("get_paper", "executes"))

    def test_a_whole_store_read_would_fail_the_bounded_statement_threshold(self):
        """A closure that queried per record would exceed the constant-factor bound on statements."""
        self.assertGreater(growth("get_paper", "executes"), BOUNDED_EXECUTE_FACTOR,
                           self.report("get_paper", "executes"))

    def test_a_whole_store_read_would_fail_the_bounded_row_and_byte_budgets(self):
        """A closure that read every record would exceed the per-added-record budgets by itself."""
        self.assertGreater(per_added_record("get_paper", "rows"), BOUNDED_ROWS_PER_RECORD,
                           self.report("get_paper", "rows"))
        self.assertGreater(per_added_record("get_paper", "bytes"), BOUNDED_BYTES_PER_RECORD,
                           self.report("get_paper", "bytes"))

    def test_even_the_leanest_possible_whole_store_pass_would_fail_the_row_budget(self):
        """A scan delivering one narrow row per record would break the row budget on its own.

        The paper-scoped control reads two rows per record, so by itself it leaves open whether some
        leaner scan could slip through the budget. It could not: the budget sits below the one row per
        record that any single pass over the store costs by definition, and both bounded operations
        still have room to spare beneath it.
        """
        self.assertLess(BOUNDED_ROWS_PER_RECORD, WHOLE_STORE_ROWS_PER_RECORD)
        for operation in ("get", "apply"):
            with self.subTest(operation=operation):
                self.assertLess(per_added_record(operation, "rows"), BOUNDED_ROWS_PER_RECORD,
                                self.report(operation, "rows"))

    def test_the_bounded_operations_stay_far_below_that_control(self):
        """Statement-scoped work is a small fraction of whole-paper work, and the gap widens."""
        for operation in ("get", "apply"):
            with self.subTest(operation=operation):
                self.assertLess(per_added_record(operation, "rows"),
                                per_added_record("get_paper", "rows") / 2, self.report(operation, "rows"))


if __name__ == "__main__":
    unittest.main()
