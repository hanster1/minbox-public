"""Phone-deletion flags flow collector -> archive import -> derived snapshot.

Run: python3 -m unittest tests.test_phone_deletions
Uses synthetic temp databases only; never the live archive.
"""
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import archive_cli  # noqa: E402
from archive_snapshot import snapshot  # noqa: E402
from storage import Archive  # noqa: E402


def collector_db(path, *, presence=True):
    db = sqlite3.connect(path)
    db.executescript('''
    CREATE TABLE conversations (conversation_id TEXT PRIMARY KEY, name TEXT, participants_json TEXT);
    CREATE TABLE contacts (participant_id TEXT PRIMARY KEY, name TEXT, e164 TEXT);
    CREATE TABLE messages (message_id TEXT PRIMARY KEY, conversation_id TEXT, source_platform TEXT,
        sender_id TEXT, body TEXT, timestamp_ms INTEGER, status INTEGER, is_from_me INTEGER,
        media_id TEXT, mime_type TEXT, decryption_key BLOB, reactions_json TEXT, reply_to_id TEXT,
        raw_proto BLOB, updated_at INTEGER);
    INSERT INTO conversations VALUES ('c1','Demo Friend','[]');
    INSERT INTO contacts VALUES ('p1','Demo Friend','+15555550101');
    ''')
    for i in (1, 2, 3):
        db.execute('INSERT INTO messages VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                   (f'm{i}', 'c1', 'gm', 'p1', f'hello {i}', 1_700_000_000_000 + i * 1000, 1, 0,
                    None, None, None, None, None, None, 0))
    if presence:
        db.executescript('''
        CREATE TABLE message_presence (message_id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL,
            missing_scans INTEGER NOT NULL DEFAULT 0, last_missing_at INTEGER NOT NULL DEFAULT 0,
            last_seen_at INTEGER NOT NULL DEFAULT 0, deleted_at INTEGER NOT NULL DEFAULT 0);
        INSERT INTO message_presence VALUES ('m2','c1',2,1760000000000,0,1760000000000);
        INSERT INTO message_presence VALUES ('m3','c1',1,1760000000000,0,0);
        ''')
    db.commit()
    db.close()


class PhoneDeletionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.root = base / 'archive'
        self.collector = base / 'collector'
        self.collector.mkdir()
        self.gm = self.collector / 'gmcli.db'

    def tearDown(self):
        self.tmp.cleanup()

    def payloads(self):
        db = sqlite3.connect(self.root / 'archive.sqlite3')
        rows = {r[0]: json.loads(r[1]) for r in db.execute("SELECT id,payload FROM messages WHERE owner='Casey'")}
        db.close()
        return rows

    def run_import(self):
        archive = Archive(self.root)
        archive.init(owners=('Casey',))
        return archive_cli._import_gmkit(archive, 'Casey', self.gm)

    def test_flag_carried_only_for_confirmed_deletions(self):
        collector_db(self.gm)
        self.run_import()
        p = self.payloads()
        self.assertIn('phone_deleted_at', p['m2'])
        self.assertNotIn('phone_deleted_at', p['m1'])
        self.assertNotIn('phone_deleted_at', p['m3'])  # one miss is not enough
        self.assertNotIn('phone_deleted_at_ms', p['m1'])

    def test_snapshot_skips_deleted_but_keeps_row(self):
        collector_db(self.gm)
        self.run_import()
        snap = snapshot(self.root, 'Casey', None, '1970-01-01')
        ids = {s['friendly_id'] for s in snap['sources']}
        self.assertEqual(ids, {'Mm1', 'Mm3'})
        self.assertEqual(len(snap['phone_deleted_source_ids']), 1)
        self.assertIn('m2', self.payloads())  # archive row retained

    def test_old_collector_without_table_changes_nothing(self):
        collector_db(self.gm, presence=False)
        self.run_import()
        self.assertFalse(any('phone_deleted_at' in v for v in self.payloads().values()))
        self.assertEqual(len(snapshot(self.root, 'Casey', None, '1970-01-01')['sources']), 3)

    def test_cleared_flag_restores_message(self):
        collector_db(self.gm)
        self.run_import()
        db = sqlite3.connect(self.gm)
        db.execute("UPDATE message_presence SET deleted_at=0, missing_scans=0 WHERE message_id='m2'")
        db.commit()
        db.close()
        self.run_import()
        self.assertNotIn('phone_deleted_at', self.payloads()['m2'])
        self.assertEqual(len(snapshot(self.root, 'Casey', None, '1970-01-01')['sources']), 3)


if __name__ == '__main__':
    unittest.main()
