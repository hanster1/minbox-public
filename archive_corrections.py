"""Owner-scoped correction ledger. Source records are never modified.

AI clients author the line-oriented Doc format; users can speak ordinary language.
Only explicit message corrections apply. Runtime databases must be outside Git.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
from datetime import datetime

LABELS = {'personal', 'work', 'uncertain', 'mixed', 'spam'}
FIELDS = {'Correction ID': 'correction_id', 'Owner': 'owner', 'Target': 'target',
          'Scope': 'scope', 'Action': 'action', 'Instruction': 'instruction',
          'Requested at': 'requested_at', 'Undo correction': 'undo_correction'}
REQUIRED = set(FIELDS.values()) - {'undo_correction'}
MAX_TEXT = 1_000_000
MAX_RECORDS = 1000


def parse_corrections(text: str) -> list[dict]:
    """Parse bounded Doc entries, permitting introductory text before the first ID.

    Malformed entries are returned with an _error so ingestion can audit them.
    """
    if not isinstance(text, str) or len(text.encode('utf-8')) > MAX_TEXT:
        raise ValueError('correction document exceeds input bounds')
    starts = list(re.finditer(r'^Correction ID\s*:', text, re.MULTILINE))
    if len(starts) > MAX_RECORDS:
        raise ValueError('too many correction records')
    if not starts:
        return [] if not text.strip() else [{'_error': 'no correction entry found', 'raw': text}]
    records = []
    for i, start in enumerate(starts):
        raw = text[start.start():starts[i + 1].start() if i + 1 < len(starts) else len(text)].strip()
        record = {'raw': raw}
        for line in raw.splitlines():
            if not line.strip():
                continue
            name, sep, value = line.partition(':')
            key = FIELDS.get(name.strip())
            if not sep or not key or key in record:
                record.setdefault('_error', 'unknown, duplicate, or malformed field')
                continue
            record[key] = value.strip()
        records.append(record)
    return records


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def _record_error(owner, record):
    if record.get('_error'):
        return str(record['_error'])[:4096]
    if any(not isinstance(record.get(k), str) or not record[k].strip() for k in REQUIRED):
        return 'missing or invalid required field'
    if any(k not in REQUIRED | {'undo_correction', 'raw', '_error'} for k in record):
        return 'unknown correction field'
    if any(len(v) > 4096 for k, v in record.items() if isinstance(v, str) and k != 'raw'):
        return 'correction field exceeds input bounds'
    if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', record['correction_id']):
        return 'invalid correction ID'
    if record['owner'] != owner:
        return 'record owner differs from configured owner'
    if record['scope'] != 'message':
        return 'unsupported scope; explicit message scope required'
    if record['action'] not in LABELS | {'undo'}:
        return 'unsupported action'
    if record['action'] == 'undo' and not record.get('undo_correction'):
        return 'undo requires a prior correction ID'
    if record['action'] != 'undo' and record.get('undo_correction'):
        return 'undo reference requires undo action'
    try:
        requested = datetime.fromisoformat(record['requested_at'].replace('Z', '+00:00'))
        if requested.tzinfo is None or requested.utcoffset() is None:
            raise ValueError()
    except (ValueError, TypeError):
        return 'requested timestamp must include timezone'
    return None


class CorrectionLedger:
    def __init__(self, path):
        self.path = Path(path).expanduser().absolute()
        if any((ancestor / '.git').is_file() or (ancestor / '.git' / 'HEAD').is_file()
               for ancestor in self.path.parents):
            raise ValueError('runtime ledger must be outside Git')
        if self.path.is_symlink() or any(p.is_symlink() for p in self.path.parents):
            raise ValueError('ledger path must not use symlinks')
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(fd)
        except FileExistsError:
            pass
        os.chmod(self.path, 0o600)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS messages (
                owner TEXT, target TEXT, payload TEXT NOT NULL,
                PRIMARY KEY(owner,target));
            CREATE TABLE IF NOT EXISTS revisions (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, owner TEXT NOT NULL,
                correction_id TEXT NOT NULL, revision INTEGER NOT NULL,
                digest TEXT NOT NULL, payload TEXT NOT NULL, valid INTEGER NOT NULL,
                status TEXT NOT NULL, reason TEXT NOT NULL, source_context TEXT NOT NULL,
                UNIQUE(owner,correction_id,revision));
        ''')

    def close(self):
        self.db.close()

    def history(self, owner):
        return [dict(r) for r in self.db.execute(
            'SELECT * FROM revisions WHERE owner=? ORDER BY seq', (owner,))]

    def _rebuild(self, owner):
        messages = {r['target']: json.loads(r['payload']) for r in self.db.execute(
            'SELECT * FROM messages WHERE owner=?', (owner,))}
        labels = {k: v['label'] for k, v in messages.items()}
        # Latest applicable revision wins within each entry's original order.
        # Unresolved edits remain visible while a prior applicable revision survives.
        revisions = {}
        for row in self.db.execute('SELECT * FROM revisions WHERE owner=? ORDER BY seq', (owner,)):
            if row['valid']:
                revisions.setdefault(row['correction_id'], []).append(row)
        active, selected = {}, {}
        for cid, candidates in revisions.items():
            for position in range(len(candidates) - 1, -1, -1):
                row = candidates[position]
                record = json.loads(row['payload'])
                target, action = record['target'], record['action']
                reason = ''
                if target not in messages:
                    reason = 'unknown target for configured owner'
                elif action == 'undo':
                    reference = record['undo_correction']
                    prior = active.get(reference)
                    if not prior or prior['target'] != target:
                        reason = 'undo target is not an active prior correction for this message'
                    else:
                        del active[reference]
                        self.db.execute("UPDATE revisions SET status='undone',reason=? WHERE seq=?",
                                        ('undone by ' + cid, selected[reference]))
                else:
                    active[cid] = record
                self.db.execute('UPDATE revisions SET status=?,reason=? WHERE seq=?',
                                ('unresolved' if reason else 'applied', reason, row['seq']))
                if reason:
                    continue
                selected[cid] = row['seq']
                for earlier in candidates[:position]:
                    self.db.execute("UPDATE revisions SET status='superseded',reason='replaced by a later valid revision' WHERE seq=?",
                                    (earlier['seq'],))
                break
        for record in active.values():
            labels[record['target']] = record['action']
        return labels

    def ingest(self, owner, records, messages):
        """Atomically ingest records and explicit source registry, returning current views.

        Registry: {message_id: {owner, label, source_revision, provenance}}.
        The configured owner is the trusted identity; Doc Owner is only checked.
        Unknown targets are recorded unresolved and retried when source arrives.
        Revisions retain original entry order; source revisions preserve overrides.
        Omitted entries remain durable: reversal requires an explicit undo record.
        The current source context is returned; ingest-time context is audited.
        """
        if not isinstance(owner, str) or not owner.strip() or len(owner) > 128:
            raise ValueError('invalid configured owner')
        records = list(records)
        if len(records) > MAX_RECORDS or not all(isinstance(r, dict) for r in records):
            raise ValueError('invalid correction records')
        if not isinstance(messages, dict) or len(messages) > 10000:
            raise ValueError('invalid message registry')
        for target, source in messages.items():
            if (not isinstance(target, str) or not target or len(target) > 256
                    or not isinstance(source, dict) or source.get('owner') != owner
                    or source.get('label') not in LABELS
                    or not isinstance(source.get('source_revision'), str) or not source['source_revision']
                    or not isinstance(source.get('provenance'), str) or not source['provenance']
                    or len(source['source_revision']) > 4096 or len(source['provenance']) > 4096):
                raise ValueError('registry requires owner, label, source revision and provenance')
        if len(_canonical(messages).encode('utf-8')) > MAX_TEXT:
            raise ValueError('message registry exceeds input bounds')
        encoded = [_canonical(r) for r in records]
        if sum(len(v.encode('utf-8')) for v in encoded) > MAX_TEXT:
            raise ValueError('correction records exceed input bounds')
        ids = [r.get('correction_id', 'malformed-' + hashlib.sha256(p.encode()).hexdigest()[:24])
               for r, p in zip(records, encoded)]
        if not all(isinstance(cid, str) for cid in ids):
            raise ValueError('correction IDs must be text')
        collisions = {cid for cid in ids if len({p for c, p in zip(ids, encoded) if c == cid}) > 1}
        changed, results = 0, []
        with self.db:
            before = {r['seq']: (r['status'], r['reason']) for r in self.history(owner)}
            for target, source in messages.items():
                payload = _canonical(source)
                previous = self.db.execute('SELECT payload FROM messages WHERE owner=? AND target=?',
                                           (owner, target)).fetchone()
                if not previous or previous[0] != payload:
                    self.db.execute('INSERT OR REPLACE INTO messages VALUES (?,?,?)', (owner, target, payload))
                    changed += 1
            seen = set()
            for record, payload, cid in zip(records, encoded, ids):
                if cid in seen:
                    continue
                seen.add(cid)
                error = 'duplicate correction ID collision in document' if cid in collisions else _record_error(owner, record)
                # Hash the collision state too so resolving duplicates creates a new revision.
                digest = hashlib.sha256((payload + (error or '')).encode()).hexdigest()
                previous = self.db.execute('SELECT * FROM revisions WHERE owner=? AND correction_id=? ORDER BY revision DESC LIMIT 1',
                                           (owner, cid)).fetchone()
                is_new = not previous or previous['digest'] != digest
                revision = (previous['revision'] + 1 if previous else 1) if is_new else previous['revision']
                if is_new:
                    target = record.get('target')
                    source = self.db.execute('SELECT payload FROM messages WHERE owner=? AND target=?',
                                             (owner, target)).fetchone() if isinstance(target, str) else None
                    context = source[0] if source else '{}'
                    self.db.execute('INSERT INTO revisions(owner,correction_id,revision,digest,payload,valid,status,reason,source_context) VALUES (?,?,?,?,?,?,?,?,?)',
                                    (owner, cid, revision, digest, payload, not error, 'unresolved' if error else 'recorded', error or '', context))
                    changed += 1
                results.append({'correction_id': cid, 'revision': revision, 'changed': is_new})
            labels = self._rebuild(owner)
            after = self.history(owner)
            changed += sum(1 for r in after if r['seq'] in before
                           and (r['status'], r['reason']) != before[r['seq']])
            for result in results:
                row = next(r for r in after if r['correction_id'] == result['correction_id'] and r['revision'] == result['revision'])
                result.update(status=row['status'], reason=row['reason'])
                target = json.loads(row['payload']).get('target')
                source = self.db.execute('SELECT payload FROM messages WHERE owner=? AND target=?',
                                         (owner, target)).fetchone() if isinstance(target, str) else None
                result['source_context'] = json.loads(source[0]) if source else {}
        return {'changed': changed, 'statuses': results, 'effective_labels': labels,
                'views': {'private': sorted(k for k, v in labels.items() if v != 'spam'),
                          'work': sorted(k for k, v in labels.items() if v == 'work'),
                          'personal': sorted(k for k, v in labels.items() if v == 'personal')}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ledger', required=True)
    parser.add_argument('--owner', required=True)
    parser.add_argument('--messages', required=True)
    parser.add_argument('--corrections', required=True)
    args = parser.parse_args()
    def read_bounded(path):
        with open(path, 'rb') as stream:
            data = stream.read(MAX_TEXT + 1)
        if len(data) > MAX_TEXT:
            raise ValueError('input file exceeds bounds')
        return data.decode('utf-8')
    ledger = CorrectionLedger(args.ledger)
    try:
        result = ledger.ingest(args.owner, parse_corrections(read_bounded(args.corrections)),
                               json.loads(read_bounded(args.messages)))
        print(json.dumps(result, indent=2))
    finally:
        ledger.close()


if __name__ == '__main__':
    main()
