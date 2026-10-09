"""Preparation feedback describes saved assignments without changing worker evidence."""
import json
from pathlib import Path

from support import TempCase, run_cli


class PreparationFeedbackTests(TempCase):
    def test_public_reuse_preserves_payload_and_exposes_distinct_ready_selection(self):
        fx = self.fixture().primary()
        args = ('stage2', 'prepare', fx.path, '--audit', fx.audit_id, '--mode', 'independent')
        first, _ = run_cli(*args, '--out', self.path('first'))
        again, _ = run_cli(*args, '--out', self.path('again'))
        self.assertTrue(again['reused'])
        self.assertEqual(first['packet_id'], again['packet_id'])
        self.assertTrue(again['preparation_note'])
        self.assertEqual(first['conditional_on_task_ids'], again['conditional_on_task_ids'])
        for name in ('worker-packet.json', 'response-scaffold.json', 'source-navigation.json'):
            self.assertEqual(self.path('first', name).read_bytes(), self.path('again', name).read_bytes())
            self.assertNotIn('preparation_note', self.path('again', name).read_text(encoding='utf-8'))
        excludes = [flag for tid in again['assigned_task_ids'] for flag in ('--exclude-task', tid)]
        other, _ = run_cli(*args, *excludes, '--out', self.path('other'))
        self.assertTrue(other['prepared'], other)
        self.assertFalse(set(other['assigned_task_ids']) & set(again['assigned_task_ids']))

    def test_empty_and_oversized_public_preparation_create_no_worker_artifacts(self):
        fx = self.fixture().primary()
        args = ('stage2', 'prepare', fx.path, '--audit', fx.audit_id, '--mode', 'independent')
        oversized, _ = run_cli(*args, '--max-bytes', '1', '--out', self.path('oversized'))
        self.assertFalse(oversized['prepared'])
        self.assertTrue(oversized['preparation_note'])
        diagnostic = next(row for row in oversized['diagnostics'] if row['code'] == 'OVERSIZED_CONTEXT')
        self.assertGreater(diagnostic['measured_or_lower_bound_bytes'], 1)
        self.assertTrue(diagnostic['largest_contributors'])
        self.assertFalse(self.path('oversized', 'response-scaffold.json').exists())
        # A complete audit has no pending assignments, not an assumed output file.
        fx.complete()
        empty, _ = run_cli(*args, '--out', self.path('empty'))
        self.assertFalse(empty['prepared'])
        self.assertTrue(empty['preparation_note'])
        self.assertFalse(self.path('empty', 'worker-packet.json').exists())

    def test_new_group_reports_member_reuse_and_resume_keeps_fixed_membership(self):
        fx = self.fixture().primary()
        pending, _ = run_cli('stage2', 'prepare', fx.path, '--audit', fx.audit_id,
                             '--mode', 'independent', '--out', self.path('pending'))
        group, _ = run_cli('stage2', 'prepare-group', fx.path, '--audit', fx.audit_id,
                          '--max-packets', '1', '--out', self.path('group'))
        self.assertFalse(group['reused'])
        self.assertEqual([pending['packet_id']], group['reused_packet_ids'])
        self.assertTrue(group['packets'][0]['packet_reused'])
        self.assertTrue(group['preparation_note'])
        delivery = json.loads(Path(group['reviewer_delivery']).read_text(encoding='utf-8'))
        self.assertFalse({'packet_reused', 'preparation_note', 'diagnostics'} & delivery.keys())
        self.assertEqual({'labels', 'files', 'sources', 'response_path'}, set(delivery['packets'][0]))
        original_index = Path(group['group_index']).read_bytes()
        resumed, _ = run_cli('stage2', 'prepare-group', fx.path, '--audit', fx.audit_id,
                            '--resume-group', group['group_index'], '--out', self.path('group'))
        self.assertTrue(resumed['reused'])
        self.assertEqual(group['packet_ids'], resumed['reused_packet_ids'])
        self.assertEqual(original_index, Path(group['group_index']).read_bytes())

    def test_empty_oversized_group_preserves_diagnostics_outside_worker_delivery(self):
        fx = self.fixture().primary()
        result, _ = run_cli('stage2', 'prepare-group', fx.path, '--audit', fx.audit_id,
                           '--max-bytes', '1', '--out', self.path('group'))
        self.assertFalse(result['prepared'])
        self.assertFalse(result['packet_ids'])
        self.assertTrue(result['preparation_note'])
        self.assertTrue(result['diagnostics'])
        self.assertTrue(all(row['reason'] == 'oversized_context' for row in result['unassigned']))
        self.assertTrue(all(row['measured_or_lower_bound_bytes'] > 1 for row in result['diagnostics']))
        delivery = json.loads(Path(result['reviewer_delivery']).read_text(encoding='utf-8'))
        self.assertFalse(delivery['packets'])
        self.assertNotIn('diagnostics', delivery)
        self.assertFalse(list(self.path('group').rglob('response-scaffold.json')))
