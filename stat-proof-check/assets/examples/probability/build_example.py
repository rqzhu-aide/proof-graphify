"""Build an explicitly authored working example through the public core APIs.

No qualification or independent responses are fabricated. This is a worked
answer, not a fresh mathematical evaluation. Run with the user-wide Python.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys

SCRIPTS = str(Path(__file__).resolve().parents[3] / "scripts")
if "paper_core" not in sys.modules:
    sys.path.insert(0, SCRIPTS)
elif SCRIPTS not in sys.path:
    sys.path.append(SCRIPTS)

from audit_io import configure_console, write_json

from paper_core import CONTRACT_VERSION, acceptance, controller, packets, sources, storage
from paper_core.assessment import derive_full
from paper_core.canonical import canonical_bytes
from paper_core.ids import new_id

AUDIT = "aud_probability"
PROVENANCE = "Authored worked example; saved answers are demonstrations, not fresh independent audit evidence."
STEPS = ("x_tail", "y_tail", "joint", "denominator", "pointwise", "conditional", "final")


def ref(collection, identifier):
    return {"collection": collection, "id": identifier}


def create(collection, identifier, body):
    return {"op": "create", "collection": collection, "id": identifier, "expected_version": None, "body": body}


def batch(packet_id, edits):
    return {"contract_version": CONTRACT_VERSION, "request_id": new_id("request"),
            "packet_id": packet_id, "edits": edits}


def source_sections(text):
    lines = text.splitlines()
    result = {}
    for index, line in enumerate(lines):
        if line.startswith("<!-- begin:"):
            name = line.removeprefix("<!-- begin:").removesuffix(" -->")
            end = lines.index(f"<!-- end:{name} -->", index + 1)
            result[name] = {"start_line": index + 2, "end_line": end,
                            "text": "\n".join(lines[index + 1:end])}
    return result


def _packet(db, paper_id, mode="primary"):
    return packets.get_packet(db, targets=[ref("papers", paper_id)], mode=mode)


def _item(name, kind, statement, *, scope=None, owner=None, proof=None, proof_idea=None):
    passages = [{"role": "statement", "anchor_id": "anc_" + name}]
    if proof:
        passages.append({"role": "proof", "anchor_id": "anc_" + proof})
    body = {"kind": kind, "label": name.replace("_", " ").title(),
        "caption": name.replace("_", " "), "statement": {"form": "verbatim", "text": statement},
        "passages": passages, "aliases": [], "uncertainty": None, "origin": "source",
        "owner_id": owner, "scope_id": scope}
    if proof_idea:
        body["proof_idea"] = proof_idea
    return create("items", "itm_" + name, body)


def _group(name, argument, conclusion, *, scope="scp_global", discharges=()):
    return create("groups", "grp_" + name, {"argument_id": argument, "conclusion": ref("items", conclusion),
        "kind": "joint", "scope_id": scope, "case_scope_ids": [], "discharges": list(discharges),
        "rationale": "Recorded transition in the worked proof; inspect its saved calculation.",
        "evidence_refs": ["anc_" + ("hoeffding_proof" if name == "hoeffding" else name)]})


def _use(name, supplier, consumer, group, section, needed, *, substitutions=(), regime=None):
    identifier = "use_" + name
    return [create("uses", identifier, {"from": ref("items", supplier), "to": ref("items", consumer),
        "type": "dependency", "reason": needed, "evidence_refs": ["anc_" + section],
        "regime": regime, "uncertainty": None}),
        create("application_details", identifier, {"use_id": identifier, "group_id": group,
            "needed_form": {"form": "transcription", "text": needed},
            "substitutions": [{"symbol": symbol, "value": value} for symbol, value in substitutions],
            "state": "registered"})]


def build_example(destination, *, render=False):
    destination = Path(destination).resolve()
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("Use a new or empty output directory; the example never overwrites an earlier run.")
    destination.mkdir(parents=True, exist_ok=True)
    source_root = destination / "source"
    source_root.mkdir()
    source_path = source_root / "source.md"
    shutil.copyfile(Path(__file__).with_name("source.md"), source_path)
    sections = source_sections(source_path.read_text(encoding="utf-8"))
    database = destination / "probability.db"
    initialized = storage.initialize(database, source_root=source_root, title="Worked probability proof: ratio concentration")
    paper_id = initialized["paper_id"]
    receipts = []
    with storage.Database(database, write=True) as db:
        captured = sources.capture_sources(db, files=["source.md"])
        source_id = captured["sources"][0]["id"]
        packet = _packet(db, paper_id, "author")
        sources.anchor_sources(db, request={"contract_version": CONTRACT_VERSION, "request_id": new_id("request"),
            "packet_id": packet["packet_id"], "anchors": [{"id": "anc_" + name, "expected_version": None,
                "source_id": source_id, "locator": {"start_line": section["start_line"], "end_line": section["end_line"],
                                                     "page": None, "label": None}}
                for name, section in sections.items()]})
        edits = [_item("setup", "definition", sections["setup"]["text"]),
                 _item("hoeffding", "lemma", sections["hoeffding"]["text"], proof="hoeffding_proof",
                       proof_idea="Bound the variance under exponential tilting to control the centered moment generating function. "
                                  "Independence factors the joint moment, and the two tail bounds combine to give the conditional theorem."),
                 _item("ratio", "theorem", sections["ratio"]["text"], proof="ratio_proof",
                       proof_idea="Specialize the conditional concentration lemma to each coordinate and combine the two deviation events. "
                                  "On their intersection the denominator stays positive, so the ratio admits a deterministic error bound. "
                                  "Discharge the temporary event assumption and use the event's probability to obtain the final bound."),
                 _item("event", "assumption", sections["event"]["text"], scope="scp_event"),
                 create("scopes", "scp_global", {"argument_id": None, "parent_id": None, "assumptions": [],
                     "binders": [], "conditions": [], "evidence_refs": ["anc_setup"]}),
                 create("scopes", "scp_event", {"argument_id": "arg_ratio", "parent_id": "scp_global",
                     "assumptions": [ref("items", "itm_event")], "binders": [], "conditions": [],
                     "evidence_refs": ["anc_event"]})]
        for name in STEPS[:-1]:
            edits.append(_item(name, "intermediate_result", sections[name]["text"], owner="itm_ratio",
                               scope="scp_event" if name in ("denominator", "pointwise") else None))
        for name, final in (("hoeffding", "grp_hoeffding"), ("ratio", "grp_final")):
            edits.append(create("arguments", "arg_" + name, {"target": ref("items", "itm_" + name),
                "label": "Written proof of " + name, "origin": "source", "scope_id": "scp_global",
                "final_group_id": final, "evidence_refs": ["anc_" + name + "_proof"], "lifecycle": "registered"}))
        edits.append(_group("hoeffding", "arg_hoeffding", "itm_hoeffding"))
        for name in STEPS:
            edits.append(_group(name, "arg_ratio", "itm_ratio" if name == "final" else "itm_" + name,
                scope="scp_event" if name in ("denominator", "pointwise", "conditional") else "scp_global",
                discharges=["scp_event"] if name == "conditional" else []))
        edges = [
            ("hx", "hoeffding", "x_tail", "x_tail", "With Z_i=X_i and u=t: P(|bar X-mu_X|>t) <= delta/2."),
            ("hy", "hoeffding", "y_tail", "y_tail", "With Z_i=Y_i and u=t: P(|bar Y-mu_Y|>t) <= delta/2."),
            ("x_joint", "x_tail", "joint", "joint", "The first failure event has probability at most delta/2."),
            ("y_joint", "y_tail", "joint", "joint", "The second failure event has probability at most delta/2."),
            ("event_denominator", "event", "denominator", "denominator", "On this outcome in E, |bar Y-mu_Y| <= t."),
            ("denominator_ratio", "denominator", "pointwise", "pointwise", "On E, bar Y >= b/2 > 0."),
            ("event_ratio", "event", "pointwise", "pointwise", "On E, both deviations are at most t."),
            ("ratio_implication", "pointwise", "conditional", "conditional", "The pointwise error bound for an arbitrary outcome in E."),
            ("joint_final", "joint", "ratio", "final", "P(E) >= 1-delta."),
            ("implication_final", "conditional", "ratio", "final", "E is contained in the target error event.")]
        for name, supplier, consumer, group, needed in edges:
            coordinate = {"hx": "X", "hy": "Y"}.get(name)
            substitutions = (("Z_i", coordinate + "_i"), ("m", "mu_" + coordinate), ("u", "t")) if coordinate else ()
            regime = "Each coordinate sequence is independent across pairs, takes values in [0,1], and uses t>0; within-pair independence is unnecessary." if coordinate else None
            edits.extend(_use(name, "itm_" + supplier, "itm_" + consumer, "grp_" + group, group, needed,
                              substitutions=substitutions, regime=regime))
        acceptance.apply_batch(db, batch(_packet(db, paper_id)["packet_id"], edits))
        boundary_packet = _packet(db, paper_id)
        sources.review_sources(db, batch=batch(boundary_packet["packet_id"], [create("source_reviews", "srv_boundaries", {
            "source_refs": [db.head("sources", source_id).pinned],
            "anchor_refs": [db.head("anchors", "anc_" + name + "_proof").pinned for name in ("hoeffding", "ratio")],
            "purpose": "proof_boundary", "decision": "accepted", "rationale": "Complete authored proof blocks, including continuations. " + PROVENANCE,
            "reviewer": "example-author"})]))
        edits = []
        for item in db.heads("items"):
            edits.append(create("target_specs", "tgt_" + item.id.removeprefix("itm_"), {"target": item.ref,
                "statement_ref": item.pinned, "statement": None, "scope_id": item.body["scope_id"],
                "evidence_refs": [item.body["passages"][0]["anchor_id"], "anc_setup"], "state": "registered", "fidelity_ref": None}))
        for name in ("hoeffding", "ratio"):
            edits.append(create("proof_boundaries", "bnd_" + name, {"target": ref("items", "itm_" + name),
                "argument_ids": ["arg_" + name], "anchor_refs": [db.head("anchors", "anc_" + name + "_proof").pinned],
                "source_review_ref": db.head("source_reviews", "srv_boundaries").pinned, "state": "complete"}))
        edits.append(create("audits", AUDIT, {"paper_id": paper_id, "mode": "focused", "targets": [ref("items", "itm_ratio")],
            "exclusions": [], "protocol_version": "item-audit/1", "independent_required": True, "qualification_id": None,
            "global_tasks": [{"kind": kind, "applicability": "not_applicable", "reason": "This worked example concerns the two displayed proofs only."}
                for kind in ("global_consistency", "adversarial", "method_interface")], "report_path": "working.html"}))
        acceptance.apply_batch(db, batch(_packet(db, paper_id)["packet_id"], edits))
        # Coherent calls may include several applications and derivations. The
        # source of each saved worked answer is explicit; no model is dispatched.
        for attempt in range(20):
            prepared = controller.prepare_work(db, audit_id=AUDIT, mode="primary", max_units=10, allow_provisional=True)
            if not prepared["prepared"]:
                break
            response = prepared["scaffold"]
            tasks = {task["id"]: task for task in prepared["manifest"]["work"]["tasks"]}
            for row in response["results"]:
                task = tasks[row["task_id"]]
                record = db.head(task["target"]["collection"], task["target"]["id"])
                if record.collection == "target_specs":
                    record = db.head(record.body["target"]["collection"], record.body["target"]["id"])
                anchors = record.body.get("evidence_refs") or [p["anchor_id"] for p in record.body.get("passages", [])]
                if row["type"] == "source_fidelity":
                    anchors = record.body.get("evidence_refs") or [p["anchor_id"] for p in record.body.get("passages", [])
                                                                  if p["role"] in ("statement", "definition")]
                    row.update(result="matched", note="Compared the exact saved statement with the captured UTF-8 source and standing setup. " + PROVENANCE,
                               evidence_refs=anchors)
                else:
                    step = ("hoeffding_proof" if record.id in ("arg_hoeffding", "grp_hoeffding") else
                            "ratio_proof" if record.id == "arg_ratio" else
                            record.id.removeprefix("grp_") if record.collection == "groups" else
                            record.body["evidence_refs"][0].removeprefix("anc_"))
                    row.update(state="complete", outcome="supported", reasoning=PROVENANCE + "\n\n" + sections[step]["text"],
                               evidence_refs=anchors)
                    if task["kind"] == "composition":
                        name = record.id.removeprefix("arg_")
                        anchor = db.head("anchors", "anc_" + name + "_proof")
                        response["coverage"].append({"argument_id": record.id, "anchor_id": anchor.id,
                            "start_offset": 0, "end_offset": len(anchor.body["excerpt"]), "classification": "substantive",
                            "claim_refs": [record.body["target"]], "check_task_ids": [task["id"]], "existing_check_refs": [],
                            "replaces": None, "note": "Complete authored proof block is examined in the composition calculation."})
            envelope = {"contract_version": CONTRACT_VERSION, "request_id": new_id("request"), "packet_id": prepared["packet_id"],
                "rebase_packet_id": None, "reviewer": "example-author", "qualification_id": None, "exposure": None, "exposure_note": ""}
            prefix = destination / f"primary-{attempt + 1:02d}"
            prefix.with_suffix(".response.json").write_bytes(canonical_bytes(response))
            prefix.with_suffix(".submission.json").write_bytes(canonical_bytes(envelope))
            saved = controller.submit_work(db, envelope_bytes=canonical_bytes(envelope), response_bytes=canonical_bytes(response))
            if saved["state"] != "accepted":
                raise RuntimeError(f"worked primary response rejected: {saved}")
            receipts.append(saved)
        else:
            raise RuntimeError("worked example did not reach a stable primary checkpoint")
        derivation, assessment = derive_full(db, audit_id=AUDIT)
        scope_examples = {
            "conditional_theorem_in_event_scope": derivation.support(ref("items", "itm_hoeffding"), "scp_event"),
            "temporary_premise_inside_scope": derivation.support(ref("items", "itm_event"), "scp_event"),
            "temporary_premise_outside_scope": derivation.support(ref("items", "itm_event"), "scp_global"),
            "denominator_inside_scope": derivation.support(ref("items", "itm_denominator"), "scp_event"),
            "denominator_outside_scope": derivation.support(ref("items", "itm_denominator"), "scp_global"),
            "discharged_implication": derivation.support(ref("items", "itm_conditional"), "scp_global")}
        result = {"database": str(database), "audit_id": AUDIT, "provenance": PROVENANCE, "scope_examples": scope_examples,
                  "specialization_examples": {
                      "conditional_theorem_in_consumer_scope": derivation.support(ref("items", "itm_hoeffding"), "scp_global"),
                      "checked_x_application": derivation.use_support(db.head("uses", "use_hx")),
                      "checked_y_application": derivation.use_support(db.head("uses", "use_hy")),
                      "specialized_x_bound": derivation.support(ref("items", "itm_x_tail"), "scp_global"),
                      "specialized_y_bound": derivation.support(ref("items", "itm_y_tail"), "scp_global")},
                  "progress": assessment["progress"], "primary_submissions": len(receipts), "independent_review": "not performed"}
        if render:
            from paper_core.projection import build_projection
            from paper_core.publish import publish_report
            result["report"] = publish_report(db, projection=build_projection(db, audit_id=AUDIT), output=destination / "working.html", release=False)
    write_json(destination / "example-receipt.json", result)
    return result


if __name__ == "__main__":
    configure_console()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, help="new or empty output directory")
    parser.add_argument("--render", action="store_true", help="also create the working HTML report")
    args = parser.parse_args()
    print(json.dumps(build_example(args.out, render=args.render), ensure_ascii=False))
