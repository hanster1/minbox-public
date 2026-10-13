import copy
import json
import tempfile
import unittest
from pathlib import Path

from archive_incremental import AnalysisFailure, IncrementalArchive, hard_excluded
from archive_io import AdapterError


def source(sid='m1', **updates):
    result = {'source_id': sid, 'revision': '1', 'owner': 'Owner A', 'conversation_id': 'c1',
              'timestamp': '2026-10-12T12:00:00Z', 'text': 'Please send the project draft.',
              'kind': 'message', 'origin_ids': []}
    result.update(updates)
    return result


def decision(sid='m1', label='work'):
    return {'source_id': sid, 'label': label, 'facts': [{'kind': 'request', 'statement': 'Send the project draft.'}]}


class Analyzer:
    def __init__(self):
        self.calls = []
        self.fail = False
        self.response = None

    def analyze(self, payload):
        self.calls.append(copy.deepcopy(payload))
        if self.fail:
            raise RuntimeError('private source must not be echoed')
        return self.response if self.response is not None else {
            'decisions': [decision(s['source_id']) for s in payload['sources']],
            'usage': {'input_tokens': 100, 'output_tokens': 20}}


class RecoveryAnalyzer(Analyzer):
    def __init__(self):
        super().__init__()
        self.error = None

    def analyze(self, payload):
        if self.error is not None:
            self.calls.append(copy.deepcopy(payload))
            raise self.error
        return super().analyze(payload)


class IncrementalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(tempfile.gettempdir()).resolve())
        self.path = Path(self.temp.name) / 'private' / 'cache.sqlite'
        self.archive = IncrementalArchive(self.path)
        self.analyzer = Analyzer()

    def tearDown(self):
        self.archive.close()
        self.temp.cleanup()

    def test_idle_restart_and_changed_revision_content(self):
        originals = [source()]
        self.assertEqual(self.archive.analyze('Owner A', originals, self.analyzer)['model_calls'], 1)
        self.assertEqual(self.archive.analyze('Owner A', originals, self.analyzer)['model_calls'], 0)
        self.archive.close()
        self.archive = IncrementalArchive(self.path)
        self.assertEqual(self.archive.analyze('Owner A', originals, self.analyzer)['model_calls'], 0)
        changed = [source(revision='2')]
        self.assertEqual(self.archive.records('Owner A', changed)['m1']['label'], 'uncertain')
        self.archive.analyze('Owner A', changed, self.analyzer)
        self.archive.analyze('Owner A', [source(revision='2', text='Different body.')], self.analyzer)
        self.assertEqual(len(self.analyzer.calls), 3)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_security_filter_before_ai_and_context(self):
        sources = [source('code', text='Your login verification code is 123456.'),
                   source('ad', text='Big sale 30% off! Reply STOP to unsubscribe.'),
                   source('personal', text='Private family plans'),
                   source('work', text='An approved work request'),
                   source('new', context=['code', 'ad', 'personal', 'work', {'source_id': 'work', 'text': 'UNTRUSTED'}, 'untrusted body'])]
        self.archive.seed('Owner A', sources[:4], [decision(s['source_id'], 'personal' if s['source_id'] == 'personal' else 'work') for s in sources[:4]])
        result = self.archive.analyze('Owner A', sources, self.analyzer,
                                      labels={'code': 'work', 'ad': 'work', 'personal': 'personal', 'work': 'work'})
        self.assertEqual(result['analyzed'], 1)
        payload = self.analyzer.calls[0]['sources'][0]
        self.assertEqual(payload['source_id'], 'new')
        self.assertEqual([s['source_id'] for s in payload['context']], ['work'])
        self.assertNotIn('123456', str(self.analyzer.calls))
        self.assertNotIn('Private family', str(self.analyzer.calls))
        self.assertNotIn('UNTRUSTED', str(self.analyzer.calls))
        records = self.archive.records('Owner A', sources, labels={'code': 'work', 'ad': 'work', 'personal': 'personal', 'work': 'work'})
        for sid in ['code', 'ad']:
            self.assertEqual(records[sid]['label'], 'spam')
            self.assertTrue(records[sid]['security_filtered'])
        self.assertTrue(hard_excluded('Your authentication code: AB12CD'))
        self.assertFalse(hard_excluded('Please review task 123456 next week.'))
        for text in ('Your code is 123456', '123456 is your access code', 'Use 123456 to verify your account', 'Your 2FA code: 123456'):
            self.assertTrue(hard_excluded(text))
        self.assertFalse(hard_excluded('The budget is 123456 dollars.'))

    def test_owner_isolation_and_exact_scope(self):
        self.archive.seed('Owner A', [source()], [decision()])
        other = [source(owner='Owner B')]
        self.assertEqual(self.archive.records('Owner B', other)['m1']['label'], 'uncertain')
        with self.assertRaises(ValueError):
            self.archive.analyze('Owner A', other, self.analyzer)
        scoped = IncrementalArchive(Path(self.temp.name) / 'scope.db', scope={
            'owner': 'Owner A', 'conversation_ids': ['c1'], 'start_date': '2026-10-12'})
        try:
            items = [source('old', timestamp='2026-10-11T12:00:00Z'), source('wrong', conversation_id='c2'), source('good')]
            scoped.analyze('Owner A', items, self.analyzer)
            self.assertEqual([s['source_id'] for s in self.analyzer.calls[-1]['sources']], ['good'])
            self.assertEqual(scoped.records('Owner A', items)['old']['reason'], 'outside_scope')
        finally:
            scoped.close()

    def test_loom_gate_tracks_effective_corrections_and_origin_revision(self):
        message = source()
        loom = source('l1', kind='loom', origin_ids=['m1'], text='Video: send the draft.')
        self.archive.seed('Owner A', [message], [decision()])
        blocked = self.archive.analyze('Owner A', [loom], self.analyzer, labels={'m1': 'personal'})
        self.assertEqual(blocked['model_calls'], 0)
        self.assertEqual(self.archive.records('Owner A', [loom], labels={'m1': 'personal'})['l1']['reason'], 'no_work_origin')
        self.archive.analyze('Owner A', [loom], self.analyzer, labels={'m1': 'work'})
        self.assertEqual(len(self.analyzer.calls), 1)
        self.assertEqual(self.archive.analyze('Owner A', [loom], self.analyzer, labels={'m1': 'work'})['model_calls'], 0)
        self.archive.analyze('Owner A', [source(revision='2')], self.analyzer)
        self.archive.analyze('Owner A', [loom], self.analyzer, labels={'m1': 'work'})
        self.assertEqual(len(self.analyzer.calls), 3)
        self.archive.analyze('Owner A', [source(text='Login code 123456')], self.analyzer)
        self.assertEqual(self.archive.analyze('Owner A', [loom], self.analyzer, labels={'m1': 'work'})['model_calls'], 0)
        self.assertEqual(self.archive.records('Owner A', [loom], labels={'m1': 'work'})['l1']['label'], 'uncertain')

    def test_loom_correction_undo_restores_completed_facts_without_model(self):
        message = source()
        loom = source('l1', kind='loom', origin_ids=['m1'], text='Reviewed video facts.')
        self.archive.seed('Owner A', [message, loom], [decision(), decision('l1')])
        original = self.archive.records('Owner A', [loom], labels={'m1': 'work'})['l1']['facts']
        self.assertTrue(original)
        self.assertEqual(self.archive.analyze('Owner A', [loom], self.analyzer, labels={'m1': 'personal'})['model_calls'], 0)
        self.assertEqual(self.archive.records('Owner A', [loom], labels={'m1': 'personal'})['l1']['facts'], [])
        self.archive.close()
        self.archive = IncrementalArchive(self.path)
        restored = self.archive.analyze('Owner A', [loom], self.analyzer, labels={'m1': 'work'})
        self.assertEqual(restored['model_calls'], 0)
        self.assertEqual(restored['cache_hits'], 1)
        self.assertEqual(self.archive.records('Owner A', [loom], labels={'m1': 'work'})['l1']['facts'], original)
        self.assertEqual(self.analyzer.calls, [])

    def test_reverted_source_revision_reuses_prior_completed_version(self):
        original = [source()]
        self.archive.analyze('Owner A', original, self.analyzer)
        facts = self.archive.records('Owner A', original)['m1']['facts']
        changed = [source(revision='2', text='A different request.')]
        self.archive.analyze('Owner A', changed, self.analyzer)
        self.assertEqual(len(self.analyzer.calls), 2)
        self.assertEqual(self.archive.analyze('Owner A', original, self.analyzer)['model_calls'], 0)
        self.assertEqual(self.archive.records('Owner A', original)['m1']['facts'], facts)
        # Restoring the historical record also restores current origin metadata.
        current = self.archive.db.execute('SELECT metadata FROM analyses WHERE source_id=?', ('m1',)).fetchone()[0]
        self.assertIn('"revision":"1"', current)
        self.assertEqual(self.archive.db.execute('SELECT count(*) FROM analysis_versions').fetchone()[0], 2)

    def test_reviewed_seed_includes_loom_without_any_model(self):
        items = [source(), source('l1', kind='loom', origin_ids=['m1'])]
        self.archive.seed('Owner A', items, [decision('m1'), decision('l1')])
        self.assertEqual(self.archive.analyze('Owner A', items, self.analyzer)['model_calls'], 0)
        self.assertEqual(self.archive.records('Owner A', items)['l1']['label'], 'work')

    def test_auto_context_classification_does_not_create_idle_calls(self):
        items = [source('context'), source(context=['context'])]
        self.archive.analyze('Owner A', items, self.analyzer)
        self.assertEqual(self.archive.analyze('Owner A', items, self.analyzer)['model_calls'], 0)
        self.assertEqual(len(self.analyzer.calls), 1)
        # Explicit revised context labels do participate in the fingerprint.
        self.archive.analyze('Owner A', items, self.analyzer, labels={'context': 'personal'})
        self.assertEqual(len(self.analyzer.calls), 2)
        self.assertEqual(self.analyzer.calls[-1]['sources'][0]['context'], [])

    def test_policy_and_context_dependency_invalidate(self):
        items = [source('context'), source(context=['context'])]
        self.archive.seed('Owner A', items, [decision('context'), decision()])
        self.assertEqual(self.archive.analyze('Owner A', items, self.analyzer)['model_calls'], 0)
        changed = [source('context', revision='2'), source(context=['context'])]
        self.assertEqual(self.archive.records('Owner A', changed)['m1']['label'], 'uncertain')
        self.archive.analyze('Owner A', changed, self.analyzer, policy='v2')
        self.assertEqual(len(self.analyzer.calls), 1)
        self.assertEqual(len(self.analyzer.calls[0]['sources']), 2)

    def test_failed_analysis_and_invalid_batch_are_not_checkpointed(self):
        self.analyzer.fail = True
        with self.assertRaisesRegex(ValueError, '^analysis failed; batch not checkpointed$'):
            self.archive.analyze('Owner A', [source()], self.analyzer)
        self.assertEqual(self.archive.records('Owner A', [source()])['m1']['reason'], 'unanalyzed')
        self.analyzer.fail = False
        self.analyzer.response = {'decisions': [decision('wrong')], 'usage': {'input_tokens': 1, 'output_tokens': 1}}
        with self.assertRaises(ValueError):
            self.archive.analyze('Owner A', [source()], self.analyzer)
        self.assertEqual(self.archive.db.execute('SELECT count(*) FROM analyses').fetchone()[0], 0)
        self.analyzer.response = None
        self.archive.reset_failures('Owner A')
        self.archive.analyze('Owner A', [source()], self.analyzer)
        # A later publisher failure cannot cause another analysis call.
        self.assertEqual(self.archive.analyze('Owner A', [source()], self.analyzer)['model_calls'], 0)

    def test_failure_pause_persists_usage_and_requires_explicit_reset(self):
        self.analyzer.fail = True
        for _ in range(2):
            with self.assertRaises(ValueError):
                self.archive.analyze('Owner A', [source()], self.analyzer)
        self.archive.close()
        self.archive = IncrementalArchive(self.path)
        result = self.archive.analyze('Owner A', [source()], self.analyzer)
        self.assertTrue(result['paused'])
        self.assertEqual(result['model_calls'], 0)
        self.assertEqual(len(self.analyzer.calls), 2)
        self.assertEqual(result['state']['unknown_usage_calls'], 2)
        self.archive.reset_failures('Owner A')
        self.analyzer.fail = False
        result = self.archive.analyze('Owner A', [source()], self.analyzer)
        self.assertFalse(result['paused'])
        self.assertEqual(result['state']['consecutive_failures'], 0)
        self.assertEqual(result['usage'], {'input_tokens': 100, 'output_tokens': 20})
        self.assertEqual(result['state']['input_tokens'], 100)

    def test_seed_is_idempotent_and_does_not_overwrite_model_analysis(self):
        first = self.archive.seed('Owner A', [source()], [decision(label='personal')])
        self.assertEqual(first['seeded'], 1)
        self.assertEqual(self.archive.seed('Owner A', [source()], [decision()])['seeded'], 0)
        self.assertEqual(self.archive.records('Owner A', [source()])['m1']['label'], 'personal')
        changed = [source(revision='2')]
        self.archive.analyze('Owner A', changed, self.analyzer)
        self.archive.seed('Owner A', changed, [decision(label='personal')])
        self.assertEqual(self.archive.records('Owner A', changed)['m1']['label'], 'work')

    def test_loom_origin_must_be_a_message_and_untrusted_context_omitted(self):
        first = source('l1', kind='loom', origin_ids=['missing'])
        self.archive.seed('Owner A', [first], [decision('l1')])
        second = source('l2', kind='loom', origin_ids=['l1'])
        result = self.archive.analyze('Owner A', [second], self.analyzer, labels={'l1': 'work'})
        self.assertEqual(result['model_calls'], 0)
        self.assertEqual(self.archive.records('Owner A', [second], labels={'l1': 'work'})['l2']['reason'], 'no_work_origin')
        self.archive.analyze('Owner A', [source(context='unproven personal body')], self.analyzer)
        self.assertEqual(self.analyzer.calls[-1]['sources'][0]['context'], [])

    def test_bounds_and_complete_batch_validation(self):
        small = IncrementalArchive(Path(self.temp.name) / 'bounded.db', max_batch_chars=400, max_model_calls=1)
        try:
            items = [source('huge', text='x' * 1000), source('one'), source('two')]
            result = small.analyze('Owner A', items, self.analyzer)
            self.assertEqual(result['model_calls'], 1)
            self.assertIn('huge', result['deferred'])
            self.assertIn('two', result['deferred'])
            self.assertEqual(small.records('Owner A', items)['huge']['label'], 'uncertain')
        finally:
            small.close()
        self.analyzer.response = {'decisions': [decision(), decision()], 'usage': {'input_tokens': 1, 'output_tokens': 1}}
        with self.assertRaises(ValueError):
            self.archive.analyze('Owner A', [source(), source('m2')], self.analyzer)
        self.assertEqual(self.archive.db.execute('SELECT count(*) FROM analyses').fetchone()[0], 0)


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(tempfile.gettempdir()).resolve())
        self.path = Path(self.temp.name) / 'analysis.sqlite'
        self.now = 1000
        self.archive = IncrementalArchive(self.path, clock=lambda:self.now)
        self.analyzer = RecoveryAnalyzer()

    def tearDown(self):
        self.archive.close()
        self.temp.cleanup()

    def reopen(self, **options):
        self.archive.close()
        self.archive = IncrementalArchive(self.path, clock=lambda:self.now, **options)

    def fail_twice(self):
        self.analyzer.error = TimeoutError('PRIVATE PROVIDER BODY')
        for _ in range(2):
            with self.assertRaises(AnalysisFailure):
                self.archive.analyze('Owner A', [source()], self.analyzer)

    def test_cooldown_probe_cap_survives_restarts_and_failed_usage_is_counted(self):
        self.fail_twice()
        self.now = 1299
        self.reopen()
        waiting = self.archive.analyze('Owner A', [source()], self.analyzer)
        self.assertEqual((waiting['analysis_state'], waiting['model_attempts']), ('retry_wait', 0))
        self.assertEqual(waiting['recovery_probes'], 0)
        for number, stamp in enumerate((1300, 2200, 4000), 1):
            self.now = stamp
            self.reopen()
            with self.assertRaises(AnalysisFailure) as caught:
                self.archive.analyze('Owner A', [source()], self.analyzer)
            failed = caught.exception.result
            self.assertEqual(failed['model_calls'], 1)
            self.assertEqual(failed['recovery_probes'], number)
            self.assertEqual(failed['error_code'], 'analysis_timeout')
            self.assertNotIn('PRIVATE', json.dumps(failed))
            self.now += 100000
            self.assertEqual(self.archive.analyze('Owner A', [source()], self.analyzer)['model_calls'], 0)
        self.now = 1000000
        self.reopen()
        exhausted = self.archive.analyze('Owner A', [source()], self.analyzer)
        self.assertEqual(exhausted['analysis_state'], 'exhausted')
        self.assertFalse(exhausted['retryable'])
        self.assertEqual(len(self.analyzer.calls), 5)
        self.assertEqual(exhausted['state']['model_attempts'], 5)
        self.assertEqual(exhausted['state']['unknown_usage_calls'], 5)
        self.assertEqual(self.archive.records('Owner A', [source()])['m1']['label'], 'uncertain')

    def test_successful_probe_checkpoints_one_smaller_batch_and_resumes_next_run(self):
        self.fail_twice()
        self.now = 1300
        self.reopen(max_batch_chars=1000)
        self.analyzer.error = None
        items = [source('m1', text='x' * 200), source('m2', text='y' * 200)]
        recovered = self.archive.analyze('Owner A', items, self.analyzer)
        self.assertEqual(recovered['model_calls'], 1)
        self.assertTrue(recovered['recovery_probe'])
        self.assertEqual(recovered['analyzed'], 1)
        self.assertEqual(recovered['pending_sources'], 1)
        self.assertEqual(recovered['state']['consecutive_failures'], 0)
        self.assertEqual(self.archive.analyze('Owner A', items, self.analyzer)['model_calls'], 0)
        self.reopen(max_batch_chars=1000)
        complete = self.archive.analyze('Owner A', items, self.analyzer)
        self.assertEqual((complete['model_calls'], complete['analysis_state']), (1, 'ready'))
        self.assertEqual(complete['cache_hits'], 1)
        self.assertEqual(complete['state']['input_tokens'], 200)

    def test_legacy_hold_permits_one_probe_and_preserves_usage_and_analysis(self):
        self.archive.seed('Owner A', [source('cached')], [decision('cached')])
        with self.archive.db:
            self.archive.db.execute('DROP TABLE analysis_state')
            self.archive.db.execute('CREATE TABLE analysis_state (owner TEXT PRIMARY KEY, '
                'consecutive_failures INTEGER, input_tokens INTEGER, output_tokens INTEGER, unknown_usage_calls INTEGER)')
            self.archive.db.execute("INSERT INTO analysis_state VALUES ('Owner A',2,100,20,2)")
        self.reopen()
        self.assertEqual(self.archive.state('Owner A')['recovery_limit'], 1)
        self.assertEqual(self.archive.records('Owner A', [source('cached')])['cached']['label'], 'work')
        self.analyzer.error = TimeoutError('PRIVATE')
        with self.assertRaises(AnalysisFailure) as caught:
            self.archive.analyze('Owner A', [source('cached'), source()], self.analyzer)
        self.assertEqual(caught.exception.result['analysis_state'], 'exhausted')
        self.now += 100000
        self.reopen()
        blocked = self.archive.analyze('Owner A', [source()], self.analyzer)
        self.assertEqual(blocked['model_calls'], 0)
        self.assertEqual(blocked['state']['input_tokens'], 100)
        self.assertEqual(blocked['state']['output_tokens'], 20)
        self.assertEqual(blocked['state']['unknown_usage_calls'], 3)
        self.assertEqual(len(self.analyzer.calls), 1)

    def test_failed_reported_usage_is_preserved_and_invalid_usage_stays_unknown(self):
        self.analyzer.error = AdapterError('PRIVATE', {'input_tokens': 11, 'output_tokens': 3})
        with self.assertRaises(AnalysisFailure) as caught:
            self.archive.analyze('Owner A', [source()], self.analyzer)
        failed = caught.exception.result
        self.assertEqual(failed['usage'], {'input_tokens': 11, 'output_tokens': 3})
        self.assertEqual((failed['model_attempts'], failed['unknown_usage_calls']), (1, 0))
        self.analyzer.error = AdapterError('PRIVATE', {'input_tokens': True, 'output_tokens': 3})
        with self.assertRaises(AnalysisFailure) as caught:
            self.archive.analyze('Owner A', [source()], self.analyzer)
        self.assertEqual(caught.exception.result['unknown_usage_calls'], 1)
        self.now += 100000
        self.reopen()
        blocked = self.archive.analyze('Owner A', [source()], self.analyzer)
        self.assertEqual(blocked['analysis_state'], 'needs_attention')
        self.assertEqual(blocked['state']['model_attempts'], 2)
        self.assertEqual(blocked['state']['input_tokens'], 11)
        self.assertNotIn('PRIVATE', str(caught.exception))

    def test_manual_hold_config_pause_and_zero_budget_never_probe(self):
        self.fail_twice()
        self.now += 100000
        self.reopen(max_model_calls=0)
        limited = self.archive.analyze('Owner A', [source()], self.analyzer)
        self.assertEqual(limited['model_attempts'], 0)
        self.assertEqual(limited['recovery_probes'], 0)
        self.reopen(operator_paused=True)
        self.assertEqual(self.archive.analyze('Owner A', [source()], self.analyzer)['analysis_state'], 'manual_hold')
        self.reopen(recovery_enabled=False)
        self.assertEqual(self.archive.analyze('Owner A', [source()], self.analyzer)['analysis_state'], 'manual_hold')
        self.archive.set_manual_hold('Owner A')
        self.archive.reset_failures('Owner A')
        self.reopen()
        self.analyzer.error = None
        held = self.archive.analyze('Owner A', [source()], self.analyzer)
        self.assertEqual((held['model_attempts'], held['analysis_state']), (0, 'manual_hold'))
        other = self.archive.analyze('Owner B', [source(owner='Owner B')], self.analyzer)
        self.assertEqual(other['model_attempts'], 1)
        self.archive.set_manual_hold('Owner A', False)
        self.assertEqual(self.archive.analyze('Owner A', [source()], self.analyzer)['model_attempts'], 1)

    def test_legacy_large_source_is_honestly_deferred_without_spending_probe(self):
        with self.archive.db:
            self.archive.db.execute("INSERT INTO analysis_state(owner,consecutive_failures,failure_code,"
                "failure_retryable,recovery_limit) VALUES ('Owner A',2,'legacy_failure',1,1)")
        result = self.archive.analyze('Owner A', [source(text='x' * 6500)], self.analyzer)
        self.assertEqual(result['model_attempts'], 0)
        self.assertEqual(result['recovery_probes'], 0)
        self.assertEqual(result['deferred_reasons'], {'probe_input_limit': 1})
        self.assertEqual(self.analyzer.calls, [])

    def test_interrupted_probe_retains_reservation_and_unknown_usage(self):
        self.fail_twice()
        self.now = 1300
        self.reopen()
        self.analyzer.error = KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            self.archive.analyze('Owner A', [source()], self.analyzer)
        self.reopen()
        waiting = self.archive.analyze('Owner A', [source()], self.analyzer)
        self.assertEqual(waiting['model_attempts'], 0)
        self.assertEqual(waiting['recovery_probes'], 1)
        self.assertEqual(waiting['state']['model_attempts'], 3)
        self.assertEqual(waiting['state']['unknown_usage_calls'], 3)
        self.assertEqual(waiting['analysis_state'], 'retry_wait')

    def test_action_rejection_never_retries_or_publishes_failed_result(self):
        self.analyzer.error = AdapterError('Codex emitted a prohibited tool or action event')
        with self.assertRaises(AnalysisFailure) as caught:
            self.archive.analyze('Owner A', [source()], self.analyzer)
        self.assertEqual(caught.exception.result['analysis_state'], 'needs_attention')
        self.now += 100000
        self.reopen()
        self.assertEqual(self.archive.analyze('Owner A', [source()], self.analyzer)['model_attempts'], 0)
        self.assertEqual(self.archive.db.execute('SELECT count(*) FROM analyses').fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main()
