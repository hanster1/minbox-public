from copy import deepcopy
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

import drive_migration as migration
from publisher_status import write_json


class DriveMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.email = 'owner@example.invalid'
        self.credential = self.directory / 'google-drive-authorized-user.json'
        self.old_credential = dict(type='authorized_user', client_id='fixture-client',
                                   client_secret='fixture-client-secret', refresh_token='old-sensitive-grant')
        write_json(self.credential, self.old_credential)
        self.manifest = self.directory / 'runtime/manifest.json'
        write_json(self.manifest, dict(owner='Casey', folder_id='root', chunks={'2026-10': 'chunk'}))
        self.ledger = self.directory / 'runtime/corrections.sqlite3'
        self.ledger.write_bytes(b'fixture-corrections-ledger')
        scopes = ['https://www.googleapis.com/auth/drive', 'https://www.googleapis.com/auth/spreadsheets']
        common = dict(owner='Casey', google_account_email=self.email, google_scopes=scopes,
                      credentials_file=str(self.credential), archive_root=str(self.directory / 'archive'))
        self.full_path = self.directory / 'publishers/Casey-full.json'
        self.full = dict(common, scope='owner_all', folder_id='root',
                         documents={'guide': 'full-guide', 'status': 'full-status', 'corrections': 'corrections'},
                         manifest_file=str(self.manifest), correction_path=str(self.ledger), work_guide_id='work-guide',
                         status_file=str(self.directory / 'runtime/full-status.json'), custom_setting='preserved')
        self.work_path = self.directory / 'publishers/alex-work.json'
        self.work = dict(common, folder_id='work', corrections_folder_id='root',
                         documents={'guide': 'work-guide', 'messages': 'work-messages', 'corrections': 'corrections'},
                         analysis_path=str(self.directory / 'runtime/analysis.sqlite3'), custom_setting='work-preserved')
        write_json(self.full_path, self.full)
        write_json(self.work_path, self.work)
        self.files = {}
        for identity, mime, parent in [('root', migration.FOLDER, 'my-drive'),
                                       ('work', migration.FOLDER, 'root'),
                                       ('full-guide', migration.DOCUMENT, 'root'),
                                       ('full-status', migration.DOCUMENT, 'root'),
                                       ('corrections', migration.DOCUMENT, 'root'),
                                       ('chunk', migration.DOCUMENT, 'root'),
                                       ('work-guide', migration.DOCUMENT, 'work'),
                                       ('work-messages', migration.DOCUMENT, 'work')]:
            self.files[identity] = dict(id=identity, name='A custom folder name' if identity == 'root' else identity,
                mimeType=mime, parents=[parent], shared=False, trashed=False,
                owners=[{'emailAddress': self.email}], capabilities={'canEdit': True},
                isAppAuthorized=identity not in {'root', 'work-guide'})
        self.calls, self.publications, self.tokens = [], [], []
        self.inventory = self.gather()
        self.new_credential = dict(self.old_credential, refresh_token='fresh-sensitive-grant',
                                   token='untrusted-cached-token', expiry='2030-01-01T00:00:00Z',
                                   scopes=migration.FILE_SCOPES)
        self.envelope = dict(binding=dict(owner='Casey', google_account_email=self.email, folder_id='root',
                                         archive_root_folder_id='root', folder_access='selected_folder',
                                         google_scopes=migration.FILE_SCOPES), credentials=self.new_credential)

    def request(self, method, url, body, headers, timeout):
        self.calls.append((method, url, body))
        self.assertEqual(method, 'GET')
        self.assertIsNone(body)
        path = urlsplit(url).path
        if path.endswith('/about'):
            return {'user': {'emailAddress': self.email}}
        self.assertIn('/files/', path)
        return deepcopy(self.files[path.rsplit('/', 1)[-1]])

    def gather(self):
        return migration.gather_inventory('Casey', self.directory, request=self.request,
                                           token_provider=lambda: 'old-fixture-token')

    def token(self, path):
        value = json.loads(path.read_text())
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(value['refresh_token'], 'fresh-sensitive-grant')
        for field in ('token', 'expiry', 'scopes'):
            self.assertNotIn(field, value)
        self.tokens.append(path)
        return 'fresh-fixture-token'

    def publish(self, kind, path):
        config = json.loads(path.read_text())
        self.assertEqual(config['google_scopes'], migration.FILE_SCOPES)
        self.assertEqual(config['folder_access'], 'selected_folder')
        self.assertEqual(config['archive_root_folder_id'], 'root')
        self.assertNotEqual(config['credentials_file'], str(self.credential))
        self.assertEqual(json.loads(self.credential.read_text())['refresh_token'], 'old-sensitive-grant')
        self.assertEqual(json.loads(self.full_path.read_text())['google_scopes'], self.full['google_scopes'])
        self.publications.append((kind, config))
        if kind == 'full':
            return dict(writes=0, model_calls=0, published_messages=10, excluded_messages=1)
        return dict(writes=0, model_calls=0, work_messages=2, work_looms=0)

    def apply(self, envelope=None, inventory=None, publish=None, token=None):
        return migration.apply_migration('Casey', envelope or self.envelope, inventory or self.inventory,
                                          self.directory, request=self.request,
                                          token_provider=token or self.token, publish=publish or self.publish)

    def originals(self):
        return {path: path.read_bytes() for path in
                (self.credential, self.full_path, self.work_path, self.manifest, self.ledger)}

    def assert_originals(self, originals):
        for path, raw in originals.items():
            self.assertEqual(path.read_bytes(), raw)
        self.assertFalse((self.directory / 'owners/Casey/drive.json').exists())

    def test_inventory_reads_only_registered_metadata_and_excludes_credentials(self):
        inventory = self.inventory
        self.assertEqual(inventory['archive_root_folder_id'], 'root')
        self.assertEqual(inventory['picker_file_ids'], ['root', 'work-guide'])
        self.assertEqual(len(inventory['entries']), 8)
        self.assertEqual(len(inventory['publishers']), 2)
        self.assertNotIn('sensitive', json.dumps(inventory))
        self.assertNotIn('fixture-client-secret', json.dumps(inventory))
        self.assertTrue(all('/files/' in url or '/about?' in url for _, url, _ in self.calls))
        self.assertEqual(self.files['root']['name'], 'A custom folder name')

    def test_success_preserves_all_bindings_names_ledgers_manifests_and_fields(self):
        originals = self.originals()
        result = self.apply()
        self.assertEqual(result, dict(ok=True, publishers=2, folders=2, documents=6))
        self.assertEqual([kind for kind, _ in self.publications], ['full', 'work'])
        for path, old in [(self.full_path, self.full), (self.work_path, self.work)]:
            current = json.loads(path.read_text())
            expected = dict(old, google_scopes=migration.FILE_SCOPES, folder_access='selected_folder',
                            archive_root_folder_id='root')
            self.assertEqual(current, expected)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.manifest.read_bytes(), originals[self.manifest])
        self.assertEqual(self.ledger.read_bytes(), originals[self.ledger])
        self.assertEqual(json.loads(self.credential.read_text())['refresh_token'], 'fresh-sensitive-grant')

    def test_renaming_or_relocating_selected_root_does_not_break_migration(self):
        self.files['root']['name'] = 'Whatever I Choose'
        self.files['root']['parents'] = ['new-private-parent']
        self.assertTrue(self.apply()['ok'])
        self.assertEqual(self.files['root']['name'], 'Whatever I Choose')

    def test_optional_analysis_delay_does_not_block_verified_drive_cutover(self):
        def publish(kind, path):
            result = self.publish(kind, path)
            if kind == 'work':
                result.update(analysis_failed_or_paused=True, deferred_sources=3)
            return result
        self.assertTrue(self.apply(publish=publish)['ok'])
        drive = json.loads((self.directory / 'owners/Casey/drive.json').read_text())
        self.assertEqual(drive['folder_id'], 'root')
        self.assertEqual(drive['credentials_file'], str(self.credential))
        self.assertEqual(drive['google_scopes'], migration.FILE_SCOPES)
        stage = next((self.directory / 'owners/Casey').glob('.migration-*'))
        self.assertEqual(json.loads((stage / 'journal.json').read_text())['state'], 'complete')
        self.assertEqual(json.loads((stage / 'journal.json').read_text())['old_grant_validity'], 'not_established')
        self.assertEqual(self.files['root']['name'], 'A custom folder name')

    def test_existing_owner_drive_configuration_preserves_extra_fields(self):
        path = self.directory / 'owners/Casey/drive.json'
        value = dict(owner='Casey', google_account_email=self.email, folder_id='root',
                     google_scopes=self.full['google_scopes'], credentials_file=str(self.credential),
                     custom_owner_setting='keep-me')
        write_json(path, value)
        result = self.apply(inventory=self.gather())
        self.assertTrue(result['ok'])
        self.assertEqual(json.loads(path.read_text())['custom_owner_setting'], 'keep-me')

    def test_default_auth_verifies_staged_credential_with_narrow_scope(self):
        calls = []
        def auth(path, *, scopes):
            calls.append((path, scopes))
            return SimpleNamespace(token=lambda: self.token(path))
        with patch('drive_migration.GoogleAuth', side_effect=auth):
            migration.apply_migration('Casey', self.envelope, self.inventory, self.directory,
                                      request=self.request, publish=self.publish)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1], migration.FILE_SCOPES)
        self.assertNotEqual(calls[0][0], self.credential)

    def test_owner_account_scope_root_and_client_mismatches_preserve_configs(self):
        originals = self.originals()
        for key, value in [('owner', 'Morgan'), ('google_account_email', 'other@example.invalid'),
                           ('google_scopes', self.full['google_scopes']), ('folder_id', 'different'),
                           ('archive_root_folder_id', 'different'), ('folder_access', 'legacy')]:
            envelope = deepcopy(self.envelope)
            envelope['binding'][key] = value
            with self.assertRaises(migration.MigrationError):
                self.apply(envelope=envelope)
            self.assert_originals(originals)
        envelope = deepcopy(self.envelope)
        envelope['credentials']['client_secret'] = 'different-client-secret'
        with self.assertRaises(migration.MigrationError):
            self.apply(envelope=envelope)
        self.assert_originals(originals)
        self.assertFalse(self.publications)

    def test_actual_account_or_refresh_scope_rejection_precedes_publication(self):
        originals = self.originals()
        self.email = 'wrong@example.invalid'
        with self.assertRaises(migration.MigrationError) as caught:
            self.apply()
        self.assertTrue(caught.exception.staged_grant_retained)
        self.assert_originals(originals)
        self.email = 'owner@example.invalid'
        def rejected_token(path):
            raise RuntimeError('PRIVATE broad scope response and token')
        with self.assertRaises(migration.MigrationError) as caught:
            self.apply(token=rejected_token)
        self.assertNotIn('PRIVATE', str(caught.exception))
        self.assert_originals(originals)
        self.assertFalse(self.publications)

    def test_changed_config_or_manifest_digest_rejected(self):
        for path in (self.full_path, self.work_path, self.manifest, self.credential):
            raw = path.read_bytes()
            path.write_bytes(raw + b'\n')
            with self.assertRaises(migration.MigrationError) as caught:
                self.apply()
            self.assertEqual(caught.exception.error_code, 'migration_inventory_changed')
            self.assertEqual(path.read_bytes(), raw + b'\n')
            path.write_bytes(raw)
        self.assertFalse(self.publications)

    def test_moved_shared_trashed_foreign_or_noneditable_destination_precedes_publication(self):
        originals = self.originals()
        for identity, key, value in [('chunk', 'parents', ['elsewhere']), ('work', 'parents', ['elsewhere']),
                                     ('corrections', 'shared', True), ('root', 'trashed', True),
                                     ('work-guide', 'owners', []), ('full-status', 'capabilities', {'canEdit': False})]:
            old = deepcopy(self.files[identity])
            self.files[identity][key] = value
            with self.assertRaises(migration.MigrationError):
                self.apply()
            self.files[identity] = old
            self.assert_originals(originals)
        self.assertFalse(self.publications)

    def test_failed_publication_retains_fresh_grant_without_cutover(self):
        originals = self.originals()
        def publish(kind, path):
            self.publish(kind, path)
            if kind == 'work':
                raise RuntimeError('PRIVATE publication content')
            return dict(writes=0, model_calls=0, published_messages=10, excluded_messages=1)
        with self.assertRaises(migration.MigrationError) as caught:
            self.apply(publish=publish)
        self.assertTrue(caught.exception.staged_grant_retained)
        self.assert_originals(originals)
        self.assertEqual(len(self.publications), 2)
        grants = list((self.directory / 'owners/Casey').glob('.migration-*/grant.json'))
        self.assertEqual(len(grants), 1)
        self.assertEqual(json.loads(grants[0].read_text())['refresh_token'], 'fresh-sensitive-grant')

    def test_busy_or_degraded_publication_is_not_cutover_proof(self):
        originals = self.originals()
        for result in ({'status': 'already_running'}, dict(writes=0, model_calls=0, published_messages=10,
                                                          excluded_messages=1, analysis_failed_or_paused=True)):
            with self.assertRaises(migration.MigrationError):
                self.apply(publish=lambda kind, path: result)
            self.assert_originals(originals)

    def test_concurrent_config_change_during_staged_publication_is_preserved(self):
        raw = self.full_path.read_bytes()
        def publish(kind, path):
            result = self.publish(kind, path)
            if kind == 'work':
                self.full_path.write_bytes(raw + b'\n')
            return result
        with self.assertRaises(migration.MigrationError):
            self.apply(publish=publish)
        self.assertEqual(self.full_path.read_bytes(), raw + b'\n')
        self.assertEqual(json.loads(self.credential.read_text())['refresh_token'], 'old-sensitive-grant')

    def test_added_publisher_registration_during_publication_prevents_cutover(self):
        originals = self.originals()
        def publish(kind, path):
            result = self.publish(kind, path)
            if kind == 'work':
                write_json(self.directory / 'publishers/another-work.json', self.work)
            return result
        with self.assertRaises(migration.MigrationError) as caught:
            self.apply(publish=publish)
        self.assertEqual(caught.exception.error_code, 'migration_inventory_changed')
        self.assert_originals(originals)

    def test_failed_publication_can_retry_using_same_fresh_grant_and_inventory(self):
        with self.assertRaises(migration.MigrationError):
            self.apply(publish=lambda kind, path: {'status': 'already_running'})
        self.assertTrue(self.apply()['ok'])

    def test_publisher_may_append_chunks_without_rebinding_existing_chunks(self):
        def publish(kind, path):
            result = self.publish(kind, path)
            if kind == 'full':
                manifest = json.loads(self.manifest.read_text())
                manifest['chunks']['2026-11'] = 'new-chunk'
                write_json(self.manifest, manifest)
                self.files['new-chunk'] = dict(self.files['chunk'], id='new-chunk', name='new-chunk')
            return result
        result = self.apply(publish=publish)
        self.assertEqual(result['documents'], 7)
        self.assertEqual(json.loads(self.manifest.read_text())['chunks']['2026-10'], 'chunk')

    def test_cutover_failure_restores_original_bytes_but_keeps_fresh_grant(self):
        originals = self.originals()
        def write(path, value):
            if Path(path) == self.credential:
                raise OSError('fixture disk error')
            write_json(path, value)
        with patch('drive_migration.write_json', side_effect=write):
            with self.assertRaises(migration.MigrationError) as caught:
                self.apply()
        self.assertEqual(caught.exception.error_code, 'migration_cutover_failed')
        self.assertTrue(caught.exception.staged_grant_retained)
        self.assert_originals(originals)
        stage = next((self.directory / 'owners/Casey').glob('.migration-*'))
        self.assertTrue((stage / 'grant.json').exists())
        self.assertEqual(json.loads((stage / 'journal.json').read_text())['state'], 'rolled_back')

    def test_cutover_error_after_replacement_also_restores_credential(self):
        originals = self.originals()
        def write(path, value):
            write_json(path, value)
            if Path(path) == self.credential:
                raise OSError('fixture post-replacement fsync error')
        with patch('drive_migration.write_json', side_effect=write):
            with self.assertRaises(migration.MigrationError):
                self.apply()
        self.assert_originals(originals)

    def test_rollback_preserves_concurrent_writer_change(self):
        def write(path, value):
            if Path(path) == self.credential:
                self.full_path.write_bytes(b'{"independent_writer":"preserved"}')
                raise OSError('fixture disk error')
            write_json(path, value)
        with patch('drive_migration.write_json', side_effect=write):
            with self.assertRaises(migration.MigrationError) as caught:
                self.apply()
        self.assertEqual(caught.exception.error_code, 'migration_rollback_incomplete')
        self.assertEqual(json.loads(self.full_path.read_text()), {'independent_writer': 'preserved'})
        self.assertEqual(json.loads(self.credential.read_text())['refresh_token'], 'old-sensitive-grant')

    def test_unregistered_inventory_item_cannot_authorize_arbitrary_drive_traversal(self):
        inventory = deepcopy(self.inventory)
        inventory['entries'].append(dict(id='arbitrary', mime_type=migration.DOCUMENT, name='unrelated', parents=['root']))
        before = len(self.calls)
        with self.assertRaises(migration.MigrationError):
            self.apply(inventory=inventory)
        self.assertEqual(len(self.calls), before)

    def test_default_publisher_routes_existing_clis_with_bounded_timeout(self):
        result = SimpleNamespace(returncode=0, stdout=b'{"writes":0}', stderr=b'PRIVATE')
        with patch('drive_migration.subprocess.run', return_value=result) as execute:
            self.assertEqual(migration._publish('full', Path('/private/config.json')), {'writes': 0})
            self.assertEqual(migration._publish('work', Path('/private/config.json')), {'writes': 0})
        self.assertTrue(execute.call_args_list[0].args[0][1].endswith('owner_publish_cli.py'))
        self.assertTrue(execute.call_args_list[1].args[0][1].endswith('archive_publish_cli.py'))
        self.assertEqual(execute.call_args.kwargs['timeout'], 900)

    def test_other_owner_publisher_is_not_inventoried(self):
        other = dict(self.work, owner='Morgan', credentials_file='/private/unrelated-credential.json',
                     folder_id='unrelated-folder')
        write_json(self.directory / 'publishers/Morgan-work.json', other)
        inventory = self.gather()
        self.assertEqual(inventory, self.inventory)
        self.assertNotIn('unrelated', json.dumps(inventory))

    def test_declared_intermediate_folder_is_inventoried_without_drive_traversal(self):
        work = dict(self.work, managed_folder_parents={'work': 'intermediate', 'intermediate': 'root'})
        write_json(self.work_path, work)
        self.files['intermediate'] = dict(self.files['work'], id='intermediate', name='intermediate')
        self.files['work']['parents'] = ['intermediate']
        inventory = self.gather()
        self.assertIn('intermediate', {item['id'] for item in inventory['entries']})
        result = self.apply(inventory=inventory)
        self.assertEqual(result['folders'], 3)
        self.assertEqual(json.loads(self.work_path.read_text())['managed_folder_parents'], work['managed_folder_parents'])

    def test_symlink_private_files_rejected_before_api_calls(self):
        raw = self.credential.read_bytes()
        target = self.directory / 'target.json'
        target.write_bytes(raw)
        target.chmod(0o600)
        self.credential.unlink()
        self.credential.symlink_to(target)
        before = len(self.calls)
        with self.assertRaises(ValueError):
            self.gather()
        self.assertEqual(len(self.calls), before)

    def test_cli_stdin_is_bounded_and_stdout_contains_no_secrets(self):
        body = json.dumps(dict(credential_envelope=self.envelope, inventory=self.inventory)).encode()
        for input_body in (body, b'PRIVATE malformed', b'x' * (migration.MAX_FILE_BYTES + 1)):
            out = io.StringIO()
            with patch('drive_migration.sys.stdin', SimpleNamespace(buffer=io.BytesIO(input_body))), \
                    patch('drive_migration.apply_migration', side_effect=RuntimeError('fresh-sensitive-grant PRIVATE')), \
                    redirect_stdout(out):
                self.assertEqual(migration.main(['apply', '--owner', 'Casey']), 1)
            value = json.loads(out.getvalue())
            self.assertFalse(value['ok'])
            self.assertNotIn('sensitive', out.getvalue())
            self.assertNotIn('PRIVATE', out.getvalue())


if __name__ == '__main__':
    unittest.main()
