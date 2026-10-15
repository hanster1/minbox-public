from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from archive_corrections import CorrectionLedger
from archive_snapshot import snapshot
from local_archive_export import export_archive, main, MANIFEST, MAX_CHUNK_BYTES
import local_archive_export as exporter
from owner_archive_publisher import run as publish
from phone_spam import ensure_schema
from storage import Archive


class MemoryClient:
    """Synthetic reference publisher adapter: no credentials or network."""
    def __init__(self):
        self.bodies = {'guide': '', 'status': '', 'corrections': 'Corrections begin below.\n'}
        self.keys = {}

    def read(self, document):
        return {'text': self.bodies[document], 'revision': 'synthetic-r1'}

    def replace(self, document, text):
        changed = self.bodies.get(document) != text
        self.bodies[document] = text
        return changed

    def ensure_document(self, key, title):
        self.keys.setdefault(key, 'document-' + str(len(self.keys)))
        return self.keys[key]

    def withdraw_phone_spam(self, source_ids, images):
        return {'withdrawn_images': 0, 'pending_image_deletions': 0}


class LocalExportTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / 'runtime'
        self.archive = Archive(self.root)
        self.archive.init(['Casey'])
        self.state = self.base / 'publisher-state'
        self.state.mkdir(mode=0o700)
        self.ledger = self.state / 'corrections.sqlite3'
        ledger = CorrectionLedger(self.ledger)
        ledger.close()
        self.destination = self.base / 'filtered'
        self.records = []
        self.phone_spam([])

    def phone_spam(self, conversations):
        with self.archive._connect() as db:
            ensure_schema(db)
            db.execute('INSERT OR REPLACE INTO phone_spam_sync VALUES (?,?,?)', ('Casey', 1, '2026-10-14T12:00:00Z'))
            db.execute('DELETE FROM phone_spam_exclusions WHERE owner=?', ('Casey',))
            for conversation in conversations:
                db.execute('''INSERT INTO phone_spam_exclusions
                    (owner,source,conversation_id,status,observed_at) VALUES (?,?,?,?,?)''',
                    ('Casey', 'google-messages', conversation, 5, '2026-10-14T12:00:00Z'))

    def record(self, number, text='Synthetic dinner at six', **updates):
        record = dict(id=str(number), conversation_id='chat', sender='Synthetic Sender',
                      timestamp='2020-05-12T12:00:00Z', text=text)
        record.update(updates)
        return record

    def load(self, records, *, owner='Casey'):
        path = self.base / 'synthetic-input.json'
        path.write_text(json.dumps(records))
        path.chmod(0o600)
        self.archive.import_messages(owner, 'google-messages', path)

    def correction(self, cid, action, target='M1', undo=None):
        record = dict(correction_id=cid, owner='Casey', target=target, scope='message',
                      action=action, instruction='Synthetic owner instruction', requested_at='2026-10-14T12:00:00Z')
        if undo:
            record['undo_correction'] = undo
        return record

    def correct(self, records, *, registry=True, ledger=None):
        managed = ledger or CorrectionLedger(self.ledger)
        sources = snapshot(self.root, 'Casey', None, '1970-01-01', phone_spam_policy='off')['sources']
        messages = {s['friendly_id']: {'owner': 'Casey', 'label': 'uncertain',
                    'source_revision': s['revision'], 'provenance': s['source_id']} for s in sources} if registry else {}
        try:
            return managed.ingest('Casey', records, messages)
        finally:
            if ledger is None:
                managed.close()

    def loom(self, video, origin_ids, text, phrases=None):
        with self.archive._connect() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS loom_queue(owner,video_id,current_revision,status);
                CREATE TABLE IF NOT EXISTS loom_origins(owner,video_id,source,message_id);
                CREATE TABLE IF NOT EXISTS loom_revisions(owner,video_id,revision,semantic_sha256,text,phrases,captured_at,source_url);''')
            db.execute('INSERT INTO loom_queue VALUES (?,?,?,?)', ('Casey', video, 1, 'ok'))
            for message in origin_ids:
                db.execute('INSERT INTO loom_origins VALUES (?,?,?,?)', ('Casey', video, 'google-messages', str(message)))
            db.execute('INSERT INTO loom_revisions VALUES (?,?,?,?,?,?,?,?)',
                ('Casey', video, 1, 'synthetic-hash', text, json.dumps(phrases or []),
                 '2026-10-14T12:00:00Z', 'https://www.loom.com/share/' + video))

    def export(self, **updates):
        args = dict(phone_spam_policy='spam_and_blocked')
        args.update(updates)
        return export_archive(self.root, 'Casey', self.ledger, self.destination, **args)

    def text(self):
        return '\n'.join(p.read_text() for p in sorted(self.destination.glob('*.txt')))

    def generation(self):
        return {p.name: p.read_bytes() for p in self.destination.iterdir()}

    def test_reference_filter_parity_including_ocr_phone_spam_and_bound_looms(self):
        self.load([
            self.record(1, 'Retained synthetic message'),
            self.record(2, 'Your security code is 123456'),
            self.record(3, 'Shop our sale today, 20% off. Reply STOP'),
            self.record(4, 'Excluded innocuous body', attachments=[{
                'capture_status': 'captured', 'local_path': '/private/image-original.png',
                'ocr_text': 'Your verification code is 246810'}]),
            self.record(5, 'Explicitly hidden synthetic message'),
            self.record(6, 'Your login code is 135790'),
            self.record(7, '', attachments=[{'capture_status': 'captured',
                'local_path': '/private/attachment-location', 'ocr_text': 'Retained synthetic image caption'}]),
            self.record(8, 'Excluded phone folder message', conversation_id='junk'),
            self.record(9, 'Excluded phone folder reply', conversation_id='junk'),
            self.record(11, '')])
        self.load([self.record(1, 'Another owner must never appear')], owner='Jordan')
        self.phone_spam(['junk'])
        self.correct([self.correction('hide', 'spam', 'M5'), self.correction('code-work', 'work', 'M6')])
        self.loom('retained', [1, 5], 'Retained transcript', [{'ts': 61.25, 'value': 'Retained transcript'}])
        self.loom('orphan', [5], 'Orphan transcript must never appear')
        (self.root / 'credentials.json').write_text('PRIVATE-CREDENTIAL-FILE-MARKER')
        archive_before, ledger_before = (self.root / 'archive.sqlite3').read_bytes(), self.ledger.read_bytes()
        with patch('socket.socket', side_effect=AssertionError('network prohibited')):
            result = self.export()
        self.assertEqual(result['published_messages'], 2)
        self.assertEqual(result['published_looms'], 1)
        self.assertEqual(result['filtered_counts'], {'phone_spam': 2, 'hard_excluded': 4, 'explicit_spam': 1, 'empty': 1})
        contents = self.text()
        for retained in ('Retained synthetic message', 'Retained synthetic image caption', '01:01.250', 'Origin messages: M1'):
            self.assertIn(retained, contents)
        for excluded in ('123456', '246810', '135790', 'Excluded innocuous body', 'Explicitly hidden synthetic message',
                         'Excluded phone folder', 'Orphan transcript', 'Another owner', '/private/', 'PRIVATE-CREDENTIAL-FILE-MARKER'):
            self.assertNotIn(excluded, contents)
        self.assertEqual((self.root / 'archive.sqlite3').read_bytes(), archive_before)
        self.assertEqual(self.ledger.read_bytes(), ledger_before)
        # Compare the shipped publisher over exactly the same snapshot and durable corrections.
        other_ledger = self.base / 'reference-corrections.sqlite3'
        other_ledger.write_bytes(ledger_before)
        other_ledger.chmod(0o600)
        client = MemoryClient()
        reference = publish({'owner': 'Casey', 'documents': {k: k for k in ('guide', 'corrections', 'status')},
            'correction_path': str(other_ledger), 'phone_spam_policy': 'spam_and_blocked'},
            snapshot(self.root, 'Casey', None, '1970-01-01', phone_spam_policy='spam_and_blocked'), client)
        for field in ('published_messages', 'excluded_messages', 'filtered_counts', 'model_calls'):
            self.assertEqual(result[field], reference[field])

    def test_durable_spam_requires_undo_and_survives_source_edits(self):
        self.load([self.record(1, 'Synthetic restored after undo')])
        self.correct([self.correction('hide', 'spam'), self.correction('later-work', 'work')])
        self.assertEqual(self.export()['published_messages'], 0)
        self.load([self.record(1, 'Synthetic edited restoration')])
        self.assertEqual(self.export()['published_messages'], 0)
        self.correct([self.correction('restore', 'undo', undo='hide')])
        before = self.ledger.read_bytes()
        self.assertEqual(self.export()['published_messages'], 1)
        self.assertIn('Synthetic edited restoration', self.text())
        self.assertIn('Label: work', self.text())
        self.assertEqual(self.ledger.read_bytes(), before)

    def test_unresolved_durable_correction_applies_when_source_arrives_without_mutation(self):
        result = self.correct([self.correction('future', 'spam', 'M9')], registry=False)
        self.assertEqual(result['statuses'][0]['status'], 'unresolved')
        self.load([self.record(9, 'Future spam excluded locally')])
        before = self.ledger.read_bytes()
        self.assertEqual(self.export()['published_messages'], 0)
        self.assertNotIn('Future spam', self.text())
        self.assertEqual(self.ledger.read_bytes(), before)

    def test_committed_wal_correction_is_read_instead_of_only_database_pages(self):
        self.load([self.record(1, 'Committed WAL spam')])
        ledger = CorrectionLedger(self.ledger)
        self.addCleanup(ledger.close)
        ledger.db.execute('PRAGMA journal_mode=WAL')
        self.correct([self.correction('wal-hide', 'spam')], ledger=ledger)
        before = self.ledger.read_bytes()
        wal = Path(str(self.ledger) + '-wal')
        wal_before = wal.read_bytes()
        self.assertEqual(self.export()['published_messages'], 0)
        self.assertNotIn('Committed WAL spam', self.text())
        self.assertEqual(self.ledger.read_bytes(), before)
        self.assertEqual(wal.read_bytes(), wal_before)

    def test_changed_values_and_withdrawals_remove_stale_files_from_real_directory(self):
        self.load([self.record(1, 'Old synthetic value', timestamp='2020-01-01T10:00:00Z'),
                   self.record(2, 'Withdrawn year', timestamp='2019-01-01T10:00:00Z')])
        first = self.export()
        from archive_search import ReadOnlyArchive
        reader = ReadOnlyArchive(self.destination)
        old = reader.search('Old synthetic value')['sources'][0]
        withdrawn = reader.search('Withdrawn year')['sources'][0]
        self.load([self.record(1, 'New synthetic value', timestamp='2020-01-01T10:00:00Z')])
        with self.archive._connect() as db:
            db.execute('DELETE FROM messages WHERE owner=? AND id=?', ('Casey', '2'))
        second = self.export()
        self.assertNotEqual(first['generation'], second['generation'])
        self.assertTrue(self.destination.is_dir())
        self.assertFalse(self.destination.is_symlink())
        self.assertFalse(list(self.destination.glob('messages-2019-*')))
        self.assertIn('New synthetic value', self.text())
        self.assertNotIn('Old synthetic value', self.text())
        self.assertNotIn('Withdrawn year', self.text())
        self.assertEqual(list(self.base.glob('.minbox-export-work-*')), [])
        fresh = reader.search('New synthetic value')['sources'][0]
        self.assertEqual(fresh['source_id'], old['source_id'])
        self.assertNotEqual(fresh['sha256'], old['sha256'])
        with self.assertRaisesRegex(ValueError, 'source changed'):
            reader.read_source(old['source_id'], old['sha256'])
        self.assertIn('New synthetic value', reader.read_source(old['source_id'])['body'])
        with self.assertRaises(LookupError):
            reader.read_source(withdrawn['source_id'])

    def test_partial_write_failure_leaves_previous_generation_byte_for_byte(self):
        self.load([self.record(1, 'Prior complete generation')])
        self.export()
        before, inode = self.generation(), self.destination.stat().st_ino
        self.load([self.record(1, 'New uncommitted generation')])
        original = exporter._write_private
        writes = []
        def fail_after_first(directory, name, data):
            writes.append(name)
            if len(writes) == 2:
                raise OSError('synthetic disk write failure')
            return original(directory, name, data)
        with patch.object(exporter, '_write_private', side_effect=fail_after_first):
            with self.assertRaisesRegex(OSError, 'disk write failure'):
                self.export()
        self.assertEqual(self.generation(), before)
        self.assertEqual(self.destination.stat().st_ino, inode)
        self.assertEqual(list(self.base.glob('.minbox-export-work-*')), [])
        self.assertIn('Prior complete generation', self.text())

    def test_correction_commit_during_generation_refuses_acknowledgement(self):
        self.load([self.record(1, 'Earlier generation')])
        self.export()
        before = self.generation()
        original = exporter._write_private
        def change_policy(directory, name, data):
            original(directory, name, data)
            if name == MANIFEST:
                self.correct([self.correction('during-write', 'spam')])
        with patch.object(exporter, '_write_private', side_effect=change_policy):
            with self.assertRaisesRegex(RuntimeError, 'policy changed'):
                self.export()
        self.assertEqual(self.generation(), before)
        self.assertEqual(self.export()['published_messages'], 0)
        self.assertNotIn('Earlier generation', self.text())

    def test_phone_block_or_source_edit_during_generation_refuses_installation(self):
        self.load([self.record(1, 'Prior stable source')])
        self.export()
        before = self.generation()
        original = exporter._write_private
        def change_source(directory, name, data):
            original(directory, name, data)
            if name == MANIFEST:
                self.phone_spam(['chat'])
        with patch.object(exporter, '_write_private', side_effect=change_source):
            with self.assertRaisesRegex(RuntimeError, 'source snapshot changed'):
                self.export()
        self.assertEqual(self.generation(), before)
        self.assertEqual(self.export()['published_messages'], 0)
        self.assertNotIn('Prior stable source', self.text())

    def test_unicode_chunks_remain_readable_bounded_and_citable(self):
        self.load([self.record(1, 'A\x00\r\n' + 'Synthetic résumé 雪 ' * 2000)])
        self.export(max_chunk_bytes=4096)
        chunks = list(self.destination.glob('messages-*.txt'))
        self.assertGreater(len(chunks), 2)
        self.assertIn('[U+0000]', self.text())
        for chunk in chunks:
            self.assertLessEqual(len(chunk.read_bytes()), 4096)
            text = chunk.read_text()
            self.assertIn('archive://Casey/google-messages/1', text)
            self.assertIn('2020-05-12T12:00:00', text)
        self.assertIn('Continuation of the same source.', self.text())
        from archive_search import ReadOnlyArchive
        result = ReadOnlyArchive(self.destination).search('résumé')
        self.assertTrue(result['sources'])

    def test_rendered_loom_phrases_cannot_bypass_hard_filter(self):
        self.load([self.record(1)])
        self.loom('mismatched', [1], 'Innocuous stored transcript', [{'ts': 0, 'value': 'Your OTP code is 123456'}])
        result = self.export()
        self.assertEqual(result['published_looms'], 0)
        self.assertNotIn('123456', self.text())

    def test_private_content_free_receipt_and_cli_result(self):
        self.load([self.record(1, 'Synthetic secret payload')])
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(['--archive-root', str(self.root), '--owner', 'Casey',
                '--correction-ledger', str(self.ledger), '--destination', str(self.destination),
                '--phone-spam-policy', 'spam_and_blocked']), 0)
        receipt = (self.destination / MANIFEST).read_text()
        for text in (output.getvalue(), receipt):
            for private in ('Synthetic secret payload', 'archive://', 'Casey', str(self.root), str(self.ledger), 'Synthetic Sender'):
                self.assertNotIn(private, text)
        self.assertEqual(stat.S_IMODE(self.destination.stat().st_mode), 0o700)
        for path in self.destination.iterdir():
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertTrue(path.name == MANIFEST or path.suffix == '.txt')
        self.assertIn('committed local ledger snapshot only', self.text())
        self.assertIn('Regenerate after imports', self.text())

    def test_refuses_missing_ledger_instead_of_exporting_without_corrections(self):
        self.load([self.record(1)])
        self.ledger.unlink()
        with self.assertRaises((ValueError, OSError)):
            self.export()
        self.assertFalse(self.destination.exists())

    def test_phone_policy_signal_missing_fails_closed_and_off_requires_explicit_choice(self):
        self.load([self.record(1)])
        with self.archive._connect() as db:
            db.execute('DELETE FROM phone_spam_sync')
        with self.assertRaisesRegex(ValueError, 'signal is unavailable'):
            self.export()
        self.assertFalse(self.destination.exists())
        self.assertEqual(self.export(phone_spam_policy='off')['published_messages'], 1)

    def test_source_runtime_git_and_traversal_destinations_are_refused(self):
        self.load([self.record(1)])
        paths = [self.root / 'filtered', self.state / 'filtered', self.base,
                 self.base / 'unused' / '..' / 'filtered']
        git = self.base / 'checkout'
        git.mkdir(mode=0o700)
        (git / '.git').mkdir()
        (git / '.git' / 'HEAD').write_text('ref: refs/heads/synthetic\n')
        paths.append(git / 'filtered')
        for destination in paths:
            with self.subTest(destination=destination), self.assertRaises((ValueError, OSError)):
                export_archive(self.root, 'Casey', self.ledger, destination, phone_spam_policy='spam_and_blocked')
        self.assertFalse(self.destination.exists())

    def test_symlinked_input_ancestor_and_destination_are_refused(self):
        self.load([self.record(1)])
        alias = self.base / 'alias'
        alias.symlink_to(self.root, target_is_directory=True)
        ledger_alias = self.state / 'alias.sqlite3'
        ledger_alias.symlink_to(self.ledger)
        outside = self.base / 'outside'
        outside.mkdir(mode=0o700)
        self.destination.symlink_to(outside, target_is_directory=True)
        ancestor = self.base / 'ancestor'
        ancestor.symlink_to(self.base, target_is_directory=True)
        for root, ledger, destination in [(alias, self.ledger, outside / 'filtered'),
                (self.root, ledger_alias, outside / 'filtered'), (self.root, self.ledger, self.destination),
                (self.root, self.ledger, ancestor / 'another')]:
            with self.subTest(root=root, ledger=ledger, destination=destination), self.assertRaises((ValueError, OSError)):
                export_archive(root, 'Casey', ledger, destination, phone_spam_policy='spam_and_blocked')
        self.assertEqual(list(outside.iterdir()), [])

    def test_refuses_unmanaged_and_edited_or_linked_exports_without_deleting_them(self):
        self.load([self.record(1)])
        self.destination.mkdir(mode=0o700)
        unrelated = self.destination / 'credentials.json'
        unrelated.write_text('synthetic unrelated secret')
        with self.assertRaisesRegex(ValueError, 'unmanaged'):
            self.export()
        self.assertEqual(unrelated.read_text(), 'synthetic unrelated secret')
        unrelated.unlink()
        self.export()
        message = next(self.destination.glob('messages-*.txt'))
        original = message.read_bytes()
        message.write_text('manually edited export')
        with self.assertRaisesRegex(ValueError, 'verification failed'):
            self.export()
        self.assertEqual(message.read_text(), 'manually edited export')
        message.write_bytes(original)
        hardlink = self.base / 'outside-linked-file'
        os.link(message, hardlink)
        with self.assertRaisesRegex(ValueError, 'singly linked'):
            self.export()
        self.assertEqual(hardlink.read_bytes(), original)

    def test_nonprivate_paths_and_database_links_are_refused(self):
        self.load([self.record(1)])
        for path, mode in [(self.root, 0o755), (self.ledger, 0o644), (self.base, 0o750)]:
            old = stat.S_IMODE(path.stat().st_mode)
            path.chmod(mode)
            try:
                with self.subTest(path=path), self.assertRaises((ValueError, OSError)):
                    self.export()
            finally:
                path.chmod(old)
        hardlink = self.base / 'linked-archive.sqlite3'
        os.link(self.root / 'archive.sqlite3', hardlink)
        with self.assertRaisesRegex(ValueError, 'singly linked'):
            self.export()

    def test_atomic_rename_failure_preserves_previous_generation(self):
        self.load([self.record(1)])
        self.export()
        before = self.generation()
        self.load([self.record(1, 'Uninstalled synthetic change')])
        with patch.object(exporter, '_rename', side_effect=OSError('unsupported synthetic filesystem')):
            with self.assertRaises(OSError):
                self.export()
        self.assertEqual(self.generation(), before)
        self.assertEqual(list(self.base.glob('.minbox-export-work-*')), [])

    def test_cli_failure_does_not_print_private_path_or_exception(self):
        result = subprocess.run([sys.executable, str(Path(exporter.__file__)), '--archive-root', str(self.root),
            '--owner', 'Casey', '--correction-ledger', str(self.state / 'missing-sensitive-ledger.sqlite3'),
            '--destination', str(self.destination), '--phone-spam-policy', 'spam_and_blocked'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, '')
        for private in (str(self.base), 'missing-sensitive-ledger', 'Traceback', 'Casey'):
            self.assertNotIn(private, result.stderr)

    def test_standalone_source_bundle_needs_no_site_packages_or_credentials(self):
        self.load([self.record(1)])
        bundle = self.base / 'local-export-tool'
        bundle.mkdir(mode=0o700)
        for name in ('local_archive_export', 'archive_corrections', 'archive_drive', 'archive_incremental',
                     'archive_io', 'archive_snapshot', 'owner_archive_publisher', 'phone_spam', 'publisher_status', 'storage'):
            shutil.copyfile(Path(exporter.__file__).parent / (name + '.py'), bundle / (name + '.py'))
        environment = dict(os.environ)
        environment.pop('PYTHONPATH', None)
        command = [sys.executable, '-S', str(bundle / 'local_archive_export.py'), '--archive-root', str(self.root),
            '--owner', 'Casey', '--correction-ledger', str(self.ledger), '--destination', str(self.destination),
            '--phone-spam-policy', 'spam_and_blocked']
        first = subprocess.run(command, cwd=self.base, env=environment, capture_output=True, text=True)
        self.assertEqual(first.returncode, 0, first.stderr)
        second = subprocess.run(command, cwd=self.base, env=environment, capture_output=True, text=True)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(json.loads(second.stdout)['published_messages'], 1)
        self.assertNotEqual(json.loads(first.stdout)['generation'], json.loads(second.stdout)['generation'])


if __name__ == '__main__':
    unittest.main()
