import hashlib
import base64
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

import mac_messages
from mac_messages import MacMessagesError, apple_timestamp, collect, decode_attributed_body, inspect_database, read_messages
from storage import Archive


def synthetic_attributed(text, mutable=False, root_name=None):
    """Independent encoder for a tiny typedstream grammar subset; no real fixture data."""
    def number(n):
        return bytes([n]) if n < 128 else b'\x81' + n.to_bytes(2, 'little')
    def shared(value):
        return b'\x84' + number(len(value)) + value
    def clazz(name, version, parent=None):
        return b'\x84' + shared(name) + number(version) + (parent if parent else b'\x85')
    def obj(cls, fields):
        return b'\x84' + cls + fields + b'\x86'
    def group(encoding, data):
        return shared(encoding) + data
    base = clazz(b'NSObject', 0)
    string = obj(clazz(b'NSString', 1, base), group(b'+', number(len(text.encode())) + text.encode()))
    root = clazz(root_name or b'NSAttributedString', 0, base)
    if mutable:
        root = clazz(b'NSMutableAttributedString', 0, root)
    return b'\x04\x0bstreamtyped\x81\xe8\x03' + group(b'@', obj(root, group(b'@', string)))


class MacMessagesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(tempfile.gettempdir()).resolve())
        self.root = Path(self.temp.name)
        self.path = self.root / 'chat.db'
        self.db = sqlite3.connect(self.path)
        self.db.executescript('''
            CREATE TABLE message(ROWID INTEGER PRIMARY KEY,guid TEXT,text TEXT,attributedBody BLOB,
                date,is_from_me INTEGER,handle_id INTEGER,service TEXT,associated_message_guid TEXT,
                associated_message_type INTEGER,type INTEGER,item_type INTEGER,group_action_type INTEGER,
                date_edited,date_read,date_delivered,date_retracted,is_unsent INTEGER,is_deleted INTEGER,
                message_summary_info BLOB,thread_originator_guid TEXT);
            CREATE TABLE handle(ROWID INTEGER PRIMARY KEY,id TEXT);
            CREATE TABLE chat(ROWID INTEGER PRIMARY KEY,guid TEXT,chat_identifier TEXT,display_name TEXT);
            CREATE TABLE chat_message_join(message_id INTEGER,chat_id INTEGER);
            CREATE TABLE chat_handle_join(chat_id INTEGER,handle_id INTEGER);
            CREATE TABLE attachment(ROWID INTEGER PRIMARY KEY,guid TEXT,mime_type TEXT,uti TEXT,
                total_bytes INTEGER,transfer_name TEXT,filename TEXT);
            CREATE TABLE message_attachment_join(message_id INTEGER,attachment_id INTEGER);
            INSERT INTO handle VALUES(1,'synthetic@example.invalid');
            INSERT INTO handle VALUES(2,'other@example.invalid');
            INSERT INTO chat VALUES(1,'chat-guid-1','private-thread-1','Private group name');
            INSERT INTO chat VALUES(2,'chat-guid-2','private-thread-2','Second group');
            INSERT INTO chat_handle_join VALUES(1,1),(1,2),(1,2);
        ''')
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def add(self, rowid=1, **updates):
        values = dict(guid='message-guid-' + str(rowid), text='Synthetic message 🌙 café', date=500000000,
                      is_from_me=0, handle_id=1, service='iMessage', associated_message_type=0,
                      type=0, item_type=0, group_action_type=0)
        values.update(updates)
        keys = ['ROWID'] + list(values)
        self.db.execute('INSERT INTO message(' + ','.join(keys) + ') VALUES(' + ','.join('?' for _ in keys) + ')', [rowid] + list(values.values()))
        self.db.execute('INSERT INTO chat_message_join VALUES(?,1)', (rowid,))
        self.db.commit()

    def test_seconds_nanoseconds_unicode_directions_and_optional_dates(self):
        self.add(date=500000000, date_read=0, date_edited='corrupt')
        self.add(2, date=500000000 * 1000000000 + 123456789, is_from_me=1)
        records, report = read_messages(self.path)
        self.assertEqual(records[0]['timestamp'], '2016-11-05T00:53:20+00:00')
        self.assertEqual(records[1]['timestamp'], '2016-11-05T00:53:20.123456+00:00')
        self.assertEqual(records[0]['text'], 'Synthetic message 🌙 café')
        self.assertEqual(records[0]['direction'], 'received')
        self.assertEqual(records[1]['direction'], 'sent')
        self.assertEqual(records[1]['sender'], 'self')
        self.assertEqual(records[0]['participants'], ['other@example.invalid', 'synthetic@example.invalid'])
        self.assertIsNone(records[0]['apple_metadata']['date_edited'])
        self.assertNotIn('date_read', records[0]['apple_metadata'])
        self.assertEqual(report['gaps']['invalid_optional_dates'], 1)
        self.assertIsNone(apple_timestamp(float('nan')))
        self.assertIsNone(apple_timestamp(0))
        self.assertIsNone(apple_timestamp(-10))
        self.assertIsNone(apple_timestamp(10 ** 30))

    def test_group_join_duplicates_multichat_ids_and_guid_dedupe(self):
        self.add()
        original = read_messages(self.path)[0][0]['id']
        self.db.execute('INSERT INTO chat_message_join VALUES(1,1),(1,2)')
        self.db.commit()
        records, _ = read_messages(self.path)
        self.assertEqual(len(records), 2)
        self.assertEqual(len({r['id'] for r in records}), 2)
        self.assertIn(original, {r['id'] for r in records})
        self.add(2, guid='message-guid-1')
        self.assertEqual(len(read_messages(self.path)[0]), 2)
        self.db.execute("UPDATE message SET text='Conflicting body' WHERE ROWID=2")
        self.db.commit()
        with self.assertRaisesRegex(MacMessagesError, 'Conflicting'):
            read_messages(self.path)

    def test_missing_id_bad_dates_and_chat_fallback_no_global_merge(self):
        self.add(guid=None)
        self.add(2, date=0)
        self.add(3, date='corrupt')
        self.add(4)
        self.db.execute("UPDATE chat SET guid=NULL WHERE ROWID=1")
        self.db.commit()
        records, report = read_messages(self.path)
        self.assertEqual(len(records), 1)
        self.assertTrue(records[0]['conversation_id'].startswith('apple-chat-identifier:'))
        self.assertEqual(report['gaps']['invalid_timestamps'], 2)
        self.assertEqual(report['gaps']['missing_message_ids'], 1)
        self.db.execute("INSERT INTO chat VALUES(3,NULL,'private-thread-1','duplicate')")
        self.db.commit()
        self.assertEqual(read_messages(self.path)[0], [])

    def test_blank_attributed_missing_decoder_and_oversized_gap(self):
        self.add(text=None, attributedBody=b'not safely decoded PRIVATE binary')
        self.add(2, text=None)
        self.add(3, text=None, attributedBody=b'x' * (mac_messages.MAX_BODY_BYTES + 1))
        with patch.dict(sys.modules, {'typedstream': None}):
            records, report = read_messages(self.path)
        states = {r['apple_metadata']['guid']: r['apple_metadata']['body_status'] for r in records}
        self.assertEqual(states, {'message-guid-1': 'decoder_unavailable', 'message-guid-2': 'blank', 'message-guid-3': 'attributed_body_too_large'})
        self.assertTrue(all(r['text'] == '' for r in records))
        self.assertEqual(report['gaps']['unavailable_bodies'], 2)
        self.assertNotIn('PRIVATE', json.dumps(records))
        self.assertEqual(report['health'], 'partial')

    @unittest.skipUnless(importlib.util.find_spec('typedstream'), 'optional pytypedstream not installed')
    def test_optional_parser_real_independent_unicode_mutable_and_rejected_graph(self):
        text = 'Synthetic long Unicode 🌙 café ' * 10
        for mutable in (False, True):
            self.assertEqual(decode_attributed_body(synthetic_attributed(text, mutable)), (text, 'attributed_body_decoded'))
        self.assertEqual(decode_attributed_body(synthetic_attributed('private unrelated', root_name=b'OtherRoot'))[1], 'attributed_body_unsupported')
        self.assertEqual(decode_attributed_body(b'malformed PRIVATE')[1], 'attributed_body_unsupported')
        self.add(text=None, attributedBody=synthetic_attributed(text))
        records, report = read_messages(self.path)
        self.assertEqual(records[0]['text'], text)
        self.assertEqual(report['gaps']['decoded_bodies'], 1)

    def test_reactions_system_unsent_and_edits_not_work_text(self):
        self.add(text='Loved a quoted work request', associated_message_type=2000, associated_message_guid='p:0/original-guid')
        self.add(2, text='System actor text', item_type=1)
        self.add(3, text='Retracted content', is_unsent=1)
        self.add(4, text='Observed edited body', date_edited=500000100, message_summary_info=b'PRIVATE history bytes')
        records, report = read_messages(self.path)
        by_guid = {r['apple_metadata']['guid']: r for r in records}
        self.assertEqual(by_guid['message-guid-1']['apple_metadata']['record_type'], 'reaction')
        self.assertEqual(by_guid['message-guid-1']['apple_metadata']['associated_message_guid'], 'p:0/original-guid')
        for i in range(1, 4):
            self.assertEqual(by_guid['message-guid-' + str(i)]['text'], '')
        self.assertTrue(by_guid['message-guid-3']['apple_metadata']['is_unsent'])
        self.assertEqual(by_guid['message-guid-4']['text'], 'Observed edited body')
        self.assertEqual(by_guid['message-guid-4']['apple_metadata']['edit_history_status'], 'metadata_only')
        self.assertNotIn('PRIVATE', json.dumps(records))
        self.assertEqual(report['gaps']['reaction_records'], 1)
        self.assertEqual(report['gaps']['system_records'], 2)

    def test_attachments_only_metadata_no_absolute_paths_or_file_reads(self):
        self.add()
        self.db.execute("INSERT INTO attachment VALUES(1,'att-guid','image/jpeg','public.jpeg',123,'/Users/PRIVATE/picture.jpg','/Users/PRIVATE/secret.jpg')")
        self.db.execute('INSERT INTO message_attachment_join VALUES(1,1),(1,1)')
        self.db.commit()
        records, report = read_messages(self.path)
        self.assertEqual(len(records[0]['attachments']), 1)
        attachment = records[0]['attachments'][0]
        self.assertEqual(attachment['name'], 'picture.jpg')
        self.assertEqual(attachment['capture'], 'metadata_only')
        self.assertFalse(attachment['available'])
        self.assertNotIn('/Users', json.dumps(records))
        self.assertNotIn('filename', attachment)
        self.assertTrue(report['attachment_metadata_supported'])

    def test_collect_copies_image_and_preserves_it_after_source_disappears(self):
        self.add(text='')
        directory = self.root / 'Attachments'
        directory.mkdir()
        image = directory / 'synthetic.png'
        image.write_bytes(b'\x89PNG\r\n\x1a\n' + b'synthetic image')
        self.db.execute('INSERT INTO attachment VALUES(?,?,?,?,?,?,?)',
                        (1, 'image-guid', 'image/png', 'public.png', image.stat().st_size,
                         'synthetic.png', str(image)))
        self.db.execute('INSERT INTO message_attachment_join VALUES(1,1)')
        self.db.commit()
        root = self.root / 'archive'
        with patch('attachment_capture.shutil.which', return_value=None):
            result = collect(self.path, root, 'Alex')
        self.assertEqual(result['image_capture']['captured'], 1)
        attachment = Archive(root).messages('Alex')[0]['attachments'][0]
        self.assertEqual(Path(attachment['local_path']).read_bytes(), image.read_bytes())
        self.assertNotIn('_source_path', attachment)
        self.assertEqual(Path(attachment['local_path']).stat().st_mode & 0o777, 0o600)
        image.unlink()
        result = collect(self.path, root, 'Alex')
        self.assertEqual(result['image_capture']['captured'], 1)
        self.assertEqual(result['updated'], 0)

    def test_mac_image_source_cannot_escape_attachment_directory(self):
        records = [{'attachments': [{'guid': 'image', 'mime_type': 'image/png',
                                      '_source_path': str(self.path)}]}]
        result = mac_messages.capture_mac_images(records, self.root / 'archive', 'Alex', self.path)
        self.assertEqual(result['unavailable'], 1)
        self.assertNotIn('_source_path', records[0]['attachments'][0])

    def test_schema_diagnostics_missing_and_private_errors(self):
        self.add()
        report = inspect_database(self.path)
        self.assertTrue(report['supported'])
        self.assertNotIn('Synthetic message', json.dumps(report))
        self.assertNotIn('private-thread', json.dumps(report))
        self.assertNotIn('Private group', json.dumps(report))
        self.db.execute('DROP TABLE handle')
        self.db.commit()
        with self.assertRaises(MacMessagesError) as caught:
            inspect_database(self.path)
        self.assertEqual(caught.exception.error_code, 'unsupported_schema')
        with self.assertRaises(MacMessagesError) as caught:
            inspect_database(self.root / 'PRIVATE missing path')
        self.assertNotIn('PRIVATE', str(caught.exception))
        self.assertIn('Full Disk Access', str(caught.exception))

    def test_missing_required_column_byte_cap_and_check_cli_no_bodies(self):
        self.add(text='PRIVATE source body ' * 100)
        with self.assertRaises(MacMessagesError) as caught:
            read_messages(self.path, max_bytes=1024)
        self.assertEqual(caught.exception.error_code, 'bounds_exceeded')
        with patch.object(sys, 'argv', ['mac_messages.py', '--database', str(self.path), '--check-only']):
            with patch('builtins.print') as printed:
                self.assertEqual(mac_messages.main(), 0)
        self.assertNotIn('PRIVATE source', printed.call_args.args[0])
        self.db.execute('ALTER TABLE message DROP COLUMN handle_id')
        self.db.commit()
        with self.assertRaises(MacMessagesError) as caught:
            inspect_database(self.path)
        self.assertEqual(caught.exception.error_code, 'unsupported_schema')

    def test_wal_visible_consistent_snapshot_no_source_writes(self):
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA wal_autocheckpoint=0')
        self.add()
        wal = Path(str(self.path) + '-wal')
        before = (self.path.read_bytes(), wal.read_bytes())
        records, _ = read_messages(self.path)
        self.assertEqual(len(records), 1)
        self.assertEqual(before, (self.path.read_bytes(), wal.read_bytes()))
        original_schema = mac_messages._schema
        def concurrent_schema(db):
            result = original_schema(db)
            self.add(2)
            return result
        with patch('mac_messages._schema', side_effect=concurrent_schema):
            records, report = read_messages(self.path)
        self.assertEqual(len(records), 1)
        self.assertEqual(report['database_messages'], 1)
        self.assertEqual(len(read_messages(self.path)[0]), 2)

    @unittest.skipUnless(importlib.util.find_spec('typedstream'), 'optional decoder not installed')
    def test_unchanged_binary_body_reuses_verified_decode(self):
        self.add(text=None, attributedBody=synthetic_attributed('Synthetic decoded request'))
        archive_root = self.root / 'archive'
        first = collect(self.path, archive_root, 'Alex')
        self.assertEqual(first['imported'], 1)
        with patch.object(mac_messages, 'decode_attributed_body', side_effect=AssertionError('reuse verified body')):
            second = collect(self.path, archive_root, 'Alex')
        self.assertEqual(second['status'], 'imported')
        self.assertEqual(second['updated'], 0)
        self.assertEqual(second['gaps']['reused_decoded_bodies'], 1)

    def test_unavailable_source_blobs_retained_privately_for_decoder_repair(self):
        original = b'synthetic unsupported archived body'
        self.add(text=None, attributedBody=original, message_summary_info=b'synthetic edit bytes')
        records, report = read_messages(self.path)
        self.assertEqual(records[0]['text'], '')
        blobs = records[0]['source_blobs']
        self.assertEqual(base64.b64decode(blobs['attributedBody']['data']), original)
        self.assertEqual(base64.b64decode(blobs['message_summary_info']['data']), b'synthetic edit bytes')
        result = collect(self.path, self.root / 'archive', 'Alex')
        self.assertEqual(result['imported'], 1)
        self.db.execute('DELETE FROM message')
        self.db.commit()
        retained = Archive(self.root / 'archive').messages('Alex')[0]
        self.assertEqual(base64.b64decode(retained['source_blobs']['attributedBody']['data']), original)

    def test_delta_import_owner_isolation_idle_does_not_write_archive(self):
        self.add()
        root, status_file = self.root / 'archive', self.root / 'status.json'
        first = collect(self.path, root, 'Casey', status_file=status_file)
        self.assertEqual(first['imported'], 1)
        archive = Archive(root)
        before = (archive.db.read_bytes(), archive.messages('Casey')[0]['imported_at'])
        with patch.object(Archive, 'import_messages', side_effect=AssertionError('idle must not import')):
            second = collect(self.path, root, 'Casey', status_file=status_file)
        self.assertEqual(second['status'], 'imported')
        self.assertEqual(second['duplicates'], 1)
        self.assertEqual(before, (archive.db.read_bytes(), archive.messages('Casey')[0]['imported_at']))
        self.db.execute("UPDATE message SET text='Changed source body' WHERE ROWID=1")
        self.db.commit()
        changed = collect(self.path, root, 'Casey')
        self.assertEqual(changed['updated'], 1)
        self.assertEqual(len(list((root / 'Casey' / 'raw').iterdir())), 2)
        self.assertEqual(collect(self.path, root, 'Jordan')['imported'], 1)
        self.assertEqual(len(archive.messages('Jordan')), 1)
        self.assertEqual(status_file.stat().st_mode & 0o777, 0o600)
        self.assertNotIn('Synthetic message', status_file.read_text())

    def test_failure_does_not_advance_success_or_mutate_source_and_caps_preflight(self):
        self.add()
        root, status = self.root / 'archive', self.root / 'status.json'
        first = collect(self.path, root, 'Casey', status_file=status)
        with patch.object(Archive, 'import_messages', side_effect=RuntimeError('PRIVATE account payload')):
            self.db.execute("UPDATE message SET text='Changed pending source' WHERE ROWID=1")
            self.db.commit()
            failed = collect(self.path, root, 'Casey', status_file=status)
        self.assertEqual(failed['status'], 'error')
        self.assertEqual(failed['last_success_at'], first['last_success_at'])
        self.assertNotIn('PRIVATE', json.dumps(failed))
        self.add(2)
        with self.assertRaises(MacMessagesError) as caught:
            read_messages(self.path, max_messages=1)
        self.assertEqual(caught.exception.error_code, 'bounds_exceeded')
        preflight = collect(self.path, check_only=True, max_messages=1)
        self.assertEqual(preflight['error_code'], 'bounds_exceeded')
        before = hashlib.sha256(self.path.read_bytes()).hexdigest()
        collect(self.path, check_only=True)
        self.assertEqual(before, hashlib.sha256(self.path.read_bytes()).hexdigest())


if __name__ == '__main__':
    unittest.main()
