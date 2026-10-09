"""The coordinator can resolve peripheral response defects without repeat review."""
import json

from support import TempCase
from paper_core import controller, stage2
from paper_core.assessment import derive_full


class LocalDispositionTests(TempCase):
    def test_generated_integration_disposes_peripheral_row_without_mutating_review(self):
        self.exercise_disposition(adverse=False)

    def test_disposition_does_not_erase_an_adverse_independent_examination(self):
        self.exercise_disposition(adverse=True)

    def exercise_disposition(self, *, adverse):
        fixture = self.fixture().audit().primary()
        with fixture.open() as db:
            originals = []
            for attempt in range(2):
                prepared = stage2.prepare(db, audit_id=fixture.audit_id)
                self.assertTrue(prepared['prepared'], prepared)
                worker = prepared['scaffold']
                for row in worker['judgments']:
                    row.update(state='complete', outcome='gap' if adverse else 'supported',
                        reasoning='Synthetic disputed prerequisite.' if adverse else 'Synthetic whole proof examination.')
                worker['judgments'].append({'reasoning': 'An unrelated notation remark with no mathematical judgment.'})
                raw = json.dumps(worker).encode()
                envelope = {'contract_version': 4, 'request_id': fixture.request_id(),
                    'packet_id': prepared['packet_id'], 'rebase_packet_id': None,
                    'reviewer': 'separate test reviewer', 'qualification_id': None,
                    'exposure': 'source_only', 'exposure_note': 'Synthetic source-only review.'}
                result = controller.submit_work(db, envelope_bytes=json.dumps(envelope).encode(), response_bytes=raw)
                self.assertEqual('accepted', result['state'], result)
                response = db.head('responses', result['response_id'])
                originals.append((response.pinned, response.body, raw))
            self.assertFalse(derive_full(db, audit_id=fixture.audit_id)[1]['progress']['process_complete'])
            for attempt in range(2):
                prepared = stage2.prepare(db, audit_id=fixture.audit_id, mode='reconcile')
                self.assertTrue(prepared['prepared'], prepared)
                worker = prepared['scaffold']
                for row in worker['integrations']:
                    row.update(decision='unresolved' if adverse else 'agree',
                        rationale='Compared both whole examinations and retained any substantive disagreement.')
                    self.assertTrue(row['response_dispositions'])
                    for disposition in row['response_dispositions']:
                        disposition['rationale'] = 'This notation remark asserts no defect or missing premise and is retained in the original response.'
                envelope = {'contract_version': 4, 'request_id': fixture.request_id(),
                    'packet_id': prepared['packet_id'], 'rebase_packet_id': None,
                    'reviewer': 'coordinator', 'qualification_id': None, 'exposure': None, 'exposure_note': ''}
                result = controller.submit_work(db, envelope_bytes=json.dumps(envelope).encode(),
                    response_bytes=json.dumps(worker).encode())
                self.assertEqual('accepted', result['state'], result)
            assessment = derive_full(db, audit_id=fixture.audit_id)[1]
            self.assertTrue(assessment['progress']['process_complete'])
            if adverse:
                self.assertEqual('disputed', assessment['assessments']['items:itm_thm']['label'])
                self.assertNotEqual('available', assessment['support']['items:itm_thm'])
            for pin, body, raw in originals:
                response = db.head('responses', pin['id'])
                self.assertEqual(pin, response.pinned)
                self.assertEqual(body, response.body)
                self.assertEqual(raw, db.get_blob(body['original_blob']))
            self.assertFalse(stage2.prepare(db, audit_id=fixture.audit_id, mode='reconcile')['prepared'])
