import fcntl
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

import archive_publish_cli
import owner_publish_cli
from publisher_status import PublisherStatus, classify_failure, write_json


class DurableStatus(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'status.json'

    def read(self):
        return json.loads(self.path.read_text())

    def test_failed_retry_preserves_success_then_recovery_clears_failure(self):
        with PublisherStatus(self.path) as status:
            status.phase('publishing', 'source-one')
            status.success('source-one', {'published_messages': 3, 'model_calls': 0})
        success = self.read()
        with self.assertRaises(TimeoutError):
            with PublisherStatus(self.path) as status:
                running = self.read()
                self.assertEqual(running['run_state'], 'running')
                self.assertEqual(running['checked_at'], success['checked_at'])
                status.phase('publishing', 'source-two')
                raise TimeoutError('PRIVATE MESSAGE URL TOKEN')
        failed = self.read()
        for key in ('source_import_timestamp', 'published_messages', 'last_success_at', 'last_publication_at'):
            self.assertEqual(failed[key], success[key])
        self.assertEqual(failed['attempt_source_import_timestamp'], 'source-two')
        self.assertEqual(failed['run_state'], 'failed')
        self.assertEqual(failed['consecutive_failures'], 1)
        self.assertEqual(failed['failure_kind'], 'transient')
        self.assertNotIn('PRIVATE', json.dumps(failed))
        with self.assertRaises(TimeoutError):
            with PublisherStatus(self.path):
                raise TimeoutError('PRIVATE')
        self.assertEqual(self.read()['consecutive_failures'], 2)
        with PublisherStatus(self.path) as status:
            status.success('source-two', {'published_messages': 4, 'model_calls': 0})
        recovered = self.read()
        self.assertEqual(recovered['run_state'], 'succeeded')
        self.assertEqual(recovered['consecutive_failures'], 0)
        self.assertNotIn('error_code', recovered)
        self.assertEqual(recovered['source_import_timestamp'], 'source-two')
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_degraded_output_does_not_claim_analysis_success(self):
        with PublisherStatus(self.path) as status:
            status.success('source-one', {'work_messages': 2, 'analysis_failed_or_paused': False, 'deferred_sources': 0})
        old = self.read()
        with PublisherStatus(self.path) as status:
            status.success('source-two', {'work_messages': 2, 'analysis_failed_or_paused': True, 'deferred_sources': 2})
        result = self.read()
        self.assertEqual(result['run_state'], 'degraded')
        self.assertEqual(result['last_success_at'], old['last_success_at'])
        self.assertEqual(result['last_analysis_success_at'], old['last_analysis_success_at'])
        self.assertNotEqual(result['last_publication_at'], old['last_publication_at'])
        self.assertEqual(result['source_import_timestamp'], 'source-two')

    def test_private_symlink_and_public_existing_status_refused(self):
        target = self.path.with_name('target.json')
        target.write_text('{}')
        self.path.symlink_to(target)
        with self.assertRaises(ValueError):
            write_json(self.path, {})
        self.assertEqual(target.read_text(), '{}')
        self.path.unlink()
        self.path.write_text('{}')
        self.path.chmod(0o644)
        with self.assertRaises(ValueError):
            PublisherStatus(self.path)

    def test_safe_failure_categories(self):
        for error, kind in (
            (TimeoutError('PRIVATE'), 'transient'),
            (URLError(ConnectionResetError('PRIVATE')), 'transient'),
            (ValueError('Google account differs from owner binding'), 'privacy'),
            (ValueError('manifest owner/folder differs'), 'privacy'),
            (RuntimeError('publication readback mismatch'), 'integrity'),
            (RuntimeError('Google authentication failed'), 'auth'),
            (ValueError('PRIVATE'), 'unknown'),
        ):
            with self.subTest(kind=kind):
                result = classify_failure(error)
                self.assertEqual(result['failure_kind'], kind)
                self.assertNotIn('PRIVATE', json.dumps(result))
        for code, kind in ((401, 'auth'), (403, 'auth'), (429, 'transient'), (503, 'transient')):
            error = HTTPError('https://PRIVATE', code, 'PRIVATE', {}, None)
            self.addCleanup(error.close)
            self.assertEqual(classify_failure(error), {'error_code': 'http_failure',
                                                      'http_status': code, 'failure_kind': kind})


class PublisherLifecycle(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.status = root / 'status.json'
        self.analysis = root / 'analysis.sqlite'
        self.config = root / 'config.json'
        from storage import Archive
        Archive(root).init(owners=('Synthetic',))
        write_json(self.config, {'owner': 'Synthetic', 'scope': 'owner_all',
                                'status_file': str(self.status), 'analysis_path': str(self.analysis),
                                'archive_root': str(root), 'credentials_file': str(root / 'credentials.json'),
                                'conversations': [], 'start_date': '1970-01-01',
                                'google_account_email': 'synthetic@example.invalid',
                                'documents': {'corrections': 'input', 'guide': 'output'}})

    def invoke(self, module):
        return module.main(['--config', str(self.config)])

    def test_owner_validating_failure_and_successful_retry(self):
        with patch.object(owner_publish_cli, 'OwnerDocs', side_effect=TimeoutError('PRIVATE')):
            with self.assertRaises(TimeoutError):
                self.invoke(owner_publish_cli)
        failed = json.loads(self.status.read_text())
        self.assertEqual(failed['run_state'], 'failed')
        self.assertEqual(failed['failure_kind'], 'transient')
        self.assertNotIn('last_success_at', failed)
        with patch.object(owner_publish_cli, 'OwnerDocs', return_value=Mock(manifest={'chunks': {}})), \
                patch.object(owner_publish_cli, 'snapshot', return_value={'latest_import': 'source-one'}), \
                patch('owner_archive_publisher.run', return_value={
                    'writes': 0, 'published_messages': 3, 'excluded_messages': 1, 'model_calls': 0,
                    'verified_images': 0, 'published_images': 0, 'pending_images': 0,
                    'unavailable_images': 0, 'attachment_writes': 0,
                    'withdrawn_images': 0, 'phone_spam_conversations': 0}):
            self.assertEqual(self.invoke(owner_publish_cli), 0)
        self.assertEqual(json.loads(self.status.read_text())['run_state'], 'succeeded')

    def test_work_validating_failure_is_durable(self):
        with patch.object(archive_publish_cli, 'GoogleAuth', side_effect=TimeoutError('PRIVATE')):
            with self.assertRaises(TimeoutError):
                self.invoke(archive_publish_cli)
        status = json.loads(self.analysis.with_suffix('.last-run.json').read_text())
        self.assertEqual(status['run_state'], 'failed')
        self.assertEqual(status['error_code'], 'transport_failure')

    def test_work_verified_degraded_outputs(self):
        with patch.object(archive_publish_cli, 'GoogleAuth'), \
                patch.object(archive_publish_cli, '_http_request', return_value={
                    'user': {'emailAddress': 'synthetic@example.invalid'}}), \
                patch.object(archive_publish_cli, 'verify_destinations'), \
                patch.object(archive_publish_cli, 'DocsClient'), \
                patch.object(archive_publish_cli, 'ArchiveAnalyzer'), \
                patch.object(archive_publish_cli, 'snapshot', return_value={'latest_import': 'source-two'}), \
                patch.object(archive_publish_cli, 'run', return_value={
                    'writes': 0, 'work_messages': 2, 'work_looms': 0,
                    'message_analysis': {'paused': True, 'deferred': ['source']},
                    'loom_analysis': {}}):
            self.assertEqual(self.invoke(archive_publish_cli), 0)
        status = json.loads(self.analysis.with_suffix('.last-run.json').read_text())
        self.assertEqual(status['run_state'], 'degraded')
        self.assertEqual(status['source_import_timestamp'], 'source-two')
        self.assertIn('last_publication_at', status)
        self.assertNotIn('last_success_at', status)

    def test_enabled_phone_policy_versions_work_cache_even_after_last_restore(self):
        config = json.loads(self.config.read_text())
        config.update(phone_spam_policy='spam_and_blocked', seed_decisions=['old'], seed_revisions=['old'])
        write_json(self.config, config)
        policies = []
        for excluded, generation in [(['junk'], 'active-junk'), ([], 'empty-active-set')]:
            with patch.object(archive_publish_cli, 'GoogleAuth'), \
                    patch.object(archive_publish_cli, '_http_request', return_value={'user': {'emailAddress': 'synthetic@example.invalid'}}), \
                    patch.object(archive_publish_cli, 'verify_destinations'), \
                    patch.object(archive_publish_cli, 'DocsClient'), \
                    patch.object(archive_publish_cli, 'ArchiveAnalyzer'), \
                    patch.object(archive_publish_cli, 'snapshot', return_value={'latest_import': 'source', 'phone_spam_source_ids': excluded, 'phone_spam_generation': generation}), \
                    patch.object(archive_publish_cli, 'run', return_value={'writes':0,'work_messages':0,'work_looms':0,'message_analysis':{},'loom_analysis':{}}) as run:
                self.assertEqual(self.invoke(archive_publish_cli), 0)
                used = run.call_args.args[0]
                self.assertNotIn('seed_decisions', used)
                self.assertNotIn('seed_revisions', used)
                policies.append(used['analysis_policy'])
        self.assertTrue(all(':phone-exclusions:' in policy for policy in policies))
        self.assertNotEqual(*policies)

    def test_busy_owner_skips_publishers_without_auth_or_status_changes(self):
        from phone_spam import owner_operation
        config = json.loads(self.config.read_text())
        for module, status_path, network_constructor in (
            (owner_publish_cli, self.status, 'OwnerDocs'),
            (archive_publish_cli, self.analysis.with_suffix('.last-run.json'), 'GoogleAuth'),
        ):
            for existing_status in (False, True):
                with self.subTest(module=module.__name__, existing_status=existing_status):
                    if status_path.exists():
                        status_path.unlink()
                    before = None
                    if existing_status:
                        write_json(status_path, {'run_state':'succeeded','checked_at':'old','last_success_at':'old'})
                        before = status_path.read_bytes()
                    with owner_operation(config['archive_root'], config['owner']), \
                            patch.object(module, network_constructor) as network, \
                            patch.object(module, 'snapshot') as snap, \
                            patch.object(module, 'PublisherStatus') as status:
                        output = io.StringIO()
                        with contextlib.redirect_stdout(output):
                            self.assertEqual(self.invoke(module), 0)
                        self.assertEqual(json.loads(output.getvalue()), {'status':'owner_busy'})
                        network.assert_not_called()
                        snap.assert_not_called()
                        status.assert_not_called()
                    self.assertEqual(status_path.read_bytes() if status_path.exists() else None, before)

    def test_locks_leave_active_attempt_status_unchanged(self):
        for module, lock_path, status_path in (
            (owner_publish_cli, self.status.with_suffix('.lock'), self.status),
            (archive_publish_cli, self.analysis.with_suffix('.publisher.lock'),
             self.analysis.with_suffix('.last-run.json')),
        ):
            with self.subTest(module=module.__name__):
                write_json(status_path, {'run_state': 'running', 'started_at': 'active'})
                before = status_path.read_bytes()
                fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
                with os.fdopen(fd, 'a+b') as lock:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    output = io.StringIO()
                    with contextlib.redirect_stdout(output):
                        self.assertEqual(self.invoke(module), 0)
                    self.assertEqual(json.loads(output.getvalue()), {'status': 'already_running'})
                self.assertEqual(status_path.read_bytes(), before)
