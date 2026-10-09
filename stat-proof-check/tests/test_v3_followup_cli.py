"""Optional response assistance preserves source files and the read-only boundary."""
from copy import deepcopy
import json

from support import R, TempCase, run_cli, sha, write_json
from paper_core import stage1


class FollowupCliTests(TempCase):
    def authored(self):
        fixture = self.fixture().audit(independent_required=False)
        with fixture.open() as db:
            prepared = stage1.prepare_stage(db, audit_id=fixture.audit_id,
                                           focus=R('items', 'itm_lem'))
        response = deepcopy(prepared['scaffold'])
        for row in response['results']:
            if row['type'] == 'source_fidelity':
                row.update(result='matched', note='Compared the supplied lemma passage.', evidence_refs=['anc_lem'])
            else:
                row.update(state='complete', outcome='gap', reasoning='The supplied induction lacks its base case.',
                           evidence_refs=['anc_lem_proof'], extent='whole_unit', omissions='')
        original = write_json(self.path('original.json'), response)
        return fixture, prepared, response, original

    def intake_args(self, fixture, prepared, original, output):
        return ('stage1', 'intake-response', fixture.path, '--packet', prepared['packet_id'],
                '--response', original, '--out', output)

    def test_optional_subset_is_read_only_then_accepted_through_normal_command(self):
        fixture, prepared, response, original = self.authored()
        response['results'].extend([None, {'reasoning': 'Additional adverse content with no target.'}])
        write_json(original, response)
        before = (sha(fixture.path.read_bytes()), original.read_bytes())
        output = self.path('candidate.json')
        result, _ = run_cli(*self.intake_args(fixture, prepared, original, output))
        self.assertEqual(before, (sha(fixture.path.read_bytes()), original.read_bytes()))
        self.assertEqual(2, len(result['deferred']))
        self.assertEqual(response['results'][-2:], [x['original'] for x in result['deferred']])
        candidate = json.loads(output.read_text(encoding='utf-8'))
        self.assertEqual(response['results'][:-2], candidate['results'])
        receipt, _ = run_cli('stage1', 'examine', fixture.path, '--packet', prepared['packet_id'],
                            '--reviewer', 'actual fixture examiner', '--response', output)
        self.assertEqual('accepted', receipt['state'], receipt)
        with fixture.open(write=False) as db:
            self.assertTrue(any(r.body['outcome'] == 'gap' for r in db.heads('checks')))
        self.assertEqual(before[1], original.read_bytes())

    def test_candidate_never_overwrites_original_database_source_or_existing_output(self):
        fixture, prepared, response, original = self.authored()
        with fixture.open(write=False) as db:
            paper = db.heads('papers')[0]
            source = db.heads('sources')[0]
            from pathlib import Path
            source_path = Path(paper.body['source_root']) / source.body['path']
        existing = self.path('existing.json')
        existing.write_text('retained output', encoding='utf-8')
        for destination in (original, fixture.path, source_path, existing):
            with self.subTest(destination=destination):
                prior = destination.read_bytes()
                result, _ = run_cli(*self.intake_args(fixture, prepared, original, destination), expect=2)
                self.assertEqual('OUTPUT_CONFLICT', result['error']['code'], result)
                self.assertEqual(prior, destination.read_bytes())

    def test_malformed_file_and_empty_return_write_no_candidate(self):
        fixture, prepared, response, original = self.authored()
        baseline = sha(fixture.path.read_bytes())
        for name, raw in [('malformed', b'{invalid'), ('empty', json.dumps({
                'packet_id': prepared['packet_id'], 'results': [], 'coverage': [], 'findings': []}).encode())]:
            with self.subTest(name=name):
                original.write_bytes(raw)
                output = self.path(name + '-candidate.json')
                result, _ = run_cli(*self.intake_args(fixture, prepared, original, output))
                self.assertIsNone(result['candidate_file'])
                self.assertFalse(output.exists())
                self.assertEqual(raw, original.read_bytes())
                self.assertEqual(baseline, sha(fixture.path.read_bytes()))

    def test_candidate_reexport_does_not_replace_different_content(self):
        fixture, prepared, response, original = self.authored()
        output = self.path('candidate.json')
        args = self.intake_args(fixture, prepared, original, output)
        run_cli(*args)
        prior = output.read_bytes()
        run_cli(*args)
        self.assertEqual(prior, output.read_bytes())
        next(row for row in response['results'] if row['type'] == 'check')['reasoning'] += ' Additional analysis.'
        write_json(original, response)
        result, _ = run_cli(*args, expect=2)
        self.assertEqual('OUTPUT_CONFLICT', result['error']['code'])
        self.assertEqual(prior, output.read_bytes())
