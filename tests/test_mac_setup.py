import contextlib
import io
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import mac_setup as setup


class MacSetup(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='mac fixture ')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.checkout = self.root / 'checkout'
        self.checkout.mkdir()
        for name in ('README.md', 'archive_cli.py', 'mac_messages.py', 'mac_setup.py',
                     'owner_publish_cli.py', 'archive_publish_cli.py'):
            (self.checkout / name).write_text('# fixture\n')
        (self.checkout / 'README.md').write_text('# Minbox text archive\n')
        (self.checkout / 'secret.env').write_text('never copy')
        self.home = self.root / 'owner home'
        self.args = setup.parser().parse_args([
            'install', '--owner', 'Alex', '--checkout', str(self.checkout),
            '--home', str(self.home), '--archive-root', str(self.root / 'archive data'),
            '--python', sys.executable])
        self.opts = setup.options(self.args)
        user_home = patch.object(setup.Path, 'home', return_value=self.home)
        user_home.start()
        self.addCleanup(user_home.stop)
        self.mac = patch.object(setup.platform, 'system', return_value='Darwin')
        self.mac.start()
        self.addCleanup(self.mac.stop)
        self.overrides = patch.object(setup, 'launch_overrides', side_effect=lambda labels: {label:None for label in labels})
        self.overrides.start()
        self.addCleanup(self.overrides.stop)
        self.loaded = patch.object(setup, 'launch_loaded', side_effect=lambda label: label in setup.read_manifest(self.opts, 'Alex')['enabled'])
        self.loaded.start()
        self.addCleanup(self.loaded.stop)
        self.launch = patch.object(setup, 'launch')
        self.calls = self.launch.start()
        self.addCleanup(self.launch.stop)
        self.preflight = patch.object(setup, 'doctor', return_value={
            'python_sqlite': True, 'messages_readable': True, 'google_modules': True,
            'codex_binary': True, 'codex_auth_present': True})
        self.preflight.start()
        self.addCleanup(self.preflight.stop)

    def publisher(self):
        creds = self.root / 'creds.json'
        creds.write_text('{}')
        creds.chmod(0o600)
        config = self.root / 'publisher.json'
        config.write_text(json.dumps({
            'owner': 'Alex', 'archive_root': str(self.opts['archive']),
            'conversations': ['private-thread'], 'start_date': '2026-10-01',
            'google_account_email': 'owner@example.invalid', 'folder_id': 'folder_identifier',
            'documents': {k: k + '_document_identifier' for k in
                          ('guide', 'messages', 'looms', 'knowledge', 'corrections', 'status')},
            'credentials_file': str(creds), 'analysis_path': str(self.root / 'analysis.sqlite3'),
            'correction_path': str(self.root / 'corrections.sqlite3')}))
        config.chmod(0o600)
        self.args.publisher_config = str(config)
        return config

    def full_publisher(self):
        path = self.publisher()
        config = json.loads(path.read_text())
        for key in ('conversations', 'start_date', 'analysis_path'):
            del config[key]
        config.update(scope='owner_all',
                      documents={k: config['documents'][k] for k in ('guide', 'corrections', 'status')},
                      manifest_file=str(self.root / 'owner manifest.json'),
                      status_file=str(self.root / 'owner status.json'))
        path.write_text(json.dumps(config))
        return path

    def update_args(self, plan=False):
        return setup.parser().parse_args([
            'update', '--owner', 'Alex', '--checkout', str(self.checkout),
            '--home', str(self.home), '--archive-root', str(self.opts['archive']),
            *(['--plan'] if plan else [])])

    def test_monitor_opt_in_and_saved_update_preserves_its_pause(self):
        label = 'com.minbox-text-archive.health.Alex'
        self.assertNotIn(label, setup.render(self.args))
        (self.checkout / 'mac_health.py').write_text('# health fixture\n')
        self.args.enable = True
        self.args.enable_monitor = True
        units = setup.render(self.args)
        self.assertEqual(units[label]['StartInterval'], 60)
        self.assertEqual(units[label]['ProgramArguments'][-3:], ['check', '--owner', 'Alex'])
        setup.install(self.args)
        self.calls.reset_mock()
        setup.launch_overrides.side_effect = lambda labels: {name: name == label for name in labels}
        result = setup.update(self.update_args())
        self.assertFalse(result['monitor_enabled'])
        plist = plistlib.loads((self.home / 'Library/LaunchAgents' / (label + '.plist')).read_bytes())
        self.assertTrue(plist['Disabled'])
        self.assertFalse(plist['RunAtLoad'])
        self.assertNotIn(('enable', label), [call.args for call in self.calls.call_args_list])
        self.assertIn(str(self.home / 'Library/LaunchAgents' / (label + '.plist')),
                      setup.read_manifest(self.opts, 'Alex')['files'])

    def test_installed_monitor_manifest_is_accepted_by_health_observer(self):
        import mac_health
        self.args.archive_root = str(self.home / 'archive')
        self.opts = setup.options(self.args)
        (self.checkout / 'mac_health.py').write_text('# health fixture\n')
        self.args.enable_monitor = True
        setup.install(self.args)
        support, jobs = mac_health.installation(self.home, 'Alex')
        self.assertEqual(support, self.opts['support'])
        self.assertIn('com.minbox-text-archive.collector.Alex', jobs)
        self.assertNotIn('com.minbox-text-archive.health.Alex', jobs)
        self.assertFalse(jobs['com.minbox-text-archive.collector.Alex']['enabled'])

    def interrupted(self, target_name, update=False):
        real_write = setup.write
        def interrupt(path, data, mode):
            real_write(path, data, mode)
            if path.name == target_name:
                raise KeyboardInterrupt('simulated process exit')
        with patch.object(setup, 'write', side_effect=interrupt):
            with self.assertRaises(KeyboardInterrupt):
                setup.update(self.update_args()) if update else setup.install(self.args)

    def test_interrupted_fresh_source_plist_manifest_recover_and_plan(self):
        for filename in ('mac_messages.py', 'com.minbox-text-archive.collector.Alex.plist', 'installation-Alex.json'):
            with self.subTest(filename=filename):
                self.interrupted(filename)
                journal = setup.journal_path(self.opts, 'Alex')
                before = journal.read_bytes()
                self.assertEqual(journal.stat().st_mode & 0o777, 0o600)
                self.calls.reset_mock()
                plan = self.update_args(plan=True)
                plan.command = 'recover'
                self.assertFalse(setup.recover(plan)['mutations'])
                self.assertEqual(journal.read_bytes(), before)
                self.assertFalse(self.calls.called)
                for operation in (setup.install, setup.update, setup.uninstall):
                    with self.assertRaisesRegex(ValueError, 'pending installation journal'):
                        operation(self.args if operation != setup.update else self.update_args())
                setup.recover(self.args)
                self.assertFalse(journal.exists())
                self.assertFalse(setup.manifest_path(self.opts, 'Alex').exists())
                self.assertFalse((self.opts['support'] / 'app/mac_messages.py').exists())

    def test_interrupted_update_restores_saved_files_preserves_archive_credentials_and_pause(self):
        config = self.full_publisher()
        self.args.enable = True
        setup.install(self.args)
        archive = self.opts['archive'] / 'archive.sqlite3'
        archive.write_bytes(b'private archive')
        credentials = Path(json.loads(config.read_bytes())['credentials_file'])
        originals = {p: p.read_bytes() for p in (config, archive, credentials,
                     self.opts['support'] / 'app/mac_messages.py', setup.manifest_path(self.opts, 'Alex'))}
        (self.checkout / 'mac_messages.py').write_text('# candidate source')
        self.interrupted('mac_messages.py', update=True)
        self.calls.reset_mock()
        setup.recover(self.update_args())
        for path, value in originals.items():
            self.assertEqual(path.read_bytes(), value)
        self.assertNotIn(('enable', 'com.minbox-text-archive.publisher.Alex'),
                         [call.args for call in self.calls.call_args_list])
        self.assertEqual([call.args[0] for call in self.calls.call_args_list].count('bootstrap'), 2)

    def test_interrupted_launch_operations_and_disabled_loaded_job_do_not_resume_pause(self):
        self.args.enable = True
        setup.install(self.args)
        before = setup.manifest_path(self.opts, 'Alex').read_bytes()
        for action in ('bootout', 'bootstrap'):
            with self.subTest(action=action):
                fired = False
                def interrupt(current, target):
                    nonlocal fired
                    if current == action and not fired:
                        fired = True
                        raise KeyboardInterrupt()
                    return True
                self.calls.side_effect = interrupt
                with self.assertRaises(KeyboardInterrupt):
                    setup.install(self.args)
                self.calls.side_effect = None
                self.calls.reset_mock()
                setup.recover(self.args)
                self.assertEqual(setup.manifest_path(self.opts, 'Alex').read_bytes(), before)
                self.assertEqual([call.args[0] for call in self.calls.call_args_list].count('bootstrap'), 2)
        setup.launch_overrides.side_effect = lambda labels: {label: True for label in labels}
        self.interrupted('mac_messages.py')
        self.calls.reset_mock()
        setup.recover(self.args)
        self.assertNotIn('enable', [call.args[0] for call in self.calls.call_args_list])
        self.assertNotIn('bootstrap', [call.args[0] for call in self.calls.call_args_list])

    def test_interrupted_uninstall_restores_only_owned_plists_and_manifest(self):
        self.args.enable = True
        setup.install(self.args)
        before = setup.manifest_path(self.opts, 'Alex').read_bytes()
        real_remove = setup.remove_file
        def interrupt(path):
            real_remove(path)
            if path.suffix == '.plist':
                raise KeyboardInterrupt()
        with patch.object(setup, 'remove_file', side_effect=interrupt):
            with self.assertRaises(KeyboardInterrupt):
                setup.uninstall(self.args)
        setup.recover(self.args)
        self.assertEqual(setup.manifest_path(self.opts, 'Alex').read_bytes(), before)
        setup.read_manifest(self.opts, 'Alex')

    def test_operation_lock_is_shared_across_owners_and_tmpdir_processes(self):
        # A separate process must contend with the same fixed lock even when
        # it selects another owner and another temporary directory.
        @setup.operation_lock
        def hold(args):
            code = "import mac_setup as s; s.require_mac=lambda:None; s.Path.home=lambda:s.Path(%r); a=" % str(self.home) + "s.parser().parse_args(['install','--owner','Other','--home',%r,'--archive-root',%r]); f=s.operation_lock(lambda a: None); f(a)" % (str(self.home), str(self.opts['archive']))
            environment = {**os.environ, 'TMPDIR': str(self.root)}
            result = subprocess.run([sys.executable, '-c', code], cwd=Path(setup.__file__).parent,
                                    env=environment, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(b'another local installation operation is active', result.stderr)
        hold(self.args)

    def test_pending_other_owner_blocks_installation(self):
        self.opts['support'].mkdir(parents=True)
        other = setup.journal_path(self.opts, 'Other')
        setup.write(other, b'{}', 0o600)
        self.calls.reset_mock()
        with self.assertRaisesRegex(ValueError, 'pending installation journal'):
            setup.install(self.args)
        self.assertFalse(self.calls.called)

    def test_recovery_preserves_new_external_pause_and_plan_is_read_only(self):
        self.args.enable = True
        setup.install(self.args)
        (self.checkout / 'mac_messages.py').write_text('# candidate')
        self.interrupted('mac_messages.py', update=True)
        journal = setup.journal_path(self.opts, 'Alex')
        before = journal.read_bytes()
        setup.launch_overrides.side_effect = lambda labels: {label: '.collector.' in label for label in labels}
        self.calls.reset_mock()
        plan = setup.recover(self.update_args(plan=True))
        self.assertEqual(plan['preserved_pauses'], 1)
        self.assertEqual(journal.read_bytes(), before)
        self.assertFalse(self.calls.called)
        result = setup.recover(self.args)
        self.assertEqual(result['preserved_pauses'], 1)
        calls = [call.args for call in self.calls.call_args_list]
        self.assertNotIn(('enable', 'com.minbox-text-archive.collector.Alex'), calls)
        self.assertFalse(any(action == 'bootstrap' and '.collector.' in str(target) for action, target in calls))
        self.assertEqual([action for action, target in calls].count('bootstrap'), 1)

    def test_unsupported_original_mode_refused_before_journal_or_job_changes(self):
        setup.install(self.args)
        app = self.opts['support'] / 'app/mac_messages.py'
        app.chmod(0o640)
        self.calls.reset_mock()
        with self.assertRaisesRegex(ValueError, 'unsupported original'):
            setup.install(self.args)
        self.assertFalse(self.calls.called)
        self.assertFalse(setup.journal_path(self.opts, 'Alex').exists())
        self.assertEqual(app.stat().st_mode & 0o777, 0o640)

    def test_coherently_changed_payload_and_missing_jobs_refused_by_inventory_binding(self):
        import base64
        setup.install(self.args)
        (self.checkout / 'mac_messages.py').write_text('# candidate')
        self.interrupted('mac_messages.py', update=True)
        path = setup.journal_path(self.opts, 'Alex')
        original = path.read_bytes()
        journal = json.loads(original)
        record = journal['files'][str(self.opts['support'] / 'app/mac_messages.py')]
        record['original'] = base64.b64encode(b'# malicious original').decode()
        record['original_sha256'] = setup.digest(b'# malicious original')
        setup.write(path, json.dumps(journal).encode(), 0o600)
        self.calls.reset_mock()
        with self.assertRaisesRegex(ValueError, 'manifest inventory'):
            setup.recover(self.args)
        self.assertFalse(self.calls.called)
        journal = json.loads(original)
        journal['jobs'].pop(next(iter(journal['jobs'])))
        setup.write(path, json.dumps(journal).encode(), 0o600)
        with self.assertRaisesRegex(ValueError, 'plist records'):
            setup.recover(self.args)
        self.assertFalse(self.calls.called)

    def test_valid_json_payload_corruption_refuses_before_mutating(self):
        setup.install(self.args)
        (self.checkout / 'mac_messages.py').write_text('# candidate')
        self.interrupted('mac_messages.py', update=True)
        path = setup.journal_path(self.opts, 'Alex')
        journal = json.loads(path.read_bytes())
        record = journal['files'][str(self.opts['support'] / 'app/mac_messages.py')]
        record['original'] = 'Y29ycnVwdA=='
        setup.write(path, json.dumps(journal).encode(), 0o600)
        before = path.read_bytes()
        self.calls.reset_mock()
        with self.assertRaisesRegex(ValueError, 'integrity'):
            setup.recover(self.args)
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse(self.calls.called)

    def test_recovery_conflict_and_wrong_binding_preserve_journal_and_files(self):
        self.interrupted('mac_messages.py')
        journal = setup.journal_path(self.opts, 'Alex')
        before = journal.read_bytes()
        target = self.opts['support'] / 'app/mac_messages.py'
        target.write_bytes(b'external edit')
        self.calls.reset_mock()
        with self.assertRaisesRegex(ValueError, 'conflict'):
            setup.recover(self.args)
        self.assertFalse(self.calls.called)
        self.assertEqual(journal.read_bytes(), before)
        self.assertEqual(target.read_bytes(), b'external edit')
        wrong = self.update_args(plan=True)
        wrong.archive_root = str(self.root / 'wrong archive')
        with self.assertRaisesRegex(ValueError, 'binding'):
            setup.recover(wrong)

    def test_recovery_can_resume_after_restoration_interruption(self):
        setup.install(self.args)
        original = (self.opts['support'] / 'app/mac_messages.py').read_bytes()
        (self.checkout / 'mac_messages.py').write_text('# next version')
        self.interrupted('mac_messages.py', update=True)
        real_write = setup.write
        def interrupt(path, data, mode):
            real_write(path, data, mode)
            if path.name == 'mac_messages.py':
                raise KeyboardInterrupt()
        with patch.object(setup, 'write', side_effect=interrupt):
            with self.assertRaises(KeyboardInterrupt):
                setup.recover(self.args)
        self.assertTrue(setup.journal_path(self.opts, 'Alex').exists())
        setup.recover(self.args)
        self.assertEqual((self.opts['support'] / 'app/mac_messages.py').read_bytes(), original)

    def test_update_preserves_interpreter_limits_private_config_data_and_pauses(self):
        config = self.full_publisher()
        config_before = config.read_bytes()
        credentials = Path(json.loads(config_before)['credentials_file'])
        self.args.enable = True
        self.args.max_messages = 250000
        self.args.max_bytes = 128 * 1024 * 1024
        self.args.messages_db = str(self.root / 'custom Messages.sqlite3')
        setup.install(self.args)
        data = self.opts['archive'] / 'archive.sqlite3'
        data.write_bytes(b'private archive data')
        (self.checkout / 'mac_messages.py').write_text('# new source\n')
        self.calls.reset_mock()
        args = self.update_args()
        args.python = '/unavailable/default/python'
        report = setup.update(args)
        self.assertTrue(report['updated'])
        self.assertFalse(report['publisher_enabled'])
        self.assertEqual(args.python, sys.executable)
        self.assertEqual(args.max_messages, 250000)
        self.assertEqual(args.max_bytes, 128 * 1024 * 1024)
        self.assertEqual(args.messages_db, str(self.root / 'custom Messages.sqlite3'))
        self.assertEqual(config.read_bytes(), config_before)
        self.assertEqual(credentials.read_bytes(), b'{}')
        self.assertEqual(data.read_bytes(), b'private archive data')
        self.assertEqual((self.opts['support'] / 'app/mac_messages.py').read_text(), '# new source\n')
        publisher = 'com.minbox-text-archive.publisher.Alex'
        self.assertNotIn(publisher, setup.read_manifest(self.opts, 'Alex')['enabled'])
        self.assertNotIn(('enable', publisher), [call.args for call in self.calls.call_args_list])
        self.assertEqual([call.args[0] for call in self.calls.call_args_list].count('bootstrap'), 2)

    def test_update_preserves_external_publisher_pause_and_rejects_split_capture_state(self):
        self.full_publisher()
        self.args.enable = True
        self.args.enable_publisher = True
        setup.install(self.args)
        self.calls.reset_mock()
        setup.launch_overrides.side_effect = lambda labels: {
            label: '.publisher.' in label for label in labels}
        report = setup.update(self.update_args())
        self.assertFalse(report['publisher_enabled'])
        self.assertNotIn(('enable', 'com.minbox-text-archive.publisher.Alex'),
                         [call.args for call in self.calls.call_args_list])
        self.calls.reset_mock()
        setup.launch_overrides.side_effect = lambda labels: {
            label: '.collector.' in label or '.publisher.' in label for label in labels}
        with self.assertRaisesRegex(ValueError, 'overrides differ'):
            setup.update(self.update_args())
        self.assertFalse(self.calls.called)

    def test_update_rejects_modified_missing_or_untracked_configuration_before_jobs(self):
        config = self.full_publisher()
        setup.install(self.args)
        original = config.read_bytes()
        manifest_path = setup.manifest_path(self.opts, 'Alex')
        manifest = manifest_path.read_bytes()
        self.calls.reset_mock()
        config.write_bytes(original + b'\n')
        with self.assertRaisesRegex(ValueError, 'configuration was modified'):
            setup.update(self.update_args())
        config.unlink()
        with self.assertRaisesRegex(ValueError, 'configuration is missing'):
            setup.update(self.update_args())
        setup.write(config, original, 0o600)
        legacy = json.loads(manifest)
        legacy.pop('publisher_config')
        setup.write(manifest_path, json.dumps(legacy).encode(), 0o600)
        with self.assertRaisesRegex(ValueError, 'configuration is untracked'):
            setup.update(self.update_args())
        setup.write(manifest_path, manifest, 0o600)
        (self.opts['support'] / 'app/mac_messages.py').write_text('# modified installed source')
        with self.assertRaisesRegex(ValueError, 'tracked file was modified'):
            setup.update(self.update_args())
        self.assertFalse(self.calls.called)

    def test_update_binding_compile_and_dependency_failures_precede_mutation(self):
        setup.install(self.args)
        self.calls.reset_mock()
        args = self.update_args()
        args.archive_root = str(self.root / 'different archive')
        with self.assertRaisesRegex(ValueError, 'binding'):
            setup.update(args)
        (self.checkout / 'mac_messages.py').write_text('invalid Python syntax!')
        setup.doctor.reset_mock()
        with self.assertRaisesRegex(ValueError, 'failed compilation'):
            setup.update(self.update_args())
        setup.doctor.assert_not_called()
        (self.checkout / 'mac_messages.py').write_text('# valid source')
        setup.doctor.return_value = {'python_sqlite': False}
        with self.assertRaisesRegex(ValueError, 'dependencies failed'):
            setup.update(self.update_args())
        self.assertFalse(self.calls.called)
        self.assertEqual((self.opts['support'] / 'app/mac_messages.py').read_text(), '# fixture\n')

    def test_update_plan_is_nonmutating_and_refuses_runtime_overrides(self):
        setup.install(self.args)
        before = setup.manifest_path(self.opts, 'Alex').read_bytes()
        self.calls.reset_mock()
        with patch.object(setup.platform, 'system', return_value='Linux'):
            report = setup.update(self.update_args(plan=True))
        self.assertFalse(report['mutations'])
        self.assertFalse(report['launchd_overrides_verified'])
        self.assertEqual(setup.manifest_path(self.opts, 'Alex').read_bytes(), before)
        with contextlib.redirect_stdout(io.StringIO()):
            result = setup.main(['update', '--plan', '--owner', 'Alex', '--archive-root',
                                 str(self.opts['archive']), '--enable-publisher'])
        self.assertEqual(result, 1)
        self.assertFalse(self.calls.called)

    def test_update_requires_manifest_and_never_resumes_manifest_paused_jobs(self):
        with self.assertRaisesRegex(ValueError, 'existing owned installation manifest'):
            setup.update(self.update_args())
        setup.install(self.args)
        manifest = setup.manifest_path(self.opts, 'Alex')
        original = manifest.read_bytes()
        changed = json.loads(original)
        changed['owner'] = 'Other'
        setup.write(manifest, json.dumps(changed).encode(), 0o600)
        self.calls.reset_mock()
        with self.assertRaisesRegex(ValueError, 'unsupported installation manifest'):
            setup.update(self.update_args())
        setup.write(manifest, original, 0o600)
        setup.launch_overrides.side_effect = lambda labels: {label: False for label in labels}
        with self.assertRaisesRegex(ValueError, 'paused job has an external enable override'):
            setup.update(self.update_args())
        self.assertFalse(self.calls.called)

    def test_update_install_failure_restores_source_manifest_and_jobs(self):
        self.args.enable = True
        setup.install(self.args)
        app = self.opts['support'] / 'app/mac_messages.py'
        before = app.read_bytes()
        manifest = setup.manifest_path(self.opts, 'Alex').read_bytes()
        (self.checkout / 'mac_messages.py').write_text('# update candidate\n')
        failed = False
        def fail_once(action, target):
            nonlocal failed
            if action == 'bootstrap' and '.looms.' in str(target) and not failed:
                failed = True
                raise RuntimeError('launch failure')
            return True
        self.calls.reset_mock()
        self.calls.side_effect = fail_once
        with self.assertRaisesRegex(RuntimeError, 'previous tracked files and jobs restored'):
            setup.update(self.update_args())
        self.assertEqual(app.read_bytes(), before)
        self.assertEqual(setup.manifest_path(self.opts, 'Alex').read_bytes(), manifest)
        self.assertEqual([call.args[0] for call in self.calls.call_args_list].count('bootstrap'), 4)

    def test_full_publisher_plan_selects_model_free_script_and_separate_enable(self):
        path = self.full_publisher()
        with patch.object(setup.platform, 'system', return_value='Linux'):
            units = setup.render(self.args)
        publisher = units['com.minbox-text-archive.publisher.Alex']
        self.assertEqual(publisher['ProgramArguments'], [sys.executable,
                         str(self.opts['support'] / 'app/owner_publish_cli.py'), '--config', str(path)])
        self.assertFalse(publisher['RunAtLoad'])
        self.assertTrue(publisher['Disabled'])
        self.assertEqual(plistlib.loads(plistlib.dumps(publisher)), publisher)
        self.assertFalse(self.home.exists())
        self.args.enable = True
        self.assertFalse(setup.render(self.args)['com.minbox-text-archive.publisher.Alex']['RunAtLoad'])
        self.args.enable = False
        self.args.enable_publisher = True
        units = setup.render(self.args)
        self.assertTrue(units['com.minbox-text-archive.publisher.Alex']['RunAtLoad'])
        self.assertFalse(units['com.minbox-text-archive.collector.Alex']['RunAtLoad'])
        self.assertFalse(self.calls.called)

    def test_full_publisher_binding_documents_and_runtime_paths(self):
        path = self.full_publisher()
        original = json.loads(path.read_text())
        checkout_runtime = self.checkout / 'private runtime.json'
        checkout_runtime.write_text('{}')
        checkout_runtime.chmod(0o600)
        invalid = [('owner', 'other'), ('archive_root', str(self.root / 'other')),
                   ('google_account_email', 'not-an-email'), ('folder_id', 'root'),
                   ('corrections_folder_id', 'bad/id'),
                   ('documents', {k: v for k, v in original['documents'].items() if k != 'status'}),
                   ('documents', {**original['documents'], 'messages': 'extra_document_identifier'}),
                   ('documents', {**original['documents'], 'status': original['documents']['guide']}),
                   ('documents', {**original['documents'], 'status': original['folder_id']})]
        for key in setup.publisher_paths(original):
            invalid.extend([(key, 'relative/file'), (key, str(self.checkout / 'private runtime.json'))])
        for field, value in invalid:
            with self.subTest(field=field, value=value):
                path.write_text(json.dumps({**original, field: value}))
                with self.assertRaises(ValueError):
                    setup.options(self.args)
        for key in setup.publisher_paths(original):
            with self.subTest(missing=key):
                config = {k: v for k, v in original.items() if k != key}
                path.write_text(json.dumps(config))
                with self.assertRaises(ValueError):
                    setup.options(self.args)
        for folder in (original['folder_id'], 'separate_corrections_folder'):
            path.write_text(json.dumps({**original, 'corrections_folder_id': folder}))
            self.assertEqual(setup.options(self.args)['publisher']['corrections_folder_id'], folder)
        path.write_text(json.dumps(original))
        credentials = Path(original['credentials_file'])
        credentials.chmod(0o644)
        with self.assertRaises(ValueError):
            setup.options(self.args)
        credentials.chmod(0o600)
        link = self.root / 'credentials link.json'
        link.symlink_to(credentials)
        path.write_text(json.dumps({**original, 'credentials_file': str(link)}))
        with self.assertRaisesRegex(ValueError, 'symlink'):
            setup.options(self.args)
        self.assertFalse(self.calls.called)

    def test_full_publisher_cli_plan_on_linux_never_initializes_or_starts(self):
        path = self.full_publisher()
        with patch.object(setup.platform, 'system', return_value='Linux'), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            code = setup.main(['install', '--plan', '--owner', 'Alex', '--checkout', str(self.checkout),
                               '--home', str(self.home), '--archive-root', str(self.opts['archive']),
                               '--python', sys.executable, '--publisher-config', str(path),
                               '--enable-publisher'])
        self.assertEqual(code, 0)
        result = json.loads(output.getvalue())
        self.assertFalse(result['mutations'])
        self.assertTrue(result['units']['com.minbox-text-archive.publisher.Alex']['RunAtLoad'])
        self.assertFalse(self.opts['archive'].exists())
        self.assertFalse(self.home.exists())
        self.assertFalse(self.calls.called)

    def test_full_publisher_doctor_has_no_codex_or_auth_requirement(self):
        self.full_publisher()
        self.preflight.stop()
        with patch.object(setup, 'inspect_messages', return_value={'supported': False}), \
                patch.object(setup, 'python_check', return_value=True), \
                patch.object(setup.shutil, 'which') as which:
            report = setup.doctor(self.args)
        which.assert_not_called()
        self.assertTrue(report['google_modules'])
        self.assertNotIn('codex_binary', report)
        self.assertNotIn('codex_auth_present', report)
        self.assertEqual(report['google_account_authorization'], 'unverified_offline')
        self.assertEqual(report['private_document_permissions'], 'unverified_offline')
        self.assertFalse(self.home.exists())

    def test_full_publisher_install_only_requires_sqlite_and_google_modules(self):
        self.full_publisher()
        self.args.enable_publisher = True
        setup.doctor.return_value = {'python_sqlite': True, 'google_modules': True,
                                    'messages_readable': False}
        report = setup.install(self.args)
        self.assertEqual(report['enabled_jobs'], 1)
        self.assertTrue(report['publisher_enabled'])
        unit = self.home / 'Library/LaunchAgents/com.minbox-text-archive.publisher.Alex.plist'
        self.assertTrue(plistlib.loads(unit.read_bytes())['ProgramArguments'][1].endswith('/owner_publish_cli.py'))
        for dependency in ('python_sqlite', 'google_modules'):
            with self.subTest(dependency=dependency):
                setup.doctor.return_value = {'python_sqlite': True, 'google_modules': True, dependency: False}
                with self.assertRaisesRegex(ValueError, 'publisher dependencies'):
                    setup.install(self.args)

    def test_work_publisher_keeps_codex_preflight_and_script(self):
        self.publisher()
        command = setup.render(self.args)['com.minbox-text-archive.publisher.Alex']['ProgramArguments']
        self.assertTrue(command[1].endswith('/archive_publish_cli.py'))
        self.preflight.stop()
        with patch.object(setup, 'inspect_messages', return_value={'supported': True}), \
                patch.object(setup, 'python_check', return_value=True), \
                patch.object(setup.shutil, 'which', return_value=None) as which:
            report = setup.doctor(self.args)
        which.assert_called_once_with('codex')
        self.assertFalse(report['codex_binary'])
        self.assertFalse(report['codex_auth_present'])
        self.args.enable_publisher = True
        with patch.object(setup, 'doctor', return_value=report):
            with self.assertRaisesRegex(ValueError, 'publisher dependencies'):
                setup.install(self.args)

    def test_plan_linux_without_mutation_and_paths_with_spaces(self):
        with patch.object(setup.platform, 'system', return_value='Linux'):
            units = setup.render(self.args)
            with self.assertRaises(ValueError):
                setup.install(self.args)
        self.assertFalse(self.home.exists())
        collector = units['com.minbox-text-archive.collector.Alex']
        self.assertEqual(collector['StartInterval'], 120)
        self.assertFalse(collector['RunAtLoad'])
        self.assertTrue(collector['Disabled'])
        self.assertEqual(collector['ProgramArguments'][1], str(self.opts['support'] / 'app/mac_messages.py'))
        for label, unit in units.items():
            self.assertEqual(plistlib.loads(plistlib.dumps(unit)), unit)
            self.assertEqual(unit['Label'], label)
        self.assertEqual(units['com.minbox-text-archive.looms.Alex']['StartInterval'], 300)
        self.assertFalse(self.calls.called)

    def test_fresh_install_refuses_legacy_support_before_mutation(self):
        legacy = self.home / 'Library/Application Support/Family Text Archive'
        legacy.mkdir(parents=True)
        retained = legacy / 'archive.sqlite3'
        retained.write_bytes(b'legacy archive fixture')
        with self.assertRaisesRegex(ValueError, 'legacy Family Text Archive.*migration'):
            setup.install(self.args)
        self.assertEqual(retained.read_bytes(), b'legacy archive fixture')
        self.assertFalse((self.opts['support'] / 'app').exists())
        self.assertFalse(self.opts['archive'].exists())
        self.assertFalse(self.calls.called)

    def test_install_inactive_and_only_authored_top_level_python(self):
        setup.install(self.args)
        self.assertEqual({c.args[0] for c in self.calls.call_args_list}, {'disable'})
        self.assertEqual(self.opts['support'],
                         self.home / 'Library/Application Support/Minbox Text Archive')
        app = self.opts['support'] / 'app'
        self.assertFalse((app / 'secret.env').exists())
        self.assertEqual((self.opts['support'] / 'config').stat().st_mode & 0o777, 0o700)
        manifest = setup.manifest_path(self.opts, 'Alex')
        self.assertEqual(manifest.stat().st_mode & 0o777, 0o600)
        agents = list((self.home / 'Library/LaunchAgents').glob('*.plist'))
        self.assertEqual(len(agents), 2)
        self.assertTrue(all(p.stat().st_mode & 0o777 == 0o644 for p in agents))
        setup.install(self.args)

    def test_untracked_or_modified_unit_refused_before_mutation(self):
        target = self.home / 'Library/LaunchAgents/com.minbox-text-archive.collector.Alex.plist'
        target.parent.mkdir(parents=True)
        target.write_text('foreign')
        with self.assertRaises(ValueError):
            setup.install(self.args)
        self.assertEqual(target.read_text(), 'foreign')
        self.assertFalse(self.calls.called)
        target.unlink()
        setup.install(self.args)
        target.write_text('modified')
        with self.assertRaises(ValueError):
            setup.install(self.args)
        with self.assertRaises(ValueError):
            setup.uninstall(self.args)
        self.assertEqual(target.read_text(), 'modified')

    def test_enable_requires_successful_preflight(self):
        self.args.enable = True
        with patch.object(setup, 'doctor', return_value={'python_sqlite': True, 'messages_readable': False}):
            with self.assertRaises(ValueError):
                setup.install(self.args)
        self.assertFalse((self.opts['support'] / 'app').exists())
        self.assertFalse(self.opts['archive'].exists())
        setup.install(self.args)
        self.assertEqual([c.args[0] for c in self.calls.call_args_list].count('bootstrap'), 2)
        self.assertEqual([c.args[0] for c in self.calls.call_args_list].count('enable'), 2)

    def test_failed_launch_restores_previous_files_and_enabled_jobs(self):
        self.args.enable = True
        setup.install(self.args)
        app = self.opts['support'] / 'app/mac_messages.py'
        before = app.read_bytes()
        manifest = setup.manifest_path(self.opts, 'Alex').read_bytes()
        (self.checkout / 'mac_messages.py').write_text('# changed\n')
        self.calls.reset_mock()
        failed = False
        def fail_once(action, target):
            nonlocal failed
            if action == 'bootstrap' and '.looms.' in str(target) and not failed:
                failed = True
                raise RuntimeError('private detail')
            return True
        self.calls.side_effect = fail_once
        with self.assertRaisesRegex(RuntimeError, 'previous tracked files and jobs restored'):
            setup.install(self.args)
        self.assertEqual(app.read_bytes(), before)
        self.assertEqual(setup.manifest_path(self.opts, 'Alex').read_bytes(), manifest)
        actions = [c.args[0] for c in self.calls.call_args_list]
        self.assertEqual(actions.count('bootout'), 4)  # both attempted jobs cleaned
        self.assertEqual(actions.count('bootstrap'), 4)  # both prior jobs restored

    def test_uninstall_only_tracked_plists_preserves_data_credentials_logs_app(self):
        self.args.enable = True
        setup.install(self.args)
        retained = [self.opts['archive'] / 'archive.sqlite3', self.opts['support'] / 'logs/private.log',
                    self.opts['support'] / 'config/credentials.json']
        for p in retained:
            p.write_text('private')
        foreign = self.home / 'Library/LaunchAgents/other.plist'
        foreign.write_text('foreign')
        setup.uninstall(self.args)
        self.assertTrue(all(p.read_text() == 'private' for p in retained))
        self.assertTrue((self.opts['support'] / 'app/mac_messages.py').exists())
        self.assertEqual(foreign.read_text(), 'foreign')
        self.assertEqual(setup.read_manifest(self.opts, 'Alex')['enabled'], [])

    def test_publisher_requires_private_bound_config_and_separate_enable(self):
        self.args.enable_publisher = True
        with self.assertRaises(ValueError):
            setup.render(self.args)
        self.args.enable_publisher = False
        config = self.publisher()
        config.chmod(0o644)
        with self.assertRaises(ValueError):
            setup.render(self.args)
        config.chmod(0o600)
        setup.install(self.args)
        self.assertEqual({c.args[0] for c in self.calls.call_args_list}, {'disable'})
        self.calls.reset_mock()
        self.args.enable_publisher = True
        setup.install(self.args)
        self.assertEqual([c.args[0] for c in self.calls.call_args_list].count('bootstrap'), 1)
        self.assertIn('.publisher.Alex.plist', str(self.calls.call_args.args[1]))

    def test_reconfigure_without_publisher_removes_old_tracked_job(self):
        self.publisher()
        self.args.enable_publisher = True
        setup.install(self.args)
        agent = self.home / 'Library/LaunchAgents/com.minbox-text-archive.publisher.Alex.plist'
        self.assertTrue(agent.exists())
        self.args.enable_publisher = False
        self.args.publisher_config = None
        self.calls.reset_mock()
        setup.install(self.args)
        self.assertFalse(agent.exists())
        self.assertNotIn(str(agent), setup.read_manifest(self.opts, 'Alex')['files'])
        self.assertIn('bootout', [c.args[0] for c in self.calls.call_args_list])

    def test_runtime_inside_git_and_bad_owner_rejected(self):
        (self.root / '.git').mkdir()
        (self.root / '.git/HEAD').write_text('ref: fixture')
        with self.assertRaises(ValueError):
            setup.options(self.args)
        (self.root / '.git/HEAD').unlink()
        (self.root / '.git').rmdir()
        self.args.owner = '../Alex'
        with self.assertRaises(ValueError):
            setup.options(self.args)

    def test_bundle_runtime_paths_and_collection_limits(self):
        original = self.args.archive_root
        self.args.archive_root = str(self.checkout / 'private archive')
        with self.assertRaisesRegex(ValueError, 'outside the source checkout'):
            setup.options(self.args)
        self.args.archive_root = original
        self.args.max_messages = 250000
        self.args.max_bytes = 128 * 1024 * 1024
        command = setup.render(self.args)['com.minbox-text-archive.collector.Alex']['ProgramArguments']
        self.assertEqual(command[command.index('--max-messages') + 1], '250000')
        self.args.max_messages = 0
        with self.assertRaises(ValueError):
            setup.options(self.args)

    def test_launchctl_arguments_are_arrays(self):
        self.launch.stop()
        with patch.object(setup.subprocess, 'run') as run:
            setup.launch('bootstrap', Path('/Users/Alex/Library/LaunchAgents/path with spaces.plist'))
        self.assertEqual(run.call_args.args[0], [
            '/bin/launchctl', 'bootstrap', 'gui/' + str(os.getuid()),
            '/Users/Alex/Library/LaunchAgents/path with spaces.plist'])

    def test_launchctl_override_and_confirmed_absent_service(self):
        self.launch.stop()
        with patch.object(setup.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)) as command:
            setup.launch('enable', 'com.minbox-text-archive.collector.Alex')
        self.assertEqual(command.call_args.args[0], ['/bin/launchctl', 'enable',
            'gui/' + str(os.getuid()) + '/com.minbox-text-archive.collector.Alex'])
        missing = subprocess.CompletedProcess([], 113, stderr='Could not find service "owned" in domain')
        with patch.object(setup.subprocess, 'run', return_value=missing) as command:
            self.assertFalse(setup.launch('bootout', Path('/private/owned.plist')))
        self.assertEqual(command.call_count, 1)
        failure = subprocess.CompletedProcess([], 1, stderr='private failure')
        with patch.object(setup.subprocess, 'run', return_value=failure):
            with self.assertRaises(RuntimeError):
                setup.launch('bootout', Path('/private/owned.plist'))

    def test_external_disabled_override_parser_and_rollback(self):
        self.overrides.stop()
        label = 'com.minbox-text-archive.collector.Alex'
        result = subprocess.CompletedProcess([], 0, stdout='{ "'+label+'" => true }')
        with patch.object(setup.subprocess, 'run', return_value=result):
            self.assertEqual(setup.launch_overrides([label, 'other']), {label:True, 'other':None})
        self.overrides.start()
        setup.launch_overrides.side_effect = lambda labels: {label:True for label in labels}
        self.args.enable = True
        def fail_bootstrap(action, target):
            if action == 'bootstrap':
                raise RuntimeError('bootstrap failed')
            return False if action == 'bootout' else True
        self.calls.side_effect = fail_bootstrap
        with self.assertRaisesRegex(RuntimeError, 'previous tracked files and jobs restored'):
            setup.install(self.args)
        self.assertEqual([c.args[0] for c in self.calls.call_args_list].count('disable'), 2)
        self.assertFalse(setup.manifest_path(self.opts, 'Alex').exists())

    def test_selected_interpreter_probes_only_schema(self):
        with patch.object(setup.subprocess, 'run', return_value=subprocess.CompletedProcess(
                [], 0, stdout='{"supported":true}')) as run:
            report = setup.inspect_messages(Path('/Users/Alex/Library/Messages/chat.db'),
                                            Path('/private/venv/bin/python3'), self.checkout)
        self.assertTrue(report['supported'])
        command = run.call_args.args[0]
        self.assertEqual(command[0], '/private/venv/bin/python3')
        self.assertEqual(command[1], '-c')
        self.assertIn('inspect_database', command[2])
        self.assertNotIn('SELECT', command[2])
        self.assertFalse(self.calls.called)

    def test_plan_flag_main_is_nonmutating_on_linux(self):
        with patch.object(setup.platform, 'system', return_value='Linux'), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            code = setup.main(['install', '--plan', '--owner', 'Alex',
                               '--checkout', str(self.checkout), '--home', str(self.home),
                               '--archive-root', str(self.opts['archive']), '--python', sys.executable])
        self.assertEqual(code, 0)
        self.assertFalse(json.loads(output.getvalue())['mutations'])
        self.assertFalse(self.home.exists())

    def test_live_other_user_home_is_rejected(self):
        with patch.object(setup.Path, 'home', return_value=self.root / 'different home'):
            with self.assertRaises(ValueError):
                setup.install(self.args)
            with self.assertRaises(ValueError):
                setup.uninstall(self.args)
        self.assertFalse(self.home.exists())

    def test_publisher_owner_scope_binding_is_required(self):
        path = self.publisher()
        config = json.loads(path.read_text())
        for field, value in (('owner', 'other'), ('conversations', []),
                             ('folder_id', 'bad/id'), ('archive_root', str(self.root / 'other'))):
            with self.subTest(field=field):
                path.write_text(json.dumps({**config, field: value}))
                with self.assertRaises(ValueError):
                    setup.render(self.args)
        self.assertFalse(self.calls.called)

    def test_doctor_sanitizes_inspection_without_network_or_content(self):
        self.preflight.stop()
        with patch.object(setup, 'inspect_messages', return_value={'supported': True, 'private': 'SECRET'}), \
                patch.object(setup, 'python_check', return_value=True):
            report = setup.doctor(self.args)
        self.assertTrue(report['messages_readable'])
        self.assertNotIn('SECRET', json.dumps(report))
        self.assertEqual(report['device_sync'], 'unknown_user_verification_required')
        self.assertFalse(self.calls.called)


if __name__ == '__main__':
    unittest.main()
