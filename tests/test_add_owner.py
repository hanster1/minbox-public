"""scripts/add-owner on a temporary HOME; never touches systemd or a real account."""
import importlib.machinery
import importlib.util
import io
import json
import os
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts' / 'add-owner'


def load(home):
    with patch.dict(os.environ, {'HOME': str(home), 'MINBOX_PROTECTED_OWNERS': 'Jordan'}):
        loader = importlib.machinery.SourceFileLoader('add_owner_%d' % id(home), str(SCRIPT))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
    return module


class AddOwnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.mod = load(self.home)
        lib = self.mod.LIB
        (lib / 'bin').mkdir(parents=True)
        (lib / 'bin' / 'gmcli').write_text('#!/bin/sh\n')
        for name in ('local_archive_export.py', 'archive_corrections.py', 'archive_io.py'):
            shutil.copy(ROOT / name, lib / name)
        self.mod.UNITS.mkdir(parents=True)
        for t in self.mod.REQUIRED_TEMPLATES:
            shutil.copy(ROOT / 'services' / t, self.mod.UNITS / t)
        self.mod.ARCHIVE_ROOT.mkdir(parents=True)
        (self.mod.ARCHIVE_ROOT / 'archive.sqlite3').write_bytes(b'')

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = self.mod.main([*args, '--no-systemd'])
        return code, out.getvalue(), err.getvalue()

    def test_dry_run_changes_nothing(self):
        before = sorted(p.relative_to(self.home) for p in self.home.rglob('*'))
        code, out, _ = self.run_cli('Casey', '--dry-run')
        self.assertEqual(code, 0)
        self.assertIn('[dry-run]', out)
        self.assertEqual(before, sorted(p.relative_to(self.home) for p in self.home.rglob('*')))

    def test_prepare_is_private_idempotent_and_marked(self):
        self.assertEqual(self.run_cli('Casey')[0], 0)
        p = self.mod.paths('Casey')
        marker = json.loads(p['marker'].read_text())
        self.assertEqual(marker['created_by'], 'add-owner')
        self.assertEqual(p['marker'].stat().st_mode & 0o777, 0o600)
        self.assertEqual(p['store'].stat().st_mode & 0o777, 0o700)
        self.assertTrue(p['ledger'].is_file())
        code, out, _ = self.run_cli('Casey')
        self.assertEqual(code, 0)
        self.assertIn('already prepared', out)

    def test_refuses_protected_and_hand_built_owners(self):
        self.assertEqual(self.run_cli('Jordan')[0], 3)
        store = self.mod.paths('Riley')['store']
        store.mkdir(parents=True)
        (store / 'session.json').write_text('{}')
        code, _, err = self.run_cli('Riley')
        self.assertEqual(code, 3)
        self.assertIn('not created by add-owner', err)

    def test_enable_requires_pairing_and_rejects_bad_names(self):
        self.run_cli('Casey')
        self.assertEqual(self.run_cli('Casey', '--enable')[0], 3)
        self.assertEqual(self.run_cli('casey')[0], 2)

    def test_missing_prerequisites_reported(self):
        (self.mod.LIB / 'bin' / 'gmcli').unlink()
        code, _, err = self.run_cli('Casey')
        self.assertEqual(code, 1)
        self.assertIn('collector binary missing', err)


if __name__ == '__main__':
    unittest.main()
