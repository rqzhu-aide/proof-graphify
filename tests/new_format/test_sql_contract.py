"""Behavioral checks for one SQL authority, semantic extensions and safe upgrades."""
import copy
import json
import sqlite3

import support
from support import TempCase, R, edit
from paper_core import acceptance, storage, packets
from paper_core import review, assessment
from paper_core.canonical import digest
from paper_core.errors import InvalidRequest, IncompatibleError
from paper_core.semantics import application


class SupersetContractTests(TempCase):
    def test_parallel_overview_connections_preserve_distinct_identities(self):
        fixture = self.fixture().structure()
        with fixture.open() as db:
            shared = db.head('uses', 'use_lem_thm').body
            fixture.apply(db, [
                edit('create', 'uses', 'use_summary_a', dict(shared, reason='First summary contribution.')),
                edit('create', 'uses', 'use_summary_b', dict(shared, reason='Second summary contribution.'))])
            self.assertEqual(len(db.heads('uses')), 3)
            self.assertIsNone(db.head('application_details', 'use_summary_a'))
            self.assertIsNone(db.head('application_details', 'use_summary_b'))

    def test_applications_are_separate_canonical_records_and_sql_queryable(self):
        fixture = self.fixture().structure()
        with fixture.open() as db:
            use = db.head('uses', 'use_lem_thm')
            self.assertNotIn('group_id', use.body)
            self.assertNotIn('needed_form', use.body)
            self.assertEqual(application(db, use)['group_id'], 'grp_thm')
            row = db.conn.execute('SELECT * FROM proof_applications WHERE supplier_id=?', ('itm_lem',)).fetchone()
            self.assertEqual(row['group_id'], 'grp_thm')
            self.assertEqual(row['state'], 'registered')
            old = db.head('application_details', use.id)
            body = copy.deepcopy(use.body)
            body['uncertainty'] = 'Presentation note only'
            fixture.apply(db, [edit('replace','uses',use.id,body,use.version)], *fixture.ITEMS)
            self.assertEqual(db.head('application_details',use.id), old)

    def test_endpoint_change_cannot_leave_unchanged_active_application_inconsistent(self):
        fixture = self.fixture().structure()
        with fixture.open() as db:
            use = db.head('uses','use_lem_thm')
            body = dict(use.body, to=R('items','itm_lem'), **{'from':R('items','itm_thm')})
            with self.assertRaises(InvalidRequest) as caught:
                fixture.apply(db,[edit('replace','uses',use.id,body,use.version)],*fixture.ITEMS)
            self.assertIn('inference',str(caught.exception.records))
            self.assertEqual(db.head('uses',use.id).version,1)

    def test_complete_primary_fixture_contains_exact_targets_and_reviewed_boundaries(self):
        try:
            fixture = self.fixture().primary()
        except InvalidRequest as exc:
            self.fail(str(exc.records))
        with fixture.open() as db:
            self.assertEqual(db.conn.execute('SELECT count(*) FROM proof_targets').fetchone()[0],2)
            self.assertEqual(len(db.heads('proof_boundaries')),2)
            self.assertEqual(len(db.heads('source_reviews')),1)
            self.assertEqual(db.integrity()['integrity'],['ok'])

    def test_unknown_writer_cannot_append_commits(self):
        fixture = self.fixture()
        connection = sqlite3.connect(fixture.path)
        try:
            with self.assertRaises(sqlite3.OperationalError):
                connection.execute('INSERT INTO commits VALUES (2,1,1,?,?,?,?)',
                                   ('old_writer',digest({}),'{}','2026-09-21T00:00:00Z'))
            connection.rollback()
        finally:
            connection.close()

    def test_exact_shared_comparison_can_be_reused_without_new_examination(self):
        fixture=self.fixture().structure()
        with fixture.open() as db:
            packet=fixture.packet(db,*fixture.ITEMS,mode='primary')
            review.compare(db,batch=fixture.batch([edit('create','observations','obs_prior',{
                'target':R('items','itm_lem'),'result':'matched','reviewer':'fixture',
                'note':'Examined the complete statement and setup.','evidence_refs':['anc_lem']})],packet['packet_id']))
            body={'target':R('items','itm_lem'),'statement_ref':db.head('items','itm_lem').pinned,
                  'statement':None,'scope_id':None,'evidence_refs':['anc_lem'],'state':'registered',
                  'fidelity_ref':db.head('observations','obs_prior').pinned}
            fixture.apply(db,[edit('create','target_specs','tgt_reused',body)],*fixture.ITEMS)
            self.assertEqual(len(db.heads('observations')),1)
            current=assessment.judgment_freshness(assessment.Snapshot(db,db.max_revision()),db.head('observations','obs_prior'),superseded=False)
            self.assertEqual(current['freshness'],'current')

    def test_new_setup_cannot_borrow_prior_shared_comparison_as_exact_fidelity(self):
        fixture=self.fixture().structure()
        with fixture.open() as db:
            packet=fixture.packet(db,*fixture.ITEMS,mode='primary')
            review.compare(db,batch=fixture.batch([edit('create','observations','obs_prior',{
                'target':R('items','itm_lem'),'result':'matched','reviewer':'fixture',
                'note':'Examined the original statement.','evidence_refs':['anc_lem']})],packet['packet_id']))
            body={'target':R('items','itm_lem'),'statement_ref':db.head('items','itm_lem').pinned,
                  'statement':None,'scope_id':'scp_extra','evidence_refs':['anc_lem'],'state':'registered',
                  'fidelity_ref':db.head('observations','obs_prior').pinned}
            with self.assertRaises(InvalidRequest) as error:
                fixture.apply(db,[edit('create','scopes','scp_extra',{'argument_id':None,'parent_id':None,
                    'assumptions':[],'binders':[],'conditions':['additional restriction'],'evidence_refs':[]}),
                    edit('create','target_specs','tgt_reused',body)])
            self.assertTrue(any('newly normalized setup' in e for e in error.exception.records))

    def test_generation_change_rejects_already_open_revised_client(self):
        fixture = self.fixture()
        with fixture.open() as db:
            other = sqlite3.connect(fixture.path)
            try:
                other.execute("UPDATE metadata SET value='different-generation' WHERE key='generation'")
                other.commit()
            finally:
                other.close()
            with self.assertRaises(IncompatibleError):
                db.begin_immediate()
            self.assertFalse(db.conn.in_transaction)

    def test_v3_migration_preserves_history_and_prevents_late_old_writer(self):
        fixture = self.fixture().structure()
        # Construct the prior format with its genuine legacy use body. This
        # models historical data, not a grant of new mathematical credit.
        with fixture.open() as db:
            body = dict(db.head('uses','use_lem_thm').body,
                        group_id='grp_thm',needed_form={'form':'verbatim','text':'Lemma 1 text'},substitutions=[])
            db.begin_immediate()
            revision = db.max_revision()+1
            db.insert_commit(revision=revision,parent_revision=revision-1,base_revision=revision-1,
                             request_id='legacy_setup',request_digest=digest(body),receipt={})
            db.insert_version('uses','use_lem_thm',2,revision,body)
            db.set_head('uses','use_lem_thm',2)
            # Clear the extension and new-format metadata only for this historical fixture.
            db.insert_version('application_details','use_lem_thm',2,revision,None)
            db.set_head('application_details','use_lem_thm',2)
            db.conn.execute("UPDATE metadata SET value='3' WHERE key IN ('storage_format','contract_version')")
            db.conn.execute("UPDATE metadata SET value='[]' WHERE key='features'")
            db.commit()
        # Materialize the actual previous DDL; simply changing metadata on a
        # format-4 database would leave new views/triggers in a fake fixture.
        prior_path = self.path('genuine-v3.db')
        prior = sqlite3.connect(prior_path)
        try:
            prior.executescript((support.HANDOFF/'schema.sql').read_text(encoding='utf-8'))
            prior.execute('PRAGMA foreign_keys=OFF')
            prior.execute('ATTACH DATABASE ? AS seeded',(str(fixture.path),))
            new_collections = "'application_details','target_specs','proof_boundaries','overview_selections','connection_refinements'"
            for table, in prior.execute("SELECT name FROM sqlite_master WHERE type='table' AND name!='metadata'").fetchall():
                where = ''
                if table in ('record_versions','record_heads','record_facets'):
                    where = f' WHERE collection NOT IN ({new_collections})'
                elif table in ('record_refs','evidence_bindings'):
                    where = f' WHERE owner_collection NOT IN ({new_collections})'
                prior.execute(f'INSERT INTO {table} SELECT * FROM seeded.{table}{where}')
            prior.execute("INSERT OR IGNORE INTO metadata SELECT * FROM seeded.metadata")
            prior.commit()
        finally:
            prior.close()
        fixture.path = prior_path
        old = sqlite3.connect(fixture.path)
        old.execute('SELECT max(revision) FROM commits').fetchone()
        try:
            receipt=storage.migrate_database(fixture.path,backup=self.path('before.db'))
            self.assertEqual(receipt['previous_storage_format'],3)
            with storage.Database(fixture.path) as db:
                self.assertEqual(db.version('uses','use_lem_thm',2).body,body)
                self.assertNotIn('group_id',db.head('uses','use_lem_thm').body)
                self.assertEqual(db.integrity()['integrity'],['ok'])
                self.assertEqual(len(db.heads('target_specs')),0)
            with self.assertRaises(sqlite3.OperationalError):
                old.execute('INSERT INTO commits VALUES (99,1,1,?,?,?,?)',
                            ('late_old_writer',digest({}),'{}','2026-09-21T00:00:00Z'))
            old.rollback()
        finally:
            old.close()
