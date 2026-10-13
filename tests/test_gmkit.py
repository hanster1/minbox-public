from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
import subprocess
from unittest.mock import patch

from archive_cli import import_gmkit
from storage import Archive


class GmkitTests(unittest.TestCase):
    def test_import_retains_text_and_metadata_without_credentials_and_reimports_edits(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / 'gmcli.db'
            with closing(sqlite3.connect(database)) as db:
                db.executescript('''
                CREATE TABLE messages(message_id,conversation_id,sender_id,body,timestamp_ms,
                is_from_me,media_id,mime_type,decryption_key,raw_proto,updated_at);
                CREATE TABLE conversations(conversation_id,name,participants_json);
                CREATE TABLE contacts(participant_id,name,e164);
                INSERT INTO conversations VALUES('chat','Friend','[]');
                INSERT INTO contacts VALUES('p1','Demo Friend','+15555550101');
                INSERT INTO messages VALUES('m1','chat','p1','Website Friday?',1791637200000,
                0,'media','image/jpeg',X'0123',X'1234',1);
                ''')
            archive = Archive(root / 'archive')
            self.assertEqual(import_gmkit(archive, 'Casey', database)['imported'], 1)
            self.assertEqual(import_gmkit(archive, 'Casey', database)['duplicates'], 1)
            message = archive.messages('Casey')[0]
            self.assertEqual(message['sender_name'], 'Demo Friend')
            self.assertEqual(message['direction'], 'incoming')
            self.assertEqual(message['attachments'][0]['capture_status'], 'unavailable')
            self.assertNotIn('decryption_key', message)
            self.assertNotIn('raw_proto', message)
            with closing(sqlite3.connect(database)) as db:
                db.execute("UPDATE messages SET body='Website Thursday?', updated_at=2")
                db.commit()
            self.assertEqual(import_gmkit(archive, 'Casey', database)['updated'], 1)
            self.assertEqual(archive.messages('Casey')[0]['text'], 'Website Thursday?')
            self.assertEqual(archive.messages('Jordan'), [])
            # The failure cooldown expires, then an image-only edited message is captured.
            binary = root / 'gmcli'
            binary.write_text('#!/bin/sh\n')
            binary.chmod(0o700)
            with closing(sqlite3.connect(database)) as db:
                db.execute("UPDATE messages SET body='', updated_at=3")
                db.commit()
            def download(args, **kwargs):
                Path(args[-1]).write_bytes(b'\xff\xd8\xfffixture')
                return subprocess.CompletedProcess(args, 0)
            options = dict(executable=binary, clock=lambda: 9999999999, ocr=False)
            with patch('attachment_capture.subprocess.run', side_effect=download) as run:
                self.assertEqual(import_gmkit(archive, 'Casey', database, capture_options=options)['updated'], 1)
                captured = archive.messages('Casey')[0]
                self.assertEqual(captured['text'], '')
                self.assertEqual(captured['attachments'][0]['capture_status'], 'captured')
                self.assertEqual(import_gmkit(archive, 'Casey', database, capture_options=options)['duplicates'], 1)
                self.assertEqual(run.call_count, 1)
                # Captures survive a later missing executable without download or payload churn.
                options['executable'] = root / 'missing'
                self.assertEqual(import_gmkit(archive, 'Casey', database, capture_options=options)['duplicates'], 1)



if __name__ == '__main__': unittest.main()
