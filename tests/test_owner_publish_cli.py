import copy
import json
from pathlib import Path
import tempfile
import unittest
from urllib.parse import urlparse, parse_qs
from owner_publish_cli import OwnerDocs, failure_details
from archive_io import AdapterError
from unittest.mock import Mock
from urllib.error import HTTPError


class FailureDiagnostics(unittest.TestCase):
    def test_nested_http_status_does_not_expose_private_error_details(self):
        original = HTTPError('https://private.invalid/secret', 503, 'PRIVATE BODY',
                             {'Authorization': 'PRIVATE TOKEN'}, None)
        self.addCleanup(original.close)
        middle = AdapterError('PRIVATE source text')
        middle.__context__ = original
        outer = AdapterError('PRIVATE provider text')
        outer.__context__ = middle
        result = failure_details(outer)
        self.assertEqual(result, {'error_code': 'http_failure', 'http_status': 503})
        self.assertNotIn('PRIVATE', json.dumps(result))
        self.assertNotIn('private.invalid', json.dumps(result))

    def test_fixed_categories_and_cyclic_exception_chain(self):
        self.assertEqual(failure_details(BlockingIOError()), {'error_code': 'publisher_busy'})
        self.assertEqual(failure_details(TimeoutError('PRIVATE')), {'error_code': 'transport_failure'})
        self.assertEqual(failure_details(RuntimeError('publication readback mismatch')),
                         {'error_code': 'readback_mismatch'})
        error = ValueError('PRIVATE')
        error.__context__ = error
        self.assertEqual(failure_details(error), {'error_code': 'publication_failed'})


class OwnerTransport(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'manifest.json'
        self.config = dict(owner='Casey', folder_id='full-folder', corrections_folder_id='work-folder',
            google_account_email='synthetic@example.invalid', credentials_file='/private/unused.json',
            manifest_file=str(self.path), documents=dict(guide='guide', status='status', corrections='corrections'))
        def metadata(file_id, mime, parent=None):
            return dict(id=file_id, mimeType=mime, parents=[parent] if parent else [], shared=False,
                trashed=False, owners=[{'emailAddress':'synthetic@example.invalid'}], capabilities={'canEdit':True})
        self.files = {f:metadata(f, 'application/vnd.google-apps.folder') for f in ('full-folder', 'work-folder')}
        for key in self.config['documents']:
            self.files[key] = metadata(key, 'application/vnd.google-apps.document',
                'work-folder' if key == 'corrections' else 'full-folder')
        self.created = 0
        self.chunk = None

    def request(self, method, url, body, headers, timeout):
        path = urlparse(url).path
        if path.endswith('/about'):
            return {'user': {'emailAddress':'synthetic@example.invalid'}}
        if method == 'GET' and path.endswith('/files'):
            return {'files': [{'id':self.chunk}] if self.chunk else []}
        if method == 'POST' and path.endswith('/files'):
            self.created += 1
            self.chunk = 'chunk-' + str(self.created)
            self.files[self.chunk] = dict(id=self.chunk, mimeType=body['mimeType'], parents=body['parents'],
                shared=False, trashed=False, owners=[{'emailAddress':'synthetic@example.invalid'}], capabilities={'canEdit':True})
            self.assertEqual(body['name'], 'Casey Text Archive — Messages 2026')
            self.assertIn('familyArchiveChunk', body['appProperties'])
            return {'id':self.chunk}
        return copy.deepcopy(self.files[path.rsplit('/',1)[-1]])

    def client(self):
        return OwnerDocs(self.config, request=self.request, token_provider=lambda:'synthetic-token')

    def test_manifest_resume_and_retry_identity_readonly_corrections(self):
        first = self.client()
        doc = first.ensure_document('messages:2026:part001', 'Casey Text Archive — Messages 2026')
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertNotIn('corrections', first.client.write_ids)
        second = self.client()
        self.assertEqual(second.ensure_document('messages:2026:part001', 'Casey Text Archive — Messages 2026'), doc)
        self.assertEqual(self.created, 1)
        self.path.unlink()  # Simulate creation succeeded but manifest persistence failed.
        recovered = self.client()
        self.assertEqual(recovered.ensure_document('messages:2026:part001', 'Casey Text Archive — Messages 2026'), doc)
        self.assertEqual(self.created, 1)

    def test_private_account_folder_doc_bindings_fail_closed(self):
        for file, key, value in [('full-folder','shared',True), ('guide','parents',['other']),
                                 ('corrections','trashed',True), ('guide','owners',[])]:
            original = copy.deepcopy(self.files[file])
            self.files[file][key] = value
            with self.assertRaises(ValueError):
                self.client()
            self.files[file] = original
        self.config['google_account_email'] = 'wrong@example.invalid'
        with self.assertRaises(ValueError):
            self.client()
        self.assertEqual(self.created, 0)

    def test_verified_output_readback_is_used_once_but_corrections_are_fresh(self):
        client = self.client()
        transport = Mock()
        transport.take_verified_readback.side_effect = ['verified output', None]
        transport.read.return_value = 'fresh content'
        client.client = transport
        self.assertEqual(client.read('guide'), 'verified output')
        self.assertEqual(client.read('guide'), 'fresh content')
        self.assertEqual(client.read('corrections'), 'fresh content')
        self.assertEqual(transport.take_verified_readback.call_count, 2)
        self.assertEqual(transport.read.call_count, 2)

    def test_manifest_binding_and_wrong_owner_title_refused(self):
        client = self.client()
        with self.assertRaises(ValueError):
            client.ensure_document('messages:2026:part001', 'Jordan Text Archive — Messages')
        self.path.write_text(json.dumps({'owner':'Jordan','folder_id':'full-folder','chunks':{}}))
        self.path.chmod(0o600)
        with self.assertRaises(ValueError):
            self.client()

    def test_selected_folder_boundary_checked_before_documents_or_writes(self):
        self.config.update(folder_access='selected_folder',
            google_scopes=['https://www.googleapis.com/auth/drive.file'], archive_root_folder_id='full-folder')
        self.files['full-folder']['name'] = 'An arbitrary selected folder'
        self.files['full-folder']['parents'] = ['unrelated-location']
        self.files['work-folder']['parents'] = ['full-folder']
        client = self.client()
        self.assertEqual(self.created, 0)
        self.assertNotIn('corrections', client.client.write_ids)
        self.files['work-folder']['parents'] = ['outside']
        requested = []
        def request(method, url, body, headers, timeout):
            requested.append((method, urlparse(url).path.rsplit('/', 1)[-1]))
            return self.request(method, url, body, headers, timeout)
        with self.assertRaises(ValueError):
            OwnerDocs(self.config, request=request, token_provider=lambda: 'synthetic-token')
        self.assertFalse(any(identifier in self.config['documents'].values() for _, identifier in requested))
        self.assertTrue(all(method == 'GET' for method, _ in requested))
        self.assertEqual(self.created, 0)
