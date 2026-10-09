"""Behaviour tests for ``paper_core.assessment`` (architecture 9.3, record-contract 6-7, handoff 7.3).

``assessment`` is the only place where stored records become a colour. Nothing it produces is written
back, so every value here has to be reproducible from the snapshot alone: the obligation set is derived
from the registered structure and the declared audit, freshness comes from comparing a judgment's stored
binding with the snapshot, dependency support follows the recorded uses, and one reducer turns
constituents into the four presentation states that the report and ``status`` both render.

These tests pin four things the rest of the system depends on.

* The reducer's lattice. ``reduce`` is exercised directly on hand-built constituents so that every
  branch -- defect precedence, dispute, "nothing assessed", the amber reason list and its ordering --
  is checked without a database in the way, including the rule that colour follows primary work while
  independent and coordinator work only moves the indicator.
* Identity. ``obligation_id``/``key_of``/``ref_of``/``pinned_of`` are the names the projection, the
  report and the packets all agree on, so they must be stable functions of their inputs.
* The two ports named in the handoff. A changed prerequisite has to stale the judgments that consumed
  it (and only those), and a repair that merely records a restricted statement must not silently
  revalidate the dependent judgments.
* Process completeness. ``process_complete`` is a statement about *process*, not about mathematics: a
  completed audit may report a gap and still be complete, while an unmet obligation, an open source
  issue or an unreconciled dispute must all hold it back.

Scenario values (obligation counts, labels, explanations) were taken from the real API through
``support.Fixture``; the fixture is extended locally only where a scenario needs a third item, a second
use or an independent round whose outcome and exposure differ from the shared helper's.
"""
from __future__ import annotations

import json
import unittest

from support import GLOBAL_TASKS, PAPER_TEX, R, TempCase, edit

from paper_core import controller, packets, review, sources
from paper_core.canonical import canonical_bytes
from paper_core.assessment import (DEFECT_OUTCOMES, INDICATORS, OBLIGATION_KINDS, PROOF_CHECK_KINDS,
                                   PROOF_KINDS, ROLES, STATES, Snapshot, derive_assessment, derive_full,
                                   judgment_freshness, key_of, obligation_id, pinned_of, reduce, ref_of)
from paper_core.errors import InvalidRequest
from paper_core.refs import facet_digests

# -- documented explanations (the report prints these verbatim) --------------------------------------
GREEN = ("every represented use and required supporting derivation is currently supported with dependency "
         "support available under declared premises")
REUSE_SUFFIX = " (some work carried by accepted reuse decisions)"
NO_WORK = "no work is represented"
NOTHING_ASSESSED = "no completed or substantive draft assessment exists for the represented work"
DISPUTE = "completed assessments disagree and have no explicit resolution"
RECHECK = "historical defect against a changed input; recheck qualification pending"

# -- documented result surfaces ----------------------------------------------------------------------
RESULT_KEYS = {"analysis_complete", "assessments", "audit_id", "audits", "by_target", "constituents", "context", "findings",
               "independent", "judgments", "mode", "obligations", "problems", "progress",
               "published_revision", "revision", "route_records", "routes", "scope", "source_limits",
               "statements", "support", "coverage_diagnostics", "coverage_diagnostic_count",
               "coverage_diagnostics_truncated"}
OBLIGATION_KEYS = {"assessment", "check_refs", "explanation", "freshness", "id", "kind", "outcome",
                   "required", "role", "satisfied", "state", "target"}
CONSTITUENT_KEYS = {"check_refs", "compromised", "disputed", "finding_refs", "freshness", "kind",
                    "obligation_id", "outcome", "required", "reused", "role", "state", "substantive",
                    "support", "target"}
JUDGMENT_KEYS = {"audit_id", "context_changed", "exposure", "freshness", "kind", "outcome", "ref",
                 "response_state", "reused", "reviewer", "revision", "role", "state", "substantive",
                 "superseded", "target", "unbound"}
ASSESSMENT_KEYS = {"check_refs", "explanation", "finding_refs", "independent_review",
                   "missing_obligation_ids", "label", "state"}

# The obligation set the shared fixture's focused audit must derive: eleven required judgments plus the
# three global tasks it declares not applicable.
FIXTURE_OBLIGATIONS = {
    ("arguments:arg_lem", "composition", "primary", True),
    ("arguments:arg_lem", "composition", "independent", True),
    ("arguments:arg_thm", "composition", "primary", True),
    ("arguments:arg_thm", "composition", "independent", True),
    ("groups:grp_lem", "derivation", "primary", True),
    ("groups:grp_thm", "derivation", "primary", True),
    ("uses:use_lem_thm", "application", "primary", True),
    ("items:itm_lem", "source_fidelity", "primary", True),
    ("items:itm_thm", "source_fidelity", "primary", True),
    ("target_specs:tgt_lem", "source_fidelity", "primary", True),
    ("target_specs:tgt_thm", "source_fidelity", "primary", True),
    ("items:itm_lem", "reconciliation", "coordinator", True),
    ("items:itm_thm", "reconciliation", "coordinator", True),
    ("audits:aud_1", "global_consistency", "primary", False),
    ("audits:aud_1", "adversarial", "primary", False),
    ("audits:aud_1", "method_interface", "primary", False),
}
PROGRESS_COMPLETE = {"process_complete": True, "required_obligations": 13,
                     "completed_current_obligations": 13, "draft_checks": 0, "major_results": 2,
                     "source_unbound_items": 0}

# -- bodies the fixture does not build ---------------------------------------------------------------
ASSUMPTION_ITEM = {"kind": "assumption", "label": "Assumption 1", "caption": "Assumption 1",
                   "statement": {"form": "verbatim", "text": "second moments are finite"},
                   "passages": [{"role": "statement", "anchor_id": "anc_lem"}], "aliases": [],
                   "uncertainty": None, "origin": "source", "owner_id": None, "scope_id": None}
USE_ASS_LEM = {"from": R("items", "itm_ass"), "to": R("items", "itm_lem"), "type": "dependency",
               "group_id": "grp_lem", "reason": "applied as stated", "needed_form": None,
               "substitutions": [], "evidence_refs": ["anc_lem_proof"], "regime": None, "uncertainty": None}
INTERMEDIATE_ITEM = {"kind": "intermediate_result", "label": "Step 1", "caption": "Step 1",
                     "statement": {"form": "verbatim", "text": "the partial sums are bounded"},
                     "passages": [], "aliases": [], "uncertainty": None, "origin": "reconstruction",
                     "owner_id": "itm_lem", "scope_id": None}
REPAIR_ITEM = {"kind": "lemma", "label": "Lemma 1 (restricted)", "caption": "Lemma 1 (restricted)",
               "statement": {"form": "verbatim", "text": "a_n <= 1 for bounded increments"},
               "passages": [], "aliases": [], "uncertainty": None, "origin": "proposed_repair",
               "owner_id": None, "scope_id": None}
RESTRICTED_REPAIR = {"finding_id": "fnd_1", "kind": "restricted_statement",
                     "description": "the bound holds only for bounded increments",
                     "supported_form": R("items", "itm_lem_r"), "argument_id": None,
                     "added_conditions": ["increments are bounded"], "evidence_refs": ["anc_lem_proof"]}
SOURCE_ISSUE = {"anchor_id": None, "category": "ambiguous_label", "description": "label lem:a is ambiguous",
                "lifecycle": "open", "resolution": None, "reviewer": "coord"}
INTERMEDIATE_AUDIT = {"mode": "focused", "targets": [R("items", "itm_int")], "exclusions": [],
                      "protocol_version": "item-audit/1", "independent_required": False,
                      "qualification_id": "qua_r1", "report_path": "reports/aud_2.html"}
EXCLUDING_AUDIT = {"mode": "focused", "targets": [R("items", "itm_lem"), R("items", "itm_thm")],
                   "exclusions": [{"target": R("items", "itm_lem"), "source_anchor_ids": [],
                                   "reason": "audited in an earlier round",
                                   "consequence": "the lemma is taken as given"}],
                   "protocol_version": "item-audit/1", "independent_required": False,
                   "qualification_id": "qua_r1", "report_path": "reports/aud_3.html"}


# -- local helpers -----------------------------------------------------------------------------------
def constituent(**overrides) -> dict:
    """One reducer input: a satisfied required primary constituent unless the caller says otherwise."""
    base = {"obligation_id": "obl_base", "required": True, "kind": "derivation", "role": "primary",
            "target": R("groups", "grp_lem"), "state": "complete", "substantive": True,
            "outcome": "supported", "freshness": "current", "reused": False, "support": "available",
            "check_refs": [], "finding_refs": [], "disputed": False, "compromised": False}
    base.update(overrides)
    return base


def obligation_tuples(result) -> set:
    """(target key, kind, role, required) for every derived obligation."""
    return {(key_of(o["target"]), o["kind"], o["role"], o["required"]) for o in result["obligations"]}


def freshness_of(result) -> dict:
    """judgment key -> derived freshness."""
    return {key: info["freshness"] for key, info in result["judgments"].items()}


def gap_edits(fixture, db) -> list:
    """A completed gap on the lemma's only inference step plus the open finding that reports it."""
    fixture.apply(db, [fixture.check_edit("chk_der_lem2", R("groups", "grp_lem"), "derivation",
                                          outcome="gap", supersedes=fixture.pin(db, "checks", "chk_der_lem"))],
                  *fixture.ITEMS, mode="primary")
    return [edit("create", "findings", "fnd_1", {
        "audit_id": fixture.audit_id, "target": R("groups", "grp_lem"), "category": "proof_gap",
        "lifecycle": "open", "description": "the induction step is not shown",
        "evidence_refs": ["anc_lem_proof"], "check_refs": [fixture.pin(db, "checks", "chk_der_lem2")],
        "affected_uses": ["use_lem_thm"], "impact_reason": "the theorem consumes the lemma",
        "resolution": None})]


def independent_round(fixture, db, *, item_id, argument_id, anchor, outcome, exposure="source_only",
                      status="none_known", reviewer="checker-A"):
    """A blinded independent round whose outcome and exposure the caller chooses.

    ``support.Fixture.independent_round`` always reports a supported outcome from an uncompromised
    reviewer, so the disputed and compromised corners of the indicator lattice need this variant. The
    worker names the passage rather than the argument, exactly as a blinded reviewer must, and the
    coordinator maps that judgment onto the argument afterwards.
    """
    packet = packets.get_packet(db, targets=[R("items", item_id)], mode="independent")
    response = {"packet_id": packet["packet_id"], "covered_targets": [R("items", item_id)],
                "coverage_note": "read the statement and proof from the source",
                "exposure_report": {"status": status,
                                    "note": "" if status == "none_known" else "saw a draft assessment"},
                "judgments": [{"target": {"source_anchor_id": anchor, "description": "the proof passage"},
                               "kind": "composition", "state": "complete", "outcome": outcome,
                               "reasoning": "independent reading of the proof", "evidence_refs": [anchor],
                               "conditions": [], "next_action": None, "supersedes": None}]}
    submitted = review.submit_review(db, submission={
        "contract_version": 3, "request_id": fixture.request_id(), "packet_id": packet["packet_id"],
        "reviewer": reviewer, "qualification_id": "qua_r1", "exposure": exposure,
        "exposure_note": "" if exposure == "source_only" else "the coordinator shared a draft"},
        response_bytes=json.dumps(response).encode("utf-8"))
    if submitted["state"] == "accepted":
        return submitted["checks"][0]["check_id"]
    mapping_packet = fixture.packet(db, *fixture.ITEMS, mode="primary")
    mapped = review.map_response(db, mapping={
        "contract_version": 3, "request_id": fixture.request_id(), "packet_id": mapping_packet["packet_id"],
        "response_id": submitted["response_id"],
        "entries": [{"judgment_index": 0, "target": R("arguments", argument_id),
                     "rationale": "the proof passage is this argument"}],
        "reviewer": "coord"})
    return mapped["checks"][0]["check_id"]


class ReduceTests(unittest.TestCase):
    """The reducer: constituents in, one of four presentation states out (architecture 9.3)."""

    def test_no_constituents_is_gray_and_says_no_work_is_represented(self):
        """A record with nothing to assess is gray, and its explanation distinguishes it from unassessed."""
        result = reduce([])
        self.assertEqual(result["state"], "gray")
        self.assertEqual(result["label"], "unassessed")
        self.assertEqual(result["explanation"], NO_WORK)
        self.assertEqual(result["check_refs"], [])
        self.assertEqual(result["finding_refs"], [])
        self.assertEqual(result["missing_obligation_ids"], [])
        self.assertEqual(result["independent_review"], "not_required")

    def test_only_missing_obligations_is_gray_and_names_them_sorted(self):
        """Registered but unstarted work is gray "unassessed" and reports its obligation ids in order."""
        result = reduce([constituent(obligation_id="obl_b", state="missing", outcome=None, freshness=None),
                         constituent(obligation_id="obl_a", state="missing", outcome=None, freshness=None)])
        self.assertEqual((result["state"], result["label"]), ("gray", "unassessed"))
        self.assertEqual(result["explanation"], NOTHING_ASSESSED)
        self.assertEqual(result["missing_obligation_ids"], ["obl_a", "obl_b"])

    def test_a_missing_required_constituent_without_an_obligation_id_is_not_listed(self):
        """The synthesised constituent of an unregistered use has no id, so it cannot be reported missing."""
        result = reduce([constituent(), constituent(obligation_id=None, state="missing", outcome=None,
                                                   freshness=None)])
        self.assertEqual(result["missing_obligation_ids"], [])
        self.assertEqual((result["state"], result["label"]), ("amber", "partial"))

    def test_a_satisfied_required_constituent_is_green_with_the_documented_explanation(self):
        """Green means every required constituent is complete, current, supported and supported-by."""
        result = reduce([constituent()])
        self.assertEqual((result["state"], result["label"]), ("green", "supported"))
        self.assertEqual(result["explanation"], GREEN)
        self.assertEqual(result["missing_obligation_ids"], [])

    def test_green_names_reuse_when_a_constituent_was_carried_by_a_reuse_decision(self):
        """A reused judgment still counts as current, but the explanation says the work was carried."""
        result = reduce([constituent(), constituent(obligation_id="obl_r", reused=True)])
        self.assertEqual(result["state"], "green")
        self.assertEqual(result["explanation"], GREEN + REUSE_SUFFIX)

    def test_work_that_is_never_required_is_amber_mixed(self):
        """Complete optional work with no required constituent cannot be called supported."""
        result = reduce([constituent(required=False)])
        self.assertEqual((result["state"], result["label"]), ("amber", "mixed"))
        self.assertEqual(result["explanation"], "mixed: work exists but nothing is required here")

    def test_a_current_completed_defect_is_red_and_names_the_kind_and_the_outcome(self):
        """A gap recorded by a current completed proof check turns the record red."""
        result = reduce([constituent(outcome="gap")])
        self.assertEqual((result["state"], result["label"]), ("red", "defect"))
        self.assertEqual(result["explanation"], "current completed derivation assessment identifies gap")

    def test_red_joins_several_defect_kinds_and_outcomes_in_sorted_order(self):
        """The red explanation is deterministic: kinds comma-joined, outcomes slash-joined, both sorted."""
        result = reduce([constituent(kind="derivation", outcome="gap"),
                         constituent(obligation_id="obl_2", kind="application", outcome="refuted")])
        self.assertEqual(result["explanation"],
                         "current completed application, derivation assessment identifies gap/refuted")

    def test_red_appends_the_number_of_required_obligations_still_incomplete(self):
        """A defect alongside unfinished work says so, so a reader does not read red as "fully assessed"."""
        result = reduce([constituent(outcome="gap"),
                         constituent(obligation_id="obl_missing", state="missing", outcome=None,
                                     freshness=None)])
        self.assertEqual(result["explanation"], "current completed derivation assessment identifies gap; "
                                                "1 required obligation(s) also incomplete")
        self.assertEqual(result["missing_obligation_ids"], ["obl_missing"])

    def test_a_defect_beats_an_open_dispute(self):
        """Defect precedence is absolute: a current defect outranks an unreconciled independent review."""
        result = reduce([constituent(outcome="gap")], independent="disputed")
        self.assertEqual((result["state"], result["label"]), ("red", "defect"))
        self.assertEqual(result["independent_review"], "disputed")

    def test_a_stale_or_historical_defect_is_not_red(self):
        """Red requires a *current* judgment; a defect against an older version is amber instead."""
        stale = reduce([constituent(outcome="gap", freshness="needs_review")])
        historical = reduce([constituent(outcome="gap", freshness="historical")])
        self.assertEqual((stale["state"], stale["label"]), ("amber", "stale"))
        self.assertEqual((historical["state"], historical["label"]), ("amber", "historical defect"))

    def test_a_defect_outside_the_proof_check_kinds_is_amber_not_red(self):
        """Only the six proof-check kinds can turn a record red; a global task's gap is reported amber."""
        result = reduce([constituent(kind="global_consistency", outcome="gap")])
        self.assertEqual((result["state"], result["label"]), ("amber", "historical defect"))

    def test_an_independent_defect_does_not_colour_the_statement(self):
        """Colour follows primary work: an independent gap moves the indicator, never the colour."""
        result = reduce([constituent(),
                         constituent(obligation_id="obl_ind", role="independent", outcome="gap")],
                        independent="pending")
        self.assertEqual((result["state"], result["label"]), ("green", "supported"))

    def test_an_unsatisfied_independent_obligation_is_still_reported_as_missing(self):
        """Independent work is excluded from the colour but never from the outstanding-work list."""
        result = reduce([constituent(),
                         constituent(obligation_id="obl_ind", role="independent", state="missing",
                                     outcome=None, freshness=None)],
                        independent="pending")
        self.assertEqual(result["state"], "green")
        self.assertEqual(result["missing_obligation_ids"], ["obl_ind"])

    def test_a_disputed_constituent_is_amber_whatever_its_role(self):
        """A disputed coordinator constituent is amber even though coordinator work has no colour."""
        result = reduce([constituent(), constituent(obligation_id="obl_rec", role="coordinator",
                                                    kind="reconciliation", disputed=True)])
        self.assertEqual((result["state"], result["label"]), ("amber", "disputed"))
        self.assertEqual(result["explanation"], DISPUTE)

    def test_the_disputed_indicator_alone_turns_the_state_amber(self):
        """An unreconciled disagreement holds a fully supported primary record at amber."""
        result = reduce([constituent()], independent="disputed")
        self.assertEqual((result["state"], result["label"]), ("amber", "disputed"))
        self.assertEqual(result["explanation"], DISPUTE)

    def test_a_substantive_draft_is_amber_partial(self):
        """A draft with reasoning counts as work in progress, not as no work at all."""
        result = reduce([constituent(state="draft", outcome=None, freshness="current")])
        self.assertEqual((result["state"], result["label"]), ("amber", "partial"))
        self.assertEqual(result["explanation"], "partial")

    def test_a_draft_without_substance_counts_as_nothing_assessed(self):
        """An empty draft may not lift a record out of gray."""
        result = reduce([constituent(state="draft", substantive=False, outcome=None, freshness="current")])
        self.assertEqual((result["state"], result["label"]), ("gray", "unassessed"))
        self.assertEqual(result["explanation"], NOTHING_ASSESSED)

    def test_each_freshness_and_outcome_has_its_own_amber_label(self):
        """The amber labels are the vocabulary the report prints; each reason maps to exactly one."""
        cases = {"stale": [constituent(freshness="needs_review")],
                 "historical": [constituent(freshness="historical")],
                 "inconclusive": [constituent(outcome="inconclusive")],
                 "source attention": [constituent(kind="source_fidelity", outcome="needs_attention")],
                 "conditional": [constituent(support="conditional")],
                 "premise unavailable": [constituent(support="unavailable")],
                 "compromised independence": [constituent(compromised=True)],
                 "partial": [constituent(),
                             constituent(obligation_id="obl_2", state="missing", outcome=None,
                                         freshness=None)]}
        for label, constituents in cases.items():
            with self.subTest(label=label):
                result = reduce(constituents)
                self.assertEqual(result["state"], "amber")
                self.assertEqual(result["label"], label)

    def test_an_unrecognised_outcome_is_reported_verbatim(self):
        """An outcome the reducer does not know is surfaced rather than silently treated as supported."""
        result = reduce([constituent(outcome="withdrawn")])
        self.assertEqual((result["state"], result["label"]), ("amber", "withdrawn"))

    def test_reasons_are_deduplicated_and_the_first_one_names_the_label(self):
        """Several constituents may raise the same reason; the label is the first distinct reason."""
        result = reduce([constituent(freshness="needs_review"),
                         constituent(obligation_id="obl_2", freshness="needs_review", support="conditional"),
                         constituent(obligation_id="obl_3", state="missing", outcome=None, freshness=None)])
        self.assertEqual(result["label"], "stale")
        self.assertEqual(result["explanation"], "stale; conditional; partial")

    def test_a_non_required_historical_defect_asks_for_a_recheck_qualification(self):
        """A defect that is no longer required still has to be re-qualified, not quietly dropped."""
        result = reduce([constituent(required=False, state="complete", freshness="historical",
                                     outcome="refuted")])
        self.assertEqual(result["state"], "amber")
        self.assertEqual(result["label"], "historical defect against a changed input")
        self.assertEqual(result["explanation"], RECHECK)

    def test_check_and_finding_refs_are_deduplicated_in_first_seen_order(self):
        """One check reached through two obligations is listed once, in the order it was first seen."""
        first = {"collection": "checks", "id": "chk_a", "version": 1}
        second = {"collection": "checks", "id": "chk_b", "version": 1}
        finding = {"collection": "findings", "id": "fnd_1", "version": 2}
        result = reduce([constituent(check_refs=[first, second], finding_refs=[finding]),
                         constituent(obligation_id="obl_2", check_refs=[second, first],
                                     finding_refs=[finding])])
        self.assertEqual(result["check_refs"], [first, second])
        self.assertEqual(result["finding_refs"], [finding])

    def test_two_versions_of_one_check_are_both_kept(self):
        """Deduplication is by pinned version, so a superseding version never hides its predecessor."""
        v1 = {"collection": "checks", "id": "chk_a", "version": 1}
        v2 = {"collection": "checks", "id": "chk_a", "version": 2}
        result = reduce([constituent(check_refs=[v1, v2])])
        self.assertEqual(result["check_refs"], [v1, v2])

    def test_every_indicator_is_carried_into_the_result(self):
        """The independent indicator is reported for every record, and only "disputed" changes the colour."""
        for indicator in INDICATORS:
            with self.subTest(indicator=indicator):
                result = reduce([constituent()], independent=indicator)
                self.assertEqual(result["independent_review"], indicator)
                self.assertEqual(result["state"], "amber" if indicator == "disputed" else "green")

    def test_an_unknown_indicator_is_rejected(self):
        """A typo in the indicator is a programming error, not a new presentation state."""
        with self.assertRaises(ValueError) as caught:
            reduce([constituent()], independent="reviewed")
        self.assertEqual(str(caught.exception), "unknown independent indicator 'reviewed'")

    def test_reduce_does_not_mutate_its_constituents(self):
        """The projection reduces the same constituent objects again; reducing must not disturb them."""
        constituents = [constituent(check_refs=[{"collection": "checks", "id": "chk_a", "version": 1}]),
                        constituent(obligation_id="obl_2", state="missing", outcome=None, freshness=None)]
        before = json.dumps(constituents, sort_keys=True)
        reduce(constituents)
        self.assertEqual(json.dumps(constituents, sort_keys=True), before)


class IdentityTests(unittest.TestCase):
    """Names and ids: every caller has to be able to recompute them."""

    def test_key_of_joins_collection_and_id(self):
        """The assessment key is "collection:id", the same string the report and status index by."""
        self.assertEqual(key_of(R("items", "itm_lem")), "items:itm_lem")
        self.assertEqual(key_of({"collection": "checks", "id": "chk_1", "version": 3}), "checks:chk_1")

    def test_obligation_id_is_a_stable_prefixed_digest(self):
        """The same identity always produces the same "obl_"-prefixed sha256."""
        first = obligation_id("aud_1", R("groups", "grp_lem"), "derivation", "primary")
        second = obligation_id("aud_1", {"id": "grp_lem", "collection": "groups"}, "derivation", "primary")
        self.assertEqual(first, second)
        self.assertTrue(first.startswith("obl_"))
        self.assertEqual(len(first), 68)
        int(first[4:], 16)

    def test_obligation_id_ignores_fields_beyond_collection_and_id(self):
        """A pinned target names the same obligation as the unpinned one."""
        pinned = {"collection": "groups", "id": "grp_lem", "version": 4}
        self.assertEqual(obligation_id("aud_1", pinned, "derivation", "primary"),
                         obligation_id("aud_1", R("groups", "grp_lem"), "derivation", "primary"))

    def test_obligation_id_depends_on_every_component(self):
        """Audit, collection, id, kind and role each change the obligation's identity."""
        base = ("aud_1", R("groups", "grp_lem"), "derivation", "primary")
        variants = [("aud_2", R("groups", "grp_lem"), "derivation", "primary"),
                    ("aud_1", R("arguments", "grp_lem"), "derivation", "primary"),
                    ("aud_1", R("groups", "grp_thm"), "derivation", "primary"),
                    ("aud_1", R("groups", "grp_lem"), "composition", "primary"),
                    ("aud_1", R("groups", "grp_lem"), "derivation", "independent")]
        ids = {obligation_id(*args) for args in [base] + variants}
        self.assertEqual(len(ids), 6)

    def test_obligation_id_separates_its_components(self):
        """Components are encoded as a list, so neighbouring fields cannot run together into one key."""
        self.assertNotEqual(obligation_id("aud_1", R("groups", "a"), "bc", "primary"),
                            obligation_id("aud_1", R("groups", "ab"), "c", "primary"))

    def test_the_module_publishes_the_documented_vocabularies(self):
        """These tuples are the vocabulary the contract, the report and the skills all quote."""
        self.assertEqual(STATES, ("green", "red", "gray", "amber"))
        self.assertEqual(INDICATORS, ("not_required", "pending", "complete", "disputed", "compromised"))
        self.assertEqual(ROLES, ("primary", "independent", "coordinator"))
        self.assertEqual(DEFECT_OUTCOMES, ("gap", "refuted"))
        self.assertEqual(PROOF_KINDS, ("lemma", "proposition", "theorem", "corollary"))
        self.assertEqual(PROOF_CHECK_KINDS, ("derivation", "application", "composition", "case_coverage",
                                             "scope_discharge", "external_source"))
        self.assertEqual(OBLIGATION_KINDS, PROOF_CHECK_KINDS + ("global_consistency", "adversarial",
                                                                "method_interface", "source_fidelity",
                                                                "reconciliation"))


class AssessmentCase(TempCase):
    """Shared plumbing for the database-backed derivations."""

    def complete_fixture(self, name="paper"):
        """A fixture whose process is complete: structure, audit, primary work, independent, reconciled."""
        fixture = self.fixture(name)
        fixture.complete()
        return fixture

    def derive(self, fixture, **kwargs):
        """Derive against the head revision of a closed database."""
        with fixture.open(write=False) as db:
            return derive_assessment(db, audit_id=fixture.audit_id, **kwargs)

    def assert_state(self, result, key, state, label):
        """Assert one presentation state, reporting the explanation when it does not match."""
        entry = result["assessments"][key]
        self.assertEqual((entry["state"], entry["label"]), (state, label), entry["explanation"])
        return entry


class SnapshotTests(AssessmentCase):
    """``Snapshot``: the live records of one revision, with relation, facet and ownership lookups."""

    def test_a_revision_outside_the_live_range_is_rejected(self):
        """Revisions are 1..head; anything else is REVISION_RANGE, never an empty snapshot."""
        fixture = self.complete_fixture()
        with fixture.open(write=False) as db:
            top = db.max_revision()
            for bad in (0, -1, top + 1, "3", None, 1.5):
                with self.subTest(revision=bad):
                    with self.assertRaises(InvalidRequest) as caught:
                        Snapshot(db, bad)
                    self.assertEqual(caught.exception.code, "REVISION_RANGE")
                    self.assertEqual(str(caught.exception), f"revision {bad!r} is not in 1..{top}")

    def test_every_revision_in_range_is_a_snapshot(self):
        """Each accepted revision is addressable, and the first one holds only the paper record."""
        fixture = self.complete_fixture()
        with fixture.open(write=False) as db:
            top = db.max_revision()
            for revision in range(1, top + 1):
                self.assertEqual(Snapshot(db, revision).revision, revision)
            first = Snapshot(db, 1)
            self.assertEqual(len(first.all("papers")), 1)
            self.assertEqual(first.all("items"), [])

    def test_a_snapshot_shows_the_version_that_was_live_at_its_revision(self):
        """An older snapshot keeps the old body; ``get`` and ``live`` agree and later edits are invisible."""
        fixture = self.complete_fixture()
        with fixture.open() as db:
            before = db.max_revision()
            head = db.head("items", "itm_lem")
            fixture.apply(db, [edit("replace", "items", "itm_lem",
                                    dict(head.body, statement={"form": "verbatim", "text": "a_n <= 2"}),
                                    expected=head.version)])
            old, new = Snapshot(db, before), Snapshot(db, db.max_revision())
            self.assertEqual(old.live("items", "itm_lem").body["statement"]["text"], "Lemma 1 text")
            self.assertEqual(new.live("items", "itm_lem").body["statement"]["text"], "a_n <= 2")
            self.assertEqual(old.get(R("items", "itm_lem")).version, 1)
            self.assertEqual(new.get(R("items", "itm_lem")).version, 2)

    def test_get_is_none_for_a_reference_that_is_not_live(self):
        """A dangling or absent reference resolves to None instead of raising."""
        fixture = self.complete_fixture()
        with fixture.open(write=False) as db:
            snap = Snapshot(db, db.max_revision())
            self.assertIsNone(snap.get(None))
            self.assertIsNone(snap.get(R("items", "itm_nope")))
            self.assertIsNone(snap.live("checks", "chk_nope"))
            self.assertEqual(snap.all("repairs"), [])

    def test_relation_lookups_follow_the_stored_references(self):
        """Membership comes from the recorded refs, not from a body scan, and members are sorted by id."""
        fixture = self.complete_fixture()
        with fixture.open(write=False) as db:
            snap = Snapshot(db, db.max_revision())
            self.assertEqual([r.id for r in snap.member_records("arguments_for_target",
                                                                R("items", "itm_lem"))], ["arg_lem"])
            self.assertEqual([r.id for r in snap.member_records("groups_in_argument",
                                                                R("arguments", "arg_thm"))], ["grp_thm"])
            self.assertEqual([r.id for r in snap.member_records("uses_in_group",
                                                                R("groups", "grp_thm"))], ["use_lem_thm"])
            self.assertEqual([r.id for r in snap.member_records("incoming_uses",
                                                                R("items", "itm_thm"))], ["use_lem_thm"])
            self.assertEqual(snap.relation_members("groups_in_argument", R("arguments", "arg_lem")),
                             [("groups", "grp_lem", 1)])
            self.assertEqual(snap.member_records("incoming_uses", R("items", "itm_lem")), [])

    def test_facets_are_the_refs_digests_and_are_memoised_per_version(self):
        """Freshness compares facet digests, so the snapshot must compute exactly what ``refs`` computes."""
        fixture = self.complete_fixture()
        with fixture.open(write=False) as db:
            snap = Snapshot(db, db.max_revision())
            item = snap.live("items", "itm_lem")
            self.assertEqual(snap.facets(item), facet_digests("items", item.body))
            self.assertEqual(sorted(snap.facets(item)), ["full", "proof", "statement"])
            self.assertIs(snap.facets(item), snap.facets(item))

    def test_ref_of_and_pinned_of_differ_only_in_the_version(self):
        """An unpinned ref names a record; a pinned ref names the version a judgment was bound to."""
        fixture = self.complete_fixture()
        with fixture.open() as db:
            head = db.head("items", "itm_lem")
            self.assertEqual(ref_of(head), {"collection": "items", "id": "itm_lem"})
            self.assertEqual(ref_of(head), R("items", "itm_lem"))
            self.assertEqual(pinned_of(head), {"collection": "items", "id": "itm_lem", "version": 1})
            self.assertEqual(key_of(ref_of(head)), key_of(pinned_of(head)))
            fixture.apply(db, [edit("replace", "items", "itm_lem",
                                    dict(head.body, statement={"form": "verbatim", "text": "a_n <= 2"}),
                                    expected=head.version)])
            moved = db.head("items", "itm_lem")
            self.assertEqual(ref_of(moved), ref_of(head))
            self.assertEqual(pinned_of(moved)["version"], 2)

    def test_binding_is_the_stored_binding_of_a_judgment_and_none_for_other_records(self):
        """Only bound judgments carry a binding; a structural record has none."""
        fixture = self.complete_fixture()
        with fixture.open(write=False) as db:
            snap = Snapshot(db, db.max_revision())
            binding = snap.binding(snap.live("checks", "chk_der_lem"))
            self.assertEqual(sorted(binding), ["bindings", "packet_id"])
            self.assertIn("records", binding["bindings"])
            self.assertIsNone(snap.binding(snap.live("items", "itm_lem")))

    def test_the_source_context_digest_follows_the_captured_sources(self):
        """The digest is a function of every live source version and changes when one is recaptured."""
        fixture = self.complete_fixture()
        with fixture.open() as db:
            before = Snapshot(db, db.max_revision()).source_context_digest()
            self.assertEqual(before, Snapshot(db, db.max_revision()).source_context_digest())
            (fixture.source_root / "paper.tex").write_text("% revised\n" + PAPER_TEX, encoding="utf-8")
            sources.capture_sources(db, files=["paper.tex"])
            after = Snapshot(db, db.max_revision()).source_context_digest()
        self.assertNotEqual(before, after)

    def test_ownership_resolves_every_assessed_collection_to_its_major_item(self):
        """Uses, groups and arguments are all owned by the major result they conclude."""
        fixture = self.complete_fixture()
        with fixture.open(write=False) as db:
            snap = Snapshot(db, db.max_revision())
            self.assertEqual(snap.owner_of(R("items", "itm_lem")).id, "itm_lem")
            self.assertEqual(snap.owner_of(R("groups", "grp_lem")).id, "itm_lem")
            self.assertEqual(snap.owner_of(R("arguments", "arg_thm")).id, "itm_thm")
            self.assertEqual(snap.owner_of(R("uses", "use_lem_thm")).id, "itm_thm")
            self.assertIsNone(snap.owner_of(None))
            self.assertIsNone(snap.owner_of(R("uses", "use_nope")))
            self.assertIsNone(snap.owner_of(R("sources", fixture.source_id)))

    def test_kind_of_reads_the_kind_of_the_referenced_record(self):
        """``kind_of`` answers for items and groups and is None for a reference that is not live."""
        fixture = self.complete_fixture()
        with fixture.open(write=False) as db:
            snap = Snapshot(db, db.max_revision())
            self.assertEqual(snap.kind_of(R("items", "itm_lem")), "lemma")
            self.assertEqual(snap.kind_of(R("items", "itm_thm")), "theorem")
            self.assertEqual(snap.kind_of(R("groups", "grp_lem")), "joint")
            self.assertIsNone(snap.kind_of(R("items", "itm_nope")))

    def test_a_family_is_the_statement_plus_the_intermediates_of_its_major_item(self):
        """Intermediate results are assessed with their owner, and an intermediate's family is itself."""
        fixture = self.complete_fixture()
        with fixture.open() as db:
            snap = Snapshot(db, db.max_revision())
            self.assertEqual([r.id for r in snap.family(snap.live("items", "itm_lem"))], ["itm_lem"])
            self.assertEqual(snap.intermediates_of("itm_lem"), [])
            fixture.apply(db, [edit("create", "items", "itm_int", dict(INTERMEDIATE_ITEM))])
            grown = Snapshot(db, db.max_revision())
            self.assertEqual([r.id for r in grown.family(grown.live("items", "itm_lem"))],
                             ["itm_lem", "itm_int"])
            self.assertEqual([r.id for r in grown.intermediates_of("itm_lem")], ["itm_int"])
            self.assertEqual([r.id for r in grown.family(grown.live("items", "itm_int"))], ["itm_int"])
            self.assertEqual(grown.major_of(R("items", "itm_int")).id, "itm_lem")


class ShapeTests(AssessmentCase):
    """The derived result surface: the keys every caller reads, and the two error codes."""

    def test_derive_assessment_returns_the_documented_keys(self):
        """The result surface is fixed; a key that appears or disappears breaks status and the report."""
        result = self.derive(self.complete_fixture())
        self.assertEqual(set(result), RESULT_KEYS)

    def test_each_derived_record_carries_its_documented_keys(self):
        """Obligations, constituents, judgments and assessments all have a fixed shape."""
        result = self.derive(self.complete_fixture())
        for obligation in result["obligations"]:
            self.assertEqual(set(obligation), OBLIGATION_KEYS)
            self.assertEqual(set(obligation["assessment"]), ASSESSMENT_KEYS)
        for c in result["constituents"].values():
            self.assertEqual(set(c), CONSTITUENT_KEYS)
        for judgment in result["judgments"].values():
            self.assertEqual(set(judgment), JUDGMENT_KEYS)
        for key, entry in result["assessments"].items():
            extra = {"availability", "local_state", "local_label"} if key.startswith(("items:", "parts:", "uses:")) else set()
            self.assertEqual(set(entry), ASSESSMENT_KEYS | extra)

    def test_derive_full_hands_back_the_live_indexes_it_used(self):
        """The projection reuses the derivation, so the result must expose the very same objects."""
        fixture = self.complete_fixture()
        with fixture.open(write=False) as db:
            derivation, result = derive_full(db, audit_id=fixture.audit_id)
            self.assertIs(result["constituents"], derivation.constituents)
            self.assertIs(result["judgments"], derivation.judgments)
            self.assertIs(result["routes"], derivation.routes)
            self.assertEqual(derivation.snap.revision, result["revision"])
            self.assertEqual(derivation.audit.id, result["audit_id"])
            self.assertEqual(derive_assessment(db, audit_id=fixture.audit_id), result)

    def test_derive_defaults_to_the_head_revision_and_accepts_an_older_one(self):
        """Without a revision the head is derived; with one, that snapshot is derived instead."""
        fixture = self.complete_fixture()
        with fixture.open() as db:
            complete_revision = db.max_revision()
            fixture.apply(db, [edit("create", "items", "itm_ass", dict(ASSUMPTION_ITEM))])
            head = derive_assessment(db, audit_id=fixture.audit_id)
            old = derive_assessment(db, audit_id=fixture.audit_id, revision=complete_revision)
            self.assertEqual(head["revision"], db.max_revision())
            self.assertEqual(old["revision"], complete_revision)
            self.assertNotEqual(head["revision"], old["revision"])

    def test_an_audit_that_is_not_live_at_the_revision_is_rejected(self):
        """AUDIT_UNKNOWN names the audit and the revision; nothing is derived for a guess."""
        fixture = self.complete_fixture()
        with fixture.open(write=False) as db:
            revision = db.max_revision()
            with self.assertRaises(InvalidRequest) as caught:
                derive_assessment(db, audit_id="aud_nope")
            self.assertEqual(caught.exception.code, "AUDIT_UNKNOWN")
            self.assertEqual(str(caught.exception), f"audit aud_nope is not live at revision {revision}")

    def test_an_audit_registered_later_is_unknown_at_an_earlier_revision(self):
        """The audit has to be live *at that revision*, not merely somewhere in the history."""
        fixture = self.fixture()
        fixture.structure()
        with fixture.open(write=False) as db:
            before_audit = db.max_revision()
        fixture.audit()
        with fixture.open(write=False) as db:
            self.assertEqual(derive_assessment(db, audit_id="aud_1")["audit_id"], "aud_1")
            with self.assertRaises(InvalidRequest) as caught:
                derive_assessment(db, audit_id="aud_1", revision=before_audit)
            self.assertEqual(caught.exception.code, "AUDIT_UNKNOWN")

    def test_without_an_audit_the_snapshot_is_overview_mode_with_nothing_derived(self):
        """Structure alone is not an assessment: no scope, no obligations, no judgments, no colours."""
        fixture = self.fixture()
        fixture.structure()
        with fixture.open(write=False) as db:
            result = derive_assessment(db)
        self.assertEqual(set(result), RESULT_KEYS)
        self.assertEqual(result["mode"], "overview")
        self.assertIsNone(result["audit_id"])
        self.assertEqual(result["scope"], {"mode": "overview", "target_refs": [], "exclusions": []})
        self.assertEqual(result["statements"], [])
        self.assertEqual(result["obligations"], [])
        self.assertEqual(result["assessments"], {})
        self.assertEqual(result["judgments"], {})
        self.assertEqual(result["support"], {})
        self.assertEqual(result["independent"], {})
        self.assertEqual(result["audits"], [])
        self.assertIs(result["progress"]["process_complete"], False)

    def test_the_scope_block_repeats_the_audit_targets_and_exclusions(self):
        """A reader can see what was in scope without loading the audit record itself."""
        fixture = self.complete_fixture()
        result = self.derive(fixture)
        self.assertEqual(result["mode"], "focused")
        self.assertEqual(result["scope"], {"mode": "focused", "target_refs": list(fixture.ITEM_REFS),
                                           "exclusions": []})
        self.assertEqual(result["statements"], list(fixture.ITEM_REFS))
        self.assertEqual(result["audits"], ["aud_1"])
        self.assertIsNone(result["published_revision"])
        self.assertEqual(result["problems"], [])

    def test_routes_and_route_records_name_the_work_behind_each_statement(self):
        """The route is the argument list; the route records are every record the colour depends on."""
        result = self.derive(self.complete_fixture())
        self.assertEqual(result["routes"], {"items:itm_lem": ["arg_lem"], "items:itm_thm": ["arg_thm"]})
        self.assertEqual(result["route_records"]["items:itm_lem"], ["arguments:arg_lem", "groups:grp_lem"])
        self.assertEqual(result["route_records"]["items:itm_thm"],
                         ["arguments:arg_thm", "groups:grp_thm", "uses:use_lem_thm"])


class ObligationTests(AssessmentCase):
    """Obligations are the required-judgment set derived from the structure and the audit."""

    def test_the_audit_derives_exactly_the_required_judgment_set(self):
        """Eleven required obligations plus the three declared global tasks, and nothing else."""
        result = self.derive(self.complete_fixture())
        self.assertEqual(obligation_tuples(result), FIXTURE_OBLIGATIONS)
        self.assertEqual(len(result["obligations"]), 16)
        self.assertEqual(sum(1 for o in result["obligations"] if o["required"]), 13)
        self.assertEqual(result["progress"]["required_obligations"], 13)

    def test_every_obligation_id_is_the_hash_of_its_own_identity(self):
        """A caller can recompute any obligation id from the audit, the target, the kind and the role."""
        fixture = self.complete_fixture()
        result = self.derive(fixture)
        for obligation in result["obligations"]:
            self.assertEqual(obligation["id"], obligation_id(fixture.audit_id, obligation["target"],
                                                             obligation["kind"], obligation["role"]))
        self.assertEqual(len({o["id"] for o in result["obligations"]}), len(result["obligations"]))

    def test_obligations_are_listed_in_id_order_and_indexed_by_target(self):
        """The list order is the sorted id order, and ``by_target`` finds every obligation of a record."""
        result = self.derive(self.complete_fixture())
        ids = [o["id"] for o in result["obligations"]]
        self.assertEqual(ids, sorted(ids))
        indexed = sorted(sum(result["by_target"].values(), []))
        self.assertEqual(indexed, sorted(ids))
        for key, oids in result["by_target"].items():
            self.assertEqual(oids, sorted(oids))
            for oid in oids:
                self.assertEqual(key_of(result["constituents"][oid]["target"]), key)

    def test_a_global_task_declared_not_applicable_is_an_obligation_but_is_not_required(self):
        """The audit still has to answer for it; it just does not hold the process back."""
        result = self.derive(self.complete_fixture())
        tasks = [o for o in result["obligations"] if o["target"]["collection"] == "audits"]
        self.assertEqual({o["kind"] for o in tasks}, {task["kind"] for task in GLOBAL_TASKS})
        for task in tasks:
            self.assertIs(task["required"], False)
            self.assertEqual(task["state"], "missing")
            self.assertIs(task["satisfied"], False)
            self.assertEqual(task["explanation"], f"no primary {task['kind']} work recorded")

    def test_the_audit_record_itself_stays_gray(self):
        """The audit collects only global tasks; with none recorded its own assessment is unassessed."""
        result = self.derive(self.complete_fixture())
        entry = self.assert_state(result, "audits:aud_1", "gray", "unassessed")
        self.assertEqual(entry["explanation"], NOTHING_ASSESSED)

    def test_a_satisfied_obligation_reports_its_judgment_and_its_own_assessment(self):
        """Each obligation carries the check that answers it and the colour that check produces alone."""
        result = self.derive(self.complete_fixture())
        derivation = next(o for o in result["obligations"]
                          if o["target"]["id"] == "grp_lem" and o["kind"] == "derivation")
        self.assertEqual(derivation["state"], "complete")
        self.assertIs(derivation["satisfied"], True)
        self.assertEqual(derivation["freshness"], "current")
        self.assertEqual(derivation["outcome"], "supported")
        self.assertEqual(derivation["check_refs"], [{"collection": "checks", "id": "chk_der_lem",
                                                     "version": 1}])
        self.assertEqual(derivation["explanation"], "primary derivation complete; outcome supported")
        self.assertEqual((derivation["assessment"]["state"], derivation["assessment"]["label"]),
                         ("green", "supported"))

    def test_independent_and_coordinator_obligations_have_no_colour_of_their_own(self):
        """Their own assessment is gray because colour follows primary work only."""
        result = self.derive(self.complete_fixture())
        for obligation in result["obligations"]:
            if obligation["role"] == "primary":
                continue
            with self.subTest(kind=obligation["kind"], role=obligation["role"]):
                self.assertEqual(obligation["state"], "complete")
                self.assertIs(obligation["satisfied"], True)
                self.assertEqual(obligation["assessment"]["state"], "gray")

    def test_adding_a_use_adds_application_and_consumed_source_fidelity(self):
        """A new premise requires both its application and comparison with its recorded source."""
        fixture = self.complete_fixture()
        before = self.derive(fixture)
        with fixture.open() as db:
            fixture.apply(db, [edit("create", "items", "itm_ass", dict(ASSUMPTION_ITEM)),
                               edit("create", "uses", "use_ass_lem", dict(USE_ASS_LEM))])
            after = derive_assessment(db, audit_id=fixture.audit_id)
        self.assertEqual(obligation_tuples(after) - obligation_tuples(before),
                         {("uses:use_ass_lem", "application", "primary", True),
                          ("items:itm_ass", "source_fidelity", "primary", True)})
        self.assertEqual(obligation_tuples(before) - obligation_tuples(after), set())
        self.assertEqual(after["progress"]["required_obligations"], 15)
        self.assertEqual(after["route_records"]["items:itm_lem"],
                         ["arguments:arg_lem", "groups:grp_lem", "uses:use_ass_lem"])

    def test_the_new_obligation_is_unassessed_and_is_named_as_missing_by_the_consumer(self):
        """The new use is gray, and the statement that depends on it reports the outstanding id."""
        fixture = self.complete_fixture()
        with fixture.open() as db:
            fixture.apply(db, [edit("create", "items", "itm_ass", dict(ASSUMPTION_ITEM)),
                               edit("create", "uses", "use_ass_lem", dict(USE_ASS_LEM))])
            result = derive_assessment(db, audit_id=fixture.audit_id)
        expected = obligation_id(fixture.audit_id, R("uses", "use_ass_lem"), "application", "primary")
        entry = self.assert_state(result, "uses:use_ass_lem", "gray", "unassessed")
        self.assertEqual(entry["missing_obligation_ids"], [expected])
        self.assertIn(expected, result["assessments"]["items:itm_lem"]["missing_obligation_ids"])
        self.assertEqual(result["assessments"]["items:itm_thm"]["missing_obligation_ids"], [])

    def test_an_exclusion_removes_a_statement_and_its_obligations_from_the_audit(self):
        """An excluded target keeps its structure but stops generating required work for this audit."""
        fixture = self.complete_fixture()
        with fixture.open() as db:
            fixture.apply(db, [edit("create", "audits", "aud_3", dict(
                EXCLUDING_AUDIT, paper_id=fixture.paper_id,
                global_tasks=[dict(task) for task in GLOBAL_TASKS]))], *fixture.ITEMS, mode="primary")
            result = derive_assessment(db, audit_id="aud_3")
        self.assertEqual(result["statements"], [R("items", "itm_thm")])
        self.assertEqual(obligation_tuples(result), {
            ("arguments:arg_thm", "composition", "primary", True),
            ("groups:grp_thm", "derivation", "primary", True),
            ("uses:use_lem_thm", "application", "primary", True),
            ("items:itm_thm", "source_fidelity", "primary", True),
            ("target_specs:tgt_thm", "source_fidelity", "primary", True),
            ("audits:aud_3", "global_consistency", "primary", False),
            ("audits:aud_3", "adversarial", "primary", False),
            ("audits:aud_3", "method_interface", "primary", False)})
        self.assertEqual(result["independent"], {"items:itm_thm": "not_required"})
        self.assertNotIn("items:itm_lem", result["assessments"])

    def test_checks_are_scoped_to_their_audit_while_observations_are_not(self):
        """A second audit sees no judgments from the first, but source comparisons remain facts."""
        fixture = self.complete_fixture()
        with fixture.open() as db:
            fixture.apply(db, [edit("create", "audits", "aud_3", dict(
                EXCLUDING_AUDIT, paper_id=fixture.paper_id,
                global_tasks=[dict(task) for task in GLOBAL_TASKS]))], *fixture.ITEMS, mode="primary")
            result = derive_assessment(db, audit_id="aud_3")
        self.assertEqual(result["judgments"], {})
        fidelity = next(o for o in result["obligations"] if o["kind"] == "source_fidelity" and o["target"] == R("items", "itm_thm"))
        self.assertIs(fidelity["satisfied"], True)
        self.assertEqual(fidelity["check_refs"], [{"collection": "observations", "id": "obs_thm",
                                                   "version": 1}])
        self.assertEqual(result["progress"]["completed_current_obligations"], 2)

    def test_an_audit_target_that_cannot_be_assessed_is_reported_as_a_problem(self):
        """An intermediate result is never an audit target; the derivation says so instead of guessing."""
        fixture = self.complete_fixture()
        with fixture.open() as db:
            fixture.apply(db, [edit("create", "items", "itm_int", dict(INTERMEDIATE_ITEM))])
            fixture.apply(db, [edit("create", "audits", "aud_2", dict(
                INTERMEDIATE_AUDIT, paper_id=fixture.paper_id,
                global_tasks=[dict(task) for task in GLOBAL_TASKS]))], *fixture.ITEMS, mode="primary")
            result = derive_assessment(db, audit_id="aud_2")
        self.assertEqual(result["problems"], ["audit target items:itm_int is an intermediate result"])
        self.assertEqual(result["statements"], [])
        self.assertEqual(sorted(result["assessments"]), ["audits:aud_2"])
        self.assertIs(result["progress"]["process_complete"], False)


class StageTests(AssessmentCase):
    """The fixture stages are the documented progression from registered structure to a complete audit."""

    def test_a_registered_audit_starts_with_every_obligation_missing(self):
        """Before any judgment exists the statements are gray and no required obligation is satisfied."""
        fixture = self.fixture()
        fixture.audit()
        result = self.derive(fixture)
        self.assertEqual(result["progress"], {"process_complete": False, "required_obligations": 13,
                                              "completed_current_obligations": 0, "draft_checks": 0,
                                              "major_results": 2, "source_unbound_items": 0})
        self.assert_state(result, "items:itm_lem", "gray", "unassessed")
        self.assert_state(result, "items:itm_thm", "gray", "unassessed")
        self.assertEqual(result["independent"], {"items:itm_lem": "pending", "items:itm_thm": "pending"})
        self.assertEqual(result["support"], {"items:itm_lem": "conditional", "items:itm_thm": "conditional"})

    def test_primary_work_alone_leaves_the_independent_obligations_outstanding(self):
        """Seven of eleven obligations are satisfied; the colour waits for the independent round."""
        fixture = self.fixture()
        fixture.primary()
        result = self.derive(fixture)
        self.assertEqual(result["progress"]["completed_current_obligations"], 9)
        self.assertIs(result["progress"]["process_complete"], False)
        self.assertEqual(result["independent"], {"items:itm_lem": "pending", "items:itm_thm": "pending"})
        outstanding = {(key_of(o["target"]), o["kind"], o["role"]) for o in result["obligations"]
                       if o["required"] and not o["satisfied"]}
        self.assertEqual(outstanding, {("arguments:arg_lem", "composition", "independent"),
                                       ("arguments:arg_thm", "composition", "independent"),
                                       ("items:itm_lem", "reconciliation", "coordinator"),
                                       ("items:itm_thm", "reconciliation", "coordinator")})

    def test_a_reconciled_audit_is_complete_and_both_results_are_green(self):
        """The complete fixture: every obligation satisfied, both indicators complete, support available."""
        result = self.derive(self.complete_fixture())
        self.assertEqual(result["progress"], PROGRESS_COMPLETE)
        for key in ("items:itm_lem", "items:itm_thm", "arguments:arg_lem", "groups:grp_thm",
                    "uses:use_lem_thm"):
            with self.subTest(key=key):
                entry = self.assert_state(result, key, "green", "supported")
                self.assertEqual(entry["explanation"], GREEN)
        self.assertEqual(result["independent"], {"items:itm_lem": "complete", "items:itm_thm": "complete"})
        self.assertEqual(result["support"], {"items:itm_lem": "available", "items:itm_thm": "available"})
        self.assertEqual(result["findings"], {"open": [], "resolved": [], "superseded": [], "refs": []})
        self.assertEqual(result["source_limits"], [])

    def test_a_draft_judgment_is_counted_but_does_not_satisfy_its_obligation(self):
        """A substantive draft turns the record amber "partial" and is reported as a draft check."""
        fixture = self.fixture()
        fixture.audit()
        with fixture.open() as db:
            fixture.apply(db, [fixture.check_edit("chk_draft", R("groups", "grp_lem"), "derivation",
                                                  state="draft", outcome=None)], *fixture.ITEMS,
                          mode="primary")
            result = derive_assessment(db, audit_id=fixture.audit_id)
        self.assertEqual(result["progress"]["draft_checks"], 1)
        self.assertEqual(result["progress"]["completed_current_obligations"], 0)
        self.assertEqual(result["judgments"]["checks:chk_draft"]["state"], "draft")
        self.assertIs(result["judgments"]["checks:chk_draft"]["substantive"], True)
        self.assert_state(result, "groups:grp_lem", "amber", "partial")
        self.assert_state(result, "items:itm_lem", "amber", "partial")

    def test_the_assessed_records_are_the_statements_and_their_routes(self):
        """Every record a colour is derived for is a statement, one of its route records, or the audit."""
        result = self.derive(self.complete_fixture())
        self.assertEqual(sorted(result["assessments"]),
                         ["arguments:arg_lem", "arguments:arg_thm", "audits:aud_1", "groups:grp_lem",
                          "groups:grp_thm", "items:itm_lem", "items:itm_thm", "uses:use_lem_thm"])


class FreshnessTests(AssessmentCase):
    """Freshness is derived by comparing a judgment's stored binding with the snapshot."""

    def test_a_superseded_judgment_is_historical_without_consulting_its_binding(self):
        """Supersession is decided by the record graph, not by the binding."""
        fixture = self.complete_fixture()
        with fixture.open(write=False) as db:
            snap = Snapshot(db, db.max_revision())
            check = snap.live("checks", "chk_der_lem")
            info = judgment_freshness(snap, check, superseded=True)
        self.assertEqual(info, {"freshness": "historical", "reused": False, "unbound": False,
                                "changes": None, "context_changed": False})

    def test_an_untouched_snapshot_leaves_every_judgment_current(self):
        """Nothing changed since the judgments were bound, so all of them are current and bound."""
        result = self.derive(self.complete_fixture())
        self.assertEqual(set(freshness_of(result).values()), {"current"})
        for info in result["judgments"].values():
            self.assertIs(info["unbound"], False)
            self.assertIs(info["reused"], False)
            self.assertIs(info["superseded"], False)

    def test_a_judgment_of_a_record_that_changed_version_is_historical(self):
        """When the judged record itself moves on, its judgment is about a version that is gone."""
        fixture = self.complete_fixture()
        with fixture.open() as db:
            head = db.head("items", "itm_lem")
            fixture.apply(db, [edit("replace", "items", "itm_lem",
                                    dict(head.body, statement={"form": "verbatim", "text": "a_n <= 2"}),
                                    expected=head.version)])
            result = derive_assessment(db, audit_id=fixture.audit_id)
        fidelity = next(o for o in result["obligations"]
                        if o["kind"] == "source_fidelity" and o["target"]["id"] == "itm_lem")
        self.assertEqual(fidelity["freshness"], "historical")
        self.assertIs(fidelity["satisfied"], False)
        self.assertEqual(fidelity["explanation"],
                         "primary source_fidelity complete; outcome supported; freshness historical")

    def test_a_changed_prerequisite_stales_every_judgment_that_consumed_it(self):
        """The changed-prerequisite port: editing the lemma stales the theorem's judgments too."""
        fixture = self.complete_fixture()
        with fixture.open() as db:
            complete_revision = db.max_revision()
            head = db.head("items", "itm_lem")
            fixture.apply(db, [edit("replace", "items", "itm_lem",
                                    dict(head.body, statement={"form": "verbatim", "text": "a_n <= 2"}),
                                    expected=head.version)])
            result = derive_assessment(db, audit_id=fixture.audit_id)
            older = derive_assessment(db, audit_id=fixture.audit_id, revision=complete_revision)
        self.assertEqual(set(freshness_of(result).values()), {"needs_review"})
        self.assertEqual(len(result["judgments"]), 7)
        self.assert_state(result, "items:itm_lem", "amber", "historical")
        for key in ("items:itm_thm", "uses:use_lem_thm", "arguments:arg_thm", "groups:grp_thm"):
            with self.subTest(key=key):
                entry = self.assert_state(result, key, "amber", "stale")
                self.assertEqual(entry["explanation"], "stale; conditional")
        # Stale independent evidence also reopens both reconciliations; only
        # the theorem's unchanged source comparison remains complete.
        self.assertEqual(result["progress"]["completed_current_obligations"], 2)
        self.assertIs(result["progress"]["process_complete"], False)
        self.assertEqual(result["support"], {"items:itm_lem": "conditional", "items:itm_thm": "conditional"})
        self.assertEqual(older["progress"], PROGRESS_COMPLETE)
        self.assertEqual(older["assessments"]["items:itm_thm"]["state"], "green")

    def test_a_staled_statement_names_the_obligations_that_have_to_be_redone(self):
        """The consumer lists the obligations whose judgments stopped being current, and only those."""
        fixture = self.complete_fixture()
        with fixture.open() as db:
            head = db.head("items", "itm_lem")
            fixture.apply(db, [edit("replace", "items", "itm_lem",
                                    dict(head.body, statement={"form": "verbatim", "text": "a_n <= 2"}),
                                    expected=head.version)])
            result = derive_assessment(db, audit_id=fixture.audit_id)
        expected = sorted(obligation_id(fixture.audit_id, target, kind, role) for target, kind, role in (
            (R("arguments", "arg_thm"), "composition", "primary"),
            (R("arguments", "arg_thm"), "composition", "independent"),
            (R("groups", "grp_thm"), "derivation", "primary"),
            (R("uses", "use_lem_thm"), "application", "primary"),
            (R("items", "itm_thm"), "reconciliation", "coordinator")))
        self.assertEqual(result["assessments"]["items:itm_thm"]["missing_obligation_ids"], expected)
        # The theorem's own statement did not move, so its source comparison is still current.
        fidelity = obligation_id(fixture.audit_id, R("items", "itm_thm"), "source_fidelity", "primary")
        self.assertNotIn(fidelity, result["assessments"]["items:itm_thm"]["missing_obligation_ids"])

    def test_an_unrelated_new_record_does_not_stale_anything(self):
        """Freshness follows the bound neighbourhood; adding an unused intermediate touches nothing."""
        fixture = self.complete_fixture()
        with fixture.open() as db:
            fixture.apply(db, [edit("create", "items", "itm_int", dict(INTERMEDIATE_ITEM))])
            result = derive_assessment(db, audit_id=fixture.audit_id)
        self.assertEqual(set(freshness_of(result).values()), {"current"})
        self.assertEqual(result["progress"], PROGRESS_COMPLETE)


class ContextTests(AssessmentCase):
    """The source context: which captured sources the judgments were made against."""

    def test_the_derived_context_reports_the_snapshot_digest(self):
        """``context`` carries the digest of the live sources and a count of older-context judgments."""
        fixture = self.complete_fixture()
        with fixture.open(write=False) as db:
            snap = Snapshot(db, db.max_revision())
            result = derive_assessment(db, audit_id=fixture.audit_id)
        self.assertEqual(result["context"], {"source_context_digest": snap.source_context_digest(),
                                             "judgments_in_older_context": 0})

    def test_a_judgment_stores_the_source_context_it_was_made_in(self):
        """The binding records the digest, which is what makes an older-context judgment detectable."""
        fixture = self.complete_fixture()
        with fixture.open(write=False) as db:
            snap = Snapshot(db, db.max_revision())
            binding = snap.binding(snap.live("checks", "chk_der_lem"))
            self.assertIsNone(binding["bindings"]["source_context_digest"])
            self.assertTrue(any(row["ref"]["collection"] == "sources" for row in binding["bindings"]["records"]))

    # REGRESSION: judgment_freshness used to read the stored context digest off the
    # {"packet_id", "bindings"} wrapper Database.binding() returns instead of off the binding itself,
    # so context_changed could never become True and judgments_in_older_context was stuck at zero for
    # every database. The digest is now read from the same unwrapped binding binding_changes gets.
    def test_a_judgment_bound_in_an_older_source_context_is_reported(self):
        """Recapturing a changed source must mark the judgments made against the older context."""
        fixture = self.complete_fixture()
        with fixture.open() as db:
            before = Snapshot(db, db.max_revision()).source_context_digest()
            (fixture.source_root / "paper.tex").write_text("% revised\n" + PAPER_TEX, encoding="utf-8")
            sources.capture_sources(db, files=["paper.tex"])
            snap = Snapshot(db, db.max_revision())
            check = snap.live("checks", "chk_der_lem")
            self.assertIsNone(snap.binding(check)["bindings"]["source_context_digest"])
            self.assertNotEqual(snap.source_context_digest(), before)
            info = judgment_freshness(snap, check, superseded=False)
            result = derive_assessment(db, audit_id=fixture.audit_id)
        self.assertIs(info["context_changed"], True)
        self.assertEqual(result["context"]["judgments_in_older_context"], len(result["judgments"]))


class DefectTests(AssessmentCase):
    """An unsupported or refuted judgment pulls its target, and its consumers, out of green."""

    def test_a_gap_turns_the_step_and_its_statement_red(self):
        """A completed derivation gap is a current defect: the group, the argument and the item are red."""
        fixture = self.complete_fixture()
        with fixture.open() as db:
            fixture.apply(db, gap_edits(fixture, db), *fixture.ITEMS, mode="primary")
            result = derive_assessment(db, audit_id=fixture.audit_id)
        for key in ("groups:grp_lem", "arguments:arg_lem", "items:itm_lem"):
            with self.subTest(key=key):
                entry = self.assert_state(result, key, "red", "defect")
                self.assertEqual(entry["explanation"],
                                 "current completed derivation assessment identifies gap")

    def test_a_gap_makes_the_consumer_amber_and_its_premise_unavailable(self):
        """The theorem is not refuted, but the lemma it consumes no longer supports it."""
        fixture = self.complete_fixture()
        with fixture.open() as db:
            fixture.apply(db, gap_edits(fixture, db), *fixture.ITEMS, mode="primary")
            result = derive_assessment(db, audit_id=fixture.audit_id)
        for key in ("items:itm_thm", "uses:use_lem_thm"):
            with self.subTest(key=key):
                entry = self.assert_state(result, key, "amber", "premise unavailable")
                self.assertEqual(entry["explanation"], "premise unavailable")
        self.assertEqual(result["support"], {"items:itm_lem": "unavailable", "items:itm_thm": "unavailable"})

    def test_the_finding_is_reported_on_the_defective_record_and_on_the_affected_use(self):
        """A finding reaches a statement through its target, its checks and the uses it names."""
        fixture = self.complete_fixture()
        with fixture.open() as db:
            fixture.apply(db, gap_edits(fixture, db), *fixture.ITEMS, mode="primary")
            result = derive_assessment(db, audit_id=fixture.audit_id)
        finding = {"collection": "findings", "id": "fnd_1", "version": 1}
        self.assertEqual(result["findings"]["open"], [finding])
        self.assertEqual(result["findings"]["refs"], [{"ref": finding, "category": "proof_gap",
                                                       "target": R("groups", "grp_lem"),
                                                       "lifecycle": "open"}])
        self.assertEqual(result["assessments"]["items:itm_lem"]["finding_refs"], [finding])
        self.assertEqual(result["assessments"]["items:itm_thm"]["finding_refs"], [finding])

    def test_a_completed_audit_may_report_a_defect_and_still_be_process_complete(self):
        """process_complete is about process: the gap is recorded, so the obligation is answered."""
        fixture = self.complete_fixture()
        with fixture.open() as db:
            fixture.apply(db, gap_edits(fixture, db), *fixture.ITEMS, mode="primary")
            result = derive_assessment(db, audit_id=fixture.audit_id)
        self.assertEqual(result["progress"], PROGRESS_COMPLETE)
        derivation = next(o for o in result["obligations"]
                          if o["target"]["id"] == "grp_lem" and o["kind"] == "derivation")
        self.assertIs(derivation["satisfied"], True)
        self.assertEqual(derivation["outcome"], "gap")

    def test_a_refuted_application_is_a_defect_of_the_consumer_not_of_the_supplier(self):
        """A use that cannot carry the lemma refutes the theorem's route; the lemma stays green."""
        fixture = self.complete_fixture()
        with fixture.open() as db:
            fixture.apply(db, [fixture.check_edit("chk_app2", R("uses", "use_lem_thm"), "application",
                                                  outcome="refuted", supersedes=fixture.pin(db, "checks", "chk_app"))],
                          *fixture.ITEMS, mode="primary")
            result = derive_assessment(db, audit_id=fixture.audit_id)
        for key in ("uses:use_lem_thm", "groups:grp_thm", "arguments:arg_thm", "items:itm_thm"):
            with self.subTest(key=key):
                entry = self.assert_state(result, key, "red", "defect")
                self.assertEqual(entry["explanation"],
                                 "current completed application assessment identifies refuted")
        self.assert_state(result, "items:itm_lem", "green", "supported")
        self.assertEqual(result["support"], {"items:itm_lem": "available", "items:itm_thm": "unavailable"})

    def test_unsuperseded_conflicting_judgments_remain_disputed(self):
        """Both current outcomes remain visible; insertion order is not a resolution."""
        fixture = self.complete_fixture()
        with fixture.open() as db:
            fixture.apply(db, [fixture.check_edit("chk_app2", R("uses", "use_lem_thm"), "application",
                                                  outcome="refuted")], *fixture.ITEMS, mode="primary")
            result = derive_assessment(db, audit_id=fixture.audit_id)
        application = next(o for o in result["obligations"] if o["target"]["id"] == "use_lem_thm")
        self.assertEqual(application["outcome"], "inconclusive")
        self.assertFalse(application["satisfied"])
        self.assertEqual(application["assessment"]["label"], "disputed")
        self.assertFalse(result["progress"]["process_complete"])
        self.assertEqual([ref["id"] for ref in application["check_refs"]], ["chk_app", "chk_app2"])

    def test_an_inconclusive_composition_is_amber_not_red(self):
        """An inconclusive result is a qualified answer, not a defect."""
        fixture = self.fixture()
        fixture.audit(independent_required=False)
        fixture.primary()
        with fixture.open() as db:
            fixture.apply(db, [fixture.check_edit("chk_comp_thm2", R("arguments", "arg_thm"), "composition",
                                                  outcome="inconclusive", evidence=["anc_thm_proof"],
                                                  supersedes=fixture.pin(db, "checks", "chk_comp_thm"))],
                          *fixture.ITEMS, mode="primary")
            result = derive_assessment(db, audit_id=fixture.audit_id)
        for key in ("arguments:arg_thm", "items:itm_thm"):
            with self.subTest(key=key):
                entry = self.assert_state(result, key, "amber", "inconclusive")
                self.assertEqual(entry["explanation"], "inconclusive")
        self.assert_state(result, "items:itm_lem", "green", "supported")
        self.assertEqual(result["support"]["items:itm_thm"], "conditional")

    def test_a_defective_statement_lists_every_judgment_it_rests_on(self):
        """The check list of a statement is the deduplicated evidence behind its colour."""
        fixture = self.complete_fixture()
        with fixture.open() as db:
            fixture.apply(db, [fixture.check_edit("chk_app2", R("uses", "use_lem_thm"), "application",
                                                  outcome="refuted")], *fixture.ITEMS, mode="primary")
            result = derive_assessment(db, audit_id=fixture.audit_id)
        refs = result["assessments"]["items:itm_thm"]["check_refs"]
        self.assertEqual(len(refs), len({(r["collection"], r["id"], r["version"]) for r in refs}))
        by_collection = {}
        for ref in refs:
            by_collection.setdefault(ref["collection"], []).append(ref["id"])
        self.assertEqual(sorted(by_collection), ["checks", "observations", "reconciliations"])
        self.assertEqual(by_collection["observations"], ["obs_thm"])
        self.assertEqual(by_collection["reconciliations"], ["rec_thm"])
        # The independent check is named by the review response, so only its role is predictable.
        independent = [key_of(info["ref"]) for info in result["judgments"].values()
                       if info["role"] == "independent" and info["target"]["id"] == "arg_thm"]
        self.assertEqual(sorted(by_collection["checks"]),
                         sorted(["chk_comp_thm", "chk_der_thm", "chk_app", "chk_app2"]
                                + [key.split(":", 1)[1] for key in independent]))


class RepairTests(AssessmentCase):
    """The restricted-repair port: proposing a repair may not revalidate anything by itself."""

    def record_gap_and_repair_statement(self, fixture, db):
        """Record the gap, its finding, and the separately identified proposed_repair statement."""
        fixture.apply(db, gap_edits(fixture, db), *fixture.ITEMS, mode="primary")
        fixture.apply(db, [edit("create", "items", "itm_lem_r", dict(REPAIR_ITEM))])

    def test_a_restricted_statement_repair_changes_no_assessment(self):
        """Recording the repair leaves every colour, explanation and support value exactly as it was."""
        fixture = self.complete_fixture()
        with fixture.open() as db:
            self.record_gap_and_repair_statement(fixture, db)
            before = derive_assessment(db, audit_id=fixture.audit_id)
            fixture.apply(db, [edit("create", "repairs", "rep_1", dict(RESTRICTED_REPAIR))],
                          *fixture.ITEMS, mode="primary")
            after = derive_assessment(db, audit_id=fixture.audit_id)
        self.assertEqual(after["assessments"], before["assessments"])
        self.assertEqual(after["support"], before["support"])
        self.assertEqual(after["progress"], before["progress"])
        self.assertEqual(obligation_tuples(after), obligation_tuples(before))
        self.assertEqual(after["statements"], before["statements"])

    def test_a_restricted_statement_repair_leaves_the_defect_and_the_finding_standing(self):
        """The lemma is still red and the finding is still open until the repair is actually carried out."""
        fixture = self.complete_fixture()
        with fixture.open() as db:
            self.record_gap_and_repair_statement(fixture, db)
            fixture.apply(db, [edit("create", "repairs", "rep_1", dict(RESTRICTED_REPAIR))],
                          *fixture.ITEMS, mode="primary")
            result = derive_assessment(db, audit_id=fixture.audit_id)
        self.assert_state(result, "items:itm_lem", "red", "defect")
        self.assertEqual([ref["id"] for ref in result["findings"]["open"]], ["fnd_1"])
        self.assertEqual({j["freshness"] for j in result["judgments"].values() if not j["superseded"]}, {"current"})

    def test_carrying_the_restriction_into_the_statement_stales_the_judgments(self):
        """Only editing the statement moves anything, and then nothing is silently revalidated."""
        fixture = self.complete_fixture()
        with fixture.open() as db:
            self.record_gap_and_repair_statement(fixture, db)
            fixture.apply(db, [edit("create", "repairs", "rep_1", dict(RESTRICTED_REPAIR))],
                          *fixture.ITEMS, mode="primary")
            head = db.head("items", "itm_lem")
            fixture.apply(db, [edit("replace", "items", "itm_lem", dict(
                head.body, statement={"form": "verbatim", "text": "a_n <= 1 for bounded increments"}),
                expected=head.version)])
            result = derive_assessment(db, audit_id=fixture.audit_id)
        self.assertEqual({j["freshness"] for j in result["judgments"].values() if not j["superseded"]}, {"needs_review"})
        self.assert_state(result, "items:itm_lem", "amber", "historical")
        self.assert_state(result, "groups:grp_lem", "amber", "stale")
        self.assertIs(result["progress"]["process_complete"], False)
        self.assertEqual([ref["id"] for ref in result["findings"]["open"]], ["fnd_1"])


class IndependentTests(AssessmentCase):
    """The independent indicator is a separate lattice; it never colours a record green."""

    def test_a_disagreeing_independent_round_disputes_the_statement(self):
        """An independent gap against a primary supported outcome is a dispute until it is reconciled."""
        fixture = self.fixture()
        fixture.primary()
        with fixture.open() as db:
            independent_round(fixture, db, item_id="itm_lem", argument_id="arg_lem",
                              anchor="anc_lem_proof", outcome="gap")
            result = derive_assessment(db, audit_id=fixture.audit_id)
        entry = self.assert_state(result, "items:itm_lem", "amber", "disputed")
        self.assertEqual(entry["explanation"], DISPUTE)
        self.assertEqual(entry["independent_review"], "disputed")
        self.assertEqual(result["independent"], {"items:itm_lem": "disputed", "items:itm_thm": "pending"})
        self.assertIs(result["progress"]["process_complete"], False)

    def test_a_dispute_leaves_the_reconciliation_obligation_unsatisfied(self):
        """The coordinator still owes a reconciliation, and the obligation says why."""
        fixture = self.fixture()
        fixture.primary()
        with fixture.open() as db:
            independent_round(fixture, db, item_id="itm_lem", argument_id="arg_lem",
                              anchor="anc_lem_proof", outcome="gap")
            result = derive_assessment(db, audit_id=fixture.audit_id)
        obligation = next(o for o in result["obligations"]
                          if o["kind"] == "reconciliation" and o["target"]["id"] == "itm_lem")
        self.assertEqual(obligation["state"], "missing")
        self.assertIs(obligation["satisfied"], False)
        self.assertEqual(obligation["outcome"], "inconclusive")
        self.assertIs(result["constituents"][obligation["id"]]["disputed"], True)

    def test_reconciling_the_dispute_completes_the_indicator(self):
        """Once the coordinator adjudicates, the indicator is complete and the colour is green again."""
        fixture = self.fixture()
        fixture.primary()
        with fixture.open() as db:
            check_id = independent_round(fixture, db, item_id="itm_lem", argument_id="arg_lem",
                                         anchor="anc_lem_proof", outcome="gap")
            packet = fixture.packet(db, *fixture.ITEMS, mode="reconcile")
            review.reconcile(db, batch=fixture.batch(
                [fixture.reconciliation_edit(db, "rec_lem", "arg_lem", "chk_comp_lem", check_id)],
                packet["packet_id"]))
            result = derive_assessment(db, audit_id=fixture.audit_id)
        self.assertEqual(result["independent"]["items:itm_lem"], "complete")
        self.assert_state(result, "items:itm_lem", "green", "supported")

    def test_a_compromised_round_is_reported_without_being_counted(self):
        """A reviewer who may have seen the draft cannot satisfy the independent obligation."""
        fixture = self.fixture()
        fixture.primary()
        with fixture.open() as db:
            independent_round(fixture, db, item_id="itm_lem", argument_id="arg_lem",
                              anchor="anc_lem_proof", outcome="supported", status="possible_exposure")
            result = derive_assessment(db, audit_id=fixture.audit_id)
        self.assertEqual(result["independent"]["items:itm_lem"], "compromised")
        obligation = next(o for o in result["obligations"] if o["kind"] == "composition"
                          and o["role"] == "independent" and o["target"]["id"] == "arg_lem")
        self.assertEqual(obligation["state"], "missing")
        self.assertIs(obligation["satisfied"], False)
        self.assertIn("independent exposure is declared compromised", obligation["explanation"])
        self.assertIn("possible exposure", obligation["assessment"]["explanation"])
        self.assertIs(result["constituents"][obligation["id"]]["compromised"], True)
        judgment = next(info for info in result["judgments"].values() if info["role"] == "independent")
        self.assertEqual(judgment["exposure"], "compromised")
        self.assertEqual(judgment["response_state"], "accepted")
        self.assertIs(result["progress"]["process_complete"], False)

    def test_partially_mapped_source_only_response_is_pending_until_whole_response_acceptance(self):
        from test_review import entry, judgment, mapping_request, source_target, submission, worker_response
        fixture = self.fixture().primary()
        with fixture.open() as db:
            packet = packets.get_packet(db, targets=[R("items", "itm_lem")], mode="independent")
            raw = json.dumps(worker_response(packet["packet_id"], [
                judgment(source_target("anc_lem_proof", "Final conclusion")),
                judgment(source_target("anc_lem_proof", "Local inference"), kind="derivation")])).encode()
            saved = review.submit_review(db, submission=submission(fixture, packet["packet_id"]), response_bytes=raw)
            mapping_packet = fixture.packet(db, *fixture.ITEMS, mode="primary")
            review.map_response(db, mapping=mapping_request(fixture, mapping_packet["packet_id"], saved["response_id"],
                [entry(0, R("arguments", "arg_lem"))]))
            partial = derive_assessment(db, audit_id=fixture.audit_id)
            obligation = next(o for o in partial["obligations"] if o["role"] == "independent"
                and o["target"] == R("arguments", "arg_lem"))
            self.assertEqual(partial["independent"]["items:itm_lem"], "pending")
            self.assertFalse(partial["constituents"][obligation["id"]]["compromised"])
            self.assertFalse(obligation["satisfied"])
            self.assertIn("mapping is unfinished", obligation["explanation"])
            self.assertIn("mapping is unfinished", obligation["assessment"]["explanation"])
            self.assertFalse(partial["progress"]["process_complete"])
            self.assertEqual(db.head("responses", saved["response_id"]).body["exposure"], "source_only")
            mapping_packet = fixture.packet(db, *fixture.ITEMS, mode="primary")
            review.map_response(db, mapping=mapping_request(fixture, mapping_packet["packet_id"], saved["response_id"],
                [entry(1, R("groups", "grp_lem"))]))
            full = derive_assessment(db, audit_id=fixture.audit_id)
            self.assertEqual(full["independent"]["items:itm_lem"], "pending")
            self.assertTrue(next(o for o in full["obligations"] if o["id"] == obligation["id"])["satisfied"])
            self.assertFalse(full["progress"]["process_complete"])
            self.assertEqual(db.get_blob(db.head("responses", saved["response_id"]).body["original_blob"]), raw)

    def test_supplied_route_with_invalidated_basis_is_pending_without_claiming_exposure(self):
        from unittest import mock
        fixture = self.fixture().independent()
        with fixture.open() as db:
            prepared = controller.prepare_work(db, audit_id=fixture.audit_id, mode="independent", route_id="arg_lem")
            worker = json.loads(json.dumps(prepared["scaffold"]))
            worker["coverage_note"] = "Examined the supplied route after the preserved blind review."
            for task in prepared["manifest"]["work"]["tasks"]:
                worker["judgments"].append({"target": task["target"], "kind": task["kind"], "state": "complete",
                    "outcome": "supported", "reasoning": "The exact source inference follows under its stated conditions.",
                    "evidence_refs": ["anc_lem_proof"], "conditions": [], "next_action": None, "supersedes": None})
            saved = controller.submit_work(db, envelope_bytes=canonical_bytes({"contract_version": 4,
                "request_id": fixture.request_id(), "packet_id": prepared["packet_id"], "rebase_packet_id": None,
                "reviewer": "checker-A", "qualification_id": "qua_r1", "exposure": "route_provided",
                "exposure_note": "Fresh context containing this supplied route only."}), response_bytes=canonical_bytes(worker))
            self.assertEqual(saved["state"], "accepted", saved)
            valid = derive_assessment(db, audit_id=fixture.audit_id)
            valid_obligation = next(o for o in valid["obligations"] if o["role"] == "independent"
                and o["target"] == R("arguments", "arg_lem"))
            self.assertTrue(valid_obligation["satisfied"])
            route = db.head("arguments", "arg_lem")
            group = db.head("groups", "grp_lem")
            fixture.apply(db, [edit("create", "scopes", "scp_changed", {
                "argument_id": "arg_lem", "parent_id": "scp_plain", "assumptions": [], "binders": [],
                "conditions": ["A newly stated positive-input condition"], "evidence_refs": ["anc_lem_proof"]}),
                edit("replace", "arguments", route.id, dict(route.body, scope_id="scp_changed"), route.version),
                edit("replace", "groups", group.id, dict(group.body, scope_id="scp_changed"), group.version)],
                *fixture.ITEMS, mode="primary")
            derivation, stale = derive_full(db, audit_id=fixture.audit_id)
            obligation = next(o for o in stale["obligations"] if o["id"] == valid_obligation["id"])
            self.assertFalse(obligation["satisfied"])
            self.assertFalse(stale["constituents"][obligation["id"]]["compromised"])
            self.assertEqual(stale["independent"]["items:itm_lem"], "pending")
            route_info = next(info for info in stale["judgments"].values() if info["exposure"] == "route_provided"
                and info["kind"] == "composition")
            self.assertFalse(derivation.independent_usable(route_info))
            # With only the supplied-route judgment available, the missing basis
            # still describes pending work, not a declaration of exposure.
            with mock.patch.object(derivation, "_independent_checks_for", return_value=[route_info]):
                self.assertEqual(derivation.independent_indicator("items:itm_lem"), "pending")
            self.assertIn("supplied-route review lacks", derivation._independent_limitation(route_info))
            self.assertFalse(stale["progress"]["process_complete"])

    def test_missing_or_failed_qualification_keeps_review_pending(self):
        from test_review import qualification_receipt, submission, worker_response
        fixture = self.fixture().primary()
        with fixture.open() as db:
            review.record_qualification(db, receipt=qualification_receipt(fixture, qid="qua_failed",
                reviewer="checker-A", qualified=False))
            packet = packets.get_packet(db, targets=[R("items", "itm_lem")], mode="independent")
            for identity in ("qua_missing", "qua_failed"):
                with self.subTest(qualification=identity):
                    revision = db.max_revision()
                    with self.assertRaises(InvalidRequest):
                        review.submit_review(db, submission=submission(fixture, packet["packet_id"], qualification_id=identity),
                            response_bytes=canonical_bytes(worker_response(packet["packet_id"], [])))
                    result = derive_assessment(db, audit_id=fixture.audit_id)
                    self.assertEqual(db.max_revision(), revision)
                    self.assertEqual(result["independent"]["items:itm_lem"], "pending")
                    self.assertFalse(any(c["compromised"] for c in result["constituents"].values()))
                    self.assertFalse(result["progress"]["process_complete"])

    def test_an_independent_judgment_records_its_response_state_and_exposure(self):
        """Every judgment says where it came from, so a reader can tell blinded work from mapped work."""
        result = self.derive(self.complete_fixture())
        independent = [info for info in result["judgments"].values() if info["role"] == "independent"]
        self.assertEqual(len(independent), 2)
        for info in independent:
            with self.subTest(check=info["ref"]["id"]):
                self.assertEqual(info["response_state"], "accepted")
                self.assertEqual(info["exposure"], "source_only")
                self.assertEqual(info["reviewer"], "checker-A")
                self.assertEqual(info["kind"], "composition")
        primary = [info for info in result["judgments"].values() if info["role"] == "primary"]
        self.assertEqual({info["response_state"] for info in primary}, {None})
        self.assertEqual({info["exposure"] for info in primary}, {None})


class ProcessCompletenessTests(AssessmentCase):
    """``process_complete`` is the gate the publication and the report both read."""

    def test_an_unmet_required_obligation_holds_the_process_open(self):
        """While any required obligation is unsatisfied the process is not complete."""
        fixture = self.complete_fixture()
        with fixture.open() as db:
            fixture.apply(db, [edit("create", "items", "itm_ass", dict(ASSUMPTION_ITEM)),
                               edit("create", "uses", "use_ass_lem", dict(USE_ASS_LEM))])
            result = derive_assessment(db, audit_id=fixture.audit_id)
        self.assertIs(result["progress"]["process_complete"], False)
        self.assertEqual(result["progress"]["required_obligations"], 15)
        self.assertLess(result["progress"]["completed_current_obligations"],
                        result["progress"]["required_obligations"])

    def test_an_open_source_issue_holds_the_process_open_without_changing_a_colour(self):
        """A source limit is a process limit: the assessments stand, the completeness does not."""
        fixture = self.complete_fixture()
        before = self.derive(fixture)
        with fixture.open() as db:
            packet = fixture.packet(db)
            sources.review_sources(db, batch=fixture.batch([edit("create", "source_issues", "sis_1", dict(
                SOURCE_ISSUE, source_id=fixture.source_id))], packet["packet_id"]))
            result = derive_assessment(db, audit_id=fixture.audit_id)
        self.assertEqual(result["source_limits"], [{"collection": "source_issues", "id": "sis_1",
                                                    "version": 1}])
        self.assertIs(result["progress"]["process_complete"], False)
        self.assertEqual(result["progress"]["completed_current_obligations"], 13)
        self.assertEqual(result["assessments"], before["assessments"])

    def test_a_resolved_source_issue_stops_limiting_the_process(self):
        """Only open issues limit the audit; resolving one restores completeness."""
        fixture = self.complete_fixture()
        with fixture.open() as db:
            packet = fixture.packet(db)
            sources.review_sources(db, batch=fixture.batch([edit("create", "source_issues", "sis_1", dict(
                SOURCE_ISSUE, source_id=fixture.source_id))], packet["packet_id"]))
            resolved = dict(SOURCE_ISSUE, source_id=fixture.source_id, lifecycle="resolved",
                            resolution="re-anchored by exact lines")
            packet = fixture.packet(db)
            sources.review_sources(db, batch=fixture.batch(
                [edit("replace", "source_issues", "sis_1", resolved, expected=1)], packet["packet_id"]))
            result = derive_assessment(db, audit_id=fixture.audit_id)
        self.assertEqual(result["source_limits"], [])
        self.assertIs(result["progress"]["process_complete"], True)

    def test_an_overview_snapshot_is_never_process_complete(self):
        """With no audit there is no required work, and no required work is not completion."""
        fixture = self.fixture()
        fixture.structure()
        with fixture.open(write=False) as db:
            result = derive_assessment(db)
        self.assertIs(result["progress"]["process_complete"], False)
        self.assertEqual(result["progress"]["required_obligations"], 0)

    def test_a_focused_audit_with_no_assessable_statement_is_never_complete(self):
        """An audit whose only target cannot be assessed must not report a finished process."""
        fixture = self.complete_fixture()
        with fixture.open() as db:
            fixture.apply(db, [edit("create", "items", "itm_int", dict(INTERMEDIATE_ITEM))])
            fixture.apply(db, [edit("create", "audits", "aud_2", dict(
                INTERMEDIATE_AUDIT, paper_id=fixture.paper_id,
                global_tasks=[dict(task) for task in GLOBAL_TASKS]))], *fixture.ITEMS, mode="primary")
            result = derive_assessment(db, audit_id="aud_2")
        self.assertIs(result["progress"]["process_complete"], False)
        self.assertEqual(result["progress"]["required_obligations"], 0)
        self.assertEqual(result["problems"], ["audit target items:itm_int is an intermediate result"])

    def test_progress_counts_major_results_and_unbound_statements(self):
        """The progress block also reports how much of the paper is in scope and how well it is anchored."""
        result = self.derive(self.complete_fixture())
        self.assertEqual(result["progress"]["major_results"], 2)
        self.assertEqual(result["progress"]["source_unbound_items"], 0)
        self.assertEqual(result["progress"]["draft_checks"], 0)


if __name__ == "__main__":
    unittest.main()
