import io
import json
from pathlib import Path
from contextlib import closing, redirect_stdout
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import health_monitor as health


def observation(issues=None, failed=False, missing=None):
    return {'issues': issues or {}, 'missing': missing or {}, 'check_failed': failed}


class ObservationTracking(unittest.TestCase):
    def test_failures_keep_first_observed_time_until_verified_clear(self):
        state = {}
        bad = observation({'collector_1.disconnected': 300})
        report = health.track_observation(state, bad, 100)
        self.assertEqual(report['issues'], ['collector_1.disconnected'])
        self.assertFalse(report['healthy'])
        health.track_observation(state, bad, 400)
        self.assertEqual(state['issues']['collector_1.disconnected'], {'first': 100})
        health.track_observation(state, observation(), 460)
        self.assertFalse(state['issues'])
        health.track_observation(state, bad, 520)
        self.assertEqual(state['issues']['collector_1.disconnected'], {'first': 520})

    def test_running_retry_cannot_clear_a_failure(self):
        state = {}
        key = 'publisher_1.worker_failure'
        health.track_observation(state, observation({key: health.WORKER_FAILURE_GRACE}), 100)
        running = {**observation(), 'deferred_recoveries': [key]}
        health.track_observation(state, running, 800)
        self.assertEqual(state['issues'][key]['first'], 100)
        health.track_observation(state, observation(), 860)
        self.assertFalse(state['issues'])

    def test_failed_check_cannot_clear_prior_failures(self):
        state = {}
        key = 'collector_1.authentication'
        health.track_observation(state, observation({key: 0}), 100)
        report = health.track_observation(state, observation(failed=True), 160)
        self.assertTrue(report['check_failed'])
        self.assertEqual(state['issues'][key]['first'], 100)
        health.track_observation(state, observation(), 220)
        self.assertFalse(state['issues'])

    def test_backlog_uses_hash_age_and_survives_reload(self):
        state = {}
        bad = observation(missing={'collector_1': ['opaque']})
        self.assertFalse(health.track_observation(state, bad, 0)['issues'])
        state = json.loads(json.dumps(state))
        self.assertFalse(health.track_observation(state, bad, 599)['issues'])
        report = health.track_observation(state, bad, 600)
        self.assertEqual(report['issues'], ['collector_1.archive_backlog'])
        self.assertNotIn('opaque', json.dumps(report))
        self.assertEqual(state['missing']['collector_1'], {'opaque': 0})
        health.track_observation(state, observation(missing={'collector_1': []}), 660)
        self.assertFalse(state['issues'])
        self.assertEqual(state['missing']['collector_1'], {})

    def test_partial_import_does_not_reuse_a_different_message_age(self):
        state = {}
        health.track_observation(state, observation(missing={'collector_1': ['older']}), 0)
        health.track_observation(state, observation(missing={'collector_1': ['older', 'newer']}), 100)
        health.track_observation(state, observation(missing={'collector_1': ['older', 'newer']}), 600)
        report = health.track_observation(state, observation(missing={'collector_1': ['newer']}), 660)
        self.assertFalse(report['issues'])
        self.assertEqual(state['missing']['collector_1'], {'newer': 100})
        self.assertEqual(health.track_observation(state, observation(
            missing={'collector_1': ['newer']}), 700)['issues'], ['collector_1.archive_backlog'])

    def test_old_notification_flags_are_retired_without_changing_current_episodes(self):
        state = {'issues': {'disk.low': {'first': 10, 'notified': True,
                                       'last_sent': 20, 'recovered': True}},
                 'recovery': {'disk': {'first': 10, 'notified': True, 'attempts': 0}},
                 'missing': {'collector_1': {'opaque': 5}}}
        report = health.track_observation(state, observation(
            {'disk.low': 0}, missing={'collector_1': ['opaque']}), 605)
        self.assertEqual(state['issues']['disk.low'], {'first': 10})
        self.assertEqual(state['recovery']['disk']['notified'], True)
        self.assertEqual(report['issues'], ['collector_1.archive_backlog', 'disk.low'])
        health.track_observation(state, observation(missing={'collector_1': []}), 660)
        self.assertFalse(state['issues'])


class MonitorIntegration(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.state_dir = root / 'state'
        self.config_file = root / 'health.json'
        self.config_file.write_text(json.dumps({'owners': ['Owner'],
            'state_dir': str(self.state_dir),
            'delivery': {'type': 'smtp', 'host': 'example.invalid'}}))
        self.config_file.chmod(0o600)
        self.sent = []

    def run_check(self, now, observed, *, check_only=False, sender=None):
        output = io.StringIO()
        args = ['--config', str(self.config_file)]
        if check_only:
            args.append('--check-only')
        with patch.object(health, 'observe', return_value=observed), \
             patch.object(health.time, 'time', return_value=now), \
             patch.object(health, 'unit_properties') as units, \
             patch.object(health, 'send_notification', side_effect=sender or (
                 lambda settings, body: self.sent.append(body))), redirect_stdout(output):
            code = health.main(args)
        units.assert_not_called()
        return code, json.loads(output.getvalue())

    def test_only_one_human_notice_without_repeat_or_recovery_mail(self):
        bad = observation({'collector_1.authentication': 0})
        for now in (100, 160, 21700):
            code, report = self.run_check(now, bad)
            self.assertEqual(code, 1)
            self.assertEqual(report['pending_recoveries'], [])
        self.assertEqual(len(self.sent), 1)
        self.assertTrue(self.sent[0].startswith('Human action required:'))
        self.assertIn('Owner: Google Messages pairing has expired.', self.sent[0])
        self.assertNotIn('collector_1.authentication', self.sent[0])
        self.assertEqual(self.run_check(21760, observation())[0], 0)
        self.assertEqual(self.run_check(21820, observation())[0], 0)
        self.run_check(21880, bad)
        self.assertEqual(len(self.sent), 1)
        state = json.loads((self.state_dir / 'state.json').read_text())
        self.assertEqual(state['issues']['collector_1.authentication'], {'first': 21880})

    def test_failed_human_notice_retries_without_marking_success(self):
        bad = observation({'collector_1.authentication': 0})
        def fail(settings, body):
            raise RuntimeError('private delivery detail')
        _, report = self.run_check(100, bad, sender=fail)
        self.assertEqual(report['delivery'], 'failed')
        state = json.loads((self.state_dir / 'state.json').read_text())
        self.assertFalse(state['recovery']['collector_1']['notified'])
        self.assertNotIn('private delivery detail', json.dumps(report))
        _, report = self.run_check(160, bad)
        self.assertEqual(report['delivery'], 'sent')
        self.run_check(220, bad)
        self.assertEqual(len(self.sent), 1)

    def test_check_only_leaves_incident_state_and_delivery_untouched(self):
        self.state_dir.mkdir()
        state_file = self.state_dir / 'state.json'
        state_file.write_text(json.dumps({'issues': {
            'collector_1.authentication': {'first': 5, 'notified': True, 'last_sent': 10}}}))
        original = state_file.read_bytes()
        code, report = self.run_check(100, observation(
            {'collector_1.authentication': 0}), check_only=True)
        self.assertEqual(code, 1)
        self.assertEqual(report['delivery'], 'suppressed')
        self.assertEqual(report['pending_alerts'], [])
        self.assertEqual(report['pending_recoveries'], [])
        self.assertFalse(self.sent)
        self.assertEqual(state_file.read_bytes(), original)

    def test_human_email_subject_and_operational_text(self):
        settings = dict(type='smtp', security='ssl', host='example.invalid',
                        **{'from': 'a@example.invalid', 'to': 'b@example.invalid'})
        body = 'Human action required: Minbox archive\n\nOwner: Google Messages pairing has expired.\n'
        with patch.object(health.smtplib, 'SMTP_SSL') as smtp:
            health.send_notification(settings, body)
        message = smtp.return_value.__enter__.return_value.send_message.call_args.args[0]
        self.assertEqual(message['Subject'], 'Human action required: Minbox archive - Minbox Text Health')
        self.assertIn('Google Messages pairing has expired.', message.get_content())


class Checks(unittest.TestCase):
    def fixture(self, root, now):
        archive = root / 'archive.sqlite3'
        collectors = root / 'collectors'
        owner = collectors / 'Casey'
        owner.mkdir(parents=True)
        session = owner / 'session.json'
        session.write_text('{}'); session.chmod(0o600)
        with closing(sqlite3.connect(archive)) as db:
            db.execute('CREATE TABLE imports(owner, source, imported_at)')
            db.execute('CREATE TABLE messages(owner, source, id)')
            db.execute('INSERT INTO imports VALUES (?,?,?)', ('Casey', 'google-messages', '1970-01-01T00:16:40+00:00'))
            db.execute('INSERT INTO messages VALUES (?,?,?)', ('Casey', 'google-messages', 'matched'))
            db.commit()
        with closing(sqlite3.connect(owner / 'gmcli.db')) as db:
            db.execute('CREATE TABLE messages(message_id)')
            db.executemany('INSERT INTO messages VALUES (?)', [('matched',), ('missing',)])
            db.commit()
        return {'archive': str(archive), 'collectors': str(collectors), 'owners': ['Casey']}

    @patch.object(health, 'rpc_status', return_value={'connected': True, 'auth_expired': False, 'offline': False, 'send_mode': 'off', 'last_event_ms': 0})
    @patch.object(health, 'unit_properties', return_value={'ActiveState': 'active', 'UnitFileState': 'enabled', 'Result': 'success'})
    def test_quiet_healthy_and_missing_internal_only(self, units, rpc):
        with tempfile.TemporaryDirectory() as directory:
            config = self.fixture(Path(directory), 1100)
            result = health.observe(config, 1100)
            self.assertFalse(result['issues'])
            self.assertFalse(result['check_failed'])
            self.assertEqual(len(result['missing']['collector_1']), 1)
            self.assertNotIn('missing', result['missing']['collector_1'])

    @patch.object(health, 'rpc_status', return_value={'connected': False, 'auth_expired': True, 'offline': True, 'send_mode': 'on'})
    @patch.object(health, 'unit_properties', return_value={'ActiveState': 'inactive', 'UnitFileState': 'disabled', 'Result': 'exit-code'})
    def test_failures_and_permissions(self, units, rpc):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = self.fixture(root, 2000)
            (root / 'collectors/Casey/session.json').chmod(0o644)
            result = health.observe(config, 2000)
            for label in ('service', 'import_timer', 'import_failure', 'authentication', 'send_mode', 'import_stale', 'session_permissions'):
                self.assertIn('collector_1.' + label, result['issues'])
            self.assertEqual(result['issues']['collector_1.disconnected'], 300)
            self.assertEqual(result['issues']['collector_1.import_failure'], health.WORKER_FAILURE_GRACE)
            for label in ('authentication', 'send_mode', 'session_permissions'):
                self.assertEqual(result['issues']['collector_1.' + label], 0)
            state = {}
            report = health.track_observation(state, result, 2000)
            for label in ('authentication', 'send_mode', 'session_permissions'):
                self.assertIn('collector_1.' + label, report['issues'])
            self.assertEqual(state['issues']['collector_1.import_failure']['first'], 2000)

    @patch.object(health, 'rpc_status', return_value={'connected': True, 'auth_expired': False, 'offline': False, 'send_mode': 'off'})
    def test_import_and_loom_transient_retry_and_persistent_failure(self, rpc):
        worker = {'ActiveState': 'failed', 'Result': 'exit-code'}
        def unit(name):
            if name in ('minbox-text-import@Casey.service', 'minbox-text-loom.service'):
                return worker
            return {'ActiveState': 'active', 'UnitFileState': 'enabled', 'Result': 'success'}
        with tempfile.TemporaryDirectory() as directory:
            config = self.fixture(Path(directory), 1100)
            config['loom_monitor'] = True
            with closing(sqlite3.connect(config['archive'])) as db:
                db.execute('CREATE TABLE loom_worker(id,last_completed_at)')
                db.execute('CREATE TABLE loom_queue(owner,status,discovered_at,failure_since)')
                db.execute('INSERT INTO loom_worker VALUES (?,?)', (1, '1970-01-01T00:16:40+00:00'))
                db.commit()
            # Ignore backlog for this worker failure test.
            with closing(sqlite3.connect(Path(config['collectors']) / 'Casey/gmcli.db')) as db:
                db.execute("DELETE FROM messages WHERE message_id='missing'")
                db.commit()
            keys = {'collector_1.import_failure', 'loom.worker_failure'}
            with patch.object(health, 'unit_properties', side_effect=unit):
                state = {}
                failed = health.observe(config, 1100)
                self.assertEqual(failed['issues'], dict.fromkeys(keys, health.WORKER_FAILURE_GRACE))
                health.track_observation(state, failed, 1100)
                worker.update(ActiveState='active', Result='success')
                running = health.observe(config, 1220)
                self.assertTrue(keys.issubset(running['deferred_recoveries']))
                health.track_observation(state, running, 1220)
                self.assertTrue(all(record['first'] == 1100 for record in state['issues'].values()))
                worker['ActiveState'] = 'inactive'
                health.track_observation(state, health.observe(config, 1340), 1340)
                self.assertFalse(state['issues'])
                worker.update(ActiveState='failed', Result='exit-code')
                health.track_observation(state, health.observe(config, 1340), 1340)
                # Keep completed-run freshness independent of failure persistence.
                with closing(sqlite3.connect(config['archive'])) as db:
                    stamp = '1970-01-01T00:30:00+00:00'
                    db.execute('UPDATE imports SET imported_at=?', (stamp,))
                    db.execute('UPDATE loom_worker SET last_completed_at=?', (stamp,))
                    db.commit()
                health.track_observation(state, health.observe(config, 1939), 1939)
                self.assertTrue(all(record['first'] == 1340 for record in state['issues'].values()))
                health.track_observation(state, health.observe(config, 1940), 1940)
                self.assertTrue(all(record['first'] == 1340 for record in state['issues'].values()))
                self.assertEqual(set(state['issues']), keys)

    def test_check_failure_sanitized(self):
        with patch.object(health, 'unit_properties', side_effect=RuntimeError('SECRET')), patch.object(health, 'rpc_status', side_effect=RuntimeError('SECRET')):
            result = health.observe({'archive': '/nonexistent/archive', 'collectors': '/nonexistent'}, 0)
            self.assertTrue(result['check_failed'])
            self.assertNotIn('SECRET', json.dumps(result))

    @patch.object(health, 'rpc_status', return_value={'connected': True, 'auth_expired': False, 'offline': False, 'send_mode': 'off'})
    def test_inactive_success_import_and_low_disk(self, rpc):
        def unit(name):
            return {'ActiveState': 'inactive' if name.endswith('import@Casey.service') else 'active',
                    'UnitFileState': 'enabled', 'Result': 'success'}
        with tempfile.TemporaryDirectory() as directory:
            config = self.fixture(Path(directory), 1100)
            with patch.object(health, 'unit_properties', side_effect=unit), patch.object(health.shutil, 'disk_usage', return_value=type('Usage', (), {'free': 1024, 'total': 100000})()):
                result = health.observe(config, 1100)
            self.assertEqual(result['issues'], {'disk.low': 0})

    @patch.object(health, 'rpc_status', return_value={'connected': True, 'auth_expired': False, 'offline': False, 'send_mode': 'off'})
    def test_auto_enrollment_skips_unpaired_accounts(self, rpc):
        def unit(name):
            return {'ActiveState': 'active', 'UnitFileState': 'disabled' if 'Jordan' in name else 'enabled', 'Result': 'success'}
        with tempfile.TemporaryDirectory() as directory:
            config = self.fixture(Path(directory), 1100)
            config.update(owners=['Casey', 'Jordan'], auto_enroll=True)
            with patch.object(health, 'unit_properties', side_effect=unit):
                result = health.observe(config, 1100)
            self.assertFalse(result['issues'])
            self.assertEqual(rpc.call_count, 1)

    @patch.object(health, 'rpc_status', side_effect=RuntimeError('unavailable'))
    @patch.object(health, 'unit_properties', return_value={'ActiveState': 'inactive', 'UnitFileState': 'enabled', 'Result': 'success'})
    def test_enabled_account_without_session_is_monitored(self, units, rpc):
        with tempfile.TemporaryDirectory() as directory:
            config = self.fixture(Path(directory), 1100)
            config.update(owners=['Casey', 'Jordan'], auto_enroll=True)
            result = health.observe(config, 1100)
            self.assertIn('collector_2.session_permissions', result['issues'])
            self.assertIn('collector_2.service', result['issues'])

    @patch.object(health, 'rpc_status', return_value={'connected': True, 'auth_expired': False, 'offline': False, 'send_mode': 'off'})
    @patch.object(health, 'unit_properties', return_value={'ActiveState': 'active', 'UnitFileState': 'enabled', 'Result': 'success'})
    def test_loom_health_fresh_and_aged_failure(self, units, rpc):
        with tempfile.TemporaryDirectory() as directory:
            config = self.fixture(Path(directory), 1100)
            config['loom_monitor'] = True
            with closing(sqlite3.connect(config['archive'])) as db:
                db.execute('CREATE TABLE loom_worker(id,last_completed_at)')
                db.execute('CREATE TABLE loom_queue(owner,status,discovered_at,failure_since)')
                db.execute('INSERT INTO loom_worker VALUES (?,?)', (1, '1970-01-01T00:16:40+00:00'))
                db.execute('INSERT INTO loom_queue VALUES (?,?,?,?)', ('Casey', 'network_error', '1970-01-01T00:00:00+00:00', '1970-01-01T00:00:00+00:00'))
                db.commit()
            self.assertFalse(health.observe(config, 1100)['issues'])
            result = health.observe(config, 4000)
            self.assertIn('loom.worker_stale', result['issues'])
            self.assertIn('collector_1.loom_capture_pending', result['issues'])

    def test_delivery_requires_encryption(self):
        with self.assertRaises(ValueError):
            health.send_notification({'type': 'ntfy', 'url': 'http://example.invalid/topic'}, 'test')
        with self.assertRaises(ValueError):
            health.send_notification({'type': 'smtp', 'security': 'plain', 'from': 'a@example.invalid', 'to': 'b@example.invalid'}, 'test')

    def test_atomic_private_files(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state/state.json'
            health.atomic_json(path, {'safe': True})
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
            self.assertEqual(json.loads(path.read_text()), {'safe': True})


if __name__ == '__main__':
    unittest.main()
