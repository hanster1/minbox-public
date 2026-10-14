"""Trusted phone-folder observations and current owner-scoped Drive exclusions.

This policy retains local evidence. Only the collector's reviewed metadata table
can create exclusions; message bodies and disappearance are never instructions.
"""
from contextlib import contextmanager, closing
from datetime import datetime, timezone
import fcntl
import os
from pathlib import Path
import sqlite3

from storage import Archive, _owner, _mkdir

POLICY = 'spam_and_blocked'
STATUSES = (5, 6)


@contextmanager
def owner_operation(root, owner):
    owner = _owner(owner)
    archive = Archive(Path(root))
    if not archive.db.is_file():
        raise ValueError('existing archive required for owner operation')
    if owner not in archive.owner_names():
        raise ValueError('existing owner namespace required for publication')
    directory = archive.root / owner
    _mkdir(directory)
    fd = os.open(directory / '.phone-publication.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'a+b') as lock:
        os.fchmod(lock.fileno(), 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def ensure_schema(db):
    db.execute('''CREATE TABLE IF NOT EXISTS phone_spam_exclusions (
        owner TEXT NOT NULL, source TEXT NOT NULL, conversation_id TEXT NOT NULL,
        status INTEGER NOT NULL CHECK(status IN (5,6)), observed_at TEXT NOT NULL,
        PRIMARY KEY(owner,source,conversation_id))''')
    columns = {r[1] for r in db.execute('PRAGMA table_info(phone_spam_exclusions)')}
    for name, definition in (('active', 'INTEGER NOT NULL DEFAULT 1'),
                             ('collector_revision', 'INTEGER NOT NULL DEFAULT 0'),
                             ('collector_observed_at', 'INTEGER NOT NULL DEFAULT 0'),
                             ('restored_status', 'INTEGER NOT NULL DEFAULT 0'),
                             ('restored_at', 'INTEGER NOT NULL DEFAULT 0')):
        if name not in columns:
            db.execute(f'ALTER TABLE phone_spam_exclusions ADD COLUMN {name} {definition}')
    db.execute('''CREATE TABLE IF NOT EXISTS phone_spam_sync (
        owner TEXT PRIMARY KEY, supported INTEGER NOT NULL, checked_at TEXT NOT NULL)''')


def _collector_rows(source):
    columns = {r[1] for r in source.execute('PRAGMA table_info(phone_spam_conversations)')}
    modern = {'active', 'revision', 'observed_at', 'restored_status', 'restored_at'}
    if 'active' in columns and not modern <= columns:
        raise ValueError('invalid collector phone-folder observation schema')
    if 'active' not in columns:
        return [(cid, status, 1, 0, 0, 0, 0) for cid, status in
                source.execute('SELECT conversation_id,status FROM phone_spam_conversations')]
    rows = source.execute('''SELECT conversation_id,status,active,revision,observed_at,
        restored_status,restored_at FROM phone_spam_conversations''').fetchall()
    if any(type(row[3]) is not int or row[3] < 1 or type(row[4]) is not int or row[4] < 1 for row in rows):
        raise ValueError('invalid collector phone-folder observation')
    return rows


def sync_observations(archive, owner, collector_db):
    """Import reviewed metadata, retaining originals and rejecting stale restoration."""
    owner = _owner(owner)
    with closing(sqlite3.connect(Path(collector_db).resolve(strict=True).as_uri() + '?mode=ro', uri=True)) as source:
        source.execute('PRAGMA query_only=ON')
        tables = {r[0] for r in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        supported = 'phone_spam_conversations' in tables
        rows = _collector_rows(source) if supported else []
    for cid, status, active, revision, observed, restored_status, restored in rows:
        if (not isinstance(cid, str) or not cid or
                any(type(v) is not int for v in (status, active, revision, observed, restored_status, restored)) or
                status not in STATUSES or active not in (0, 1) or revision < 0 or observed < 0 or restored < 0 or
                restored_status not in (0, 1, 2, 4) or
                (not active and (revision < 1 or observed < 1 or restored_status not in (1, 2, 4) or restored <= observed))):
            raise ValueError('invalid collector phone-folder observation')
    stamp = datetime.now(timezone.utc).isoformat()
    added = 0
    with archive._connect() as db:
        ensure_schema(db)
        for cid, status, active, revision, observed, restored_status, restored in rows:
            old = db.execute('''SELECT active,collector_revision,collector_observed_at,restored_at
                FROM phone_spam_exclusions WHERE owner=? AND source='google-messages' AND conversation_id=?''',
                (owner, cid)).fetchone()
            if old is not None:
                old_active, old_revision, old_observed, old_restored = old
                old_effective = old_observed if old_active else old_restored
                effective = observed if active else restored
                # A legacy ledger is positive-only and can never undo a modern restoration.
                if revision == 0 and observed == 0:
                    continue
                if effective < old_effective or observed < old_observed:
                    continue
                if not active and (revision <= old_revision or effective <= old_effective):
                    continue
                if active and old_active and effective == old_effective and revision < old_revision:
                    continue
            db.execute('''INSERT INTO phone_spam_exclusions
                (owner,source,conversation_id,status,observed_at,active,collector_revision,
                 collector_observed_at,restored_status,restored_at) VALUES (?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(owner,source,conversation_id) DO UPDATE SET
                status=excluded.status,observed_at=excluded.observed_at,active=excluded.active,
                collector_revision=excluded.collector_revision,collector_observed_at=excluded.collector_observed_at,
                restored_status=excluded.restored_status,restored_at=excluded.restored_at''',
                (owner, 'google-messages', cid, status, stamp, active, revision, observed, restored_status, restored))
            if active and (old is None or not old[0]):
                added += 1
        db.execute('''INSERT INTO phone_spam_sync VALUES (?,?,?)
            ON CONFLICT(owner) DO UPDATE SET supported=excluded.supported,checked_at=excluded.checked_at''',
            (owner, int(supported), stamp))
        total = db.execute('SELECT COUNT(*) FROM phone_spam_exclusions WHERE owner=? AND active=1', (owner,)).fetchone()[0]
    return {'supported': supported, 'new_exclusions': added, 'excluded_conversations': total}


def excluded_conversations(db, owner, policy):
    if policy in (None, 'off'):
        return set()
    if policy != POLICY:
        raise ValueError('unknown phone spam publication policy')
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not {'phone_spam_sync', 'phone_spam_exclusions'} <= tables:
        raise ValueError('phone spam policy requires updated collector and import')
    state = db.execute('SELECT supported FROM phone_spam_sync WHERE owner=?', (owner,)).fetchone()
    if state is None or state[0] != 1:
        raise ValueError('phone spam signal is unavailable; verify collector version')
    columns = {r[1] for r in db.execute('PRAGMA table_info(phone_spam_exclusions)')}
    active_filter = ' AND active=1' if 'active' in columns else ''
    return {r[0] for r in db.execute('''SELECT conversation_id FROM phone_spam_exclusions
        WHERE owner=? AND source='google-messages' AND status IN (5,6)''' + active_filter, (owner,))}
