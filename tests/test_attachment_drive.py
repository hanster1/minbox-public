import copy
import hashlib
import json
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
        self.deletes = []
        self.delete_mode = None
        self.missing_status = 404

    def request(self, method, url, body, headers, timeout):
        path = urlparse(url).path
        query = parse_qs(urlparse(url).query)
        file_id = path.rsplit('/', 1)[-1]
        if method == 'DELETE':
            self.assertIsNone(body)
            persisted = json.loads(self.path.read_text())
            self.assertTrue(any(record['entry']['drive_file_id'] == file_id for record in persisted['attachments_pending_deletions'].values()))
            self.deletes.append(file_id)
            if self.delete_mode == 'denied':
                raise HTTPError(url, 403, 'synthetic denied', {}, None)
            if self.delete_mode != 'retained':
                self.files.pop(file_id, None)
            if self.delete_mode in ('uncertain', 'retained'):
                raise AdapterError('HTTP request failed; private details withheld')
            return {}
        if method == 'GET' and '/files/' in path and file_id not in self.files and file_id != 'generateIds':
            raise HTTPError(url, self.missing_status, 'synthetic missing', {}, None)
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

    def test_withdraw_only_selected_images_preserves_other_images_and_docs(self):
        client = self.client()
        other = dict(self.message, source_id='archive://Casey/google-messages/2', attachments=[dict(self.item, media_id='other')])
        client.publish_attachments([self.message, other])
        selected = self.item['drive_file_id']
        retained = other['attachments'][0]['drive_file_id']
        result = client.attachments.withdraw_phone_spam([self.message['source_id']])
        self.assertEqual(result, {'withdrawn_images': 1, 'pending_image_deletions': 0})
        self.assertEqual(self.deletes, [selected])
        self.assertIn(retained, self.files)
        self.assertIn('attachments-folder', self.files)
        self.assertTrue(all(doc in self.files for doc in self.config['documents'].values()))
        self.assertEqual(len(self.client().manifest['attachments']), 1)

    def test_uncertain_delete_is_completed_only_after_missing_readback(self):
        client = self.client()
        client.publish_attachments([self.message])
        self.delete_mode = 'uncertain'
        self.assertEqual(client.attachments.withdraw_phone_spam([self.message['source_id']])['withdrawn_images'], 1)
        self.assertFalse(self.client().manifest['attachments_pending_deletions'])

    def test_delete_retained_then_crash_window_404_recovers_before_init_verify(self):
        client = self.client()
        client.publish_attachments([self.message])
        self.delete_mode = 'retained'
        with self.assertRaises(AdapterError):
            client.attachments.withdraw_phone_spam([self.message['source_id']])
        self.assertTrue(json.loads(self.path.read_text())['attachments_pending_deletions'])
        self.files.pop(self.item['drive_file_id'])  # The uncertain request eventually completed.
        resumed = self.client()
        self.assertFalse(resumed.manifest['attachments'])
        self.assertFalse(resumed.manifest['attachments_pending_deletions'])
        self.assertEqual(len(self.deletes), 1)

    def test_delete_403_holds_journal_for_later_publisher(self):
        client = self.client()
        client.publish_attachments([self.message])
        self.delete_mode = 'denied'
        with self.assertRaises(HTTPError) as caught:
            client.attachments.withdraw_phone_spam([self.message['source_id']])
        self.assertEqual(caught.exception.code, 403)
        self.assertTrue(json.loads(self.path.read_text())['attachments_pending_deletions'])
        self.delete_mode = None
        self.assertFalse(self.client().manifest['attachments'])
        self.assertEqual(len(self.deletes), 2)

    def test_missing_readback_permission_denial_cannot_complete_deletion(self):
        client = self.client()
        client.publish_attachments([self.message])
        self.missing_status = 403
        with self.assertRaises(HTTPError) as caught:
            client.attachments.withdraw_phone_spam([self.message['source_id']])
        self.assertEqual(caught.exception.code, 403)
        self.assertTrue(json.loads(self.path.read_text())['attachments_pending_deletions'])
        self.missing_status = 404
        self.assertFalse(self.client().manifest['attachments_pending_deletions'])
        self.assertEqual(len(self.deletes), 1)

    def test_unregistered_missing_image_is_not_treated_as_deleted(self):
        client = self.client()
        client.publish_attachments([self.message])
        self.files.pop(self.item['drive_file_id'])
        with self.assertRaises(HTTPError):
            client.attachments.withdraw_phone_spam([self.message['source_id']])
        self.assertFalse(self.deletes)
        self.assertTrue(client.manifest['attachments'])

    def test_durable_journal_write_failure_never_deletes(self):
        client = self.client()
        client.publish_attachments([self.message])
        with patch('attachment_drive.write_json', side_effect=OSError('synthetic disk failure')):
            with self.assertRaises(OSError):
                client.attachments.withdraw_phone_spam([self.message['source_id']])
        self.assertFalse(self.deletes)
        self.assertFalse(client.manifest['attachments_pending_deletions'])

    def test_withdraw_refresh_rejects_changed_parent_owner_identity_and_checksum(self):
        client = self.client()
        client.publish_attachments([self.message])
        file_id = self.item['drive_file_id']
        for key, value in [('parents', ['outside']), ('shared', True), ('owners', [{'emailAddress': 'other@example.invalid'}]),
                           ('mimeType', 'application/vnd.google-apps.document'), ('size', '0'),
                           ('md5Checksum', '0' * 32), ('appProperties', {'familyArchiveImage': 'wrong'})]:
            original = copy.deepcopy(self.files[file_id])
            self.files[file_id][key] = value
            with self.assertRaises((ValueError, RuntimeError)):
                client.attachments.withdraw_phone_spam([self.message['source_id']])
            self.files[file_id] = original
        self.assertFalse(self.deletes)

    def test_changed_root_or_attachments_folder_privacy_blocks_withdrawal(self):
        client = self.client()
        client.publish_attachments([self.message])
        for file_id in ('full-folder', 'attachments-folder'):
            self.files[file_id]['shared'] = True
            with self.assertRaises(ValueError):
                client.attachments.withdraw_phone_spam([self.message['source_id']])
            self.files[file_id]['shared'] = False
        self.assertFalse(self.deletes)

    def test_manifest_alias_to_doc_or_bystander_is_never_deleted(self):
        client = self.client()
        client.publish_attachments([self.message])
        identity, entry = next(iter(client.manifest['attachments'].items()))
        original = entry['drive_file_id']
        for protected in ('guide', 'attachments-folder', 'full-folder'):
            entry['drive_file_id'] = protected
            with self.assertRaises(ValueError):
                client.attachments.withdraw_phone_spam([self.message['source_id']])
        entry['drive_file_id'] = original
        self.assertFalse(self.deletes)

    def test_historical_orphan_identity_deleted_with_original_checksum(self):
        client = self.client()
        client.publish_attachments([self.message])
        historical = copy.deepcopy(self.message)
        historical['attachments'][0]['media_id'] = 'older'
        client.publish_attachments([historical])
        old_identity = client.attachments.identity(historical['source_id'], historical['attachments'][0])
        client.manifest['attachments'].pop(old_identity)
        from publisher_status import write_json
        write_json(client.path, client.manifest)
        result = client.attachments.withdraw_phone_spam([self.message['source_id']], [self.message, historical])
        self.assertEqual(result['withdrawn_images'], 2)

    def test_proven_new_empty_failed_upload_can_be_deleted(self):
        self.fail_creation = True
        client = self.client()
        self.assertEqual(client.publish_attachments([self.message])['pending_images'], 1)
        self.assertTrue(client.manifest['attachments_pending_uploads'])
        self.assertEqual(client.attachments.withdraw_phone_spam([self.message['source_id']])['withdrawn_images'], 1)
        self.assertFalse(client.manifest['attachments_pending_uploads'])

    def test_unproven_empty_orphan_is_not_deleted(self):
        client = self.client()
        client.publish_attachments([self.message])
        client.manifest['attachments'].clear()
        image = self.files[self.item['drive_file_id']]
        image.update(size='0', md5Checksum=hashlib.md5(b'').hexdigest())
        with self.assertRaises(RuntimeError):
            client.attachments.withdraw_phone_spam([self.message['source_id']], [self.message])
        self.assertFalse(self.deletes)

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

    def test_pending_generated_id_reused_when_search_lags_uncertain_creation(self):
        self.fail_creation = True
        client = self.client()
        self.assertEqual(client.publish_attachments([self.message])['pending_images'], 1)
        pending = copy.deepcopy(next(iter(client.manifest['attachments_pending_uploads'].values())))
        resumed = self.client()
        with patch.object(resumed.attachments, 'find', return_value=None) as search, \
                patch.object(resumed, 'call', wraps=resumed.call) as called:
            self.assertEqual(resumed.publish_attachments([self.message])['published_images'], 1)
        search.assert_not_called()
        self.assertFalse(any('generateIds' in call.args[1] for call in called.call_args_list))
        self.assertEqual(self.item['drive_file_id'], pending['drive_file_id'])
        self.assertEqual((self.posts, self.uploads), (2, 1))

    def test_pending_generated_id_recreated_after_failed_create_before_remote_write(self):
        client = self.client()
        original = client.call
        def fail_before_post(method, suffix, body=None):
            if method == 'POST' and body and 'familyArchiveImage' in body.get('appProperties', {}):
                raise AdapterError('HTTP request failed; private details withheld')
            return original(method, suffix, body)
        with patch.object(client, 'call', side_effect=fail_before_post):
            self.assertEqual(client.publish_attachments([self.message])['pending_images'], 1)
        pending = copy.deepcopy(next(iter(client.manifest['attachments_pending_uploads'].values())))
        self.assertNotIn(pending['drive_file_id'], self.files)
        resumed = self.client()
        with patch.object(resumed, 'call', wraps=resumed.call) as called:
            self.assertEqual(resumed.publish_attachments([self.message])['published_images'], 1)
        self.assertFalse(any('generateIds' in call.args[1] for call in called.call_args_list))
        posts = [call.args[2] for call in called.call_args_list if call.args[0] == 'POST']
        self.assertEqual([body['id'] for body in posts], [pending['drive_file_id']])
        self.assertEqual(self.item['drive_file_id'], pending['drive_file_id'])

    def test_pending_upload_metadata_mutation_or_permission_denial_fails_closed(self):
        self.fail_creation = True
        client = self.client()
        client.publish_attachments([self.message])
        identity, pending = next(iter(client.manifest['attachments_pending_uploads'].items()))
        original = copy.deepcopy(pending)
        pending['md5'] = '0' * 32
        with self.assertRaises(ValueError):
            client.publish_attachments([self.message])
        self.assertEqual(client.manifest['attachments_pending_uploads'][identity]['drive_file_id'], original['drive_file_id'])
        pending.update(original)
        remote = self.files.pop(pending['drive_file_id'])
        self.missing_status = 403
        with self.assertRaises(HTTPError):
            client.publish_attachments([self.message])
        self.assertEqual((self.posts, self.uploads), (2, 0))
        self.files[pending['drive_file_id']] = remote

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
