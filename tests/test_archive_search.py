import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from archive_search import ReadOnlyArchive, MAX_BODY_BYTES, MAX_EXCERPT_CHARS, MAX_FILE_BYTES


class ArchiveSearchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / 'export'
        self.root.mkdir()
        self.archive = ReadOnlyArchive(self.root)

    def write(self, name, body):
        target = self.root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding='utf-8')
        return target

    def test_fresh_reads_stable_ids_and_expected_version(self):
        target = self.write('notes/meeting.md', 'Synthetic launch plan 🐈')
        first = self.archive.search('LAUNCH')['sources'][0]
        self.assertEqual(first['relative_path'], 'notes/meeting.md')
        self.assertEqual(first['sha256'], hashlib.sha256(target.read_bytes()).hexdigest())
        self.assertEqual(first['version'], first['sha256'])
        self.assertEqual(self.archive.read_source(first['source_id'], first['sha256'])['body'], target.read_text())
        target.write_text('Synthetic revised launch plan', encoding='utf-8')
        second = self.archive.search('revised')['sources'][0]
        self.assertEqual(second['source_id'], first['source_id'])
        self.assertNotEqual(second['sha256'], first['sha256'])
        self.assertIn('revised', self.archive.read_source(first['source_id'])['body'])
        with self.assertRaisesRegex(ValueError, 'source changed'):
            self.archive.read_source(first['source_id'], first['sha256'])
        self.assertNotIn(str(self.root), json.dumps(second))

    def test_query_and_limit_bounds_before_access(self):
        for query in (None, 1, [], 'x' * 257, '\ud800'):
            with self.subTest(query_type=type(query)):
                with self.assertRaises(ValueError):
                    self.archive.search(query)
        for limit in (0, -1, 21, True, 1.5, '2'):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                self.archive.search('query', limit)
        self.assertEqual(self.archive.search('  ')['sources'], [])
        self.assertEqual(self.archive.search('no match')['sources'], [])
        self.write('empty.txt', '')
        self.assertEqual(self.archive.search('no match')['sources'], [])

    def test_result_excerpt_and_body_bounds(self):
        for n in range(5):
            self.write(f'{n}.txt', 'match ' + '😀' * 20000)
        result = self.archive.search('match', limit=2)
        self.assertEqual(len(result['sources']), 2)
        self.assertTrue(result['truncated'])
        self.assertTrue(all(len(s['excerpt']) <= MAX_EXCERPT_CHARS for s in result['sources']))
        read = self.archive.read_source(result['sources'][0]['source_id'])
        self.assertLessEqual(len(read['body'].encode('utf-8')), MAX_BODY_BYTES)
        self.assertTrue(read['truncated'])
        self.assertTrue(read['body'].endswith('😀'))

    def test_casefold_expansion_keeps_match_inside_excerpt(self):
        self.write('unicode.txt', 'ß' * 1000 + 'Synthetic Match' + 'x' * 1000)
        result = self.archive.search('synthetic match')
        self.assertIn('Synthetic Match', result['sources'][0]['excerpt'])

    def test_only_text_exports_and_no_obvious_runtime_files(self):
        for name in ('notes.txt', 'summary.md'):
            self.write(name, 'synthetic needle')
        for name in ('.hidden.txt', 'session.txt', 'credentials.md', 'raw/messages.txt',
                     'logs/provider.txt', '.private/notes.md', 'archive.sqlite3', 'dump.json'):
            self.write(name, 'synthetic needle')
        self.write('binary.txt', 'needle\x00private')
        (self.root / 'invalid.txt').write_bytes(b'needle\xff')
        result = self.archive.search('needle')
        self.assertEqual({s['relative_path'] for s in result['sources']}, {'notes.txt', 'summary.md'})
        self.assertGreater(result['coverage']['files_skipped'], 0)

    def test_symlink_file_directory_and_root_components_are_blocked(self):
        outside = Path(self.temp.name) / 'outside'
        outside.mkdir()
        (outside / 'secret.txt').write_text('private needle')
        (self.root / 'link.txt').symlink_to(outside / 'secret.txt')
        (self.root / 'linked').symlink_to(outside, target_is_directory=True)
        self.assertEqual(self.archive.search('needle')['sources'], [])
        linked_root = Path(self.temp.name) / 'root-link'
        linked_root.symlink_to(self.root, target_is_directory=True)
        for root in (linked_root, linked_root / 'nested'):
            with self.subTest(root=root), self.assertRaises(ValueError) as caught:
                ReadOnlyArchive(root)
            self.assertNotIn(str(root), str(caught.exception))

    def test_root_replacement_is_checked_on_each_request(self):
        self.write('safe.txt', 'needle')
        saved = self.root.with_name('saved')
        self.root.rename(saved)
        self.root.symlink_to(saved, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.archive.search('needle')

    def test_hardlinks_fifo_and_oversized_files_are_never_read(self):
        outside = Path(self.temp.name) / 'outside.txt'
        outside.write_text('private needle')
        os.link(outside, self.root / 'hardlink.txt')
        os.mkfifo(self.root / 'blocked.txt')
        self.write('oversized.txt', 'needle' + 'x' * MAX_FILE_BYTES)
        with patch('archive_search.os.read', side_effect=AssertionError('unsafe read')):
            self.assertEqual(self.archive.search('needle')['sources'], [])

    def test_file_swap_to_fifo_or_symlink_fails_closed(self):
        target = self.write('safe.txt', 'needle')
        real_read = self.archive._read
        for mode in ('fifo', 'symlink'):
            with self.subTest(mode=mode):
                if target.exists():
                    target.unlink()
                target.write_text('needle')
                def swap(fd, name, state):
                    target.unlink()
                    if mode == 'fifo':
                        os.mkfifo(target)
                    else:
                        target.symlink_to(Path(self.temp.name) / 'outside.txt')
                    return real_read(fd, name, state)
                with patch.object(self.archive, '_read', side_effect=swap):
                    self.assertEqual(self.archive.search('needle')['sources'], [])
                target.unlink()

    def test_unknown_and_path_identifiers_cannot_escape(self):
        for source_id in ('../outside.txt', '/etc/passwd', 'file_' + '0' * 63):
            with self.subTest(source_id=source_id), self.assertRaises(ValueError):
                self.archive.read_source(source_id)
        with self.assertRaisesRegex(LookupError, 'configured export coverage'):
            self.archive.read_source('file_' + '0' * 64)
        with self.assertRaises(ValueError):
            self.archive.read_source('file_' + '0' * 64, expected_hash='../file')
        with self.assertRaises(ValueError):
            ReadOnlyArchive(self.root / '..' / 'export')

    def test_traversal_file_byte_depth_and_deadline_limits_are_visible(self):
        for n in range(6):
            self.write(f'{n}.txt', 'needle')
        with patch('archive_search.MAX_ENTRIES', 2):
            result = self.archive.search('needle')
            self.assertTrue(result['truncated'])
            self.assertLessEqual(result['coverage']['entries_seen'], 2)
        with patch('archive_search.MAX_FILES', 2):
            result = self.archive.search('needle')
            self.assertTrue(result['truncated'])
            self.assertEqual(result['coverage']['files_scanned'], 2)
        with patch('archive_search.MAX_READ_BYTES', 5):
            result = self.archive.search('needle')
            self.assertTrue(result['truncated'])
            self.assertLessEqual(result['coverage']['bytes_read'], 5)
        self.write('deep/nested/file.txt', 'unique')
        with patch('archive_search.MAX_DEPTH', 1):
            result = self.archive.search('unique')
            self.assertTrue(result['truncated'])
            self.assertEqual(result['sources'], [])
        with patch('archive_search.MAX_SCAN_SECONDS', -1):
            result = self.archive.search('needle')
            self.assertTrue(result['truncated'])
            self.assertEqual(result['coverage']['bytes_read'], 0)

    def test_unsupported_safe_access_fails_closed(self):
        with patch('archive_search.os.supports_dir_fd', set()):
            with self.assertRaisesRegex(ValueError, 'unsupported'):
                ReadOnlyArchive(self.root)
