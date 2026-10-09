"""Reader prose shares math display and distinguishes review from resolution."""
from copy import deepcopy
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / 'scripts'))
import paper_records as records
import proof_overview as overview

FIXTURE = SKILL / 'tests' / 'fixtures' / 'schema3-intermediates.json'


def fixture():
    return records.validate_records(json.loads(FIXTURE.read_text(encoding='utf-8')))


def revised(data):
    data.pop('snapshot_id', None)
    return records.validate_records(data)


def reviewed(data):
    data = deepcopy(data)
    targets = [{'collection': collection, 'id': row['id']}
               for collection in ('items', 'uses') for row in data[collection]]
    data['observations'].extend(records.make_observations(data, targets, 'Synthetic reviewer'))
    return data


def reader_html(html):
    """Static reader markup, excluding scripts and inert panel copies."""
    return re.sub(r'<(script|style|template)\b[\s\S]*?</\1>', '', html)


def panel_html(html, identity):
    return re.search(r'<template id="proof-detail-' + re.escape(identity) + r'">([\s\S]*?)</template>', html).group(1)


class ReviewWordingTests(unittest.TestCase):
    def test_unreviewed_is_not_described_as_reviewed_with_questions(self):
        status = records.comparison_status(fixture())
        self.assertEqual(status['unreviewed'], status['total'])
        self.assertIn(f"0 of {status['total']} records reviewed", status['summary'])
        self.assertIn('not yet reviewed', status['summary'])

    def test_reviewed_open_question_keeps_unresolved_status_with_clear_summary(self):
        data = reviewed(fixture())
        data['observations'].extend(records.make_observations(
            data, [{'collection': 'items', 'id': 'independence'}],
            'Synthetic reviewer', result='needs_attention', note='An unresolved source question.'))
        status = records.comparison_status(data)
        self.assertEqual(status['status'], 'incomplete')  # Resolution has not been fabricated.
        self.assertEqual((status['unreviewed'], status['stale'], status['needs_attention']), (0, 0, 1))
        self.assertIn(f"All {status['total']} records reviewed", status['summary'])
        self.assertIn('unresolved source questions', status['summary'])
        report = records.record_report(data, FIXTURE.parent)
        self.assertTrue(any(status['summary'] in warning for warning in report['warnings']))
        self.assertFalse(any('Source comparison is incomplete:' in warning for warning in report['warnings']))

    def test_changed_records_require_review_again(self):
        data = reviewed(fixture())
        data['items'][0]['statement']['text'] += ' Changed hypothesis.'
        status = records.comparison_status(revised(data))
        self.assertGreater(status['stale'], 0)
        self.assertIn('need review after changes', status['summary'])
        self.assertNotIn(f"All {status['total']} records reviewed", status['summary'])

    def test_matched_summary_does_not_claim_proof_verification(self):
        status = records.comparison_status(reviewed(fixture()))
        self.assertEqual(status['status'], 'complete')
        self.assertIn('no source-comparison questions remain unresolved', status['summary'])
        self.assertNotIn('proved', status['summary'])


class MathematicalProseTests(unittest.TestCase):
    def data(self):
        data = fixture()
        data['scope'] = r'Overview for \(n \geq 1\).' + '\n\n' + r'Retain the limit \[x_n\to 0\].'
        for row in data['items']:
            row['issue'] = r'Check \(x_n^2\) and preserve <script>untrusted()</script> as text.'
        for row in data['uses']:
            row['issue'] = r'Is $\alpha > 0$ required?'
            row['regime'] = r'When \(n \geq 2\)'
        return revised(data)

    def test_math_fields_preserve_authored_records_and_original_annotations(self):
        data = self.data()
        original = deepcopy(data)
        prepared = records.prepare_records(data, FIXTURE.parent)
        self.assertEqual(data, original)
        self.assertEqual(prepared['math_diagnostics'], [])
        for row in prepared['items'] + prepared['details']:
            self.assertIn('<math', row['issue_html'])
            self.assertIn('x_n^2', row['issue_html'])
            self.assertIn('&lt;script&gt;', row['issue_html'])
            self.assertNotIn('<script>', row['issue_html'])
        for row in prepared['uses'] + prepared['detail_uses']:
            for field in ('issue', 'regime'):
                self.assertIn('<math', row[field + '_html'])
                self.assertIn('application/x-tex', row[field + '_html'])
        self.assertIn('<math', prepared['scope_display']['lead_html'])
        self.assertIn('display="block"', prepared['scope_display']['details_html'])

    def test_unsupported_math_is_located_in_each_affected_field(self):
        data = self.data()
        data['items'][0]['issue'] = r'Check $\unresolvedIssueMacro{x}$.'
        data['uses'][0]['regime'] = r'When $\unresolvedRegimeMacro{x}$.'
        data['scope'] = r'Only $\unresolvedScopeMacro{x}$ is supplied.'
        prepared = records.prepare_records(revised(data), FIXTURE.parent)
        locations = {(entry['collection'], entry['id'], entry['field'])
                     for entry in prepared['math_diagnostics']}
        self.assertEqual(locations, {
            ('items', data['items'][0]['id'], 'issue'),
            ('uses', data['uses'][0]['id'], 'regime'),
            ('metadata', 'overview', 'scope'),
        })
        self.assertIn('LaTeX (not rendered)', prepared['items'][0]['issue_html'])

    @unittest.skipUnless(shutil.which('node'), 'Shared Node.js required')
    def test_html_panels_index_and_scope_use_prepared_math(self):
        data = reviewed(self.data())
        data['observations'].extend(records.make_observations(
            data, [{'collection': 'items', 'id': 'independence'}],
            'Synthetic reviewer', result='needs_attention'))
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'overview.html'
            receipt = overview.render_dataset(data, FIXTURE.parent, output)
            html = output.read_text(encoding='utf-8')
        self.assertEqual(receipt['math_diagnostics'], [])
        self.assertEqual(receipt['graph_preservation']['status'], 'pass')
        panels = re.findall(r'<template id="proof-detail-[^"]+">([\s\S]*?)</template>', html)
        self.assertTrue(panels)
        self.assertTrue(any('proof-uncertainty' in panel and '<math' in panel for panel in panels))
        issues = re.findall(r'<div class="proof-uncertainty">([\s\S]*?)</div>', html)
        self.assertTrue(issues)
        self.assertTrue(all('<math' in issue for issue in issues))
        regimes = re.findall(r'<span class="proof-regime">([\s\S]*?)</math>', html)
        self.assertTrue(regimes)
        self.assertTrue(all('<math' in regime for regime in regimes))
        lead = re.search(r'<p class="proof-scope-lead">([\s\S]*?)</p>', html).group(1)
        self.assertIn('<math', lead)
        self.assertIn('Reviewed; source question unresolved', html)
        self.assertIn('Some source questions remain unresolved', reader_html(html))
        self.assertNotIn(records.comparison_status(data)['summary'], reader_html(html))
        self.assertNotIn('<script>untrusted()</script>', html)


class ComparisonNoteProjectionTests(unittest.TestCase):
    def test_current_notes_cover_items_intermediates_and_both_connection_types(self):
        data = fixture()
        note = r'Unresolved condition: require $\alpha>0$; literal deadbeef0123456789 and source_a61e0 remain scientific prose.'
        targets = [
            {'collection': 'items', 'id': 'main-result'},
            {'collection': 'items', 'id': 'eq-key-display'},
            {'collection': 'uses', 'id': 'use-e010f28b22255258'},
            {'collection': 'uses', 'id': 'use-display-in-theorem'},
        ]
        data['observations'].extend(records.make_observations(data, targets, 'Synthetic comparison', note=note, result='needs_attention'))
        original = deepcopy(data)
        prepared = records.prepare_records(data, FIXTURE.parent)
        self.assertEqual(data, original)
        selected = {row['id']: row for collection in ('items', 'details', 'uses', 'detail_uses') for row in prepared[collection]}
        for target in targets:
            row = selected[target['id']]
            self.assertEqual(row['fidelity'], 'needs_attention')
            self.assertEqual(row['comparison_note'], note)
            self.assertIn('<math', row['comparison_note_html'])
            self.assertIn('deadbeef0123456789 and source_a61e0', row['comparison_note_html'])
        self.assertEqual(prepared['math_diagnostics'], [])

    def test_prior_note_is_stale_when_a_prerequisite_changes(self):
        data = fixture()
        note = 'The incoming independence assumption agrees with the source.'
        data['observations'].extend(records.make_observations(data, [{'collection': 'items', 'id': 'key-bound'}], 'Synthetic comparison', note=note))
        statement = data['items'][2]['statement']['text']
        data['items'][0]['statement']['text'] += ' A changed prerequisite.'
        prepared = records.prepare_records(revised(data), FIXTURE.parent)
        row = next(row for row in prepared['items'] if row['id'] == 'key-bound')
        self.assertEqual(row['statement'], statement)
        self.assertEqual(row['fidelity'], 'stale')
        self.assertEqual(row['comparison_note'], note)


@unittest.skipUnless(shutil.which('node'), 'Shared Node.js required')
class ScientificReaderContentTests(unittest.TestCase):
    def render(self, data, *, base_dir=FIXTURE.parent):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'overview.html'
            receipt = overview.render_dataset(data, base_dir, output)
            return output.read_text(encoding='utf-8'), receipt

    def render_prepared(self, data):
        with tempfile.TemporaryDirectory() as temporary:
            prepared, output = Path(temporary) / 'prepared.json', Path(temporary) / 'overview.html'
            prepared.write_text(json.dumps(data), encoding='utf-8')
            run = subprocess.run([shutil.which('node'), str(SKILL / 'scripts/render.mjs'), str(prepared), str(output)],
                                 capture_output=True, text=True, encoding='utf-8', timeout=30)
            self.assertEqual(run.returncode, 0, run.stderr)
            return output.read_text(encoding='utf-8')

    def test_unresolved_note_keeps_conditions_math_and_separate_attribution(self):
        data = reviewed(fixture())
        note = r'The supplement was not supplied. It is unresolved whether $\alpha>0$ is required; source_a61e0 and deadbeef0123456789 name quantities.'
        data['observations'].extend(records.make_observations(data, [{'collection': 'items', 'id': 'main-result'}],
                                    'Synthetic comparison', note=note, result='needs_attention'))
        data['items'][3]['proof_idea'] = r'The paper combines the bound with $n\geq2$.'
        data = revised(data)
        # Re-compare the changed target so this note describes its current context.
        data['observations'].extend(records.make_observations(data, [{'collection': 'items', 'id': 'main-result'}],
                                    'Synthetic comparison', note=note, result='needs_attention'))
        html, receipt = self.render(data)
        panel = panel_html(html, 'main-result')
        evidence = panel.index('<summary>Sources and locators</summary>')
        self.assertLess(panel.index('The supplement was not supplied'), evidence)
        self.assertIn('<strong>Source comparison note</strong>', panel)
        self.assertIn('source_a61e0 and deadbeef0123456789', panel)
        self.assertIn(r'\alpha&gt;0', panel)
        self.assertIn(r'n\geq2', panel)
        self.assertIn('<math', panel)
        self.assertNotIn('The supplement was not supplied', panel.split('</section>')[1])
        visible = reader_html(html)
        self.assertIn('Some source questions remain unresolved', visible)
        self.assertNotIn('records reviewed for this version', visible)
        self.assertNotIn('Citation scan', visible)
        self.assertEqual(receipt['source_comparison']['needs_attention'], 1)

    def test_matched_note_stays_in_existing_evidence_disclosure(self):
        data = reviewed(fixture())
        note = 'The statement retains the condition that the minimum is attained.'
        data['observations'].extend(records.make_observations(data, [{'collection': 'items', 'id': 'main-result'}],
                                    'Synthetic comparison', note=note))
        html, receipt = self.render(data)
        panel = panel_html(html, 'main-result')
        evidence = panel.index('<summary>Sources and locators</summary>')
        self.assertNotIn(note, panel[:evidence])
        self.assertIn(note, panel[evidence:])
        self.assertNotIn('Earlier source comparison note', panel)
        self.assertEqual(receipt['source_comparison']['status'], 'complete')

    def test_stale_note_does_not_become_a_current_comparison(self):
        data = reviewed(fixture())
        note = 'The conclusion requires the incoming independence assumption.'
        data['observations'].extend(records.make_observations(data, [{'collection': 'items', 'id': 'key-bound'}],
                                    'Synthetic comparison', note=note))
        data['items'][0]['statement']['text'] += ' A changed condition.'
        html, receipt = self.render(revised(data))
        panel = panel_html(html, 'key-bound')
        self.assertIn('Earlier source comparison note', panel)
        self.assertIn('source or argument context has changed', panel)
        self.assertIn('does not establish agreement with the current version', panel)
        self.assertIn(note, panel)
        self.assertIn('Some source comparisons need updating', reader_html(html))
        self.assertGreater(receipt['source_comparison']['stale'], 0)

    def test_empty_optional_notes_and_proof_ideas_add_no_sections(self):
        data = reviewed(fixture())
        for row in data['items']:
            row.pop('proof_idea', None)
        html, _ = self.render(revised(data))
        panel = panel_html(html, 'main-result')
        self.assertNotIn('comparison-note', panel)
        self.assertNotIn('Source comparison note', panel)
        self.assertNotIn('<h4>Proof idea</h4>', panel)
        self.assertIn('Statement synopsis</h4>', panel)
        self.assertIn('How the inputs contribute', panel)

    def test_unresolved_comparison_without_a_note_does_not_promise_missing_prose(self):
        data = reviewed(fixture())
        data['observations'].extend(records.make_observations(data, [{'collection': 'items', 'id': 'main-result'}],
                                    'Synthetic comparison', result='needs_attention'))
        html, _ = self.render(data)
        panel = panel_html(html, 'main-result')
        self.assertIn('Reviewed; source question unresolved', panel)
        self.assertNotIn('Source comparison note', panel)
        self.assertIn('Some source questions remain unresolved', reader_html(html))
        self.assertNotIn('read the comparison notes', reader_html(html))

    def test_missing_sources_and_unreviewed_material_remain_visible(self):
        data = records.normalize(overview.load_data(SKILL / 'examples/representer-theorem/overview.json'), SKILL / 'examples/representer-theorem')
        data['observations'] = []
        with tempfile.TemporaryDirectory() as absent:
            html, receipt = self.render(data, base_dir=Path(absent))
        visible = reader_html(html)
        self.assertIn('Some original manuscript files are unavailable', visible)
        self.assertIn('have not yet been compared with the source', visible)
        self.assertIn('attains a finite minimum', visible)
        self.assertIn('strictly increasing', visible)
        self.assertNotIn('Captured manuscript version', visible)
        self.assertEqual(receipt['source_status'], 'historical_unavailable')
        self.assertEqual(receipt['source_comparison']['unreviewed'], 17)

    def test_generated_locator_accounting_does_not_remove_unknown_scientific_warning(self):
        prepared = records.prepare_records(fixture(), FIXTURE.parent)
        note = 'Citation scan: in the mathematical argument, source_a61e0 assumes strict positivity even when the count is 0xdeadbeef0123456789.'
        prepared['warnings'].append(note)
        html = self.render_prepared(prepared)
        visible = reader_html(html)
        self.assertIn(note, visible)
        self.assertIn('Some entered or printed result labels have not been matched', visible)
        self.assertNotIn('No mechanical source locator checks are recorded', visible)
        self.assertNotIn('anchors have locator details not mechanically verified', visible)
        self.assertIn('No source excerpt is available for this locator', visible)

    def test_math_notes_use_human_names_and_preserve_exact_fallback(self):
        data = fixture()
        data['items'][3]['proof_idea'] = r'Use $\unresolvedReaderMacro{x}$ without dropping the hypothesis $\alpha>0$.'
        html, receipt = self.render(revised(data))
        visible = reader_html(html)
        self.assertIn('Theorem 1 (proof idea)', visible)
        self.assertIn(r'\unresolvedReaderMacro{x}', visible)
        self.assertIn(r'\alpha&gt;0', visible)
        self.assertNotIn('<code>main-result</code>', visible)
        self.assertNotIn('(proof_idea)', visible)
        self.assertTrue(receipt['math_diagnostics'])
        self.assertEqual(receipt['math_diagnostics'][0]['id'], 'main-result')

    def test_compatible_groups_keep_membership_without_displaying_internal_names(self):
        prepared = records.prepare_records(fixture(), FIXTURE.parent)
        for row in prepared['uses'][:2]:
            row['group'] = {'id': 'group-deadbeef0123456789', 'kind': 'joint'}
        prepared['uses'][2]['group'] = {'id': 'group-fedcba9876543210', 'kind': 'cases'}
        html = self.render_prepared(prepared)
        visible = reader_html(html)
        self.assertIn('Joint inputs 1', visible)
        self.assertIn('Alternative cases 2', visible)
        self.assertNotIn('group-deadbeef0123456789', visible)
        self.assertNotIn('group-fedcba9876543210', visible)
        metadata = re.search(r'<script id="proof-overview-records" type="application/json">([\s\S]*?)</script>', html).group(1)
        saved = json.loads(metadata)
        self.assertEqual(saved['uses'][0]['group']['id'], saved['uses'][1]['group']['id'])
        self.assertNotEqual(saved['uses'][1]['group']['id'], saved['uses'][2]['group']['id'])


if __name__ == '__main__':
    unittest.main()
