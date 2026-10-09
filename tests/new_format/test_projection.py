"""Behaviour tests for ``paper_core.projection`` (implementation-handoff 7).

The projection is the only dataset the Node renderer ever sees, so these tests pin the contract the
renderer depends on: the version stamp, the summary progress block, determinism against one database
revision, the node/connection graph, audit scoping, and the fact that nothing but plain JSON types
reaches the renderer. Failure paths assert the exact error code and that the database file on disk is
byte identical afterwards.
"""
from __future__ import annotations

import hashlib
import json
import math
import shutil
import subprocess
import sys
import unittest

from support import CLI_ENV, GLOBAL_TASKS, R, TempCase, edit

from paper_core import PROJECTION_VERSION, projection, queries, storage
from paper_core.assessment import derive_assessment
from paper_core.canonical import compact_json
from paper_core.errors import InvalidRequest

# Stage progress blocks and counts verified against the real API by the manual validation pass.
PROGRESS_AFTER_PRIMARY = {"process_complete": False, "required_obligations": 13,
                          "completed_current_obligations": 9, "draft_checks": 0, "major_results": 2,
                          "source_unbound_items": 0}
PROGRESS_AFTER_COMPLETE = {"process_complete": True, "required_obligations": 13,
                           "completed_current_obligations": 13, "draft_checks": 0, "major_results": 2,
                           "source_unbound_items": 0}
PROGRESS_OVERVIEW = {"process_complete": False, "required_obligations": 0,
                     "completed_current_obligations": 0, "draft_checks": 0, "major_results": 0,
                     "source_unbound_items": 0}
COUNTS_AFTER_COMPLETE = {"nodes": 2, "connections": 1, "records": 37, "obligations": 16, "details": 3,
                         "locations": 36}
PUBLIC_ASSESSMENT_KEYS = {"state", "label", "explanation", "check_refs", "finding_refs",
                          "missing_obligation_ids", "independent_review"}
# The reader links to a connection by this id, so it is pinned as a literal, not recomputed here.
LEMMA_TO_THEOREM = "conn_d8e9a37bfbbbae84f85710418ceffd034a4f44f9797d4a8e484b1684566f7f9e"
# Run in a fresh interpreter (arbitrary PYTHONHASHSEED) to prove no set iteration order leaks out.
DETERMINISM_PROBE = (
    "import hashlib, json, sys\n"
    "from paper_core import projection, storage\n"
    "db = storage.Database(sys.argv[1], write=False)\n"
    "text = json.dumps(projection.build_projection(db, audit_id='aud_1'),\n"
    "                  ensure_ascii=False, allow_nan=False)\n"
    "db.close()\n"
    "sys.stdout.write(hashlib.sha256(text.encode('utf-8')).hexdigest())\n"
)


def dumped(value) -> str:
    """Exact JSON text, key order preserved, so two builds are compared byte for byte."""
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def non_json_values(value, path="$") -> list:
    """``(path, description)`` for every value the Node renderer could not receive as plain JSON."""
    bad = []
    if value is None or isinstance(value, (bool, int, str)):
        return bad
    if isinstance(value, float):
        if not math.isfinite(value):
            bad.append((path, f"non-finite number {value!r}"))
        return bad
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                bad.append((path, f"non-string object key {key!r}"))
            bad.extend(non_json_values(item, f"{path}.{key}"))
        return bad
    if isinstance(value, list):
        for index, item in enumerate(value):
            bad.extend(non_json_values(item, f"{path}[{index}]"))
        return bad
    bad.append((path, f"{type(value).__name__} {value!r}"))
    return bad


def db_digest(path) -> str:
    """SHA-256 of the database file, so "nothing was written" is checked on disk, not in memory."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sidecars(path) -> list:
    """Names beside the database file: a write would leave a -wal or -journal behind."""
    return sorted(entry.name for entry in path.parent.iterdir())


def second_audit_edit(fixture, audit_id="aud_2", targets=("itm_lem",)):
    """A second registered audit over a narrower target set, built through the public edit shape."""
    return edit("create", "audits", audit_id, {
        "paper_id": fixture.paper_id, "mode": "focused", "targets": [R("items", t) for t in targets],
        "exclusions": [], "protocol_version": "item-audit/1", "independent_required": False,
        "qualification_id": "qua_r1", "report_path": f"reports/{audit_id}.html",
        "global_tasks": [dict(task) for task in GLOBAL_TASKS]})


class ProjectionCase(TempCase):
    """Fixture plumbing shared by the projection tests."""

    def staged(self, stage="complete"):
        fixture = self.fixture()
        getattr(fixture, stage)()
        return fixture

    def projected(self, stage="complete", *, audit_id="aud_1", revision=None):
        fixture = self.staged(stage)
        with fixture.open(write=False) as db:
            return projection.build_projection(db, revision=revision, audit_id=audit_id)

    def subprocess_digest(self, fixture, seed) -> str:
        """SHA-256 of the projection text a fresh interpreter with this hash seed produces."""
        proc = subprocess.run([sys.executable, "-B", "-c", DETERMINISM_PROBE, str(fixture.path)],
                              env=dict(CLI_ENV, PYTHONHASHSEED=seed), capture_output=True,
                              text=True, encoding="utf-8")
        if proc.returncode != 0:
            raise AssertionError(f"probe exit {proc.returncode}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
        return proc.stdout.strip()


class JsonGuardTests(unittest.TestCase):
    """The JSON guard used below must itself be able to fail, or the guard proves nothing."""

    def test_non_json_values_reports_every_value_a_renderer_cannot_receive(self):
        """Sets, tuples, non-finite floats and non-string keys are each reported with their path."""
        payload = {"nodes": [{"id": "n", "refs": ("a", "b")}], "weights": [float("nan")],
                   "index": {1: "x"}, "seen": {"a"}}
        reported = dict(non_json_values(payload))
        self.assertEqual(sorted(reported), ["$.index", "$.nodes[0].refs", "$.seen", "$.weights[0]"])
        self.assertIn("tuple", reported["$.nodes[0].refs"])
        self.assertIn("set", reported["$.seen"])
        self.assertIn("nan", reported["$.weights[0]"])
        self.assertIn("non-string object key 1", reported["$.index"])

    def test_non_json_values_accepts_a_plain_json_document(self):
        """Plain objects, arrays, strings, numbers, booleans and null pass without a report."""
        self.assertEqual(non_json_values({"a": [1, 2.5, "x", True, None, {"b": []}]}), [])


class ProjectionContractTests(ProjectionCase):
    """The envelope the renderer reads: version, revision, audit and report counts."""

    def test_projection_carries_the_projection_version_and_the_projected_revision(self):
        """project() stamps PROJECTION_VERSION and the exact snapshot revision it read."""
        fixture = self.staged("complete")
        with fixture.open(write=False) as db:
            head = db.max_revision()
            proj, _ = projection.project(db, audit_id="aud_1")
        self.assertEqual(proj["projection_version"], PROJECTION_VERSION)
        self.assertEqual(PROJECTION_VERSION, 2)
        self.assertEqual(proj["snapshot_revision"], head)
        self.assertEqual(head, 16)
        self.assertEqual(proj["audit_id"], "aud_1")

    def test_project_returns_a_report_whose_counts_describe_the_projection(self):
        """The second element of project() counts exactly the collections carried in the projection."""
        fixture = self.staged("complete")
        with fixture.open(write=False) as db:
            proj, report = projection.project(db, audit_id="aud_1")
        self.assertEqual(sorted(report), ["counts", "problems"])
        self.assertEqual(report["problems"], [])
        self.assertEqual(report["counts"], {"nodes": len(proj["nodes"]), "connections": len(proj["connections"]),
                                            "records": len(proj["records"]), "obligations": len(proj["obligations"]),
                                            "details": len(proj["details"]),
                                            "locations": len(proj["record_locations"])})
        self.assertEqual(report["counts"], COUNTS_AFTER_COMPLETE)

    def test_build_projection_is_the_first_element_of_project(self):
        """build_projection() is project() without the report, not a differently built dataset."""
        fixture = self.staged("complete")
        with fixture.open(write=False) as db:
            proj, _ = projection.project(db, audit_id="aud_1")
            built = projection.build_projection(db, audit_id="aud_1")
        self.assertEqual(dumped(built), dumped(proj))

    def test_projection_has_exactly_the_documented_top_level_keys(self):
        """The renderer contract is a fixed key set; progress is not one of them."""
        proj = self.projected("complete")
        self.assertEqual(sorted(proj), ["audit_id", "connections", "details", "layout", "nodes", "obligations",
                                        "projection_version", "record_locations", "records", "snapshot_revision",
                                        "summary", "worklist"])
        self.assertNotIn("progress", proj)

    def test_summary_carries_the_progress_block_of_the_completed_process(self):
        """Progress lives at summary.progress and reports the completed audit exactly."""
        proj = self.projected("complete")
        self.assertEqual(proj["summary"]["progress"], PROGRESS_AFTER_COMPLETE)
        self.assertEqual(sorted(proj["summary"]),
                         ["factual", "findings", "limitations", "progress", "published_revision", "scope", "source_limits"])

    def test_summary_scope_mirrors_the_audit_targets_without_pinning_versions(self):
        """summary.scope repeats the audit mode and targets as unpinned refs the reader can follow."""
        proj = self.projected("complete")
        self.assertEqual(proj["summary"]["scope"], {
            "mode": "focused",
            "target_refs": [{"collection": "items", "id": "itm_lem"}, {"collection": "items", "id": "itm_thm"}],
            "exclusions": []})
        self.assertEqual(proj["summary"]["findings"], {"open": 0, "resolved": 0, "superseded": 0, "refs": []})
        self.assertEqual(proj["summary"]["source_limits"], [])
        self.assertIsNone(proj["summary"]["published_revision"])

    def test_projection_contains_only_plain_json_values(self):
        """A Node renderer receives the projection as JSON, so no tuples, sets, dates or NaN may survive."""
        fixture = self.staged("complete")
        with fixture.open(write=False) as db:
            proj, _ = projection.project(db, audit_id="aud_1")
            overview, _ = projection.project(db)
        for label, payload in (("audit", proj), ("overview", overview)):
            with self.subTest(projection=label):
                self.assertEqual(non_json_values(payload), [])
                # Object equality, not text equality: a tuple would survive a dumps/loads text comparison.
                self.assertEqual(json.loads(dumped(payload)), payload)


class ProjectionDeterminismTests(ProjectionCase):
    """The projection is a pure function of one database revision."""

    def test_projecting_the_same_revision_twice_yields_identical_content(self):
        """Two projections of one revision are byte identical, including key and list order."""
        fixture = self.staged("complete")
        with fixture.open(write=False) as db:
            first = projection.build_projection(db, audit_id="aud_1")
        with fixture.open(write=False) as db:
            second = projection.build_projection(db, audit_id="aud_1")
        self.assertEqual(dumped(first), dumped(second))

    def test_projecting_an_older_revision_reproduces_that_older_state(self):
        """Later edits do not leak backwards: the pre-reconciliation revision projects as it did then."""
        fixture = self.staged("primary")
        with fixture.open(write=False) as db:
            before_revision = db.max_revision()
            before = projection.build_projection(db, audit_id="aud_1")
        fixture.complete()
        with fixture.open(write=False) as db:
            self.assertGreater(db.max_revision(), before_revision)
            replay = projection.build_projection(db, revision=before_revision, audit_id="aud_1")
            head = projection.build_projection(db, audit_id="aud_1")
        self.assertEqual(dumped(replay), dumped(before))
        self.assertEqual(replay["snapshot_revision"], before_revision)
        self.assertNotEqual(dumped(head), dumped(replay))
        self.assertEqual(before["summary"]["progress"], PROGRESS_AFTER_PRIMARY)
        self.assertEqual(head["summary"]["progress"], PROGRESS_AFTER_COMPLETE)

    def test_default_revision_is_the_database_head(self):
        """Omitting revision projects the head, not some cached earlier snapshot."""
        fixture = self.staged("complete")
        with fixture.open(write=False) as db:
            head = db.max_revision()
            default = projection.build_projection(db, audit_id="aud_1")
            explicit = projection.build_projection(db, revision=head, audit_id="aud_1")
        self.assertEqual(default["snapshot_revision"], head)
        self.assertEqual(dumped(default), dumped(explicit))

    def test_projection_is_identical_under_a_different_interpreter_hash_seed(self):
        """No set iteration order reaches the output: a fresh interpreter agrees byte for byte."""
        fixture = self.staged("complete")
        with fixture.open(write=False) as db:
            inline = dumped(projection.build_projection(db, audit_id="aud_1"))
        expected = hashlib.sha256(inline.encode("utf-8")).hexdigest()
        for seed in ("0", "997"):
            with self.subTest(hash_seed=seed):
                self.assertEqual(self.subprocess_digest(fixture, seed), expected)

    def test_projection_does_not_depend_on_the_database_file_path(self):
        """The dataset describes the records, never where the file happens to live."""
        fixture = self.staged("complete")
        with fixture.open(write=False) as db:
            original = projection.build_projection(db, audit_id="aud_1")
        moved = self.path("moved", "renamed audit.db")
        shutil.copy2(fixture.path, moved)
        with storage.Database(moved, write=False) as db:
            relocated = projection.build_projection(db, audit_id="aud_1")
        self.assertEqual(dumped(relocated), dumped(original))
        self.assertNotIn(str(moved.parent), dumped(relocated))


class ProjectionGraphTests(ProjectionCase):
    """Nodes, connections and the record index built from the two-item fixture."""

    def test_nodes_are_the_two_major_items_with_labels_and_pinned_refs(self):
        """Each node names its item, kind, label, caption, pinned version and detail key."""
        proj = self.projected("complete")
        self.assertEqual([node["id"] for node in proj["nodes"]], ["itm_lem", "itm_thm"])
        lemma, theorem = proj["nodes"]
        self.assertEqual(lemma["kind"], "lemma")
        self.assertEqual(lemma["label"], "Lemma 1")
        self.assertEqual(lemma["caption"], "Lemma 1")
        self.assertEqual(lemma["item_ref"], {"collection": "items", "id": "itm_lem", "version": 1})
        self.assertEqual(lemma["detail_key"], "item:itm_lem")
        self.assertEqual(theorem["kind"], "theorem")
        self.assertEqual(theorem["label"], "Theorem 1")
        self.assertEqual(theorem["item_ref"], {"collection": "items", "id": "itm_thm", "version": 1})
        self.assertEqual(theorem["detail_key"], "item:itm_thm")
        self.assertEqual(sorted(lemma), ["assessment", "caption", "detail_key", "id", "item_ref", "kind", "label"])

    def test_completed_audit_assesses_both_nodes_green_with_independent_review_complete(self):
        """A reconciled audit leaves every node supported with no missing obligation."""
        proj = self.projected("complete")
        for node in proj["nodes"]:
            with self.subTest(node=node["id"]):
                self.assertEqual(node["assessment"]["state"], "green")
                self.assertEqual(node["assessment"]["label"], "supported")
                self.assertEqual(node["assessment"]["independent_review"], "complete")
                self.assertEqual(node["assessment"]["missing_obligation_ids"], [])
                self.assertEqual(node["assessment"]["finding_refs"], [])
                self.assertEqual(set(node["assessment"]), PUBLIC_ASSESSMENT_KEYS | {"availability", "local_state", "local_label"})

    def test_the_single_dependency_use_becomes_one_edge_naming_both_endpoints(self):
        """One recorded use from the lemma to the theorem is exactly one connection lemma -> theorem."""
        proj = self.projected("complete")
        self.assertEqual(len(proj["connections"]), 1)
        connection = proj["connections"][0]
        self.assertEqual(connection["from"], "itm_lem")
        self.assertEqual(connection["to"], "itm_thm")
        self.assertEqual(connection["id"], LEMMA_TO_THEOREM)
        self.assertEqual(connection["primary_use_ids"], ["use_lem_thm"])
        self.assertEqual(connection["detail_key"], "conn:" + LEMMA_TO_THEOREM)
        self.assertEqual(connection["assessment"]["state"], "green")
        self.assertEqual(connection["support_refs"], [{"collection": "checks", "id": "chk_app"}])
        self.assertEqual(connection["context_refs"], [{"collection": "items", "id": "itm_lem"},
                                                      {"collection": "anchors", "id": "anc_thm_proof"},
                                                      {"collection": "arguments", "id": "arg_thm"},
                                                      {"collection": "groups", "id": "grp_thm"}])

    def test_edge_groups_name_the_argument_and_group_that_consume_the_use(self):
        """The connection is partitioned by the argument/group the use enters, not left anonymous."""
        proj = self.projected("complete")
        connection = proj["connections"][0]
        groups = connection["groups"]
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["argument_id"], "arg_thm")
        self.assertEqual(groups[0]["group_id"], "grp_thm")
        self.assertEqual(groups[0]["use_ids"], ["use_lem_thm"])
        self.assertEqual(groups[0]["assessment"]["state"], "green")
        self.assertEqual(groups[0]["obligation_ids"], connection["obligation_ids"])
        self.assertEqual(len(connection["obligation_ids"]), 1)
        index = {obligation["id"]: obligation for obligation in proj["obligations"]}
        carried = index[connection["obligation_ids"][0]]
        self.assertEqual((carried["target"], carried["kind"], carried["role"]),
                         ({"collection": "uses", "id": "use_lem_thm"}, "application", "primary"))

    def test_two_arguments_and_two_groups_reach_the_reader_as_located_records(self):
        """Every proof record of the fixture is carried once and placed in a named detail section."""
        proj = self.projected("complete")
        carried = {(r["ref"]["collection"], r["ref"]["id"]) for r in proj["records"]}
        for expected in (("items", "itm_lem"), ("items", "itm_thm"), ("arguments", "arg_lem"),
                         ("arguments", "arg_thm"), ("groups", "grp_lem"), ("groups", "grp_thm"),
                         ("uses", "use_lem_thm"), ("scopes", "scp_plain"), ("audits", "aud_1")):
            self.assertIn(expected, carried)
        located = {(loc["ref"]["collection"], loc["ref"]["id"]): loc for loc in proj["record_locations"]}
        self.assertEqual(len(located), len(proj["record_locations"]))
        for collection, id, detail_key, section_key in (
                ("items", "itm_lem", "item:itm_lem", "statement"),
                ("items", "itm_thm", "item:itm_thm", "statement"),
                ("arguments", "arg_lem", "item:itm_lem", "composition"),
                ("groups", "grp_lem", "item:itm_lem", "composition"),
                ("arguments", "arg_thm", "item:itm_thm", "composition"),
                ("groups", "grp_thm", "item:itm_thm", "composition"),
                ("uses", "use_lem_thm", "item:itm_thm", "applications"),
                ("scopes", "scp_plain", "item:itm_lem", "premises")):
            with self.subTest(record=f"{collection}:{id}"):
                self.assertEqual(located[(collection, id)]["detail_key"], detail_key)
                self.assertEqual(located[(collection, id)]["section_key"], section_key)
                self.assertIn(detail_key, proj["details"])

    def test_every_proof_record_carried_has_exactly_one_reader_location(self):
        """A proof record with nowhere to be shown is a projection problem; only the audit sits outside."""
        fixture = self.staged("complete")
        with fixture.open(write=False) as db:
            proj, report = projection.project(db, audit_id="aud_1")
        carried = {(r["ref"]["collection"], r["ref"]["id"], r["ref"]["version"]) for r in proj["records"]}
        located = [(loc["ref"]["collection"], loc["ref"]["id"], loc["ref"]["version"])
                   for loc in proj["record_locations"]]
        self.assertEqual(len(located), len(set(located)))
        self.assertTrue(set(located) <= carried)
        self.assertEqual(carried - set(located), {("audits", "aud_1", 1)})
        proof_records = sorted(key for key in carried if key[0] in projection.PROOF_RECORD_COLLECTIONS)
        self.assertEqual(proof_records, sorted(key for key in located
                                               if key[0] in projection.PROOF_RECORD_COLLECTIONS))
        self.assertEqual(len(proof_records), 15)
        self.assertEqual(report["problems"], [])

    def test_every_record_body_is_carried_once_under_its_pinned_version(self):
        """The record table is keyed by (collection, id, version) so the renderer never guesses a body."""
        proj = self.projected("complete")
        keys = [(r["ref"]["collection"], r["ref"]["id"], r["ref"]["version"]) for r in proj["records"]]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(keys, sorted(keys))
        for record in proj["records"]:
            with self.subTest(record=record["ref"]["id"]):
                self.assertEqual(sorted(record["ref"]), ["collection", "id", "version"])
        bodies = {(r["ref"]["collection"], r["ref"]["id"]): r["body"] for r in proj["records"]}
        self.assertEqual(bodies[("uses", "use_lem_thm")]["type"], "dependency")
        self.assertEqual(bodies[("uses", "use_lem_thm")]["from"], {"collection": "items", "id": "itm_lem"})
        self.assertEqual(bodies[("uses", "use_lem_thm")]["to"], {"collection": "items", "id": "itm_thm"})
        self.assertEqual(bodies[("items", "itm_lem")]["label"], "Lemma 1")
        self.assertEqual(bodies[("arguments", "arg_thm")]["final_group_id"], "grp_thm")

    def test_every_carried_body_is_the_stored_body_at_that_version(self):
        """The renderer reads the real stored record, not a summary the projection invented."""
        fixture = self.staged("complete")
        with fixture.open(write=False) as db:
            proj = projection.build_projection(db, audit_id="aud_1")
            for record in proj["records"]:
                ref = record["ref"]
                with self.subTest(record=f"{ref['collection']}:{ref['id']}:{ref['version']}"):
                    stored = db.version(ref["collection"], ref["id"], ref["version"])
                    self.assertIsNotNone(stored)
                    self.assertEqual(record["body"], stored.body)
                    self.assertIsNotNone(stored.body)

    def test_details_exist_for_every_node_and_connection_and_follow_the_section_order(self):
        """Each detail key referenced by a node or connection resolves to ordered, titled sections."""
        proj = self.projected("complete")
        keys = [node["detail_key"] for node in proj["nodes"]] + \
               [connection["detail_key"] for connection in proj["connections"]]
        self.assertEqual(sorted(proj["details"]), sorted(keys))
        for key, detail in proj["details"].items():
            with self.subTest(detail=key):
                self.assertEqual(sorted(detail), (["reader"] if key.startswith("item:") else []) +
                                 ["record_refs", "sections"])
                order = [projection.SECTION_ORDER.index(section["kind"]) for section in detail["sections"]]
                self.assertEqual(order, sorted(order))
                for section in detail["sections"]:
                    self.assertEqual(section["key"], section["kind"])
                    self.assertEqual(section["title"], projection.SECTION_TITLES[section["kind"]])
                    self.assertTrue(section["record_refs"] or section["obligation_ids"] or section["note"])
        lemma = proj["details"]["item:itm_lem"]
        self.assertEqual([section["kind"] for section in lemma["sections"]],
                         ["statement", "premises", "composition", "coverage", "sources", "review"])
        statement = lemma["sections"][0]
        self.assertEqual(statement["record_refs"], [{"collection": "items", "id": "itm_lem", "version": 1},
                         {"collection": "target_specs", "id": "tgt_lem", "version": 1},
                         {"collection": "observations", "id": "obs_exact_lem", "version": 1}])
        self.assertEqual(statement["title"], "Statement")
        self.assertEqual(statement["note"], "Exact audited targets identify the mathematical form and scope examined.")

    def test_detail_record_refs_are_the_union_of_its_section_refs_in_section_order(self):
        """The flat record_refs list a renderer iterates matches the sections, deduplicated and ordered."""
        proj = self.projected("complete")
        for key, detail in proj["details"].items():
            with self.subTest(detail=key):
                expected, seen = [], set()
                for section in detail["sections"]:
                    for ref in section["record_refs"]:
                        pin = (ref["collection"], ref["id"], ref["version"])
                        if pin not in seen:
                            seen.add(pin)
                            expected.append(ref)
                self.assertEqual(detail["record_refs"], expected)
                self.assertTrue(expected)

    def test_acyclic_fixture_lays_out_as_a_dag(self):
        """With no cycle among majors the reader gets the diagram, not the index fallback."""
        proj = self.projected("complete")
        self.assertEqual(proj["layout"], {"mode": "dag", "reasons": []})

    def test_a_cycle_between_majors_remains_a_diagram_and_keeps_every_use(self):
        """A back edge selects cycle routing and preserves every connection identity and direction."""
        fixture = self.staged("primary")
        with fixture.open() as db:
            fixture.apply(db, [edit("create", "uses", "use_thm_lem", {
                "from": R("items", "itm_thm"), "to": R("items", "itm_lem"), "type": "dependency",
                "group_id": "grp_lem", "reason": "back edge", "needed_form": None, "substitutions": [],
                "evidence_refs": ["anc_lem_proof"], "regime": None, "uncertainty": None})],
                *fixture.ITEMS, mode="primary")
        with fixture.open(write=False) as db:
            proj = projection.build_projection(db, audit_id="aud_1")
        self.assertEqual(proj["layout"]["mode"], "cyclic")
        self.assertEqual(len(proj["layout"]["reasons"]), 2)
        self.assertIn("itm_lem to itm_thm to itm_lem", proj["layout"]["reasons"][0])
        self.assertIn("every recorded use is kept", proj["layout"]["reasons"][1])
        self.assertIn("assessment is unchanged", proj["layout"]["reasons"][1])
        self.assertEqual([(c["from"], c["to"]) for c in proj["connections"]],
                         [("itm_lem", "itm_thm"), ("itm_thm", "itm_lem")])
        self.assertEqual([c["id"] for c in proj["connections"]],
                         [LEMMA_TO_THEOREM, projection.connection_id("itm_thm", "itm_lem")])
        self.assertEqual([c["primary_use_ids"] for c in proj["connections"]],
                         [["use_lem_thm"], ["use_thm_lem"]])


class ProjectionScopeTests(ProjectionCase):
    """audit_id= selects which audit the projection speaks for."""

    def test_audit_id_scopes_records_and_obligations_to_that_audit(self):
        """A second audit sees its own obligations and none of the first audit's checks or audit record."""
        fixture = self.staged("complete")
        with fixture.open() as db:
            fixture.apply(db, [second_audit_edit(fixture)], *fixture.ITEMS, mode="primary")
        with fixture.open(write=False) as db:
            first = projection.build_projection(db, audit_id="aud_1")
            second = projection.build_projection(db, audit_id="aud_2")
        self.assertEqual(first["audit_id"], "aud_1")
        self.assertEqual(second["audit_id"], "aud_2")
        self.assertEqual([r["ref"]["id"] for r in first["records"] if r["ref"]["collection"] == "audits"],
                         ["aud_1"])
        self.assertEqual([r["ref"]["id"] for r in second["records"] if r["ref"]["collection"] == "audits"],
                         ["aud_2"])
        self.assertEqual([r["ref"]["id"] for r in second["records"] if r["ref"]["collection"] == "checks"], [])
        first_checks = sorted(r["ref"]["id"] for r in first["records"] if r["ref"]["collection"] == "checks")
        self.assertEqual(len(first_checks), 7)
        self.assertTrue(set(first_checks) >= {"chk_app", "chk_comp_lem", "chk_comp_thm", "chk_der_lem",
                                              "chk_der_thm"})
        self.assertEqual({o["target"]["id"] for o in second["obligations"]},
                         {"aud_2", "itm_lem", "arg_lem", "grp_lem", "tgt_lem"})
        self.assertEqual(second["summary"]["scope"]["target_refs"], [{"collection": "items", "id": "itm_lem"}])
        self.assertEqual(second["summary"]["progress"],
                         {"process_complete": False, "required_obligations": 4,
                          "completed_current_obligations": 2, "draft_checks": 0, "major_results": 1,
                          "source_unbound_items": 0})

    def test_a_neighbour_outside_the_audit_scope_is_drawn_as_outside_scope(self):
        """An unaudited neighbour keeps its edge but carries the gray outside-scope assessment."""
        fixture = self.staged("complete")
        with fixture.open() as db:
            fixture.apply(db, [second_audit_edit(fixture)], *fixture.ITEMS, mode="primary")
        with fixture.open(write=False) as db:
            proj = projection.build_projection(db, audit_id="aud_2")
        nodes = {node["id"]: node for node in proj["nodes"]}
        self.assertEqual(sorted(nodes), ["itm_lem", "itm_thm"])
        neighbour = nodes["itm_thm"]["assessment"]
        self.assertEqual(neighbour["state"], "gray")
        self.assertEqual(neighbour["label"], "outside scope")
        self.assertEqual(neighbour["explanation"], projection.OUTSIDE_SCOPE["explanation"])
        self.assertEqual(neighbour["check_refs"], [])
        self.assertEqual(neighbour["missing_obligation_ids"], [])
        self.assertEqual(neighbour["independent_review"], "not_required")
        self.assertEqual(nodes["itm_lem"]["assessment"]["state"], "amber")
        self.assertEqual([(c["from"], c["to"]) for c in proj["connections"]], [("itm_lem", "itm_thm")])
        note = [s["note"] for s in proj["details"]["item:itm_thm"]["sections"] if s["kind"] == "statement"]
        self.assertEqual(note, ["Outside the audit scope; shown as a neighbor of an audited result."])
        in_scope = [s["note"] for s in proj["details"]["item:itm_lem"]["sections"] if s["kind"] == "statement"]
        self.assertEqual(in_scope, ["Exact audited targets identify the mathematical form and scope examined."])

    def test_overview_projection_has_no_audit_and_derives_no_obligations(self):
        """Without audit_id the projection is the structural overview: every major item, no assessment."""
        fixture = self.staged("complete")
        with fixture.open(write=False) as db:
            proj = projection.build_projection(db)
        self.assertIsNone(proj["audit_id"])
        self.assertEqual(proj["obligations"], [])
        self.assertEqual(proj["summary"]["scope"], {"mode": "overview", "target_refs": [], "exclusions": []})
        self.assertEqual(proj["summary"]["progress"], PROGRESS_OVERVIEW)
        self.assertEqual([node["id"] for node in proj["nodes"]], ["itm_lem", "itm_thm"])
        for node in proj["nodes"]:
            with self.subTest(node=node["id"]):
                self.assertEqual(node["assessment"]["state"], "gray")
                self.assertEqual(node["assessment"]["label"], "unassessed")
                self.assertEqual(node["assessment"]["explanation"], "no work is represented")
                self.assertEqual(node["assessment"]["check_refs"], [])
                self.assertEqual(node["assessment"]["missing_obligation_ids"], [])
        self.assertEqual([(c["from"], c["to"]) for c in proj["connections"]], [("itm_lem", "itm_thm")])
        self.assertEqual(proj["connections"][0]["id"], LEMMA_TO_THEOREM)
        self.assertEqual(proj["connections"][0]["assessment"]["state"], "gray")
        self.assertEqual(proj["connections"][0]["obligation_ids"], [])
        self.assertEqual(proj["connections"][0]["groups"][0]["obligation_ids"], [])

    def test_overview_still_carries_recorded_checks_as_reader_material(self):
        """No audit means no obligations, but every recorded check is still shown, unattributed to a scope."""
        fixture = self.staged("complete")
        with fixture.open(write=False) as db:
            proj = projection.build_projection(db)
            audited = projection.build_projection(db, audit_id="aud_1")
        overview_checks = sorted(r["ref"]["id"] for r in proj["records"] if r["ref"]["collection"] == "checks")
        audited_checks = sorted(r["ref"]["id"] for r in audited["records"] if r["ref"]["collection"] == "checks")
        self.assertEqual(overview_checks, audited_checks)
        self.assertEqual(len(overview_checks), 7)
        self.assertEqual([r["ref"]["id"] for r in proj["records"] if r["ref"]["collection"] == "audits"], [])


class ProjectionIncompleteProcessTests(ProjectionCase):
    """An audit with work still owed reports what is missing rather than claiming completion."""

    def test_unmet_obligations_leave_the_process_incomplete(self):
        """Before reconciliation the progress block reports 7 of 11 required obligations done."""
        proj = self.projected("primary")
        self.assertEqual(proj["summary"]["progress"], PROGRESS_AFTER_PRIMARY)
        self.assertIs(proj["summary"]["progress"]["process_complete"], False)

    def test_missing_obligations_named_on_the_nodes_are_exactly_the_unsatisfied_required_ones(self):
        """Every required obligation not yet satisfied is named on some node, and nothing else is."""
        fixture = self.staged("primary")
        with fixture.open(write=False) as db:
            proj = projection.build_projection(db, audit_id="aud_1")
            derived = derive_assessment(db, audit_id="aud_1")
        named = sorted({oid for node in proj["nodes"] for oid in node["assessment"]["missing_obligation_ids"]})
        unsatisfied = sorted(o["id"] for o in derived["obligations"] if o["required"] and not o["satisfied"])
        self.assertEqual(named, unsatisfied)
        self.assertEqual(len(named), 4)

    def test_each_missing_obligation_resolves_to_the_work_still_owed(self):
        """The named obligations identify the independent composition and coordinator reconciliation work."""
        proj = self.projected("primary")
        index = {obligation["id"]: obligation for obligation in proj["obligations"]}
        owed = set()
        for node in proj["nodes"]:
            for oid in node["assessment"]["missing_obligation_ids"]:
                self.assertIn(oid, index)
                obligation = index[oid]
                owed.add((obligation["target"]["collection"], obligation["target"]["id"],
                          obligation["kind"], obligation["role"]))
                self.assertEqual(obligation["assessment"]["state"], "gray")
                self.assertEqual(obligation["check_refs"], [])
        self.assertEqual(owed, {
            ("arguments", "arg_lem", "composition", "independent"),
            ("arguments", "arg_thm", "composition", "independent"),
            ("items", "itm_lem", "reconciliation", "coordinator"),
            ("items", "itm_thm", "reconciliation", "coordinator")})

    def test_primary_work_colours_a_node_green_while_independent_review_is_still_pending(self):
        """Colour follows primary work; the separate indicator is what keeps the process incomplete."""
        proj = self.projected("primary")
        for node in proj["nodes"]:
            with self.subTest(node=node["id"]):
                self.assertEqual(node["assessment"]["state"], "green")
                self.assertEqual(node["assessment"]["label"], "supported")
                self.assertEqual(node["assessment"]["independent_review"], "pending")
                self.assertEqual(len(node["assessment"]["missing_obligation_ids"]), 2)
        self.assertEqual(proj["connections"][0]["assessment"]["state"], "green")
        self.assertEqual(proj["connections"][0]["assessment"]["independent_review"], "not_required")
        self.assertIs(proj["summary"]["progress"]["process_complete"], False)

    def test_node_assessments_are_the_derived_assessments_passed_through_public_assessment(self):
        """The projection re-presents derive_assessment's verdicts; it never judges a node itself."""
        fixture = self.staged("complete")
        with fixture.open(write=False) as db:
            proj = projection.build_projection(db, audit_id="aud_1")
            derived = derive_assessment(db, audit_id="aud_1")
        for node in proj["nodes"]:
            with self.subTest(node=node["id"]):
                raw = derived["assessments"]["items:" + node["id"]]
                self.assertEqual(node["assessment"], projection.public_assessment(raw))
                self.assertEqual(node["assessment"]["state"], raw["state"])
                self.assertEqual(node["assessment"]["label"], raw["label"])
                self.assertEqual(node["assessment"]["independent_review"], raw["independent_review"])
                self.assertEqual(node["assessment"]["missing_obligation_ids"], raw["missing_obligation_ids"])
                # assessment.reduce already emits exactly the public field set, so a new internal field
                # appearing here is a signal that public_assessment must learn to strip it.
                self.assertEqual(set(raw), PUBLIC_ASSESSMENT_KEYS | {"availability", "local_state", "local_label"})
                self.assertEqual(node["assessment"]["finding_refs"], [r["id"] for r in raw["finding_refs"]])

    def test_satisfied_obligations_carry_the_checks_that_discharged_them(self):
        """A discharged obligation points at the pinned check, so the reader can follow the evidence."""
        proj = self.projected("primary")
        by_target = {(o["target"]["collection"], o["target"]["id"], o["kind"]): o for o in proj["obligations"]}
        application = by_target[("uses", "use_lem_thm", "application")]
        self.assertEqual(application["role"], "primary")
        self.assertEqual(application["assessment"]["state"], "green")
        self.assertEqual(application["check_refs"], [{"collection": "checks", "id": "chk_app", "version": 1}])
        self.assertEqual(application["assessment"]["missing_obligation_ids"], [])
        self.assertEqual(sorted(application), ["assessment", "check_refs", "id", "kind", "role", "target"])


class PublicAssessmentTests(unittest.TestCase):
    """public_assessment() is the only gate between the derived assessment and the report."""

    RAW = {"state": "amber", "label": "partial", "explanation": "one required check is still draft",
           "check_refs": [{"collection": "checks", "id": "chk_1", "version": 2}],
           "finding_refs": [{"collection": "findings", "id": "fnd_1", "version": 1},
                            {"collection": "findings", "id": "fnd_1", "version": 3},
                            {"collection": "findings", "id": "fnd_2", "version": 1}],
           "missing_obligation_ids": ["obl_b", "obl_a"],
           "independent_review": "pending",
           "constituents": [{"internal": True}],
           "support_stack": {"items:itm_lem"}}

    def test_public_assessment_keeps_the_presentation_fields(self):
        """State, label, explanation and the independent indicator reach the report unchanged."""
        public = projection.public_assessment(dict(self.RAW))
        self.assertEqual(public["state"], "amber")
        self.assertEqual(public["label"], "partial")
        self.assertEqual(public["explanation"], "one required check is still draft")
        self.assertEqual(public["independent_review"], "pending")
        self.assertEqual(public["missing_obligation_ids"], ["obl_b", "obl_a"])
        self.assertEqual(public["check_refs"], [{"collection": "checks", "id": "chk_1", "version": 2}])

    def test_public_assessment_drops_every_internal_field(self):
        """Internal derivation state such as constituents never reaches the renderer."""
        public = projection.public_assessment(dict(self.RAW))
        self.assertEqual(set(public), PUBLIC_ASSESSMENT_KEYS)
        self.assertNotIn("constituents", public)
        self.assertNotIn("support_stack", public)
        self.assertEqual(non_json_values(public), [])

    def test_public_assessment_reduces_finding_refs_to_deduplicated_ids(self):
        """Findings are exposed as ids only; two versions of one finding collapse to one id."""
        public = projection.public_assessment(dict(self.RAW))
        self.assertEqual(public["finding_refs"], ["fnd_1", "fnd_2"])

    def test_public_assessment_leaves_the_assessment_it_was_given_untouched(self):
        """The gate reads the derived assessment; it does not pop or rewrite fields in place."""
        raw = dict(self.RAW)
        projection.public_assessment(raw)
        self.assertEqual(set(raw), PUBLIC_ASSESSMENT_KEYS | {"constituents", "support_stack"})
        self.assertEqual(raw["finding_refs"], self.RAW["finding_refs"])
        self.assertEqual(raw["constituents"], [{"internal": True}])

    def test_public_assessment_copies_so_the_report_cannot_mutate_the_derivation(self):
        """Mutating the public assessment leaves the derived assessment it was built from intact."""
        raw = json.loads(json.dumps({k: v for k, v in self.RAW.items() if k != "support_stack"}))
        public = projection.public_assessment(raw)
        public["check_refs"][0]["version"] = 99
        public["missing_obligation_ids"].append("obl_z")
        self.assertEqual(raw["check_refs"], [{"collection": "checks", "id": "chk_1", "version": 2}])
        self.assertEqual(raw["missing_obligation_ids"], ["obl_b", "obl_a"])


class ConnectionIdTests(unittest.TestCase):
    """connection_id() is the stable identity of an ordered pair of major results."""

    def test_connection_id_is_the_sha256_of_the_compact_ordered_pair(self):
        """The id is conn_ plus the SHA-256 of the compact JSON array [from, to]."""
        payload = compact_json(["itm_lem", "itm_thm"]).encode("utf-8")
        self.assertEqual(projection.connection_id("itm_lem", "itm_thm"),
                         "conn_" + hashlib.sha256(payload).hexdigest())

    def test_connection_id_of_the_fixture_pair_is_the_published_literal(self):
        """Reader links are permanent: this pair keeps the id recorded by the validation pass."""
        self.assertEqual(projection.connection_id("itm_lem", "itm_thm"), LEMMA_TO_THEOREM)
        self.assertEqual(projection.connection_id("itm_lem", "itm_thm"),
                         projection.connection_id("itm_lem", "itm_thm"))
        self.assertEqual(len(LEMMA_TO_THEOREM), len("conn_") + 64)

    def test_connection_id_is_distinct_for_distinct_connections(self):
        """Direction and endpoints both change the id; no two fixture pairs collide."""
        pairs = [("itm_lem", "itm_thm"), ("itm_thm", "itm_lem"), ("itm_lem", "itm_cor"),
                 ("itm_le", "mitm_thm"), ("itm_lem", "itm_lem")]
        ids = [projection.connection_id(a, b) for a, b in pairs]
        self.assertEqual(len(set(ids)), len(pairs))
        self.assertNotEqual(projection.connection_id("itm_lem", "itm_thm"),
                            projection.connection_id("itm_thm", "itm_lem"))


class ProjectionFailureTests(ProjectionCase):
    """Every rejected projection request names its code and leaves the database file untouched."""

    def test_unknown_audit_is_rejected_with_audit_unknown(self):
        """Projecting an audit that is not live raises InvalidRequest AUDIT_UNKNOWN and writes nothing."""
        fixture = self.staged("complete")
        before, files = db_digest(fixture.path), sidecars(fixture.path)
        with fixture.open(write=False) as db:
            head = db.max_revision()
            with self.assertRaises(InvalidRequest) as caught:
                projection.build_projection(db, audit_id="aud_missing")
            self.assertEqual(caught.exception.code, "AUDIT_UNKNOWN")
            self.assertIn("aud_missing", str(caught.exception))
            self.assertEqual(db.max_revision(), head)
        self.assertEqual(db_digest(fixture.path), before)
        self.assertEqual(sidecars(fixture.path), files)

    def test_audit_not_yet_registered_at_an_older_revision_is_rejected(self):
        """An audit registered later is not live at an earlier revision, so that pairing is refused."""
        fixture = self.staged("structure")
        with fixture.open(write=False) as db:
            before_audit = db.max_revision()
        fixture.complete()
        digest = db_digest(fixture.path)
        with fixture.open(write=False) as db:
            head = db.max_revision()
            with self.assertRaises(InvalidRequest) as caught:
                projection.build_projection(db, revision=before_audit, audit_id="aud_1")
            self.assertEqual(caught.exception.code, "AUDIT_UNKNOWN")
            self.assertEqual(db.max_revision(), head)
            overview = projection.build_projection(db, revision=before_audit)
        self.assertIsNone(overview["audit_id"])
        self.assertEqual(overview["snapshot_revision"], before_audit)
        self.assertEqual([node["id"] for node in overview["nodes"]], ["itm_lem", "itm_thm"])
        self.assertEqual(db_digest(fixture.path), digest)

    def test_revision_outside_the_stored_range_is_rejected_with_revision_range(self):
        """Revision 0 and any revision past the head raise InvalidRequest REVISION_RANGE."""
        fixture = self.staged("complete")
        digest = db_digest(fixture.path)
        with fixture.open(write=False) as db:
            head = db.max_revision()
            for revision in (0, -1, head + 1, head + 1000):
                with self.subTest(revision=revision):
                    with self.assertRaises(InvalidRequest) as caught:
                        projection.build_projection(db, revision=revision, audit_id="aud_1")
                    self.assertEqual(caught.exception.code, "REVISION_RANGE")
            self.assertEqual(db.max_revision(), head)
        self.assertEqual(db_digest(fixture.path), digest)

    def test_a_rejected_projection_leaves_the_next_projection_unchanged(self):
        """A refused projection leaves the head revision and the head projection byte identical."""
        fixture = self.staged("complete")
        with fixture.open(write=False) as db:
            before = projection.build_projection(db, audit_id="aud_1")
            head = db.max_revision()
        digest = db_digest(fixture.path)
        with fixture.open(write=False) as db:
            for kwargs in ({"audit_id": "nope"}, {"revision": 0, "audit_id": "aud_1"}):
                with self.subTest(request=sorted(kwargs)):
                    with self.assertRaises(InvalidRequest):
                        projection.build_projection(db, **kwargs)
        with fixture.open(write=False) as db:
            self.assertEqual(db.max_revision(), head)
            self.assertEqual(dumped(projection.build_projection(db, audit_id="aud_1")), dumped(before))
        self.assertEqual(db_digest(fixture.path), digest)


class ScopeExplanationTests(ProjectionCase):
    def test_configured_review_without_eligible_results_has_honest_summary(self):
        for empty in (False, True):
            with self.subTest(empty=empty):
                fixture = self.fixture("scope_" + str(empty)).audit(mode="full")
                with fixture.open() as db:
                    audit = db.head("audits", fixture.audit_id)
                    exclusions = [{"target": R("items", name), "source_anchor_ids": [],
                        "reason": "Explicitly excluded for this audit", "consequence": "No review of this result"}
                        for name in ("itm_lem", "itm_thm")]
                    additions = [] if empty else [fixture.item_edit("itm_setup", "assumption", "Setup", "anc_lem", "anc_lem_proof")]
                    fixture.apply(db, [*additions, edit("replace", "audits", audit.id,
                        dict(audit.body, exclusions=exclusions), audit.version)], mode="primary")
                    view = projection.build_projection(db, audit_id=fixture.audit_id)
                    state = queries.status(db, audit_id=fixture.audit_id)
                factual = view["summary"]["factual"]
                self.assertEqual(state["factual_summary"], factual)
                self.assertEqual(factual["independent_review"]["explanation"],
                    "Independent review is configured, but no eligible result targets are currently in scope.")
                self.assertEqual(factual["independent_review"]["state"], "pending" if empty else "not_required")
                self.assertFalse(any(o["role"] == "independent" for o in view["obligations"]))
                self.assertEqual(factual["scope"]["explanation"],
                    "Full audit of the declared scope after the recorded exclusions.")
                self.assertEqual({e["label"] for e in factual["scope"]["exclusions"]}, {"Lemma 1", "Theorem 1"})

    def test_included_theorem_without_route_still_needs_review(self):
        fixture = self.fixture().audit()
        with fixture.open() as db:
            audit = db.head("audits", fixture.audit_id)
            fixture.apply(db, [fixture.item_edit("itm_missing", "theorem", "Requested theorem", "anc_thm", "anc_thm_proof"),
                edit("replace", "audits", audit.id, dict(audit.body, targets=[R("items", "itm_missing")]), audit.version)],
                mode="primary")
            view = projection.build_projection(db, audit_id=fixture.audit_id)
        review = view["summary"]["factual"]["independent_review"]
        self.assertEqual(review["state"], "pending")
        self.assertEqual(review["explanation"], "Independent review: pending.")
        self.assertFalse(view["summary"]["progress"]["process_complete"])
        self.assertFalse(any(o["role"] == "independent" for o in view["obligations"]))
        self.assertIn("itm_missing", {n["id"] for n in view["nodes"]})


class AuditFindingLocationTests(ProjectionCase):
    def test_audit_findings_are_located_with_and_without_required_global_work(self):
        for required in (False, True):
            with self.subTest(required=required):
                fixture = self.fixture("finding_" + str(required)).primary()
                with fixture.open() as db:
                    if required:
                        audit = db.head("audits", fixture.audit_id)
                        tasks = [dict(t, applicability="required", reason="Synthetic manuscript-wide examination")
                            if t["kind"] == "global_consistency" else t for t in audit.body["global_tasks"]]
                        fixture.apply(db, [edit("replace", "audits", audit.id, dict(audit.body, global_tasks=tasks), audit.version)],
                            *fixture.ITEMS, mode="primary")
                    check = fixture.check_edit("chk_global", R("audits", fixture.audit_id), "global_consistency", evidence=["anc_lem"])
                    fixture.apply(db, [check], "audits:" + fixture.audit_id, mode="primary")
                    fixture.apply(db, [edit("create", "findings", "fnd_global", {
                        "audit_id": fixture.audit_id, "target": R("audits", fixture.audit_id), "category": "presentation",
                        "lifecycle": "open", "description": "Notation changes without explanation.", "evidence_refs": ["anc_thm"],
                        "check_refs": [fixture.pin(db, "checks", "chk_global")], "affected_uses": [],
                        "impact_reason": "The notation is used across the manuscript.", "resolution": None})],
                        "audits:" + fixture.audit_id, mode="primary")
                    view, report = projection.project(db, audit_id=fixture.audit_id)
                self.assertEqual(report["problems"], view["summary"]["limitations"])
                self.assertEqual({n["id"] for n in view["nodes"]}, {"itm_lem", "itm_thm"})
                self.assertEqual(view["summary"]["findings"]["open"], 1)
                detail = view["details"]["audit:" + fixture.audit_id]
                self.assertTrue({"fnd_global", "chk_global", "anc_thm", "anc_lem"}.issubset({r["id"] for r in detail["record_refs"]}))
                location = next(r for r in view["record_locations"] if r["ref"]["id"] == "fnd_global")
                self.assertEqual((location["detail_key"], location["section_key"]), ("audit:" + fixture.audit_id, "findings"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
