"""Read-only, owner/thread-scoped current archive snapshot for Drive publishing."""
import hashlib
import json
from pathlib import Path
import sqlite3
from urllib.parse import quote


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def snapshot(root, owner, conversations, start_date, *, phone_spam_policy=None):
    path = Path(root).expanduser() / 'archive.sqlite3'
    if path.is_symlink() or not path.is_file():
        raise ValueError('archive database must be an existing regular file')
    db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    try:
        db.execute('BEGIN')
        from phone_spam import excluded_conversations
        excluded_threads = excluded_conversations(db, owner, phone_spam_policy)
        excluded_ids = set()
        excluded_images = []
        messages = []
        message_gaps = []
        for row in db.execute('SELECT source,id,payload,imported_at FROM messages WHERE owner=?', (owner,)):
            value = json.loads(row['payload'])
            if row['source'] == 'google-messages' and value['conversation_id'] in excluded_threads:
                sid = 'archive://' + '/'.join(quote(x, safe='') for x in (owner, row['source'], row['id']))
                excluded_ids.add(sid)
                continue
            if (conversations is not None and value['conversation_id'] not in conversations) or value['timestamp'][:10] < start_date:
                continue
            sid = 'archive://' + '/'.join(quote(x, safe='') for x in (owner, row['source'], row['id']))
            revision_value = dict(value)
            revision_value['attachments'] = [{k: v for k, v in a.items() if k != 'local_path'}
                                             for a in value.get('attachments', [])]
            friendly = 'M' + row['id'] if row['source'] == 'google-messages' else sid
            if row['source'] == 'apple-messages':
                metadata = value.get('apple_metadata', {})
                friendly = 'A' + hashlib.sha256(sid.encode()).hexdigest()[:16]
                if (metadata.get('record_type') != 'message' or metadata.get('is_unsent') or metadata.get('is_deleted') or
                        metadata.get('retraction_metadata_present') or
                        (metadata.get('body_status') not in ('plain_text', 'attributed_body_decoded') and
                         not (metadata.get('body_status') == 'blank' and value.get('attachments')))):
                    message_gaps.append({'source_id': sid, 'friendly_id': friendly,
                        'record_type': metadata.get('record_type', 'unknown'),
                        'body_status': metadata.get('body_status', 'unknown')})
                    continue
                # Receipt/sync bookkeeping must not spend AI tokens again. Current
                # content and substantive edit/retraction metadata define a revision.
                revision_value = {k: value.get(k) for k in
                    ('text', 'timestamp', 'sender', 'direction', 'conversation_id', 'attachments')}
                revision_value['attachments'] = [{k: v for k, v in a.items() if k != 'local_path'}
                                                 for a in value.get('attachments', [])]
                revision_value['apple_metadata'] = {k: metadata.get(k) for k in
                    ('record_type', 'is_unsent', 'date_edited', 'date_retracted', 'service')}
            messages.append(dict(source_id=sid, revision=fingerprint(revision_value), owner=owner,
                conversation_id=value['conversation_id'], timestamp=value['timestamp'],
                text=value['text'], kind='message', origin_ids=[], sender=value['sender'],
                friendly_id=friendly,
                imported_at=row['imported_at'],
                attachments=value.get('attachments', []),
                attachments_available=any(a.get('capture_status') == 'captured'
                    for a in value.get('attachments', []) if isinstance(a, dict)),
                direction=value.get('direction', 'unknown'),
                conversation_name=value.get('conversation_name') or '',
                sender_name=value.get('sender_name') or ('self' if value.get('direction') in ('sent', 'outgoing') else ''),
                timestamp_known=value.get('timestamp_ms', 1) != 0))
        if excluded_threads:
            # A stable source ID stays excluded even if a later payload moves it
            # into another thread. Do not publish an ID scheduled for withdrawal.
            for row in db.execute("SELECT id,payload FROM revisions WHERE owner=? AND source='google-messages'", (owner,)):
                value = json.loads(row['payload'])
                if value['conversation_id'] in excluded_threads:
                    excluded_ids.add('archive://' + '/'.join(quote(x, safe='') for x in (owner, 'google-messages', row['id'])))
            messages = [m for m in messages if m['source_id'] not in excluded_ids]
            for row in db.execute("SELECT id,payload FROM revisions WHERE owner=? AND source='google-messages'", (owner,)):
                sid = 'archive://' + '/'.join(quote(x, safe='') for x in (owner, 'google-messages', row['id']))
                if sid not in excluded_ids:
                    continue
                value = json.loads(row['payload'])
                if value.get('attachments'):
                    excluded_images.append({'source_id': sid, 'attachments': value['attachments']})
        messages.sort(key=lambda x: (x['timestamp'], x['source_id']))
        by_id = {m['source_id']: m for m in messages}
        transcripts = []
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        has_looms = {'loom_revisions', 'loom_queue', 'loom_origins'} <= tables
        for row in (db.execute('SELECT r.* FROM loom_revisions r JOIN loom_queue q ON r.owner=q.owner AND r.video_id=q.video_id AND r.revision=q.current_revision WHERE r.owner=?', (owner,)) if has_looms else []):
            origins = ['archive://' + '/'.join(quote(x, safe='') for x in (owner, r['source'], r['message_id']))
                for r in db.execute('SELECT source,message_id FROM loom_origins WHERE owner=? AND video_id=?', (owner, row['video_id']))]
            origins = sorted(set(origins) & by_id.keys())
            if not origins:
                continue
            origin = by_id[origins[0]]
            transcripts.append(dict(source_id='archive://' + quote(owner, safe='') + '/loom/' + row['video_id'],
                revision=str(row['revision']) + ':' + row['semantic_sha256'], owner=owner,
                conversation_id=origin['conversation_id'], timestamp=origin['timestamp'], text=row['text'],
                kind='loom', origin_ids=origins, friendly_id='Loom-' + row['video_id'],
                phrases=json.loads(row['phrases']), captured_at=row['captured_at'], source_url=row['source_url']))
        gaps = []
        for queue in (db.execute('SELECT video_id,status,current_revision FROM loom_queue WHERE owner=?', (owner,)) if has_looms else []):
            if queue['current_revision'] is not None:
                continue
            origins = ['archive://' + '/'.join(quote(x,safe='') for x in (owner,r['source'],r['message_id']))
                for r in db.execute('SELECT source,message_id FROM loom_origins WHERE owner=? AND video_id=?',(owner,queue['video_id']))]
            origins = sorted(set(origins) & by_id.keys())
            if origins:
                gaps.append({'video_id':queue['video_id'],'status':queue['status'],'origin_ids':origins})
        latest_import = db.execute('SELECT MAX(imported_at) FROM imports WHERE owner=?', (owner,)).fetchone()[0]
        return {'phone_spam_generation': fingerprint(sorted(excluded_threads)),
                'phone_spam_source_ids': sorted(excluded_ids), 'phone_spam_images': excluded_images,
                'phone_spam_conversations': len(excluded_threads), 'message_gaps': message_gaps, 'loom_gaps': gaps, 'sources': messages + sorted(transcripts, key=lambda x: x['source_id']),
                'latest_import': latest_import, 'latest_scoped_message': max((m['timestamp'] for m in messages), default=None),
                'coverage': ('Selected threads only.' if conversations is not None else 'All currently captured owner conversations.') +
                    ' Import freshness does not prove full phone coverage. Image availability is reported per attachment; missing media may remain.'}
    finally:
        db.close()
