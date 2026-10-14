"""Trusted phone-folder observations and sticky owner-scoped Drive exclusions.

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
    db.execute('''CREATE TABLE IF NOT EXISTS phone_spam_sync (
        owner TEXT PRIMARY KEY, supported INTEGER NOT NULL, checked_at TEXT NOT NULL)''')


def sync_observations(archive, owner, collector_db):
    """Called under owner_operation; never query or mutate the phone itself."""
    owner = _owner(owner)
    with closing(sqlite3.connect(Path(collector_db).resolve(strict=True).as_uri() + '?mode=ro', uri=True)) as source:
        source.execute('PRAGMA query_only=ON')
        tables = {r[0] for r in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        supported = 'phone_spam_conversations' in tables
        rows = source.execute('SELECT conversation_id,status FROM phone_spam_conversations').fetchall() if supported else []
    if any(not isinstance(cid, str) or not cid or status not in STATUSES for cid, status in rows):
        raise ValueError('invalid collector phone-folder observation')
    stamp = datetime.now(timezone.utc).isoformat()
    with archive._connect() as db:
        ensure_schema(db)
        before = db.execute('SELECT COUNT(*) FROM phone_spam_exclusions WHERE owner=?', (owner,)).fetchone()[0]
        for cid, status in rows:
            db.execute('''INSERT INTO phone_spam_exclusions VALUES (?,?,?,?,?)
                ON CONFLICT(owner,source,conversation_id) DO NOTHING''',
                (owner, 'google-messages', cid, status, stamp))
        db.execute('''INSERT INTO phone_spam_sync VALUES (?,?,?)
            ON CONFLICT(owner) DO UPDATE SET supported=excluded.supported,checked_at=excluded.checked_at''',
            (owner, int(supported), stamp))
        total = db.execute('SELECT COUNT(*) FROM phone_spam_exclusions WHERE owner=?', (owner,)).fetchone()[0]
    return {'supported': supported, 'new_exclusions': total - before, 'excluded_conversations': total}


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
    return {r[0] for r in db.execute('''SELECT conversation_id FROM phone_spam_exclusions
        WHERE owner=? AND source='google-messages' AND status IN (5,6)''', (owner,))}
