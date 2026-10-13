import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import configure_gmail


class ConfigureEmailTests(unittest.TestCase):
    def run_setup(self, secret, fail=False):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            path = home / '.config/minbox-text-archive/health.json'
            path.parent.mkdir(parents=True)
            original = {'owners': ['Casey'], 'delivery': {'type': 'none'}}
            path.write_text(json.dumps(original)); path.chmod(0o600)
            output = io.StringIO()
            with patch.object(configure_gmail.Path, 'home', return_value=home), patch('sys.argv', ['setup', '--address', 'person@gmail.com']), patch('sys.stdin', io.StringIO(secret)), patch.object(configure_gmail, 'send_notification', side_effect=RuntimeError(secret) if fail else None) as sender, contextlib.redirect_stdout(output):
                result = configure_gmail.main()
            self.assertNotIn(secret, output.getvalue())
            return result, json.loads(path.read_text()), sender.call_count, path.stat().st_mode & 0o777

    def test_acceptance_saves_private_config(self):
        code, config, sends, mode = self.run_setup('abcdefghijklmnop')
        self.assertEqual((code, sends, mode), (0, 1, 0o600))
        self.assertEqual(config['delivery']['to'], 'person@gmail.com')

    def test_failure_preserves_config_and_hides_secret(self):
        code, config, sends, mode = self.run_setup('abcdefghijklmnop', fail=True)
        self.assertEqual((code, sends), (1, 1))
        self.assertEqual(config['delivery'], {'type': 'none'})

    def test_invalid_secret_never_sends(self):
        code, config, sends, mode = self.run_setup('not-an-app-password')
        self.assertEqual((code, sends), (1, 0))
        self.assertEqual(config['delivery'], {'type': 'none'})
