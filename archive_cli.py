#!/usr/bin/env python3
"""Private local archive, Loom capture, search and verified snapshots."""
import argparse
from contextlib import closing
import datetime as dt
import json
import os
from pathlib import Path
import sqlite3
import tempfile

from storage import Archive, _owner
from loom_capture import LoomCapture
from attachment_capture import AttachmentCapture

DEFAULT_ROOT = Path.home() / '.local/share/minbox-text-archive'


def import_gmkit(archive, owner, database, *, capture_options=None):
    from phone_spam import owner_operation, sync_observations
    database = database.resolve(strict=True)
    archive.init(owners=(owner,))
    with owner_operation(archive.root, owner):
        phone = sync_observations(archive, owner, database)
        result = _import_gmkit(archive, owner, database, capture_options=capture_options)
        result['phone_spam'] = phone
        return result


def _import_gmkit(archive, owner, database, *, capture_options=None):
    """Read-only snapshot of gmkit's captured rows; no phone access or auth copy."""
    database = database.resolve(strict=True)
    capture = AttachmentCapture(archive.root, owner, database.parent, **(capture_options or {}))
    with capture.session(), closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as db:
        db.row_factory = sqlite3.Row
        db.execute('BEGIN')
        rows = db.execute('''SELECT m.*, c.name AS conversation_name,
            c.participants_json, co.name AS sender_name, co.e164 AS sender_number FROM messages m
            LEFT JOIN conversations c ON c.conversation_id=m.conversation_id
            LEFT JOIN contacts co ON co.participant_id=m.sender_id
            ORDER BY m.timestamp_ms DESC, m.message_id DESC''').fetchall()
        payload = []
        rows = sorted(rows, key=lambda row: (*capture.priority(row['message_id'], row['media_id']),
                                             -row['timestamp_ms']))
        for row in rows:
            m = dict(row)
            # Keep credentials, media decryption keys and raw protocol out of derived exports.
            for key in ('decryption_key', 'raw_proto'):
                m.pop(key, None)
            stamp = dt.datetime.fromtimestamp(m['timestamp_ms'] / 1000, dt.timezone.utc).isoformat()
            attachments = []
            if m.get('media_id') or str(m.get('mime_type') or '').startswith('image/'):
                attachments = capture.capture_many(m['message_id'], m.get('media_id'), m.get('mime_type'))
            payload.append({**m, 'id': m['message_id'], 'conversation_id': m['conversation_id'],
                            'timestamp': stamp, 'sender': m['sender_id'] or 'unknown-sender', 'text': m.get('body') or '',
                            'direction': 'outgoing' if m['is_from_me'] else 'incoming',
                            'type': 'unknown SMS/MMS/RCS', 'attachments': attachments})
    payload.sort(key=lambda m: (m['timestamp'], str(m['id'])))
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / 'gmkit-export.json'
        source.write_text(json.dumps(payload), encoding='utf-8')
        source.chmod(0o600)
        result = archive.import_messages(owner, 'google-messages', source)
    result['attachment_capture'] = {**capture.stats, 'errors': capture.errors}
    result['coverage'] = 'Only rows already captured by gmkit; complete history/media not verified'
    return result


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, default=DEFAULT_ROOT)
    commands = p.add_subparsers(dest='command', required=True)
    initialize = commands.add_parser('init')
    initialize.add_argument('--owner', type=_owner)
    commands.add_parser('status')
    imp = commands.add_parser('import')
    imp.add_argument('owner', type=_owner); imp.add_argument('source'); imp.add_argument('file', type=Path)
    gm = commands.add_parser('import-gmkit')
    gm.add_argument('owner', type=_owner); gm.add_argument('database', type=Path)
    search = commands.add_parser('search')
    search.add_argument('owner', type=_owner); search.add_argument('query')
    contacts = commands.add_parser('contacts'); contacts.add_argument('owner', type=_owner)
    loom = commands.add_parser('loom-pending'); loom.add_argument('owner', type=_owner)
    commands.add_parser('loom-capture')
    loom_status = commands.add_parser('loom-status')
    loom_status.add_argument('--owner', type=_owner)
    snap = commands.add_parser('snapshot'); snap.add_argument('destination', type=Path)
    restore = commands.add_parser('restore')
    restore.add_argument('snapshot', type=Path); restore.add_argument('destination', type=Path)
    return p


def main():
    os.umask(0o077)
    p = parser(); args = p.parse_args()
    try:
        archive = Archive(args.root)
        if args.command == 'restore':
            result = {'restored_archive': str(Archive.restore(args.snapshot, args.destination).root)}
        else:
            archive.init(owners=(args.owner,)) if args.command == 'init' and args.owner else archive.init()
            if args.command == 'init': result = {'archive': str(args.root), 'owners': archive.owner_names()}
            elif args.command == 'status': result = archive.status()
            elif args.command == 'import': result = archive.import_messages(args.owner, args.source, args.file)
            elif args.command == 'import-gmkit': result = import_gmkit(archive, args.owner, args.database)
            elif args.command == 'snapshot': result = str(archive.snapshot(args.destination))
            elif args.command == 'search':
                result = [m for m in archive.messages(args.owner) if args.query.casefold() in m['text'].casefold()]
                result.extend(t for t in LoomCapture(archive).transcripts(args.owner) if args.query.casefold() in t['text'].casefold())
            elif args.command == 'contacts':
                found = {}
                for m in archive.messages(args.owner):
                    found[m['sender']] = {'id': m['sender'], 'name': m.get('sender_name', ''),
                                          'number': m.get('sender_number', '')}
                result = list(found.values())
            elif args.command == 'loom-capture':
                result = LoomCapture(archive).run()
                print(json.dumps(result, indent=2))
                return 1 if result['operational_failures'] else 0
            elif args.command == 'loom-status': result = LoomCapture(archive).status(args.owner)
            elif args.command == 'loom-pending':
                capture = LoomCapture(archive)
                capture.discover()
                with archive._connect() as db:
                    result = [dict(r) for r in db.execute('SELECT video_id,source_url AS url,status FROM loom_queue WHERE owner=? AND status!=?', (args.owner, 'captured'))]
        print(json.dumps(result, indent=2, default=str))
    except (ValueError, OSError, sqlite3.Error, json.JSONDecodeError) as error:
        p.exit(1, f'Error: {error}\n')


if __name__ == '__main__':
    raise SystemExit(main())
