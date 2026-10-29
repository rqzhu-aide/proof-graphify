"""Current saved examinations, effective opinions and compact reviewer provenance."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import sys
from unittest.mock import patch

# Exercise the maintained source before the distribution bundles are regenerated.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "shared"))
from paper_core import assessment, projection
from paper_core.storage import Record
from support import R, TempCase
import test_v3_integration as integration_tests


class FactualProjectionTests(TempCase):
    prepared_fixture = integration_tests.CoherentIntegrationTests.prepared_fixture
    examine = integration_tests.CoherentIntegrationTests.examine
    submit = integration_tests.CoherentIntegrationTests.submit
    integrate = integration_tests.CoherentIntegrationTests.integrate

    @staticmethod
    def facts(db, fixture):
        derived = assessment.derive_full(db, audit_id=fixture.audit_id)
        return projection.factual_summary(*derived)

    def test_effective_outcomes_reuse_adoption_and_preserve_initial_counts(self):
        for decision in (None, "unresolved", "primary_revised"):
            with self.subTest(decision=decision):
                fixture = self.prepared_fixture(name=str(decision))
                with fixture.open() as db:
                    self.examine(db, fixture, "gap")
                    if decision:
                        self.integrate(db, fixture, decision)
                    facts = self.facts(db, fixture)
                self.assertEqual({"supported": 2, "gap": 0, "refuted": 0, "inconclusive": 0},
                                 facts["work"]["current_primary_outcomes"])
                expected = {"supported": 1, "gap": 1, "refuted": 0, "inconclusive": 0} \
                    if decision == "primary_revised" else facts["work"]["current_primary_outcomes"]
                self.assertEqual(expected, facts["work"]["current_effective_outcomes"])
                self.assertEqual({"items": ["separate reviewer"], "total": 1},
                                 facts["independent_review"]["reviewer_context"]["independent"])

    def test_stale_integration_retains_current_initial_opinions(self):
        fixture = self.prepared_fixture()
        with fixture.open() as db:
            self.examine(db, fixture, "gap")
            self.integrate(db, fixture, "primary_revised")
            derivation, result = assessment.derive_full(db, audit_id=fixture.audit_id)
            with patch.object(derivation, "_coherent_integration", return_value={
                    "indicator": "pending", "state": "complete", "freshness": "needs_review",
                    "check_refs": []}):
                facts = projection.factual_summary(derivation, result)
        self.assertEqual(facts["work"]["current_primary_outcomes"],
                         facts["work"]["current_effective_outcomes"])

    def test_partial_complete_examination_still_counts_once(self):
        fixture = self.fixture("partial").audit(independent_required=False)
        with fixture.open() as db:
            row = fixture.check_edit("chk_partial", R("arguments", "arg_thm"), "composition",
                                     evidence=["anc_thm_proof"], outcome="inconclusive")
            row["body"].update(extent="partial", omissions="The last implication remains unexamined.")
            fixture.apply(db, [row], *fixture.ITEMS, mode="primary")
            facts = self.facts(db, fixture)
        self.assertFalse(facts["process_complete"])
        self.assertEqual({"supported": 0, "gap": 0, "refuted": 0, "inconclusive": 1},
                         facts["work"]["current_effective_outcomes"])

    def test_reviewers_filter_saved_history_and_cap_exact_identities(self):
        fixture = self.prepared_fixture()
        with fixture.open() as db:
            derivation, result = assessment.derive_full(db, audit_id=fixture.audit_id)
            obligation = next(o for o in result["obligations"] if o["role"] == "primary"
                              and o["target"] == R("arguments", "arg_thm") and o["kind"] == "composition")
            constituent = derivation.constituents[obligation["id"]]
            original = derivation.snap.get(constituent["check_refs"][0])
            extras, infos = {}, {}

            def add(identity, *, body_changes=None, **info_changes):
                body = deepcopy(original.body)
                body.update(reviewer=identity, **(body_changes or {}))
                record = replace(original, id="chk_extra_" + str(len(extras)), body=body)
                extras[record.id] = record
                infos[record.id] = dict(state="complete", freshness="current", superseded=False)
                infos[record.id].update(info_changes)
                constituent["check_refs"].append(record.pinned)

            for identity in ("alias A", "alias B", "alias C", "alias D", "alias A"):
                add(identity)
            add("stale", freshness="historical")
            add("superseded", superseded=True)
            add("draft", state="draft")
            add("wrong audit", body_changes={"audit_id": "aud_other"})
            add("wrong target", body_changes={"target": R("arguments", "arg_lem")})
            add("wrong kind", body_changes={"kind": "application"})
            add("wrong role", body_changes={"role": "independent"})
            add(None, body_changes={"response_id": "rsp_linked"})
            add(None, body_changes={"response_id": "rsp_unaccepted"})
            for identity, state, exposure in (("linked", "accepted", "source_only"),
                                               ("unaccepted", "needs_revision", "compromised"),
                                               ("unlinked", "accepted", "route_provided")):
                derivation.responses["rsp_" + identity] = Record("responses", "rsp_" + identity,
                    1, 1, False, {"audit_id": fixture.audit_id, "state": state,
                                  "reviewer": "response " + identity, "exposure": exposure})
            saved_get, saved_info = derivation.snap.get, derivation.judgment_info
            with patch.object(derivation.snap, "get", side_effect=lambda ref:
                    extras[ref["id"]] if ref["id"] in extras else saved_get(ref)), \
                    patch.object(derivation, "judgment_info", side_effect=lambda check:
                    infos[check.id] if check.id in infos else saved_info(check)):
                facts = projection.factual_summary(derivation, result)
        context = facts["independent_review"]["reviewer_context"]
        self.assertEqual({"items": ["alias A", "alias B", "alias C"], "total": 6}, context["primary"])
        self.assertEqual({"items": [], "total": 0}, context["independent"])
        self.assertEqual({"source_only": 1, "compromised": 1, "route_provided": 1},
                         facts["independent_review"]["response_exposures"])


if __name__ == "__main__":
    import unittest
    unittest.main()
