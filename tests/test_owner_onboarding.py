import copy
from contextlib import redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from urllib.parse import urlparse, parse_qs

from owner_onboarding import provision, receive, main, MAX_ENVELOPE_BYTES, FOLDER, DOCUMENT, correction_template, onboarding_lock
from owner_publish_cli import write_json
from archive_io import DRIVE_SCOPES, FILE_SCOPES
from archive_corrections import parse_corrections


class FakeGoogle:
    email = 'fixture@example.invalid'

    def __init__(self):
        self.files = {'folder': self.metadata('folder', FOLDER)}
        self.text = {}
        self.created = self.writes = 0
        self.fail_creation = False

    def metadata(self, identity, mime, parent=None):
        return dict(id=identity, mimeType=mime, parents=[parent] if parent else [], shared=False,
                    trashed=False, owners=[{'emailAddress': self.email}], capabilities={'canEdit': True})

    def request(self, method, url, body, headers, timeout):
        path = urlparse(url).path
        if path.endswith('/about'):
            return {'user': {'emailAddress': self.email}}
        if path.endswith('/files'):
            if method == 'GET':
                query = parse_qs(urlparse(url).query)['q'][0]
                return {'files': [{'id': key} for key, meta in self.files.items()
                                  if meta.get('appProperties', {}).get('familyArchiveOwnerDoc', '!') in query]}
            self.created += 1
            identity = 'doc' + str(self.created)
            self.files[identity] = dict(self.metadata(identity, DOCUMENT, body['parents'][0]), appProperties=body['appProperties'])
            self.text[identity] = '\n'
            if self.fail_creation:
                self.fail_creation = False
                raise RuntimeError('fixture creation response lost')
            return {'id': identity}
        if '/drive/' in path:
            return copy.deepcopy(self.files[path.rsplit('/', 1)[-1]])
        identity = path.rsplit('/', 1)[-1].split(':')[0]
        if method == 'GET':
            text = self.text[identity]
            return dict(revisionId='revision', tabs=[dict(tabProperties={'tabId': 'tab'}, documentTab={
                'body': {'content': [{'startIndex': 1, 'endIndex': len(text) + 1,
                                     'paragraph': {'elements': [{'textRun': {'content': text}}]}}]}})])
        self.writes += 1
        self.text[identity] = ''.join(r['insertText']['text'] for r in body['requests'] if 'insertText' in r) + '\n'
        return {}


class OnboardingTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.drive = self.base / 'drive.json'
        self.credentials = self.base / 'grant.json'
        write_json(self.credentials, {'type': 'authorized_user'})
        self.binding = dict(owner='Taylor', google_account_email=FakeGoogle.email, folder_id='folder',
                            google_scopes=list(FILE_SCOPES), credentials_file=str(self.credentials),
                            folder_access='selected_folder', archive_root_folder_id='folder')
        write_json(self.drive, self.binding)
        self.publisher = self.base / 'publisher.json'
        self.root = self.base / 'archive'
        self.runtime = self.base / 'runtime'
        self.google = FakeGoogle()

    def setup_publisher(self):
        return provision('Taylor', self.drive, self.root, self.publisher, self.runtime,
                         request=self.google.request, token_provider=lambda: 'fixture')

    def envelope(self):
        binding = {k: v for k, v in self.binding.items() if k != 'credentials_file'}
        return dict(binding=binding, credentials=dict(type='authorized_user', refresh_token='fixture-refresh',
                                                     client_id='fixture-client', client_secret='fixture-secret', token='discard-me'))

    def receive(self, envelope=None):
        def token(path):
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertNotIn('token', json.loads(path.read_text()))
            return 'fixture'
        return receive('Taylor', envelope or self.envelope(), self.base / 'owners',
                       request=self.google.request, token_provider=token)

    def test_same_owner_concurrent_setup_is_rejected_without_api_writes(self):
        with onboarding_lock(self.drive.parent):
            with self.assertRaises(BlockingIOError):
                self.setup_publisher()

    def test_legacy_granted_drive_and_sheets_scopes_are_preserved(self):
        self.setup_publisher()
        config = json.loads(self.drive.read_text())
        config['google_scopes'] = [*DRIVE_SCOPES, 'https://www.googleapis.com/auth/spreadsheets']
        config.pop('folder_access');config.pop('archive_root_folder_id')
        self.drive.write_text(json.dumps(config))
        publisher = json.loads(self.publisher.read_text())
        publisher.update(google_scopes=config['google_scopes'])
        publisher.pop('folder_access');publisher.pop('archive_root_folder_id')
        write_json(self.publisher, publisher)
        self.setup_publisher()
        self.assertEqual(json.loads(self.publisher.read_text())['google_scopes'], config['google_scopes'])

    def test_new_broad_or_extra_scope_grants_are_refused(self):
        for scopes in (DRIVE_SCOPES, [*FILE_SCOPES, 'https://www.googleapis.com/auth/spreadsheets']):
            config = dict(self.binding, google_scopes=scopes)
            write_json(self.drive, config)
            with self.assertRaises(ValueError):self.setup_publisher()
            with self.assertRaises(ValueError):
                envelope = self.envelope();envelope['binding']['google_scopes'] = scopes
                self.receive(envelope)
        self.assertEqual(self.google.created, 0)

    def test_idempotent_preserves_inputs_ledger_manifest_and_existing_settings(self):
        first = self.setup_publisher()
        correction = first['documents']['corrections']
        self.google.text[correction] = 'fixture user correction\n'
        config = json.loads(self.publisher.read_text())
        config['work_guide_id'] = 'preserved-work-guide'
        write_json(self.publisher, config)
        manifest = Path(config['manifest_file'])
        write_json(manifest, dict(owner='Taylor', folder_id='folder', chunks={}))
        ledger = Path(config['correction_path'])
        ledger.write_bytes(b'fixture-ledger')
        before = self.publisher.read_bytes(), manifest.read_bytes(), ledger.read_bytes()
        second = self.setup_publisher()
        self.assertEqual(first, second)
        self.assertEqual(self.google.created, 3)
        self.assertEqual(self.google.writes, 1)
        self.assertEqual(self.google.text[correction], 'fixture user correction\n')
        self.assertEqual(before, (self.publisher.read_bytes(), manifest.read_bytes(), ledger.read_bytes()))
        self.assertEqual(self.publisher.stat().st_mode & 0o777, 0o600)
        self.assertTrue((self.root / 'Taylor/raw').is_dir())
        self.assertEqual(parse_corrections(correction_template('Taylor').split('Corrections begin below.', 1)[1]), [])

    def test_creation_crash_recovers_app_identity_without_duplicates(self):
        self.google.fail_creation = True
        with self.assertRaises(RuntimeError):
            self.setup_publisher()
        self.assertFalse(self.publisher.exists())
        self.setup_publisher()
        self.assertEqual(self.google.created, 3)
        self.assertEqual(self.google.writes, 1)

    def test_config_persistence_crash_retains_corrections_on_retry(self):
        with patch('owner_onboarding.write_json', side_effect=RuntimeError('fixture disk error')):
            with self.assertRaises(RuntimeError):
                self.setup_publisher()
        correction = next(k for k, text in self.google.text.items() if text.strip())
        self.google.text[correction] = 'fixture added before retry\n'
        self.setup_publisher()
        self.assertEqual(self.google.created, 3)
        self.assertEqual(self.google.writes, 1)
        self.assertEqual(self.google.text[correction], 'fixture added before retry\n')

    def test_account_private_editable_and_folder_checks_precede_creation(self):
        for key, value in [('shared', True), ('trashed', True), ('owners', []), ('capabilities', {'canEdit': False})]:
            previous = copy.deepcopy(self.google.files['folder'])
            self.google.files['folder'][key] = value
            with self.assertRaises(ValueError):
                self.setup_publisher()
            self.google.files['folder'] = previous
        self.google.email = 'different@example.invalid'
        with self.assertRaises(ValueError):
            self.setup_publisher()
        self.assertEqual(self.google.created, 0)

    def test_existing_publisher_wrong_root_owner_account_folder_preserved(self):
        self.setup_publisher()
        original = json.loads(self.publisher.read_text())
        for key, value in [('owner', 'Morgan'), ('archive_root', str(self.base / 'different')),
                           ('google_account_email', 'other@example.invalid'), ('folder_id', 'other')]:
            invalid = dict(original, **{key: value})
            write_json(self.publisher, invalid)
            before = self.publisher.read_bytes()
            with self.assertRaises(ValueError):
                self.setup_publisher()
            self.assertEqual(self.publisher.read_bytes(), before)

    def test_receive_private_paths_renewal_and_failed_reconnect_preserves_files(self):
        first = self.receive()
        target = Path(first['credentials_file'])
        config = Path(first['drive_config'])
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)
        self.assertEqual(config.stat().st_mode & 0o777, 0o600)
        self.assertEqual(json.loads(config.read_text())['credentials_file'], str(target))
        self.assertEqual(self.receive(), first)
        before = target.read_bytes(), config.read_bytes()
        self.google.email = 'other@example.invalid'
        with self.assertRaises(ValueError):
            self.receive()
        self.assertEqual(before, (target.read_bytes(), config.read_bytes()))
        self.assertFalse(list(target.parent.glob('.receive-*')))
        self.google.email = FakeGoogle.email
        for key, value in [('owner', 'Morgan'), ('folder_id', 'different'), ('google_account_email', 'other@example.invalid')]:
            envelope = self.envelope()
            envelope['binding'][key] = value
            with self.assertRaises(ValueError):
                self.receive(envelope)
            self.assertEqual(before, (target.read_bytes(), config.read_bytes()))

    def test_symlink_and_git_paths_rejected(self):
        linked = self.base / 'linked'
        linked.symlink_to(self.drive)
        with self.assertRaises(ValueError):
            provision('Taylor', linked, self.root, self.publisher, self.runtime,
                      request=self.google.request, token_provider=lambda: 'fixture')
        git = self.base / 'checkout'
        (git / '.git').mkdir(parents=True)
        (git / '.git/HEAD').write_text('fixture')
        with self.assertRaises(ValueError):
            receive('Taylor', self.envelope(), git, request=self.google.request, token_provider=lambda path: 'fixture')

    def test_existing_separate_correction_folder_binding_is_reused(self):
        result = self.setup_publisher()
        self.google.files['correction-root'] = self.google.metadata('correction-root', FOLDER)
        self.google.files['correction-root']['parents'] = ['folder']
        self.google.files[result['documents']['corrections']]['parents'] = ['correction-root']
        config = json.loads(self.publisher.read_text())
        config['corrections_folder_id'] = 'correction-root'
        config['work_guide_id'] = 'existing-work-guide'
        write_json(self.publisher, config)
        before = self.publisher.read_bytes()
        self.assertEqual(self.setup_publisher(), result)
        self.assertEqual(self.publisher.read_bytes(), before)
        self.google.files['correction-root']['shared'] = True
        with self.assertRaises(ValueError):
            self.setup_publisher()

    def test_cli_bounds_stdin_and_hides_private_errors(self):
        for raw in (b'fixture-secret-invalid-json', b'x' * (MAX_ENVELOPE_BYTES + 1)):
            out, error = io.StringIO(), io.StringIO()
            with patch('owner_onboarding.sys.stdin', SimpleNamespace(buffer=io.BytesIO(raw))), \
                    redirect_stdout(out), redirect_stderr(error):
                self.assertEqual(main(['receive', '--owner', 'Taylor']), 1)
            self.assertEqual(out.getvalue(), '')
            self.assertNotIn('fixture-secret', error.getvalue())
            self.assertIn('private details withheld', error.getvalue())

    def test_publication_is_explicit_and_only_safe_counts_are_returned(self):
        args = ['provision', '--owner', 'Taylor', '--archive-root', str(self.root)]
        safe = dict(owner='Taylor', folder_id='folder', documents={})
        def publish(argv):
            print(json.dumps(dict(writes=2, published_messages=0, excluded_messages=0,
                                  model_calls=0, fixture_private_field='withheld')))
            return 0
        with patch('owner_onboarding.provision', return_value=safe), \
                patch('owner_publish_cli.main', side_effect=publish) as publisher:
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(args), 0)
            publisher.assert_not_called()
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(main(args + ['--publish-now']), 0)
            self.assertEqual(json.loads(out.getvalue())['publication'],
                             dict(writes=2, published_messages=0, excluded_messages=0, model_calls=0))
            self.assertNotIn('withheld', out.getvalue())


if __name__ == '__main__':
    unittest.main()
