"""Public CLI integration for local drafts, corrections and separate review groups.

Synthetic judgments exercise mechanics only; this is not a paper accuracy test.
"""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from support import Fixture, PROOFCHECK, TempCase, node_available, run_wrapper, sha, write_json


def exercise(root):
    root = Path(root)
    fixture = Fixture(root / "audit").anchors()
    calls = []

    def cli(*args, expect=0):
        result, _ = run_wrapper(PROOFCHECK, *args, expect=expect)
        calls.append({"args": [str(a) for a in args], "result": result})
        write_json(root / "commands.json", calls)
        return result

    def read(path):
        return json.loads(Path(path).read_text(encoding="utf-8"))

    lemma = {"local_id": "lemma", "kind": "lemma", "label": "Lemma 1",
        "statement": "For every n, a_n < 1.",
        "source": {"document": "paper.tex", "locator": "lines 5-7"},
        "unit": {"statement_anchors": ["anc_lem"], "proof_anchors": ["anc_lem_proof"],
                 "source_matched": False, "proof_complete": True,
                 "source_note": "Synthetic fixture with a transcription sign to correct."}}
    theorem = {"local_id": "theorem", "kind": "theorem", "label": "Theorem 1",
        "statement": "The sequence a_n converges.",
        "source": {"document": "paper.tex", "locator": "lines 11-13"},
        "unit": {"statement_anchors": ["anc_thm"], "proof_anchors": ["anc_thm_proof"],
                 "source_matched": True, "proof_complete": True, "source_note": "Synthetic source comparison."}}
    one = {"namespace": "one", "reviewer": "synthetic primary A", "items": [lemma],
           "examinations": [{"target": "lemma", "reasoning": "The source uses a non-strict bound."}]}
    two = {"namespace": "two", "reviewer": "synthetic primary B", "items": [deepcopy(lemma), theorem],
           "connections": [{"from": "lemma", "to": "theorem", "reason": "Uses the sequence bound.",
               "needed_form": {"form": "verbatim", "text": "a_n <= 1"}}]}
    paths = [write_json(root / "one.json", one), write_json(root / "two.json", two)]
    args = ["stage1", "consolidate-drafts", "--input", paths[0], "--input", paths[1],
            "--out", root / "consolidated.json"]
    cli(*args)
    cli(*args)
    consolidated = read(root / "consolidated.json")
    assert len(consolidated["items"]) == 2
    assert consolidated["mapping"]["one"]["lemma"] == consolidated["mapping"]["two"]["lemma"]
    assert consolidated["examinations"][0]["examination"] == one["examinations"][0]
    ids = {key: value["id"] for key, value in consolidated["mapping"]["two"].items()}
    for identity in consolidated["authoring_order"]:
        option = next(row for row in consolidated["authoring"] if row["target"]["id"] == identity)
        definition = write_json(root / (identity + ".json"), option["definition"])
        result = cli("stage1", "add-unit", fixture.path, "--input", definition)
        assert result["unit"]["item"] == identity
    packet = cli("get", fixture.path, "--target", "items:" + ids["lemma"],
                 "--mode", "author", "--out", root / "author.json")
    cli("template", fixture.path, "--collection", "items", "--id", ids["lemma"],
        "--packet", packet["packet_id"], "--out", root / "replacement.json")
    assert read(root / "replacement.json")["template"]["edits"][0]["op"] == "replace"
    correction = write_json(root / "correction.json", {"statement": "For every n, a_n <= 1."})
    args = ["stage1", "correct-claim", fixture.path, "--item", ids["lemma"],
            "--expected-version", "1", "--correction", correction]
    cli(*args)
    assert cli(*args)["reused"]
    with fixture.open(write=False) as db:
        assert len(db.heads("checks")) == 0
        assert len(db.heads("uses")) == 1
    audit = cli("stage1", "scope", fixture.path, "--mode", "full")["audit_id"]
    for name in ("lemma", "theorem"):
        directory = root / ("primary-" + name)
        prepared = cli("stage1", "prepare", fixture.path, "--audit", audit,
                       "--focus", "items:" + ids[name], "--out", directory)
        assert prepared["prepared"], prepared
        response = read(directory / "response-scaffold.json")
        for row in response["results"]:
            if row["type"] == "source_fidelity":
                row.update(result="matched", note="Compared the corrected captured statement.",
                           evidence_refs=["anc_lem" if name == "lemma" else "anc_thm"])
            else:
                row.update(state="complete", outcome="supported" if name == "lemma" else "gap",
                    reasoning="Synthetic test of the supplied induction." if name == "lemma" else
                              "Synthetic gap: boundedness alone does not establish convergence.",
                    evidence_refs=["anc_lem_proof" if name == "lemma" else "anc_thm_proof"])
        submitted = cli("stage1", "examine", fixture.path, "--packet", prepared["packet_id"],
                        "--reviewer", "synthetic primary", "--response", write_json(directory / "response.json", response))
        assert submitted["state"] == "accepted", submitted
        assert not submitted["remaining_task_ids"], submitted
    first = cli("stage2", "prepare-group", fixture.path, "--audit", audit,
                "--max-packets", "1", "--out", root / "group-a")
    second = cli("stage2", "prepare-group", fixture.path, "--audit", audit,
                 "--exclude-group", first["group_index"], "--out", root / "group-b")
    assert len(first["packets"]) == len(second["packets"]) == 1
    assert not set(first["assigned_task_ids"]) & set(second["assigned_task_ids"])
    bad = cli("stage2", "prepare-group", fixture.path, "--audit", audit, "--resume-group", first["group_index"],
              "--max-packets", "1", "--out", root / "invalid", expect=2)
    assert bad["error"]["code"] == "USAGE"
    for group in (first, second):
        for entry in group["packets"]:
            directory = Path(entry["directory"])
            response = read(directory / "response-scaffold.json")
            response["coverage_note"] = "Synthetic independent response for CLI validation only."
            response["exposure_report"] = {"status": "none_known", "note": "Synthetic test provenance, not a model audit."}
            for row in response["judgments"]:
                is_lemma = row["target"]["source_anchor_id"] == "anc_lem"
                row.update(state="complete", outcome="supported" if is_lemma else "gap",
                           reasoning="Synthetic independent induction check." if is_lemma else
                                     "Synthetic independent gap: the convergence step needs monotonicity.")
            submitted = cli("stage2", "review", fixture.path, "--packet", entry["packet_id"],
                "--reviewer", "synthetic independent", "--exposure", "source_only",
                "--response", write_json(directory / "response.json", response))
            assert submitted["state"] == "accepted", submitted
            assert not submitted["remaining_task_ids"], submitted
    recovered = cli("stage2", "prepare-group", fixture.path, "--audit", audit,
                    "--resume-group", first["group_index"], "--out", root / "recovered")
    assert recovered["packet_ids"] == first["packet_ids"]
    assert not recovered["remaining_task_ids"] or set(recovered["remaining_task_ids"]).isdisjoint(first["assigned_task_ids"])
    for name in ("lemma", "theorem"):
        directory = root / ("integration-" + name)
        prepared = cli("stage2", "prepare", fixture.path, "--audit", audit,
            "--mode", "integration", "--focus", "items:" + ids[name], "--out", directory)
        assert prepared["prepared"], prepared
        response = read(directory / "response-scaffold.json")
        for row in response["integrations"]:
            row.update(decision="agree", rationale="Both saved synthetic judgments agree; retain the actual gap.")
        submitted = cli("stage2", "integrate", fixture.path, "--packet", prepared["packet_id"],
            "--reviewer", "coordinator", "--response", write_json(directory / "response.json", response))
        assert submitted["state"] == "accepted", submitted
        assert not submitted["remaining_task_ids"], submitted
    with fixture.open(write=False) as db:
        originals = {row.id: db.get_blob(row.body["original_blob"]) for row in db.heads("responses")}
        assert len(originals) == 2
        assert len(db.heads("checks")) == 4
        assert any(row.body["outcome"] == "gap" for row in db.heads("checks"))
    frozen = cli("stage2", "finalize", fixture.path, "--audit", audit, "--out", root / "frozen")
    assert frozen["kind"] == "release" and frozen["process_complete"], frozen
    database_hash = sha(fixture.path.read_bytes())
    if node_available():
        cli("stage3", "build", root / "frozen", "--out", root / "report.html")
        assert (root / "report.html").is_file()
        assert sha(fixture.path.read_bytes()) == database_hash
    with fixture.open(write=False) as db:
        assert originals == {row.id: db.get_blob(row.body["original_blob"]) for row in db.heads("responses")}
    result = {"kind": frozen["kind"], "process_complete": frozen["process_complete"],
              "shared_items": 2, "distinct_groups": 2, "checks": 4, "original_responses": 2,
              "rendered": node_available(), "database_sha256": database_hash, "commands": len(calls)}
    write_json(root / "results.json", result)
    return result


class WorkflowCliTests(TempCase):
    def test_drafts_correction_distinct_reviews_and_delivery(self):
        result = exercise(self.path("public-workflow"))
        self.assertEqual("release", result["kind"])


if __name__ == "__main__":
    import sys
    if len(sys.argv) == 2 and sys.argv[1] != "-v":
        print(json.dumps(exercise(sys.argv[1]), indent=2))
    else:
        unittest.main()
