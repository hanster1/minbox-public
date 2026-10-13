import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from archive_snapshot import snapshot


class SnapshotTests(unittest.TestCase):
    def test_image_only_apple_message_keeps_attachment_and_stable_identity(self):
        from storage import Archive
        with tempfile.TemporaryDirectory() as directory:
            archive = Archive(Path(directory) / 'archive')
            source = Path(directory) / 'input.json'
            source.write_text(json.dumps([dict(id='image', conversation_id='chat',
                timestamp='2026-10-13T10:00:00Z', sender='Synthetic', text='',
                attachments=[{'media_id': 'synthetic-image', 'capture_status': 'captured',
                              'mime_type': 'image/png', 'sha256': 'a' * 64}],
                apple_metadata={'record_type': 'message', 'body_status': 'blank'})]))
            archive.import_messages('Alex', 'apple-messages', source)
            result = snapshot(archive.root, 'Alex', None, '1970-01-01')
            self.assertEqual(len(result['sources']), 1)
            self.assertTrue(result['sources'][0]['attachments_available'])
            self.assertEqual(result['sources'][0]['attachments'][0]['media_id'], 'synthetic-image')
            self.assertEqual(result['message_gaps'], [])

    def test_owner_thread_and_current_loom_scope_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            db = sqlite3.connect(Path(directory)/'archive.sqlite3')
            db.executescript('''CREATE TABLE messages(owner,source,id,payload,imported_at);
            CREATE TABLE imports(owner,imported_at);
            CREATE TABLE loom_queue(owner,video_id,current_revision,status);
            CREATE TABLE loom_origins(owner,video_id,source,message_id);
            CREATE TABLE loom_revisions(owner,video_id,revision,semantic_sha256,text,phrases,captured_at,source_url);''')
            for owner,mid,thread in [('Casey','1','work'),('Jordan','2','work'),('Casey','3','personal')]:
                payload={'conversation_id':thread,'timestamp':'2026-10-12T10:00:00Z','sender':'Tester','text':'hello'}
                db.execute('INSERT INTO messages VALUES(?,?,?,?,?)',(owner,'google-messages',mid,json.dumps(payload),'2026-10-12T10:01:00Z'))
            db.execute('INSERT INTO imports VALUES(?,?)',('Casey','2026-10-12T10:02:00Z'))
            db.execute('INSERT INTO loom_queue VALUES(?,?,?,?)',('Casey','video',2,'ok'))
            db.execute('INSERT INTO loom_origins VALUES(?,?,?,?)',('Casey','video','google-messages','1'))
            for revision in [1,2]:
                db.execute('INSERT INTO loom_revisions VALUES(?,?,?,?,?,?,?,?)',('Casey','video',revision,'hash','text','[]','2026-10-12T10:03:00Z','https://www.loom.com/share/video'))
            db.commit();db.close()
            before=(Path(directory)/'archive.sqlite3').read_bytes()
            result=snapshot(directory,'Casey',['work'],'2026-10-01')
            self.assertEqual(len(result['sources']),2)
            self.assertEqual(result['sources'][1]['revision'],'2:hash')
            self.assertEqual(result['sources'][1]['origin_ids'],['archive://Casey/google-messages/1'])
            self.assertEqual((Path(directory)/'archive.sqlite3').read_bytes(),before)
            full = snapshot(directory, 'Casey', None, '1970-01-01')
            self.assertEqual(len(full['sources']), 3)
            self.assertTrue(all(s['owner'] == 'Casey' for s in full['sources']))
            self.assertIn('All currently captured', full['coverage'])

    def test_apple_semantic_revisions_and_withdrawal_before_analysis(self):
        from storage import Archive
        from archive_publisher import run
        from test_archive_publisher import Client, Analyzer
        with tempfile.TemporaryDirectory() as directory:
            archive = Archive(Path(directory) / 'archive')
            source = Path(directory) / 'input.json'
            record = dict(id='stable-guid-chat', conversation_id='work',
                timestamp='2026-10-12T10:00:00Z', sender='Synthetic', text='Organize synthetic links',
                apple_metadata={'record_type':'message', 'body_status':'plain_text', 'is_read':False})
            def load():
                source.write_text(json.dumps([record]))
                archive.import_messages('Alex', 'apple-messages', source)
                return snapshot(archive.root, 'Alex', ['work'], '2026-10-01')
            first = load()
            friendly = first['sources'][0]['friendly_id']
            self.assertRegex(friendly, r'^A[0-9a-f]{16}$')
            revision = first['sources'][0]['revision']
            record['apple_metadata']['is_read'] = True
            self.assertEqual(load()['sources'][0]['revision'], revision)
            client, analyzer = Client(), Analyzer()
            config = dict(owner='Alex', conversations=['work'], start_date='2026-10-01',
                documents={k:k for k in client.bodies}, analysis_path=str(Path(directory)/'analysis.db'),
                correction_path=str(Path(directory)/'corrections.db'))
            self.assertEqual(run(config, load(), client, analyzer)['work_messages'], 1)
            calls = analyzer.calls
            self.assertEqual(run(config, load(), client, analyzer)['writes'], 0)
            self.assertEqual(analyzer.calls, calls)
            record['text'] = 'Edited synthetic request'
            edited = load()
            self.assertEqual(edited['sources'][0]['friendly_id'], friendly)
            self.assertNotEqual(edited['sources'][0]['revision'], revision)
            run(config, edited, client, analyzer)
            client.bodies['corrections'] += ('Correction ID: force-work\nOwner: Alex\nTarget: '+friendly+
                '\nScope: message\nAction: work\nInstruction: work\nRequested at: 2026-10-12T12:00:00Z\n')
            client.revision = 'r2'
            for metadata in [
                    {'record_type':'reaction', 'body_status':'non_message_event'},
                    {'record_type':'message', 'body_status':'attributed_body_unsupported'},
                    {'record_type':'message', 'body_status':'plain_text', 'is_unsent':True}]:
                record['apple_metadata'] = metadata
                withheld = load()
                self.assertEqual(withheld['sources'], [])
                self.assertEqual(len(withheld['message_gaps']), 1)
                result = run(config, withheld, client, analyzer)
                self.assertEqual(result['work_messages'], 0)
                self.assertNotIn('Edited synthetic request', client.bodies['messages'])
                self.assertNotIn('Edited synthetic request', client.bodies['knowledge'])
