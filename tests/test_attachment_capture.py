import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from attachment_capture import AttachmentCapture, MAX_BYTES, store_image

PNG = b'\x89PNG\r\n\x1a\n' + b'fixture'


class AttachmentCaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.binary = self.root / 'gmcli'
        self.binary.write_text('#!/bin/sh\n')
        self.binary.chmod(0o700)
        self.now = 1000

    def tearDown(self): self.temp.cleanup()

    def capture(self, owner='Casey', **options):
        return AttachmentCapture(self.root / 'archive', owner, self.root / 'store',
                                 executable=self.binary, clock=lambda: self.now, ocr=False, timeout=30, **options)

    def download(self, args, **kwargs):
        self.assertEqual(args[1:4], ['--store', str(self.root / 'store'), '--read-only=true'])
        self.assertEqual(os.fstat(kwargs['stdout'].fileno()).st_mode & 0o777, 0o600)
        self.assertEqual(kwargs['stderr'], subprocess.DEVNULL)
        self.assertEqual(kwargs['timeout'], 30)
        Path(args[-1]).write_bytes(PNG)
        return subprocess.CompletedProcess(args, 0)

    def test_capture_dedup_private_blob_and_owner_isolation(self):
        with patch('attachment_capture.subprocess.run', side_effect=self.download) as run:
            with self.capture().session() as capture:
                item = capture.capture('m1', 'media', 'image/png')
                self.assertEqual(capture.capture('m1', 'media', 'image/png'), item)
                capture.capture('m2', 'media2', 'image/png')
            path = Path(item['local_path'])
            self.assertEqual(item['sha256'], hashlib.sha256(PNG).hexdigest())
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
            self.assertEqual(len(list(path.parent.glob('*.png'))), 1)
            with self.capture().session() as capture:
                self.assertEqual(capture.capture('m1', 'media', 'image/png'), item)
            self.assertEqual(run.call_count, 2)
            with self.capture('Jordan').session() as capture: other = capture.capture('m1', 'media', 'image/png')
            self.assertNotEqual(other['local_path'], item['local_path'])

    def test_failure_cooldown_bounded_attempts_and_later_retry(self):
        with patch('attachment_capture.subprocess.run', return_value=subprocess.CompletedProcess([], 1)) as run:
            with self.capture(limit=1).session() as capture:
                self.assertEqual(capture.capture('m1', 'a', 'image/png')['capture_status'], 'unavailable')
                capture.capture('m2', 'b', 'image/png')
                self.assertEqual(capture.stats['deferred'], 1)
            with self.capture().session() as capture: capture.capture('m1', 'a', 'image/png')
            self.assertEqual(run.call_count, 1)
        self.now += 301
        with patch('attachment_capture.subprocess.run', side_effect=self.download):
            with self.capture().session() as capture:
                self.assertEqual(capture.capture('m1', 'a', 'image/png')['capture_status'], 'captured')

    def test_timeout_and_format_mismatch_are_sanitized(self):
        with patch('attachment_capture.subprocess.run', side_effect=subprocess.TimeoutExpired('secret', 30)):
            with self.capture().session() as capture:
                capture.capture('m1', 'a', 'image/png')
                self.assertEqual(capture.errors, {'download_timeout': 1})
        with patch('attachment_capture.subprocess.run', side_effect=self.download):
            with self.capture().session() as capture:
                self.assertEqual(capture.capture('m2', 'a', 'image/jpeg')['capture_status'], 'unavailable')
                self.assertEqual(capture.errors, {'invalid_image': 1})

    def test_corrupt_cache_and_symlink_never_claim_capture(self):
        with patch('attachment_capture.subprocess.run', side_effect=self.download):
            with self.capture().session() as capture: item = capture.capture('m1', 'a', 'image/png')
            Path(item['local_path']).write_bytes(b'broken')
            with self.capture().session() as capture:
                self.assertEqual(capture.capture('m1', 'a', 'image/png')['capture_status'], 'unavailable')
                self.assertEqual(capture.errors, {'blob_integrity': 1})
        (self.root / 'archive' / 'Jordan').mkdir()
        (self.root / 'archive' / 'Jordan' / 'attachments').symlink_to(self.root)
        with self.assertRaises(ValueError): self.capture('Jordan')

    def test_oversized_download_rejected(self):
        def download(args, **kwargs):
            with Path(args[-1]).open('wb') as handle: handle.truncate(MAX_BYTES + 1)
            return subprocess.CompletedProcess(args, 0)
        with patch('attachment_capture.subprocess.run', side_effect=download):
            with self.capture().session() as capture:
                self.assertEqual(capture.capture('m1', 'a', 'image/png')['capture_status'], 'unavailable')

    def test_local_store_reads_bounded_and_reuses_same_blob(self):
        source = self.root / 'source.png'
        source.write_bytes(PNG)
        source.chmod(0o644)
        first = store_image(self.root / 'archive', 'Alex', source, 'image/png', ocr=False)
        self.assertEqual(first, store_image(self.root / 'archive', 'Alex', source, 'image/png', ocr=False))
        self.assertEqual(source.stat().st_mode & 0o777, 0o644)
        with self.assertRaises(ValueError): store_image(self.root / 'archive', 'Alex', source, 'image/jpeg', ocr=False)

    def test_ocr_bounded_private_local_output(self):
        def run(args, **kwargs):
            if args[0] == '/local/tesseract':
                Path(args[2] + '.txt').write_text('Bank fee $15')
                return subprocess.CompletedProcess(args, 0)
            return self.download(args, **kwargs)
        with patch('attachment_capture.shutil.which', return_value='/local/tesseract'), patch('attachment_capture.subprocess.run', side_effect=run):
            capture = AttachmentCapture(self.root / 'archive', 'Casey', self.root / 'store', executable=self.binary, timeout=30)
            with capture.session(): item = capture.capture('m1', 'a', 'image/png')
            self.assertEqual(item['ocr_text'], 'Bank fee $15')
            self.assertFalse(list(capture.directory.glob('tmp*')))

    def test_multiple_images_preserve_each_part_and_reject_preview(self):
        def download(args, **kwargs):
            first = Path(args[-1])
            second = Path(str(first) + '.part-1')
            first.write_bytes(PNG)
            second.write_bytes(PNG + b'second')
            kwargs['stdout'].write(json.dumps({'attachments': [
                {'attachment_id': 'action-a', 'mime_type': 'image/png', 'path': str(first),
                 'capture_kind': 'full', 'capture_status': 'captured'},
                {'attachment_id': 'action-b', 'mime_type': 'image/png', 'path': str(second),
                 'capture_kind': 'full', 'capture_status': 'captured'},
                {'attachment_id': 'action-c', 'mime_type': 'image/png', 'path': str(first),
                 'capture_kind': 'preview', 'capture_status': 'captured'}]}).encode())
            return subprocess.CompletedProcess(args, 0)
        with patch('attachment_capture.subprocess.run', side_effect=download):
            with self.capture().session() as capture:
                parts = capture.capture_many('m1', None, 'image/png')
                self.assertEqual([a['media_id'] for a in parts], ['action-a', 'action-b', 'action-c'])
                self.assertEqual([a['capture_status'] for a in parts], ['captured', 'captured', 'unavailable'])
                self.assertNotEqual(parts[0]['sha256'], parts[1]['sha256'])

    def test_unsupported_format_cannot_starve_supported_image(self):
        with patch('attachment_capture.subprocess.run', side_effect=self.download) as run:
            with self.capture(limit=1).session() as capture:
                capture.capture('new', 'unsupported', 'image/unknown')
                self.assertEqual(capture.capture('old', 'supported', 'image/png')['capture_status'], 'captured')
                self.assertEqual(run.call_count, 1)


if __name__ == '__main__': unittest.main()
