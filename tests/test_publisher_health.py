import datetime as dt
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import health_monitor as health
from health_recovery import supervise


class PublisherHealth(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        archive = root / 'archive.sqlite3'
        sqlite3.connect(archive).close()
        self.status_file = root / 'private-publisher.last-run.json'
        self.config = {'archive': str(archive), 'owners': [], 'publishers': [
            {'name': 'private-client', 'status_file': str(self.status_file)}]}
        self.worker = {'ActiveState': 'inactive', 'Result': 'success'}
        self.timer = {'ActiveState': 'active', 'UnitFileState': 'enabled'}
        self.units_seen = []
        self.write_status()
        units = patch.object(health, 'unit_properties', side_effect=self.unit)
        units.start()
        self.addCleanup(units.stop)
        disk = patch.object(health.shutil, 'disk_usage', return_value=type(
            'Usage', (), {'free': 10 * 1024**3, 'total': 100 * 1024**3})())
        disk.start()
        self.addCleanup(disk.stop)

    def unit(self, name):
        self.units_seen.append(name)
        return self.timer if name.endswith('.timer') else self.worker

    def write_status(self, stamp=1000, **flags):
        self.status_file.write_text(json.dumps({
            'checked_at': dt.datetime.fromtimestamp(stamp, dt.timezone.utc).isoformat(),
            'analysis_failed_or_paused': False, 'deferred_sources': 0, **flags}))

    def test_owner_archive_publisher_and_backfill_health(self):
        self.config['publishers'][0]['kind'] = 'owner_all'
        self.config['backfills'] = [{'owner':'Casey', 'status_file':str(self.status_file)}]
        self.assertEqual(health.observe(self.config, 1100)['issues'], {})
        self.assertIn('minbox-owner-archive@private-client.timer', self.units_seen)
        self.assertIn('minbox-text-backfill@Casey.timer', self.units_seen)
        self.write_status(thread_states={'paused_failures':1})
        issues = health.observe(self.config, 1100)['issues']
        self.assertIn('backfill_1.paused', issues)
        text = health.issue_text('backfill_1.paused')[0]
        self.assertNotIn('Casey', text)
        self.assertIn('History collection', text)

    def test_healthy_completed_run_and_exact_units(self):
        result = health.observe(self.config, 1100)
        self.assertEqual(result['issues'], {})
        self.assertFalse(result['check_failed'])
        self.assertEqual(self.units_seen, [
            'minbox-archive-publisher@private-client.timer',
            'minbox-archive-publisher@private-client.service'])
        self.assertEqual(result['deferred_recoveries'], [])

    def test_failed_worker_and_disabled_or_inactive_timer(self):
        self.worker['Result'] = 'exit-code'
        for changes in ({'UnitFileState': 'disabled'}, {'ActiveState': 'inactive'}):
            with self.subTest(changes=changes):
                self.timer = {'ActiveState': 'active', 'UnitFileState': 'enabled', **changes}
                self.assertEqual(health.observe(self.config, 1100)['issues'], {
                    'publisher_1.timer': 0, 'publisher_1.worker_failure': health.WORKER_FAILURE_GRACE})

    def test_stale_status_after_ten_minutes(self):
        self.assertNotIn('publisher_1.worker_stale', health.observe(self.config, 1600)['issues'])
        self.assertIn('publisher_1.worker_stale', health.observe(self.config, 1601)['issues'])
        self.write_status(stamp=1601)
        self.assertNotIn('publisher_1.worker_stale', health.observe(self.config, 1601)['issues'])

    def test_failed_completed_attempt_is_fresh_but_not_successful_publication(self):
        self.config['publishers'][0]['kind'] = 'owner_all'
        self.write_status(stamp=3000, run_state='failed', failure_kind='transient',
                          last_publication_at=dt.datetime.fromtimestamp(1000, dt.timezone.utc).isoformat())
        issues = health.observe(self.config, 3100)['issues']
        self.assertNotIn('publisher_1.worker_stale', issues)
        self.assertIn('publisher_1.worker_failure', issues)
        self.assertIn('publisher_1.publication_stale', issues)

    def test_bounded_running_attempt_does_not_emit_stale_check_issue(self):
        self.worker['ActiveState'] = 'activating'
        self.write_status(stamp=1000, started_at=dt.datetime.fromtimestamp(1800, dt.timezone.utc).isoformat(), run_state='running')
        self.assertNotIn('publisher_1.worker_stale', health.observe(self.config, 1900)['issues'])
        self.assertIn('publisher_1.worker_stale', health.observe(self.config, 2161)['issues'])

    def test_analysis_hold_and_deferred_sources(self):
        self.write_status(analysis_failed_or_paused=True, deferred_sources=2)
        result = health.observe(self.config, 1100)
        self.assertEqual(result['issues'], {
            'publisher_1.analysis_paused': 0, 'publisher_1.input_limit': 1800})
        self.write_status()
        self.assertEqual(health.observe(self.config, 1160)['issues'], {})

    def test_retry_only_clears_local_failure_after_completed_run(self):
        state = {}
        self.worker['Result'] = 'exit-code'
        health.track_observation(state, health.observe(self.config, 1100), 1100)
        self.write_status(stamp=1700)
        health.track_observation(state, health.observe(self.config, 1700), 1700)
        for active in ('activating', 'active', 'deactivating'):
            with self.subTest(active=active):
                self.worker.update(ActiveState=active, Result='success')
                running = health.observe(self.config, 1760)
                self.assertIn('publisher_1.worker_failure', running['deferred_recoveries'])
                health.track_observation(state, running, 1760)
                self.assertEqual(state['issues']['publisher_1.worker_failure'], {'first': 1100})
        self.worker['ActiveState'] = 'inactive'
        health.track_observation(state, health.observe(self.config, 1820), 1820)
        self.assertFalse(state['issues'])

    def test_transient_worker_failures_preserve_local_age_until_completed(self):
        self.config['backfills'] = [{'owner': 'Casey', 'status_file': str(self.status_file)}]
        state = {}
        self.worker['Result'] = 'exit-code'
        failed = health.observe(self.config, 1100)
        self.assertEqual(failed['issues'], {
            'publisher_1.worker_failure': health.WORKER_FAILURE_GRACE,
            'backfill_1.worker_failure': health.WORKER_FAILURE_GRACE})
        health.track_observation(state, failed, 1100)
        self.worker.update(ActiveState='activating', Result='success')
        health.track_observation(state, health.observe(self.config, 1220), 1220)
        self.assertEqual(set(state['issues']), set(failed['issues']))
        self.assertTrue(all(record['first'] == 1100 for record in state['issues'].values()))
        self.worker['ActiveState'] = 'inactive'
        health.track_observation(state, health.observe(self.config, 1340), 1340)
        self.assertFalse(state['issues'])

    def test_failed_retry_preserves_failure_age_across_running_attempt(self):
        self.config['backfills'] = [{'owner': 'Casey', 'status_file': str(self.status_file)}]
        state = {}
        self.worker['Result'] = 'exit-code'
        health.track_observation(state, health.observe(self.config, 1100), 1100)
        self.worker.update(ActiveState='active', Result='success')
        self.write_status(stamp=1400)
        health.track_observation(state, health.observe(self.config, 1400), 1400)
        self.worker.update(ActiveState='failed', Result='exit-code')
        self.write_status(stamp=1699)
        health.track_observation(state, health.observe(self.config, 1699), 1699)
        health.track_observation(state, health.observe(self.config, 1700), 1700)
        self.assertTrue(all(record['first'] == 1100 for record in state['issues'].values()))
        self.worker.update(ActiveState='inactive', Result='success')
        health.track_observation(state, health.observe(self.config, 1760), 1760)
        self.assertFalse(state['issues'])

    def test_unreadable_status_does_not_establish_recovery(self):
        state = {}
        self.worker['Result'] = 'exit-code'
        health.track_observation(state, health.observe(self.config, 1100), 1100)
        self.worker['Result'] = 'success'
        self.status_file.write_text('{private-source-id')
        failed = health.observe(self.config, 1160)
        self.assertTrue(failed['check_failed'])
        self.assertEqual(failed['issues'], {'publisher_1.check_failed': 0})
        health.track_observation(state, failed, 1160)
        self.assertEqual(state['issues']['publisher_1.worker_failure'], {'first': 1100})
        self.assertNotIn('private-source-id', json.dumps(failed))
        self.write_status(stamp=1220)
        health.track_observation(state, health.observe(self.config, 1220), 1220)
        self.assertFalse(state['issues'])

    def test_invalid_name_never_reaches_systemd(self):
        self.config['publishers'][0]['name'] = 'bad/name'
        result = health.observe(self.config, 1100)
        self.assertEqual(result['issues'], {'publisher_1.configuration': 0})
        self.assertTrue(result['check_failed'])
        self.assertEqual(self.units_seen, [])

    def test_multiple_publishers_have_numbered_labels_and_private_human_notice(self):
        self.config['publishers'].append({
            'name': 'other-private-client', 'status_file': str(self.status_file)})
        self.write_status(analysis_failed_or_paused=True, deferred_sources=1,
                          run_state='failed', failure_kind='privacy',
                          error='private-source-id private-message-content')
        observed = health.observe(self.config, 1100)
        self.assertIn('publisher_2.analysis_paused', observed['issues'])
        self.assertIn('publisher_2.human_required', observed['issues'])
        state, sent = {}, []
        report = health.track_observation(state, observed, 1100)
        recovery = supervise(state, {**observed, 'issues': report['issues']}, self.config,
                             1100, properties=self.unit, deliver=sent.append)
        self.assertEqual(recovery['delivery'], 'sent')
        self.assertEqual(len(sent), 1)
        settings = {'type': 'smtp', 'security': 'ssl', 'host': 'example.invalid',
                    'from': 'a@example.invalid', 'to': 'b@example.invalid'}
        with patch.object(health.smtplib, 'SMTP_SSL') as smtp:
            health.send_notification(settings, sent[0])
        message = smtp.return_value.__enter__.return_value.send_message.call_args.args[0]
        email = message.as_string()
        self.assertIn('Publisher 1:', email)
        self.assertIn('Publisher 2:', email)
        self.assertIn('Human action required:', email)
        self.assertNotIn('publisher_1.analysis_paused', email)
        for private in ('private-client', 'other-private-client', 'private-source-id',
                        'private-message-content', str(self.status_file)):
            self.assertNotIn(private, email)
            self.assertNotIn(private, json.dumps(observed))


if __name__ == '__main__':
    unittest.main()
