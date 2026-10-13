import json
import os
from pathlib import Path
import plistlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import mac_support as support


class SupportReport(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.support = self.home / 'Library/Application Support/Minbox Text Archive'

    def private(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))
        path.chmod(0o600)

    def test_missing_partial_and_corrupt_installations_report_per_check(self):
        with patch.object(support.shutil, 'which', return_value=None):
            empty = support.report('Alex', self.home)
            self.assertEqual(empty['stage'], 'installation_required')
            self.private(self.support / 'installation-Alex.json', {'owner': 'Alex'})
            (self.support / 'installation-Alex.json').write_text('{corrupt')
            self.private(self.support / 'operation-journal-Alex.json', {'owner': 'Alex'})
            report = support.report('Alex', self.home)
        self.assertEqual(report['installation']['state'], 'invalid')
        self.assertEqual(report['pending_recovery']['state'], 'valid')
        self.assertEqual(report['stage'], 'recovery_required')
        self.assertEqual(report['jobs']['collector']['state'], 'missing')
        self.assertFalse(report['mutations'])

    def test_no_application_import_archive_credentials_or_auth_reads_and_no_provider_output(self):
        config = self.home / 'secret credentials.json'
        config.write_text('TOKEN_EMAIL_PRIVATE_MESSAGE')
        config.chmod(0o600)
        self.private(self.support / 'installation-Alex.json', {'owner': 'Alex',
                       'publisher_config': {'path': str(config)}})
        real_read = Path.read_text
        def guarded(path, *args, **kwargs):
            if path == config or '.codex' in str(path) or 'chat.db' in str(path):
                raise AssertionError('private content read')
            return real_read(path, *args, **kwargs)
        with patch.object(Path, 'read_text', guarded), patch.object(support.shutil, 'which', return_value='/agent'), \
                patch.object(support.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0,
                            stdout=b'TOKEN_EMAIL_PRIVATE_MESSAGE', stderr=b'TOKEN_EMAIL_PRIVATE_MESSAGE')) as run:
            report = support.report('Alex', self.home)
        self.assertNotIn('TOKEN_EMAIL_PRIVATE_MESSAGE', json.dumps(report))
        self.assertTrue(report['agents']['codex']['available'])
        for call in run.call_args_list:
            self.assertEqual(call.kwargs['timeout'], 5)
        self.assertEqual(report['publisher_config']['state'], 'present')

    def test_probe_failures_and_unsafe_paths_are_sanitized(self):
        (self.home / 'Library').symlink_to(self.home / 'missing')
        with patch.object(support.shutil, 'which', return_value='/agent'), \
                patch.object(support.subprocess, 'run', side_effect=subprocess.TimeoutExpired('secret', 5)):
            report = support.report('Alex', self.home)
        self.assertEqual(report['installation']['state'], 'unavailable')
        self.assertEqual(report['agents']['claude']['version_probe'], 'timeout')
        self.assertNotIn('secret', json.dumps(report))

    def test_installed_hashes_and_status_whitelist_never_emit_content(self):
        import hashlib
        app = self.support / 'app/mac_messages.py'
        app.parent.mkdir(parents=True)
        app.write_bytes(b'# PRIVATE_SOURCE')
        app.chmod(0o600)
        self.private(self.support / 'installation-Alex.json', {'owner': 'Alex', 'files': {
            str(app): hashlib.sha256(app.read_bytes()).hexdigest()}})
        self.private(self.support / 'collector-status.json', {
            'last_success_at': '2026-10-13T12:00:00+00:00', 'imported': 3,
            'reason': 'PRIVATE_SOURCE', 'message_count': 'PRIVATE_SOURCE'})
        self.private(self.support / 'publisher/status.json', {'error_category': 'transport', 'reason': 'PRIVATE_SOURCE'})
        with patch.object(support.shutil, 'which', return_value=None):
            report = support.report('Alex', self.home)
            self.assertEqual(report['installed_integrity']['matched'], 1)
            self.assertEqual(report['jobs']['collector']['status']['summary']['imported'], 3)
            self.assertEqual(report['jobs']['publisher']['status']['summary']['error_category'], 'transport')
            self.assertNotIn('PRIVATE_SOURCE', json.dumps(report))
            app.write_bytes(b'# changed')
            self.assertEqual(support.report('Alex', self.home)['installed_integrity']['changed'], 1)

    def test_normal_venv_interpreter_symlink_is_stat_only_and_supported(self):
        import sys
        path = self.support / 'venv/bin/python3'
        path.parent.mkdir(parents=True)
        path.symlink_to(sys.executable)
        with patch.object(support.shutil, 'which', return_value=None), \
                patch.object(support.subprocess, 'run') as run:
            result = support.report('Alex', self.home)
        self.assertEqual(result['venv_python']['state'], 'present')
        self.assertTrue(result['venv_python']['executable'])
        self.assertTrue(result['venv_python']['symlink'])
        self.assertNotIn(sys.executable, json.dumps(result))
        run.assert_not_called()

    def test_bundle_is_private_outside_git_no_overwrite(self):
        bundle = self.home / 'support.json'
        support.bundle_write(bundle, {'sanitized': True})
        self.assertEqual(bundle.stat().st_mode & 0o777, 0o600)
        with self.assertRaises(FileExistsError):
            support.bundle_write(bundle, {})
        git = self.home / 'repo'
        (git / '.git').mkdir(parents=True)
        (git / '.git/HEAD').write_text('ref: fixture')
        with self.assertRaisesRegex(ValueError, 'outside Git'):
            support.bundle_write(git / 'report.json', {})
