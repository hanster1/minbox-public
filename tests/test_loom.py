import json
import io
import contextlib
import fcntl
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from archive_cli import main
from loom_capture import CaptureError, LoomCapture, NoRedirect, _allowed, links, metadata, normalize
from storage import Archive

VIDEO = 'a' * 32
NOW = datetime(2026, 10, 10, tzinfo=timezone.utc)


def page(**flags):
    state = {'RegularUserVideo:' + VIDEO: {'show_transcript_to_viewer': True, 'viewerNeedsPermission': False, **flags},
             'ROOT_QUERY': {'fetchVideoTranscript({})': {'__ref': 'details'}},
             'details': {'video_id': VIDEO, 'transcription_status': 'success', 'source_url': 'https://cdn.loom.com/test.json?token=secret', 'language': 'en', 'version': 1}}
    return ('<script>window.__APOLLO_STATE__ = ' + json.dumps(state) + ';evil()</script>').encode()


def transcript(value='Follow up Friday', ts=0):
    return json.dumps({'schemaVersion': 1, 'phrases': [{'ts': ts, 'value': value, 'ranges': []}]}).encode()


class LoomTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.archive = Archive(self.root / 'archive')
        messages = [{'id': str(i), 'conversation_id': 'thread', 'timestamp': NOW.isoformat(), 'sender': 'client', 'text': text}
                    for i, text in enumerate([f'https://www.loom.com/share/{VIDEO}?x=1). https://loom.com/embed/{VIDEO}', f'https://loom.com/share/{VIDEO}.'])]
        source = self.root / 'input.json'
        source.write_text(json.dumps(messages))
        self.archive.import_messages('Casey', 'gm', source)
        self.body = transcript()
        self.calls = []
        def fetcher(url, asset=False):
            self.calls.append((url, asset))
            return self.body if asset else page()
        self.capture = LoomCapture(self.archive, fetcher)

    def tearDown(self):
        self.tmp.cleanup()

    def test_links_and_origin_dedup(self):
        self.assertEqual(links(f'https://loom.com/embed/{VIDEO}?x=1), https://www.loom.com/share/{VIDEO}.'), [VIDEO])
        self.assertEqual(links(f'https://loom.com.evil/share/{VIDEO} https://loom.com/share/{VIDEO}b'), [])
        self.capture.discover(NOW)
        self.capture.discover(NOW)
        self.assertEqual(self.capture.status()['origin_count'], 2)
        self.assertEqual(self.capture.status()['owners']['Casey'], {'pending': 1})

    def test_permissions_and_host_restrictions(self):
        for flags in ({'show_transcript_to_viewer': False}, {'viewerNeedsPermission': True}, {'requiresPassword': True}, {'requiresLogin': True}):
            with self.assertRaises(CaptureError) as cm:
                metadata(page(**flags), VIDEO)
            self.assertEqual(cm.exception.status, 'denied')
        self.assertFalse(_allowed('https://cdn.loom.com.evil/a', True))
        self.assertFalse(_allowed('http://cdn.loom.com/a', True))
        self.assertFalse(_allowed('https://user@cdn.loom.com/a', True))
        self.assertFalse(_allowed('https://www.loom.com/share/' + VIDEO + '?secret=x'))
        with self.assertRaises(CaptureError):
            NoRedirect().redirect_request(None, None, 302, '', {}, 'https://evil.test')

    def test_malformed_empty_schema(self):
        for data in (b'{}', b'notjson', b'{"schemaVersion":1,"phrases":[]}', transcript('  '), transcript(ts=-1), transcript(ts=True), transcript(ts=float('nan'))):
            with self.assertRaises(CaptureError): normalize(data)
        self.body = b'{}'
        result = self.capture.run(NOW)
        self.assertEqual(result['operational_failures'], 1)
        self.assertEqual(self.capture.transcripts('Casey'), [])
        self.assertEqual(result['owners']['Casey'], {'invalid_transcript': 1})

    def test_idempotence_daily_edit_and_last_good(self):
        self.capture.run(NOW)
        self.capture.run(NOW + timedelta(hours=1))
        self.assertEqual(len(self.calls), 2)
        self.body = json.dumps(json.loads(self.body), indent=4).encode()
        self.capture.run(NOW + timedelta(days=1))
        self.assertEqual(self.capture.transcripts('Casey')[0]['revision'], 1)
        self.body = transcript('Changed deadline')
        self.capture.run(NOW + timedelta(days=2))
        self.assertEqual(self.capture.transcripts('Casey')[0]['revision'], 2)
        self.capture.fetcher = lambda *a, **k: (_ for _ in ()).throw(CaptureError('denied'))
        self.capture.run(NOW + timedelta(days=3))
        self.assertEqual(self.capture.transcripts('Casey')[0]['revision'], 2)
        with self.archive._connect() as db:
            row = db.execute('SELECT * FROM loom_queue').fetchone()
            self.assertEqual(row['status'], 'denied')
            self.assertEqual(row['failure_since'], (NOW + timedelta(days=3)).isoformat())
            self.assertEqual(db.execute('SELECT COUNT(*) FROM loom_revisions').fetchone()[0], 2)
        self.assertEqual(self.archive.status()['messages'], 2)

    def test_retry_and_worker_zero_due(self):
        self.capture.fetcher = lambda *a, **k: (_ for _ in ()).throw(CaptureError('network_error'))
        self.capture.run(NOW)
        result = self.capture.run(NOW + timedelta(minutes=5))
        self.assertEqual(result['attempted'], 0)
        self.assertEqual(result['worker']['last_completed_at'], (NOW + timedelta(minutes=5)).isoformat())
        result = self.capture.run(NOW + timedelta(minutes=15))
        self.assertEqual(result['attempted'], 1)

    def test_cli_search_status_and_lock(self):
        self.capture.run(NOW)
        output = io.StringIO()
        with patch('sys.argv', ['archive_cli', '--root', str(self.archive.root), 'search', 'Casey', 'Follow up']), contextlib.redirect_stdout(output):
            main()
        result = json.loads(output.getvalue())
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['type'], 'loom-transcript')
        output = io.StringIO()
        with patch('sys.argv', ['archive_cli', '--root', str(self.archive.root), 'loom-status']), contextlib.redirect_stdout(output):
            main()
        self.assertNotIn(VIDEO, output.getvalue())
        self.assertNotIn('Follow up', output.getvalue())
        with (self.archive.root / 'loom.lock').open('a+b') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(ValueError): self.capture.run(NOW)
        path = self.archive.root / 'Casey/raw/loom'
        for file in path.iterdir(): file.unlink()
        path.rmdir()
        path.symlink_to(self.root)
        with self.assertRaises(ValueError): self.capture._raw('Casey', transcript(), '.json')

    def test_provenance_evidence_and_snapshot(self):
        self.capture.run(NOW)
        t = self.capture.transcripts('Casey')[0]
        self.assertEqual(t['type'], 'loom-transcript')
        self.assertEqual(t['citation'], f'archive://Casey/loom/{VIDEO}/revision/1')
        self.assertEqual(t['origin_messages'][0]['citation'], 'archive://Casey/gm/0')
        evidence = {'messages': self.capture.annotate(self.archive.messages('Casey'), 'Casey')}
        self.assertEqual(evidence['messages'][0]['loom_transcripts'][0]['text'], 'Follow up Friday')
        snapshot = self.archive.snapshot(self.root / 'snapshot')
        restored = Archive.restore(snapshot, self.root / 'restored')
        saved = LoomCapture(restored).transcripts('Casey')[0]
        self.assertEqual(saved['text'], t['text'])
        raw = restored.root / 'Casey/raw/loom' / (saved['transcript_sha256'] + '.json')
        self.assertEqual(raw.read_bytes(), self.body)
        self.assertNotIn('token=secret', restored.db.read_bytes().decode('latin1'))
        self.assertEqual(raw.stat().st_mode & 0o777, 0o600)


if __name__ == '__main__': unittest.main()
