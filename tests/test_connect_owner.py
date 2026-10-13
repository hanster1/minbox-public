import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import connect_owner as setup


class SecureOwnerConnect(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = Path(self.tmp.name) / 'owners'
        directory = self.config / 'Taylor'
        directory.mkdir(parents=True)
        credential = directory / 'credentials.json'
        credential.write_text(json.dumps({'type':'authorized_user','refresh_token':'synthetic-sensitive-value'}))
        credential.chmod(0o600)
        self.binding = directory / 'drive.json'
        self.binding.write_text(json.dumps({'owner':'Taylor','google_account_email':'taylor@example.invalid',
            'credentials_file':str(credential),'folder_id':'synthetic-folder',
            'archive_root_folder_id':'synthetic-folder','folder_access':'selected_folder',
            'google_scopes':['https://www.googleapis.com/auth/drive.file']}))
        self.binding.chmod(0o600)
        self.args = setup.parser().parse_args(['--owner','Taylor','--account-email','taylor@example.invalid',
            '--host','archivehost','--reuse-authorization','--config-dir',str(self.config)])
        self.calls = []

    def execute(self, command, **kwargs):
        self.calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout=b'{"publisher_config":"/private/config.json"}')

    def test_secret_stdin_only_and_ssh_destination_paths(self):
        result = setup.connect(self.args, execute=self.execute)
        self.assertEqual(len(self.calls), 3)
        command, options = self.calls[1]
        self.assertNotIn('synthetic-sensitive-value', ' '.join(command))
        self.assertIn('synthetic-sensitive-value', options['input'].decode())
        self.assertIn('StrictHostKeyChecking=yes', command)
        self.assertIn('BatchMode=yes', command)
        self.assertIn('"$HOME/.local/share/minbox-text-archive"', self.calls[2][0][-1])
        self.assertNotIn('synthetic-sensitive-value', json.dumps(result))

    def test_wrong_account_and_recipient_failure_before_transfer(self):
        self.args.account_email = 'wrong@example.invalid'
        with self.assertRaises(ValueError):
            setup.connect(self.args, execute=self.execute)
        self.assertEqual(len(self.calls), 1)
        self.assertNotIn('input', self.calls[0][1])
        self.args.account_email = 'taylor@example.invalid'
        with self.assertRaises(RuntimeError):
            setup.connect(self.args, execute=lambda *a,**k:subprocess.CompletedProcess([],1,stdout=b'secret'))

    def test_explicit_activation_only_after_receive_and_provision(self):
        self.args.activate = True
        setup.connect(self.args, execute=self.execute)
        self.assertEqual(len(self.calls), 4)
        self.assertIn('activate_owner.py', self.calls[-1][0][-1])
        self.assertNotIn('--publish-now', self.calls[2][0][-1])

    def test_ssh_arguments_are_quoted_and_alias_validated(self):
        with self.assertRaises(ValueError):
            setup.ssh_command('archivehost;malicious', ['owner_onboarding.py','receive'])
        command = setup.ssh_command('archivehost',['owner_onboarding.py','provision','--archive-root','/private/path with spaces'])
        self.assertIn("'/private/path with spaces'", command[-1])

    def test_local_setup_defaults_use_private_runtime_and_no_ssh(self):
        self.args.host = None
        with patch('owner_onboarding.provision', return_value={'publisher_config':'/private/config'}) as provision:
            setup.connect(self.args, execute=self.execute)
        self.assertFalse(self.calls)
        self.assertTrue(str(provision.call_args.args[3]).endswith('Taylor-full.json'))
        self.assertTrue(str(provision.call_args.args[4]).endswith('Taylor-full'))

    def test_public_credential_file_and_wrong_owner_refused(self):
        credentials = Path(json.loads(self.binding.read_text())['credentials_file'])
        credentials.chmod(0o644)
        with self.assertRaises(ValueError):
            setup.envelope('Taylor', self.config)
        credentials.chmod(0o600)
        data = json.loads(self.binding.read_text());data['owner']='Morgan'
        self.binding.write_text(json.dumps(data))
        with self.assertRaises(ValueError):
            setup.envelope('Taylor', self.config)
