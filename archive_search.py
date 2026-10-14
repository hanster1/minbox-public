"""Bounded, read-only search of a deliberately filtered text export.

This reader does not filter message content or read Minbox's runtime archive.
The caller selects one trusted export root; requests never accept filesystem paths.
"""
from contextlib import closing, contextmanager
import hashlib
import os
from pathlib import Path
import re
import stat
import time

MAX_QUERY_CHARS = 256
MAX_RESULTS = 20
MAX_FILE_BYTES = 128 * 1024
MAX_BODY_BYTES = 32 * 1024
MAX_EXCERPT_CHARS = 600
MAX_ENTRIES = 2000
MAX_FILES = 200
MAX_DEPTH = 6
MAX_READ_BYTES = 8 * 1024 * 1024
MAX_SCAN_SECONDS = 5
_RUNTIME_NAMES = {'raw', 'logs', 'cache', 'sessions', 'credentials', 'cookies',
                  'tokens', 'passwords', 'secrets', 'oauth', 'session', 'health',
                  'state', 'config', '__pycache__', 'node_modules'}
_HASH = re.compile(r'[0-9a-f]{64}')
_SOURCE_ID = re.compile(r'file_[0-9a-f]{64}')


class ReadOnlyArchive:
    """Fresh export reads; scan deadlines are checked between filesystem calls."""
    def __init__(self, root):
        if (not all(hasattr(os, flag) for flag in ('O_NOFOLLOW', 'O_DIRECTORY', 'O_NONBLOCK'))
                or os.open not in os.supports_dir_fd or os.stat not in os.supports_dir_fd
                or os.stat not in os.supports_follow_symlinks or os.scandir not in os.supports_fd):
            raise ValueError('safe export filesystem access is unsupported')
        self._root = Path(root).expanduser().absolute()
        if '..' in self._root.parts:
            raise ValueError('export root must not contain traversal components')
        with self._root_fd():
            pass

    @contextmanager
    def _root_fd(self):
        fd = None
        try:
            fd = os.open('/', self._directory_flags())
            for component in self._root.parts[1:]:
                child = os.open(component, self._directory_flags(), dir_fd=fd)
                os.close(fd)
                fd = child
            yield fd
        except OSError:
            raise ValueError('export root is unavailable or unsafe') from None
        finally:
            if fd is not None:
                os.close(fd)

    @staticmethod
    def _directory_flags():
        return os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NONBLOCK

    @staticmethod
    def _state():
        return {'entries_seen': 0, 'files_scanned': 0, 'files_skipped': 0,
                'bytes_read': 0, 'limited': False, 'deadline': time.monotonic() + MAX_SCAN_SECONDS}

    @staticmethod
    def _expired(state):
        if time.monotonic() >= state['deadline']:
            state['limited'] = True
            return True
        return False

    @staticmethod
    def _coverage(state):
        return {k: v for k, v in state.items() if k != 'deadline'} | {
            'scope': 'filtered_text_export', 'max_file_bytes': MAX_FILE_BYTES,
            'max_depth': MAX_DEPTH, 'max_files': MAX_FILES, 'max_entries': MAX_ENTRIES,
            'max_read_bytes': MAX_READ_BYTES, 'scan_seconds': MAX_SCAN_SECONDS}

    def _walk(self, fd, parents, state):
        try:
            with os.scandir(fd) as entries:
                for entry in entries:
                    if self._expired(state) or state['entries_seen'] >= MAX_ENTRIES:
                        state['limited'] = True
                        return
                    state['entries_seen'] += 1
                    name = entry.name
                    if name.startswith('.') or Path(name).stem.casefold() in _RUNTIME_NAMES:
                        state['files_skipped'] += 1
                        continue
                    try:
                        name.encode('utf-8')
                        info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                        if stat.S_ISDIR(info.st_mode):
                            if len(parents) >= MAX_DEPTH:
                                state['limited'] = True
                                continue
                            child = os.open(name, self._directory_flags(), dir_fd=fd)
                            try:
                                yield from self._walk(child, (*parents, name), state)
                            finally:
                                os.close(child)
                        elif (stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                              and Path(name).suffix.casefold() in {'.txt', '.md'}):
                            if state['files_scanned'] >= MAX_FILES:
                                state['limited'] = True
                                return
                            state['files_scanned'] += 1
                            relative = '/'.join((*parents, name))
                            yield fd, name, relative
                        else:
                            state['files_skipped'] += 1
                    except (OSError, UnicodeError):
                        state['files_skipped'] += 1
        except OSError:
            state['files_skipped'] += 1

    def _read(self, fd, name, state):
        handle = None
        try:
            if self._expired(state):
                return None
            handle = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
            before = os.fstat(handle)
            if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                    or before.st_size > MAX_FILE_BYTES):
                state['files_skipped'] += 1
                return None
            if state['bytes_read'] + before.st_size > MAX_READ_BYTES:
                state['limited'] = True
                return None
            chunks, size = [], 0
            while True:
                if self._expired(state):
                    return None
                remaining = min(MAX_FILE_BYTES + 1 - size, MAX_READ_BYTES - state['bytes_read'])
                if remaining <= 0:
                    state['limited'] = True
                    return None
                chunk = os.read(handle, min(65536, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
                state['bytes_read'] += len(chunk)
                if size > MAX_FILE_BYTES:
                    state['files_skipped'] += 1
                    return None
            after = os.fstat(handle)
            signature = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns,
                                   s.st_mode, s.st_nlink)
            if signature(before) != signature(after) or size != before.st_size:
                state['files_skipped'] += 1
                return None
            raw = b''.join(chunks)
            text = raw.decode('utf-8')
            if '\x00' in text:
                state['files_skipped'] += 1
                return None
            return raw, text
        except (OSError, UnicodeError):
            state['files_skipped'] += 1
            return None
        finally:
            if handle is not None:
                os.close(handle)

    @staticmethod
    def _source_id(relative):
        return 'file_' + hashlib.sha256(relative.encode('utf-8')).hexdigest()

    @classmethod
    def _metadata(cls, relative, raw):
        digest = hashlib.sha256(raw).hexdigest()
        return {'source_id': cls._source_id(relative), 'title': Path(relative).stem,
                'relative_path': relative, 'sha256': digest, 'version': digest}

    def search(self, query, limit=5):
        try:
            valid_query = (isinstance(query, str) and len(query) <= MAX_QUERY_CHARS
                           and len(query.encode('utf-8')) <= 1024)
        except UnicodeError:
            valid_query = False
        if not valid_query:
            raise ValueError('query must be bounded UTF-8 text')
        if type(limit) is not int or not 1 <= limit <= MAX_RESULTS:
            raise ValueError('result limit must be an integer from 1 to 20')
        state, sources = self._state(), []
        needle = query.strip().casefold()
        if needle:
            with self._root_fd() as root, closing(self._walk(root, (), state)) as files:
                for fd, name, relative in files:
                    value = self._read(fd, name, state)
                    if value is None:
                        continue
                    raw, text = value
                    position = text.casefold().find(needle)
                    if position < 0:
                        continue
                    if len(sources) == limit:
                        state['limited'] = True
                        break
                    # Case folding can expand characters, so map back to original offsets.
                    folded_offset = 0
                    for original_offset, character in enumerate(text):
                        folded_offset += len(character.casefold())
                        if folded_offset > position:
                            break
                    start = max(0, original_offset - 100)
                    excerpt = text[start:start + MAX_EXCERPT_CHARS]
                    sources.append(self._metadata(relative, raw) | {
                        'excerpt': excerpt, 'truncated': start > 0 or start + len(excerpt) < len(text)})
        return {'sources': sources, 'truncated': state['limited'], 'coverage': self._coverage(state)}

    def read_source(self, source_id, expected_hash=None):
        if not isinstance(source_id, str) or not _SOURCE_ID.fullmatch(source_id):
            raise ValueError('source identifier is invalid')
        if expected_hash is not None and (not isinstance(expected_hash, str)
                                         or not _HASH.fullmatch(expected_hash)):
            raise ValueError('expected version is invalid')
        state = self._state()
        with self._root_fd() as root, closing(self._walk(root, (), state)) as files:
            for fd, name, relative in files:
                if self._source_id(relative) != source_id:
                    continue
                value = self._read(fd, name, state)
                if value is None:
                    break
                raw, _ = value
                metadata = self._metadata(relative, raw)
                if expected_hash is not None and metadata['sha256'] != expected_hash:
                    raise ValueError('source changed since the expected version')
                body = raw[:MAX_BODY_BYTES].decode('utf-8', errors='ignore')
                return metadata | {'body': body, 'truncated': len(raw) > MAX_BODY_BYTES,
                                   'coverage': self._coverage(state)}
        raise LookupError('source is unavailable in the configured export coverage')
