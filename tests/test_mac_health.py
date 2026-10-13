import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import plistlib
import sys
import tempfile
import unittest
from unittest.mock import patch

import mac_health as h


class MacHealthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.support = self.home / 'Library/Application Support/Minbox Text Archive'
        self.support.mkdir(parents=True, mode=0o700)
        self.label = h.LABEL + '.collector.Alex'
        self.now = 2000000000
        self.actions = []
        self.sent = []
        self.state = {}
        self.jobs = {self.label: {'kind': 'collector', 'owner': 'Alex', 'essential': True,
                                 'enabled': True, 'status_path': self.support / 'collector-status.json'}}
        self.live = {self.label: {'loaded': True, 'running': False, 'disabled': False, 'exit_code': 0}}
        self.status(status='imported', health='ok')

    def put(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value if isinstance(value, bytes) else json.dumps(value).encode())
        path.chmod(0o600)

    def status(self, **values):
        self.put(self.jobs[self.label]['status_path'], {'owner': 'Alex', 'source': 'apple-messages',
            'last_checked_at': datetime.fromtimestamp(self.now, timezone.utc).isoformat(), **values})

    def run_control(self, now=None, **kwargs):
        return h.control(self.jobs, self.live, self.state, self.now if now is None else now,
                         action=self.actions.append, deliver=self.sent.append, **kwargs)

    def fixture(self):
        script = self.support / 'app/mac_messages.py'
        self.put(script, b'# fixture\n')
        unit = {'Label': self.label, 'ProgramArguments': [str(Path(sys.executable).resolve()), str(script), '--root', str(self.home / 'archive'),
            '--owner', 'Alex', '--database', str(self.home / 'Library/Messages/chat.db'), '--status-file',
            str(self.support / 'collector-status.json'), '--max-messages', '10000', '--max-bytes', '1048576'],
            'WorkingDirectory': str(script.parent), 'Disabled': False}
        plist = self.home / 'Library/LaunchAgents' / (self.label + '.plist')
        self.put(plist, plistlib.dumps(unit))
        self.put(self.support / 'installation-Alex.json', {'version': 1, 'owner': 'Alex', 'enabled': [self.label],
            'files': {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in (script, plist)}})

    def test_fresh_quiet_capture_is_healthy(self):
        self.status(status='imported', imported=0)
        result = self.run_control()
        self.assertTrue(result['healthy'])
        self.assertEqual(self.actions, [])

    def test_bounded_retry_and_one_emergency_no_recovery_email(self):
        self.status(status='error')
        for offset in (0, 59, 60, 359, 360, 1259, 1260, 1800, 3600):
            self.run_control(self.now + offset)
        self.assertEqual(len(self.actions), 3)
        self.assertEqual(len(self.sent), 1)
        self.now += 3601
        self.status(status='imported')
        self.run_control()
        self.assertEqual(len(self.sent), 1)
        self.assertTrue(self.state['episodes'][self.label]['notified'])
        self.now += 21600
        self.status(status='imported')
        self.run_control()
        self.assertEqual(self.state['episodes'], {})

    def test_missing_loaded_job_never_bootstrapped(self):
        self.live[self.label]['loaded'] = False
        self.run_control()
        self.run_control(self.now + 1801)
        self.assertEqual(self.actions, [])
        self.assertEqual(len(self.sent), 1)

    def test_disabled_manifest_pause_and_installer_hold(self):
        self.status(status='error')
        for mode in ('disabled', 'manifest', 'global'):
            live, jobs = copy.deepcopy(self.live), copy.deepcopy(self.jobs)
            if mode == 'disabled':
                live[self.label]['disabled'] = True
            if mode == 'manifest':
                jobs[self.label]['enabled'] = False
            result = h.control(jobs, live, {}, self.now, paused=mode == 'global', action=self.actions.append, deliver=self.sent.append)
            self.assertEqual(result['actions'], [])
        self.assertEqual(self.sent, [])
        self.fixture()
        self.put(self.support / 'operation-journal-Alex.json', b'corrupt pending transaction')
        result = h.check('Alex', self.home, info=lambda labels: self.live, action=self.actions.append, clock=lambda: self.now)
        self.assertTrue(result['mutations_suppressed'])

    def test_human_conditions_immediate_and_notification_failure_retries(self):
        for category in ('auth', 'privacy', 'integrity', 'tcc'):
            state = {}
            live = {self.label: {'hold': category}}
            def fail(body):
                raise RuntimeError('secret provider text')
            result = h.control(self.jobs, live, state, self.now, deliver=fail)
            self.assertEqual(result['delivery'], 'failed')
            self.assertFalse(state['episodes'][self.label]['notified'])
            h.control(self.jobs, live, state, self.now + 60, deliver=self.sent.append)
            h.control(self.jobs, live, state, self.now + 120, deliver=self.sent.append)
        self.assertEqual(len(self.sent), 4)
        self.assertEqual(self.actions, [])

    def test_publisher_busy_no_kill_and_overdue_local_observation(self):
        job = self.jobs[self.label]
        job.update(kind='publisher', essential=False)
        self.live[self.label]['running'] = True
        self.put(job['status_path'], {'run_state': 'running', 'phase': 'publishing',
            'started_at': datetime.fromtimestamp(self.now, timezone.utc).isoformat()})
        self.assertEqual(self.run_control()['components'][self.label], 'busy')
        result = self.run_control(self.now + 3600)
        self.assertEqual(result['components'][self.label], 'running_overdue')
        self.assertEqual(self.actions, [])
        self.assertEqual(self.sent, [])

    def test_successful_action_does_not_mark_healthy(self):
        self.status(status='error')
        self.run_control()
        result = self.run_control(self.now + 60)
        self.assertFalse(result['healthy'])
        self.assertEqual(len(self.actions), 1)
        self.assertIn(self.label, self.state['episodes'])

    def test_plan_does_not_create_health_files_or_notify(self):
        self.fixture()
        before = set(self.home.rglob('*'))
        result = h.check('Alex', self.home, plan=True, info=lambda labels: self.live,
                         deliver=self.sent.append, action=self.actions.append, clock=lambda: self.now)
        self.assertTrue(result['healthy'])
        self.assertEqual(before, set(self.home.rglob('*')))
        self.assertEqual(self.sent + self.actions, [])

    def test_hash_drift_untracked_path_and_status_owner_hold(self):
        self.fixture()
        self.put(self.support / 'app/mac_messages.py', b'changed')
        result = h.check('Alex', self.home, plan=True, info=lambda labels: self.live, clock=lambda: self.now)
        self.assertEqual(list(result['components'].values()), ['integrity'])
        self.status(status='imported', owner='Other')
        self.assertEqual(self.run_control()['components'][self.label], 'privacy')
        manifest = self.support / 'installation-Alex.json'
        self.put(manifest, {'version': 1, 'owner': 'Alex', 'files': {'/etc/passwd': 'a'}, 'enabled': []})
        with self.assertRaises(h.Hold):
            h.installation(self.home, 'Alex')

    def test_unknown_manifest_and_private_permissions(self):
        result = h.check('Alex', self.home, info=lambda labels: self.live, clock=lambda: self.now)
        self.assertEqual(list(result['components'].values()), ['observability_unknown'])
        directory = self.support / 'health/Alex'
        self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
        for name in ('state.json', 'report.json', 'lock'):
            self.assertEqual((directory / name).stat().st_mode & 0o777, 0o600)
        (directory / 'report.json').unlink()
        (directory / 'report.json').symlink_to(self.support / 'collector-status.json')
        with self.assertRaises(h.Hold):
            h.check('Alex', self.home, info=lambda labels: self.live, clock=lambda: self.now)

    def test_launchctl_parser_and_no_kill_command(self):
        responses = [type('R', (), {'returncode': 0, 'stdout': '{\n"' + self.label + '" => false\n}'})(),
                     type('R', (), {'returncode': 0, 'stdout': ' state = waiting\n last exit code = 1\n'})()]
        with patch('mac_health.subprocess.run', side_effect=responses):
            info = h.launch_info([self.label])
        self.assertFalse(info[self.label]['running'])
        self.assertEqual(info[self.label]['exit_code'], 1)
        with patch('mac_health.subprocess.run') as run:
            h.kickstart(self.label)
            self.assertEqual(run.call_args.args[0], ['/bin/launchctl', 'kickstart', f'gui/{os.getuid()}/{self.label}'])

    def test_hashed_venv_interpreter_symlink_is_preserved(self):
        self.fixture()
        executable = self.home / 'venv/bin/python'
        executable.parent.mkdir(parents=True)
        executable.symlink_to(Path(sys.executable).resolve())
        plist = self.home / 'Library/LaunchAgents' / (self.label + '.plist')
        unit = plistlib.loads(plist.read_bytes())
        unit['ProgramArguments'][0] = str(executable)
        self.put(plist, plistlib.dumps(unit))
        manifest = self.support / 'installation-Alex.json'
        value = json.loads(manifest.read_text())
        value['files'][str(plist)] = hashlib.sha256(plist.read_bytes()).hexdigest()
        self.put(manifest, value)
        result = h.check('Alex', self.home, plan=True, info=lambda labels: self.live, clock=lambda: self.now)
        self.assertTrue(result['healthy'])
        self.assertEqual(unit['ProgramArguments'][0], str(executable))

    def test_flapping_notice_latch_and_source_unavailable_category(self):
        self.status(status='error', error_code='database_unavailable')
        self.assertEqual(self.run_control()['components'][self.label], 'source_unavailable')
        self.assertEqual(len(self.sent), 0)
        for offset in (60, 360, 1260, 1800):
            self.run_control(self.now + offset)
        self.assertEqual(len(self.sent), 1)
        self.now += 1800
        self.now += 60
        self.status(status='imported')
        self.run_control()
        self.now += 60
        self.status(status='error', error_code='database_unavailable')
        self.run_control()
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(len(self.actions), 3)

    def test_full_publisher_status_and_progress_are_observed(self):
        self.fixture()
        publisher = h.LABEL + '.publisher.Alex'
        script = self.support / 'app/owner_publish_cli.py'
        self.put(script, b'# publisher fixture\n')
        config = self.support / 'config/publisher.json'
        status = self.support / 'publisher/status.json'
        self.put(config, {'owner': 'Alex', 'scope': 'owner_all',
                         'archive_root': str(self.home / 'archive'), 'status_file': str(status)})
        self.put(status, {'run_state': 'succeeded', 'checked_at': datetime.fromtimestamp(self.now, timezone.utc).isoformat()})
        plist = self.home / 'Library/LaunchAgents' / (publisher + '.plist')
        unit = {'Label': publisher, 'ProgramArguments': [str(Path(sys.executable).resolve()), str(script), '--config', str(config)],
                'WorkingDirectory': str(script.parent), 'Disabled': False}
        self.put(plist, plistlib.dumps(unit))
        manifest = self.support / 'installation-Alex.json'
        value = json.loads(manifest.read_text())
        value['enabled'].append(publisher)
        value['files'].update({str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in (script, plist)})
        value['publisher_config'] = {'path': str(config), 'sha256': hashlib.sha256(config.read_bytes()).hexdigest()}
        self.put(manifest, value)
        live = {**self.live, publisher: {'loaded': True, 'running': False, 'disabled': False, 'exit_code': 0}}
        result = h.check('Alex', self.home, plan=True, info=lambda labels: live, clock=lambda: self.now)
        self.assertTrue(result['healthy'])
        self.assertEqual(result['components'][publisher], 'healthy')
        self.put(status, {'run_state': 'running', 'started_at': datetime.fromtimestamp(self.now - 4000, timezone.utc).isoformat(),
                          'heartbeat_at': datetime.fromtimestamp(self.now, timezone.utc).isoformat()})
        _, jobs = h.installation(self.home, 'Alex')
        live[publisher]['running'] = True
        self.assertEqual(h.observe(jobs[publisher], live[publisher], self.now), ('busy', False))

    def test_unknown_optional_is_local_and_essential_has_grace(self):
        self.put(self.jobs[self.label]['status_path'], b'bad status')
        result = self.run_control()
        self.assertEqual(result['pending_alerts'], [])
        self.run_control(self.now + 1800)
        self.assertEqual(len(self.sent), 1)
        self.sent.clear()
        self.state.clear()
        self.jobs[self.label]['essential'] = False
        self.run_control(self.now)
        self.run_control(self.now + 1800)
        self.assertEqual(self.sent, [])

    def test_setup_lock_holds_monitor_without_observation(self):
        import fcntl
        fd = os.open(self.support / '.operation.lock', os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with patch('mac_health.installation') as observe:
                result = h.check('Alex', self.home)
            observe.assert_not_called()
            self.assertEqual(result['status'], 'setup_in_progress')
            self.assertFalse((self.support / 'health').exists())
        finally:
            os.close(fd)

    def test_unknown_global_observation_breaks_continuous_health(self):
        self.fixture()
        directory = self.support / 'health/Alex'
        directory.mkdir(parents=True, mode=0o700)
        directory.parent.chmod(0o700)
        self.put(directory / 'state.json', {'version': 1, 'owner': 'Alex', 'episodes': {
            self.label: {'since': self.now - 30000, 'attempts': 3, 'last_attempt': self.now - 29000,
                         'notified': True, 'healthy_since': self.now - 21500}}})
        with patch('mac_health.installation', side_effect=h.Hold('observability_unknown')):
            h.check('Alex', self.home, info=lambda labels: self.live, clock=lambda: self.now)
        state = json.loads((directory / 'state.json').read_text())
        self.assertNotIn('healthy_since', state['episodes'][self.label])
        self.assertTrue(state['episodes'][self.label]['notified'])

    def test_optional_transient_outage_does_not_notify(self):
        self.jobs[self.label]['essential'] = False
        self.status(status='error')
        for offset in (0, 60, 360, 1260, 5000):
            self.run_control(self.now + offset)
        self.assertEqual(len(self.actions), 3)
        self.assertEqual(self.sent, [])


if __name__ == '__main__':
    unittest.main()
