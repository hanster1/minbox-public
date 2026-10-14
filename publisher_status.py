"""Private, content-free publisher attempt state; call only under the owner lock."""
from datetime import datetime, timezone
import errno
import json
import os
from pathlib import Path
import socket
import ssl
import tempfile
import urllib.error

from storage import _outside_git


def private_path(value):
    path = Path(value).expanduser().absolute()
    _outside_git(path)
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('private path must not use symlinks')
    return path


def write_json(path, value):
    path = private_path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(value, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _chain(error):
    seen = set()
    while error is not None and id(error) not in seen and len(seen) < 32:
        seen.add(id(error))
        yield error
        if isinstance(error, urllib.error.URLError) and isinstance(error.reason, BaseException):
            error = error.reason
        else:
            error = error.__cause__ or error.__context__


_PRIVACY = {
    'attachment folder identity mismatch', 'image destination identity mismatch',
    'attachment outside owner attachment root',
    'file-scoped authorization requires a selected folder binding',
    'selected folder authorization requires only drive.file',
    'selected archive folders must remain private, editable, owner-matched and rooted',
    'invalid selected folder binding', 'invalid managed folder binding',
    'selected root cannot have a managed parent',
    'managed folders must have a known rooted chain',
    'publisher folder must remain private and owner-matched',
    'publisher destination must remain private, editable, owner-matched and in its configured folder',
    'archive destination must remain private, owner-matched and in its authorized folder',
    'Google account differs from owner binding',
    'connected Google account differs from the configured owner binding',
    'manifest owner/folder differs', 'Document is not allowlisted',
    'private path must not use symlinks', 'manifest must be private',
    'publisher config must be private', 'publisher configuration must be private',
    'Google credentials must be private', 'publisher status must be private',
}
_INTEGRITY = {
    'attachment readback mismatch', 'attachment content metadata mismatch',
    'attachment saved metadata differs', 'invalid attachment manifest identity',
    'attachment destination identities overlap', 'image destination overlaps another identity',
    'publication readback mismatch', 'Output readback differs; publication is not confirmed',
    'publisher input and output identities must be distinct', 'publisher document identities collide',
    'snapshot differs from authorized owner scope', 'snapshot differs from authorized owner/thread scope',
    'overlapping output and input identities', 'duplicate chunk identities need review',
    'chunk overlaps another identity', 'ambiguous source identity or message alias',
    'ambiguous message aliases', 'Doc must have one plain text tab; no writes performed',
    'all-owner publication must be explicitly configured',
    'distinct guide/corrections/status documents required', 'invalid owner chunk identity',
    'invalid source field', 'invalid source origins', 'invalid previous chunk key',
}


def failure_details(error):
    """Backward-compatible fixed categories; never return exception text."""
    chain = list(_chain(error))
    for item in chain:
        if isinstance(item, urllib.error.HTTPError):
            result = {'error_code': 'http_failure'}
            if type(item.code) is int and 100 <= item.code <= 599:
                result['http_status'] = item.code
            return result
        if isinstance(item, BlockingIOError):
            return {'error_code': 'publisher_busy'}
        if isinstance(item, (TimeoutError, ConnectionError)):
            return {'error_code': 'transport_failure'}
    for item in chain:
        message = str(item)
        if message in {'publication readback mismatch', 'Output readback differs; publication is not confirmed'}:
            return {'error_code': 'readback_mismatch'}
        if message in _PRIVACY:
            return {'error_code': 'privacy_binding_failed'}
        if message in _INTEGRITY:
            return {'error_code': 'integrity_failed'}
        if message == 'Google authentication failed':
            return {'error_code': 'authentication_failed'}
        if message == 'HTTP request failed; private details withheld':
            return {'error_code': 'transport_failure'}
    return {'error_code': 'publication_failed'}


def classify_failure(error):
    result = failure_details(error)
    kind = {'privacy_binding_failed': 'privacy', 'integrity_failed': 'integrity',
            'readback_mismatch': 'integrity', 'authentication_failed': 'auth',
            'transport_failure': 'transient', 'publisher_busy': 'busy'}.get(result['error_code'], 'unknown')
    for item in _chain(error):
        if isinstance(item, urllib.error.HTTPError):
            kind = 'auth' if item.code in (401, 403) else 'transient' if item.code in (408, 429, 500, 502, 503, 504) else 'unknown'
            break
        if isinstance(item, ssl.SSLError):
            kind = 'integrity'
            break
        if isinstance(item, OSError) and (item.errno in {
                errno.ETIMEDOUT, errno.ECONNRESET, errno.ECONNABORTED, errno.ECONNREFUSED,
                errno.EPIPE, errno.ENETDOWN, errno.ENETUNREACH, errno.EHOSTUNREACH} or
                isinstance(item, socket.gaierror) and item.errno == socket.EAI_AGAIN):
            result['error_code'] = 'transport_failure'
            kind = 'transient'
            break
    return {**result, 'failure_kind': kind}


_FIELDS = {'checked_at', 'last_success_at', 'last_publication_at', 'source_import_timestamp',
           'writes', 'published_messages', 'excluded_messages', 'model_calls', 'work_messages',
           'work_looms', 'analysis_failed_or_paused', 'deferred_sources', 'last_analysis_success_at',
           'consecutive_failures'}
_FIELDS.update({'analysis_state', 'analysis_error_code', 'analysis_retryable', 'pending_sources',
                'deferred_reasons', 'model_attempts', 'analysis_retry_after', 'recovery_probes'})
_FIELDS.update({'published_images', 'verified_images', 'pending_images', 'unavailable_images',
                'attachment_writes', 'withdrawn_images', 'phone_spam_conversations'})


class PublisherStatus:
    def __init__(self, path):
        self.path = private_path(path)
        self.state = {}
        if self.path.exists():
            if self.path.stat().st_mode & 0o777 != 0o600:
                raise ValueError('publisher status must be private')
            previous = json.loads(self.path.read_text())
            self.state = {k: v for k, v in previous.items() if k in _FIELDS}

    @staticmethod
    def now():
        return datetime.now(timezone.utc).isoformat()

    def phase(self, phase, source_import_timestamp=None):
        self.state.update(phase=phase, heartbeat_at=self.now())
        if source_import_timestamp is not None:
            self.state['attempt_source_import_timestamp'] = source_import_timestamp
        write_json(self.path, self.state)

    def __enter__(self):
        self.state.update(started_at=self.now(), run_state='running')
        self.phase('validating')
        return self

    def success(self, source_import_timestamp, safe):
        stamp = self.now()
        degraded = bool(safe.get('analysis_failed_or_paused') or safe.get('deferred_sources'))
        self.state.update({k: v for k, v in safe.items() if k in _FIELDS})
        self.state.update(checked_at=stamp, heartbeat_at=stamp, phase='complete',
                          run_state='degraded' if degraded else 'succeeded', consecutive_failures=0,
                          last_publication_at=stamp, source_import_timestamp=source_import_timestamp)
        if not degraded:
            self.state['last_success_at'] = stamp
            if 'work_messages' in safe:
                self.state['last_analysis_success_at'] = stamp
        write_json(self.path, self.state)

    def __exit__(self, kind, error, traceback):
        if error is not None:
            self.state.update(checked_at=self.now(), heartbeat_at=self.now(),
                              run_state='failed', phase='failed',
                              consecutive_failures=self.state.get('consecutive_failures', 0) + 1,
                              **classify_failure(error))
            write_json(self.path, self.state)
        return False
