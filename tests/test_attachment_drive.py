import copy
import hashlib
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.parse import urlparse, parse_qs
from urllib.error import HTTPError

from archive_io import AdapterError
from attachment_drive import binary_request, image_bytes
from owner_publish_cli import OwnerDocs
from tests.test_owner_publish_cli import OwnerTransport


class Images(unittest.TestCase):
    def setUp(self):
        OwnerTransport.setUp(self)
        self.config['archive_root'] = self.temp.name
        directory = Path(self.temp.name) / 'Casey' / 'attachments'
        directory.mkdir(parents=True)
        self.data = b'\x89PNG\r\n\x1a\nsynthetic image bytes'
        self.local = directory / 'one.png'
        self.local.write_bytes(self.data)
        self.item = dict(media_id='media-1', mime_type='image/png', capture_status='captured',
                         sha256=hashlib.sha256(self.data).hexdigest(), size_bytes=len(self.data), local_path=str(self.local))
        self.message = dict(source_id='archive://Casey/google-messages/1', timestamp='2026-01-01T00:00:00Z', attachments=[self.item])
        self.posts = self.uploads = 0
        self.fail_creation = self.fail_upload = False
        self.bad_checksum = False

    def request(self, method, url, body, headers, timeout):
        path = urlparse(url).path
        query = parse_qs(urlparse(url).query)
        if path.endswith('/generateIds'):
            return {'ids': ['image-' + str(self.posts + 1)]}
        if method == 'GET' and path.endswith('/files') and 'q' in query:
            q = query['q'][0]
            if 'appProperties' not in q:
                parent = q.split("'")[1]
                return {'files': [dict(v) for v in self.files.values() if v.get('parents') == [parent]]}
            prop = 'familyArchiveAttachments' if 'familyArchiveAttachments' in q else 'familyArchiveImage'
            identity = q.split("value='")[1].split("'")[0]
            return {'files': [{'id': k} for k, v in self.files.items() if v.get('appProperties', {}).get(prop) == identity]}
        if method == 'POST' and path.endswith('/files') and 'familyArchiveChunk' not in body['appProperties']:
            self.posts += 1
            file_id = body.get('id', 'attachments-folder')
            self.files[file_id] = dict(id=file_id, mimeType=body['mimeType'], parents=body['parents'], shared=False,
                trashed=False, owners=[{'emailAddress': self.config['google_account_email']}], capabilities={'canEdit': True},
                appProperties=body['appProperties'], size='0', md5Checksum=hashlib.md5(b'').hexdigest())
            if self.fail_creation and 'id' in body:
                self.fail_creation = False
                raise AdapterError('HTTP request failed; private details withheld')
            return {'id': file_id}
        return OwnerTransport.request(self, method, url, body, headers, timeout)

    def raw(self, method, url, body, headers, timeout):
        self.assertEqual(method, 'PATCH')
        self.assertEqual(body, self.data)
        self.uploads += 1
        file_id = urlparse(url).path.rsplit('/', 1)[-1]
        self.files[file_id].update(size=str(len(body)), md5Checksum='wrong' if self.bad_checksum else hashlib.md5(body).hexdigest())
        if self.fail_upload:
            self.fail_upload = False
            raise AdapterError('Image upload failed; private details withheld')
        return {'id': file_id}

    def client(self):
        return OwnerDocs(self.config, request=self.request, raw_request=self.raw, token_provider=lambda: 'synthetic')

    def test_permission_failure_needs_intervention(self):
        client = self.client()
        def denied(*args):
            try:
                raise HTTPError('https://synthetic.invalid', 403, 'synthetic denied', {}, None)
            except HTTPError as error:
                error.close()
                raise AdapterError('Image upload failed; private details withheld') from None
        client.attachments.raw_request = denied
        with self.assertRaises(AdapterError):
            client.publish_attachments([self.message])
        self.assertNotIn('drive_url', self.item)

    def test_missing_old_files_do_not_consume_upload_bound(self):
        self.config['max_image_attempts'] = 1
        newer = dict(self.message, timestamp='2027-01-01T00:00:00Z', attachments=[dict(self.item, media_id='missing', local_path=str(self.local.parent / 'missing.png'))])
        result = self.client().publish_attachments([newer, self.message])
        self.assertEqual(result['unavailable_images'], 1)
        self.assertEqual(result['published_images'], 1)

    def test_publish_readback_and_idle_zero_upload_writes(self):
        client = self.client()
        counts = client.publish_attachments([self.message])
        self.assertEqual(counts['published_images'], 1)
        self.assertEqual((self.posts, self.uploads), (2, 1))
        self.assertEqual(self.item['publication_status'], 'verified')
        self.assertIn('https://drive.google.com/file/d/', self.item['drive_url'])
        result = self.client().publish_attachments([self.message])
        self.assertEqual(result['attachment_writes'], 0)
        self.assertEqual((self.posts, self.uploads), (2, 1))

    def test_creation_timeout_reconciles_generated_identity(self):
        self.fail_creation = True
        result = self.client().publish_attachments([self.message])
        self.assertEqual(result['pending_images'], 1)
        self.assertNotIn('drive_url', self.item)
        self.assertEqual(self.client().publish_attachments([self.message])['published_images'], 1)
        self.assertEqual((self.posts, self.uploads), (2, 1))

    def test_upload_timeout_reconciles_without_reupload(self):
        self.fail_upload = True
        self.assertEqual(self.client().publish_attachments([self.message])['pending_images'], 1)
        self.assertEqual(self.client().publish_attachments([self.message])['published_images'], 1)
        self.assertEqual((self.posts, self.uploads), (2, 1))

    def test_failed_manifest_persist_adopts_existing_identity(self):
        client = self.client()
        client.attachments.folder()
        with patch('attachment_drive.write_json', side_effect=OSError('synthetic disk failure')):
            with self.assertRaises(OSError):
                client.publish_attachments([self.message])
        self.assertNotIn('drive_url', self.item)
        self.assertEqual(self.client().publish_attachments([self.message])['published_images'], 1)
        self.assertEqual((self.posts, self.uploads), (2, 1))

    def test_checksum_mismatch_never_publishes_link(self):
        self.bad_checksum = True
        with self.assertRaisesRegex(RuntimeError, 'readback mismatch'):
            self.client().publish_attachments([self.message])
        self.assertNotIn('drive_url', self.item)

    def test_remote_parent_escape_or_sharing_fails_each_run(self):
        self.client().publish_attachments([self.message])
        file_id = self.item['drive_file_id']
        for key, value in [('parents', ['outside']), ('shared', True), ('owners', [])]:
            original = copy.deepcopy(self.files[file_id])
            self.files[file_id][key] = value
            with self.assertRaises(ValueError):
                self.client()
            self.files[file_id] = original
        self.files['attachments-folder']['parents'] = ['outside']
        with self.assertRaises(ValueError):
            self.client()

    def test_local_path_escape_symlinks_hash_and_mime_rejected(self):
        for key, value in [('local_path', str(Path(self.temp.name) / 'outside.png')), ('sha256', '0' * 64),
                           ('mime_type', 'image/jpeg'), ('size_bytes', 1)]:
            item = dict(self.item, **{key: value})
            with self.assertRaises(ValueError):
                image_bytes(self.config, item)
        linked = self.local.parent / 'linked.png'
        linked.symlink_to(self.local)
        with self.assertRaises(OSError):
            image_bytes(self.config, dict(self.item, local_path=str(linked)))
        self.local.parent.rename(self.local.parent.with_name('real'))
        self.local.parent.symlink_to(self.local.parent.with_name('real'))
        with self.assertRaises(OSError):
            image_bytes(self.config, self.item)

    def test_missing_and_unsupported_media_do_not_block_text(self):
        self.local.unlink()
        result = self.client().publish_attachments([self.message])
        self.assertEqual(result['unavailable_images'], 1)
        self.assertEqual(self.posts, 0)
        self.item['capture_status'] = 'metadata_only'
        self.assertEqual(self.client().publish_attachments([self.message])['unavailable_images'], 1)

    def test_newest_first_and_attempt_bound(self):
        self.config['max_image_attempts'] = 1
        older = dict(self.message, timestamp='2020-01-01T00:00:00Z', attachments=[dict(self.item, media_id='older')])
        result = self.client().publish_attachments([older, self.message])
        self.assertEqual((result['published_images'], result['pending_images']), (1, 1))
        self.assertEqual(older['attachments'][0]['publication_status'], 'pending')
        self.assertEqual(self.item['publication_status'], 'verified')

    def test_raw_transport_rejects_untrusted_destination_and_oversize(self):
        with self.assertRaises(ValueError):
            binary_request('PATCH', 'http://example.invalid', self.data, {}, 20)
        with self.assertRaises(ValueError):
            binary_request('POST', 'https://www.googleapis.com/upload/drive/v3/files/id', self.data, {}, 20)


if __name__ == '__main__':
    unittest.main()
