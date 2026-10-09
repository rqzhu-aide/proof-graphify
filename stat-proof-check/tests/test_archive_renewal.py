"""Ordinary delivered-audit commands and the current archive contract."""
from __future__ import annotations

import argparse
import contextlib
import copy
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import test_proofcheck as fixtures

pc = fixtures.proofcheck


class ArchiveRenewalTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.FinalizationTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.root = self.fixture.base / 'portable-audit'
        with contextlib.redirect_stdout(io.StringIO()):
            pc.cmd_scaffold(argparse.Namespace(paper=self.fixture.paper, output=self.root,
                                               portable_sources=True, report_format='markdown'))
        manifest_path = self.root / 'AUDIT_MANIFEST.json'
        manifest = fixtures.read_json(manifest_path)
        self.default_challenge_version = manifest['protocol']['challenge_contract_version']
        self.fixture.audit = self.root
        self.fixture.paper = pc.resolve_stored_path(manifest['paper_file'], self.root)
        self.fixture.definitions = self.fixture.paper.parent / 'definitions.tex'
        # Reuse the historical fixture's checked mathematical records, then
        # explicitly obtain a current-contract initial response below.
        manifest['protocol'].pop('challenge_contract_version')
        fixtures.write_json(manifest_path, manifest)

    def run_command(self, command, **kwargs):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
            status = command(argparse.Namespace(root=self.root, **kwargs))
        self.assertEqual(0, status, output.getvalue())
        return json.loads(output.getvalue())

    def bytes(self):
        return {path.relative_to(self.root).as_posix(): path.read_bytes()
                for path in self.root.rglob('*') if path.is_file()}

    def prepare_current_issue(self, version=None):
        version = self.default_challenge_version if version is None else version
        ledger_path, issue = self.fixture.make_archivable_s1_audit()
        manifest_path = self.root / 'AUDIT_MANIFEST.json'
        manifest = fixtures.read_json(manifest_path)
        manifest['protocol']['challenge_contract_version'] = version
        fixtures.write_json(manifest_path, manifest)
        packet = pc.build_context_packet(self.root, 'lem:main', 'challenge')
        ledger = fixtures.read_json(ledger_path)
        response = {
            'response_schema_version': 2 if version >= 3 else 1,
            'unit_id': 'lem:main',
            'independence_level': 'fresh_context_same_model',
            'challenger_verdict': 'conditionally_verified',
            'conclusions': [{
                'conclusion_id': 'C001', 'verdict': 'conditionally_verified',
                'decisive_reason': 'The recorded missing premise on proof line 6 leaves the conclusion conditional on resolving I-001.',
                'source_refs': [{'packet_pointer': '/source/proof', 'start_line': 6, 'end_line': 6}],
            }],
            'issue_assessments': [{key: row[key] for key in (
                'issue_id', 'assessment', 'target_assessment', 'downstream_assessment')}
                for row in ledger['independent_check']['issue_assessments']],
        }
        if version >= 3:
            response['conclusions'][0].update(argument_status='conditional', statement_status='conditional')
        packet_path = self.fixture.base / 'archive-challenge.json'
        response_path = self.fixture.base / 'archive-response.json'
        fixtures.write_json(packet_path, packet)
        fixtures.write_json(response_path, response)
        self.run_command(pc.cmd_record_challenge, unit_id='lem:main', packet=packet_path, response=response_path)
        self.run_command(pc.cmd_bind_challenge, unit_id='lem:main')
        self.run_command(pc.cmd_migrate_report, markdown=True)
        self.run_command(pc.cmd_finalize)
        self.assertTrue(pc.check_finalization_freshness(self.root)['usable_finalization'])
        return issue

    def test_archive_and_refinalize_keeps_unresolved_finding(self):
        self.prepare_current_issue()
        self.run_command(pc.cmd_archive_issue, issue_id='I-001')
        self.assertFalse(pc.check_finalization_freshness(self.root)['usable_finalization'])
        self.run_command(pc.cmd_finalize)
        issue = fixtures.read_json(self.root / 'audit/06_reports/ISSUE_LOG.json')['issues'][0]
        self.assertEqual('open', issue['status'])
        self.assertIn('historical_origin', issue)
        self.assertTrue(pc.check_finalization_freshness(self.root)['usable_finalization'])

    def test_supported_previous_challenge_contract_archive_still_validates(self):
        self.prepare_current_issue(version=2)
        self.run_command(pc.cmd_archive_issue, issue_id='I-001')
        self.run_command(pc.cmd_finalize)
        self.assertTrue(pc.check_finalization_freshness(self.root)['usable_finalization'])

    def test_working_copy_source_repair_preserves_original_delivery(self):
        self.prepare_current_issue()
        original = self.bytes()
        with tempfile.TemporaryDirectory() as temporary:
            bundle = Path(temporary) / 'working-bundle'
            shutil.copytree(self.fixture.base, bundle)
            working = bundle / self.root.name
            self.assertTrue(pc.check_finalization_freshness(working)['usable_finalization'])
            source = bundle / self.fixture.paper.relative_to(self.fixture.base)
            source.write_text(source.read_text(encoding='utf-8').replace('$x=x$', '$x=x+1$'), encoding='utf-8')
            self.assertFalse(pc.check_finalization_freshness(working)['usable_finalization'])
            self.assertTrue(pc.check_finalization_freshness(self.root)['usable_finalization'])
            self.assertEqual(original, self.bytes())

    def test_unchanged_delivered_commands_preserve_all_bytes(self):
        self.prepare_current_issue()
        before = self.bytes()
        self.run_command(pc.cmd_report)
        self.assertEqual(before, self.bytes())
        self.run_command(pc.cmd_checkpoint, clear_active_unit=True,
                         active_unit=None, next_action='Deliver the completed audit to its reader.')
        self.assertEqual(before, self.bytes())
        self.run_command(pc.cmd_finalize)
        self.assertEqual(before, self.bytes())

    def test_archive_rejects_explicit_protocol_disagreement(self):
        self.prepare_current_issue()
        self.run_command(pc.cmd_archive_issue, issue_id='I-001')
        path = self.root / 'audit/06_reports/history/I-001-origin.json'
        archive = fixtures.read_json(path)
        issue = fixtures.read_json(self.root / 'audit/06_reports/ISSUE_LOG.json')['issues'][0]
        archive['prior_finalization_record']['protocol']['challenge_contract_version'] = 1
        prior = archive['prior_finalization_record']
        prior['record_payload_sha256'] = pc.finalization_payload_sha256(prior)
        archive['prior_finalization_record_sha256'] = pc.canonical_sha256(prior)
        archive['archive_payload_sha256'] = pc.resolution_archive_payload_sha256(archive)
        fixtures.write_json(path, archive)
        issue = copy.deepcopy(issue)
        issue['historical_origin']['sha256'] = pc.sha256_file(path)
        errors = []
        pc.load_resolution_archive(issue, self.root, errors)
        self.assertTrue(any('protocol' in error for error in errors), errors)


if __name__ == '__main__':
    unittest.main()
