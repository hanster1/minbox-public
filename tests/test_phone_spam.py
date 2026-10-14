from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import unittest

from archive_snapshot import snapshot
from phone_spam import owner_operation, sync_observations
from storage import Archive


class PhoneSpamTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.archive = Archive(self.base / 'archive')
        self.collector = self.base / 'gmcli.db'
        self.archive.init(owners=('Casey', 'Jordan'))
        with closing(sqlite3.connect(self.collector)) as db:
            db.execute('CREATE TABLE phone_spam_conversations(conversation_id TEXT PRIMARY KEY,status INTEGER)')
            db.execute('INSERT INTO phone_spam_conversations VALUES (?,?)', ('junk', 5))
            db.execute('INSERT INTO phone_spam_conversations VALUES (?,?)', ('blocked', 6))
            db.commit()

    def import_one(self, mid, thread, owner='Casey', source='google-messages', **extra):
        p = self.base / 'import.json'
        p.write_text(json.dumps([dict(id=mid, conversation_id=thread, timestamp='2026-10-13T10:00:00Z',
                                     sender='Synthetic', text='Synthetic ' + mid, **extra)]))
        self.archive.import_messages(owner, source, p)

    def reconcile(self, owner='Casey'):
        with owner_operation(self.archive.root, owner):
            return sync_observations(self.archive, owner, self.collector)

    def current(self, owner='Casey', conversations=None):
        return snapshot(self.archive.root, owner, conversations, '1970-01-01', phone_spam_policy='spam_and_blocked')

    def test_whole_thread_future_backfill_owner_and_source_isolation(self):
        self.import_one('old', 'junk')
        self.import_one('reply', 'junk', direction='outgoing')
        self.import_one('blocked', 'blocked')
        self.import_one('keep', 'ordinary')
        self.import_one('same-thread-apple', 'junk', source='apple-messages',
                        apple_metadata={'record_type': 'message', 'body_status': 'plain_text'})
        self.import_one('other-owner', 'junk', owner='Jordan')
        self.assertEqual(self.reconcile()['new_exclusions'], 2)
        self.import_one('future', 'junk')
        self.import_one('older-backfill', 'junk')
        result = self.current()
        self.assertEqual({s['friendly_id'] for s in result['sources'] if s['source_id'].split('/')[3]=='google-messages'}, {'Mkeep'})
        self.assertEqual(len(result['sources']), 2)
        self.assertEqual(len(result['phone_spam_source_ids']), 5)
        self.assertEqual(len(self.archive.messages('Casey')), 7)
        self.assertEqual(len(self.archive.messages('Jordan')), 1)
        self.assertTrue(list((self.archive.root/'Casey/raw').glob('*.json')))

    def test_exclusion_survives_missing_or_stale_normal_folder_updates(self):
        self.import_one('one', 'junk')
        self.reconcile()
        with closing(sqlite3.connect(self.collector)) as db:
            db.execute('DELETE FROM phone_spam_conversations');db.commit()
        self.assertEqual(self.reconcile()['new_exclusions'], 0)
        self.assertEqual(self.current()['sources'], [])
        self.assertEqual(len(self.archive.messages('Casey')), 1)

    def test_no_policy_leaves_local_snapshot_unchanged_and_missing_signal_fails_closed(self):
        self.import_one('one', 'junk')
        self.reconcile()
        self.assertEqual(len(snapshot(self.archive.root,'Casey',None,'1970-01-01')['sources']), 1)
        with self.assertRaisesRegex(ValueError, 'unavailable'):
            self.current('Jordan')
        with closing(sqlite3.connect(self.collector)) as db:
            db.execute('DROP TABLE phone_spam_conversations');db.commit()
        self.assertFalse(self.reconcile()['supported'])
        with self.assertRaisesRegex(ValueError, 'unavailable'):
            self.current()

    def test_archived_deleted_unknown_and_message_body_do_not_trigger_deletion(self):
        self.import_one('keep','ordinary', phone_status=5)
        for status in (0, 1, 2, 3, 4, 7, 99):
            with self.subTest(status=status), closing(sqlite3.connect(self.collector)) as db:
                db.execute('INSERT OR REPLACE INTO phone_spam_conversations VALUES (?,?)',('ordinary',status));db.commit()
                with self.assertRaisesRegex(ValueError,'invalid collector'):
                    self.reconcile()
        with closing(sqlite3.connect(self.collector)) as db:
            db.execute('DELETE FROM phone_spam_conversations');db.commit()
        self.reconcile()
        self.assertEqual(len(self.current()['sources']),1)

    def test_historical_image_references_are_kept_for_verified_drive_withdrawal(self):
        image={'media_id':'old','mime_type':'image/png','sha256':'a'*64,'size_bytes':1}
        self.import_one('one','junk', attachments=[image])
        self.import_one('one','junk', attachments=[dict(image,media_id='new')])
        self.reconcile()
        result=self.current(conversations=['ordinary'])
        self.assertEqual({a['media_id'] for m in result['phone_spam_images'] for a in m['attachments']},{'old','new'})

    def test_shared_loom_keeps_only_retained_origins(self):
        self.import_one('junk','junk');self.import_one('keep','ordinary');self.reconcile()
        with self.archive._connect() as db:
            db.executescript('''CREATE TABLE loom_queue(owner,video_id,current_revision,status);
            CREATE TABLE loom_origins(owner,video_id,source,message_id);
            CREATE TABLE loom_revisions(owner,video_id,revision,semantic_sha256,text,phrases,captured_at,source_url);''')
            for video,origins in [('shared',['junk','keep']),('withdraw',['junk'])]:
                db.execute('INSERT INTO loom_queue VALUES (?,?,?,?)',('Casey',video,1,'captured'))
                db.execute('INSERT INTO loom_revisions VALUES (?,?,?,?,?,?,?,?)',('Casey',video,1,'hash','Synthetic transcript','[]','2026-10-13T10:01:00Z','https://www.loom.com/share/'+video))
                for mid in origins:db.execute('INSERT INTO loom_origins VALUES (?,?,?,?)',('Casey',video,'google-messages',mid))
        looms=[s for s in self.current()['sources'] if s['kind']=='loom']
        self.assertEqual(len(looms),1)
        self.assertEqual(looms[0]['origin_ids'],['archive://Casey/google-messages/keep'])

    def test_historical_exclusion_cannot_publish_or_reupload_moved_source_id(self):
        self.import_one('one','junk')
        self.reconcile()
        self.import_one('one','ordinary',attachments=[{'media_id':'new','mime_type':'image/png','sha256':'b'*64}])
        current=self.current()
        self.assertEqual(current['sources'],[])
        self.assertEqual(current['phone_spam_source_ids'],['archive://Casey/google-messages/one'])
        self.assertEqual(current['phone_spam_images'][0]['attachments'][0]['media_id'],'new')

    def test_new_backfill_in_excluded_thread_keeps_analysis_generation_stable(self):
        self.import_one('one','junk');self.reconcile()
        before=self.current()['phone_spam_generation']
        self.import_one('older','junk')
        self.assertEqual(self.current()['phone_spam_generation'],before)

    def test_import_cannot_race_owner_publication(self):
        waiting=threading.Event();finished=threading.Event()
        def reconcile():
            waiting.set()
            self.reconcile()
            finished.set()
        with owner_operation(self.archive.root,'Casey'):
            thread=threading.Thread(target=reconcile)
            thread.start();self.assertTrue(waiting.wait(1));self.assertFalse(finished.wait(.05))
        thread.join(2)
        self.assertTrue(finished.is_set())
