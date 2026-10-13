"""Bounded private image capture; gmcli alone handles media keys and decryption."""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import resource
import shutil
import subprocess
import tempfile
import time

from storage import _mkdir, _outside_git, _owner

MAX_BYTES = 20 * 1024 * 1024
DEFAULT_GMCLI = Path.home() / '.local/lib/minbox-text-archive/bin/gmcli'
FORMATS = {'image/jpeg': 'jpg', 'image/png': 'png', 'image/gif': 'gif', 'image/webp': 'webp',
           'image/heic': 'heic', 'image/heif': 'heif', 'image/avif': 'avif',
           'image/tiff': 'tiff', 'image/bmp': 'bmp'}


def image_mime(data):
    if data.startswith(b'\xff\xd8\xff'): return 'image/jpeg'
    if data.startswith(b'\x89PNG\r\n\x1a\n'): return 'image/png'
    if data[:6] in (b'GIF87a', b'GIF89a'): return 'image/gif'
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP': return 'image/webp'
    if data.startswith((b'II*\x00', b'MM\x00*')): return 'image/tiff'
    if data.startswith(b'BM'): return 'image/bmp'
    if data[4:8] == b'ftyp':
        brands = {data[i:i + 4] for i in range(8, min(len(data), 64), 4)}
        if brands & {b'avif', b'avis'}: return 'image/avif'
        if brands & {b'heic', b'heix', b'hevc', b'hevx'}: return 'image/heic'
        if brands & {b'mif1', b'msf1'}: return 'image/heif'
    return None


def _file_limit():
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_BYTES, MAX_BYTES))


class AttachmentCapture:
    def __init__(self, root, owner, store, *, executable=None, limit=8,
                 timeout=20, cooldown=300, clock=time.time, ocr=True):
        self.owner = _owner(owner)
        self.directory = Path(root).expanduser().absolute() / owner / 'attachments'
        _outside_git(self.directory)
        _mkdir(self.directory)
        self.store = Path(store)
        self.executable = Path(executable) if executable is not None else DEFAULT_GMCLI
        self.limit, self.timeout, self.cooldown = limit, timeout, cooldown
        self.clock, self.ocr = clock, ocr
        self.deadline = time.monotonic() + 120
        self.stats = dict(captured=0, cached=0, unavailable=0, deferred=0, attempted=0)
        self.errors = {}
        self.state_path = self.directory / 'capture-state.json'

    @contextmanager
    def session(self):
        """One owner lock prevents concurrent import/download state races."""
        lock = self.directory / '.capture.lock'
        fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'r+') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            if self.state_path.is_symlink(): raise ValueError('Attachment state must not be a symlink')
            if self.state_path.exists():
                self.state_path.chmod(0o600)
                state = json.loads(self.state_path.read_text())
                if state.get('owner') != self.owner or state.get('version') != 1:
                    raise ValueError('Attachment state owner/version mismatch')
                self.entries = state['entries']
            else: self.entries = {}
            yield self

    def _save(self):
        with tempfile.NamedTemporaryFile(dir=self.directory, mode='w', delete=False) as handle:
            name = Path(handle.name)
            os.fchmod(handle.fileno(), 0o600)
            json.dump(dict(version=1, owner=self.owner, entries=self.entries), handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, self.state_path)

    def _verified(self, attachment):
        digest = attachment.get('sha256', '')
        mime = attachment.get('mime_type')
        if len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest) or mime not in FORMATS:
            return False
        expected = self.directory / (digest + '.' + FORMATS[mime])
        if attachment.get('local_path') != str(expected.absolute()) or expected.is_symlink(): return False
        try:
            if expected.stat().st_size > MAX_BYTES: return False
            with expected.open('rb') as handle: data = handle.read(MAX_BYTES + 1)
            valid = (len(data) == attachment.get('size_bytes') and image_mime(data) == mime
                     and hashlib.sha256(data).hexdigest() == digest)
            if valid: expected.chmod(0o600)
            return valid
        except OSError: return False

    def _ocr(self, path):
        binary = shutil.which('tesseract') if self.ocr else None
        remaining = self.deadline - time.monotonic()
        if not binary or remaining <= 0: return None
        with tempfile.TemporaryDirectory(dir=self.directory) as directory:
            output = Path(directory) / 'ocr'
            try:
                result = subprocess.run([binary, str(path), str(output)], stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL, timeout=min(self.timeout, 5, remaining), preexec_fn=_file_limit)
                text_path = output.with_suffix('.txt')
                if result.returncode == 0 and text_path.is_file() and not text_path.is_symlink():
                    text_path.chmod(0o600)
                    with text_path.open('rb') as handle: text = handle.read(65536).decode('utf-8', errors='replace').strip()
                    return text or None
            except (OSError, subprocess.TimeoutExpired): pass
        return None

    def _store(self, data, metadata):
        actual = image_mime(data)
        if not data or len(data) > MAX_BYTES or actual != metadata.get('mime_type') or actual not in FORMATS:
            raise ValueError('Unsupported or invalid image')
        digest = hashlib.sha256(data).hexdigest()
        dest = self.directory / (digest + '.' + FORMATS[actual])
        attachment = dict(metadata, capture_status='captured', sha256=digest,
                          size_bytes=len(data), local_path=str(dest.absolute()))
        if dest.exists() or dest.is_symlink():
            if not self._verified(attachment): raise ValueError('Attachment blob integrity failure')
        else:
            with tempfile.NamedTemporaryFile(dir=self.directory) as handle:
                os.fchmod(handle.fileno(), 0o600)
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
                try: os.link(handle.name, dest)
                except FileExistsError:
                    if not self._verified(attachment): raise ValueError('Attachment blob integrity failure')
        text = self._ocr(dest)
        if text: attachment['ocr_text'] = text
        return attachment

    def capture(self, message_id, media_id, mime):
        return self.capture_many(message_id, media_id, mime)[0]

    def priority(self, message_id, media_id):
        _, entry = self._entry(message_id, media_id)
        return (0, 0) if entry is None else (1, entry.get('last_attempt', 0))

    def _entry(self, message_id, media_id):
        # Download IDs can change after full-size refresh; source identity cannot.
        key = hashlib.sha256(json.dumps([str(message_id)]).encode()).hexdigest()
        entry = self.entries.get(key)
        if entry is None:
            for legacy_media in (media_id, None):
                legacy = hashlib.sha256(json.dumps([str(message_id), str(legacy_media)]).encode()).hexdigest()
                if legacy in self.entries:
                    entry = self.entries[legacy]
                    break
        return key, entry

    def capture_many(self, message_id, media_id, mime):
        metadata = dict(media_id=str(media_id) if media_id else 'message-' + str(message_id) + '-image',
                        mime_type=mime, capture_status='metadata')
        if not isinstance(mime, str) or not mime.startswith('image/'):
            return [metadata]
        if mime not in FORMATS:
            self.stats['unavailable'] += 1
            return [dict(metadata, capture_status='unavailable')]
        key, entry = self._entry(message_id, media_id)
        entry = entry or {}
        prior = entry.get('attachments') or ([entry['attachment']] if entry.get('attachment') else [])
        if prior and all(a.get('capture_status') == 'captured' and self._verified(a) for a in prior):
            self.stats['cached'] += len(prior)
            return prior
        prior = [a if a.get('capture_status') == 'captured' and self._verified(a) else
                 {k: v for k, v in dict(a, capture_status='unavailable').items()
                  if k not in ('sha256', 'local_path', 'size_bytes', 'ocr_text')}
                 for a in prior]
        if (entry.get('retry_after', 0) > self.clock() or self.stats['attempted'] >= self.limit or
                time.monotonic() >= self.deadline):
            self.stats['deferred'] += 1
            return prior or [dict(metadata, capture_status='unavailable')]
        reason = 'downloader_missing'
        if self.executable.is_file() and os.access(self.executable, os.X_OK):
            self.stats['attempted'] += 1
            with tempfile.TemporaryDirectory(dir=self.directory) as directory:
                path = Path(directory) / 'media'
                try:
                    with (Path(directory) / 'result.json').open('w+b') as output:
                        os.fchmod(output.fileno(), 0o600)
                        result = subprocess.run([str(self.executable), '--store', str(self.store),
                            '--read-only=true', '--json', 'media', 'download', '--message', str(message_id), '--out', str(path)],
                            stdout=output, stderr=subprocess.DEVNULL,
                            timeout=min(self.timeout, max(.1, self.deadline - time.monotonic())), preexec_fn=_file_limit)
                        output.seek(0)
                        encoded = output.read(1024 * 1024 + 1)
                    reason = 'download_failed'
                    if result.returncode == 0:
                        reason = 'invalid_image'
                        if len(encoded) > 1024 * 1024:
                            raise ValueError('Download result exceeds bound')
                        decoded = json.loads(encoded) if encoded.strip() else {}
                        parts = decoded.get('attachments') or [dict(metadata, path=str(path), capture_kind='full',
                                                                   capture_status='captured')]
                        if not isinstance(parts, list) or len(parts) > 100:
                            raise ValueError('Invalid image parts')
                        captured = []
                        for index, part in enumerate(parts):
                            actual_mime = part.get('mime_type') or mime
                            if not str(actual_mime).startswith('image/'):
                                continue
                            meta = dict(media_id=str(part.get('attachment_id') or part.get('media_id') or
                                                    metadata['media_id'] + '-part-' + str(index)),
                                        mime_type=actual_mime, capture_status='unavailable')
                            candidate = Path(part.get('path') or str(path))
                            # A collector result may name only this private download's files.
                            if (part.get('capture_kind') == 'full' and part.get('capture_status', 'captured') == 'captured' and
                                    candidate.parent == path.parent and not candidate.is_symlink() and
                                    candidate.is_file() and 0 < candidate.stat().st_size <= MAX_BYTES):
                                candidate.chmod(0o600)
                                with candidate.open('rb') as handle: data = handle.read(MAX_BYTES + 1)
                                if image_mime(data) == actual_mime and actual_mime in FORMATS:
                                    meta.update(self._store(data, meta))
                                    self.stats['captured'] += 1
                            captured.append(meta)
                        if captured:
                            missing = sum(a['capture_status'] != 'captured' for a in captured)
                            self.entries[key] = dict(attachments=captured, last_attempt=self.clock(),
                                                     retry_after=self.clock() + self.cooldown if missing else 0)
                            self._save()
                            self.stats['unavailable'] += missing
                            if missing:
                                self.errors['invalid_image'] = self.errors.get('invalid_image', 0) + missing
                            return captured
                except subprocess.TimeoutExpired: reason = 'download_timeout'
                except OSError: reason = 'download_io'
                except ValueError: reason = 'blob_integrity'
        self.entries[key] = dict(attachments=prior, last_attempt=self.clock(),
                                retry_after=self.clock() + self.cooldown)
        self._save()
        self.stats['unavailable'] += 1
        self.errors[reason] = self.errors.get(reason, 0) + 1
        return prior or [dict(metadata, capture_status='unavailable')]


def store_image(root, owner, path, mime_type, *, ocr=True):
    """Copy a local image into validated private storage; retain no source location."""
    source = Path(path)
    if source.is_symlink() or any(parent.is_symlink() for parent in source.parents):
        raise ValueError('Image source must not be a symlink')
    with source.open('rb') as handle:
        data = handle.read(MAX_BYTES + 1)
    capture = AttachmentCapture(root, owner, source.parent, ocr=ocr)
    return capture._store(data, dict(mime_type=mime_type))
