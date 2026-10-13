"""Read-only, fixture-tested Mac Messages collector; live Mac coverage is unverified.

Apple dates follow ReagentX/imessage-exporter util/dates.rs (2001 UTC epoch,
seconds or nanoseconds). Optional pytypedstream parses attributed bodies as data;
only known attributed-string roots and direct NSString bodies are accepted.
No native unarchiver, pickle, heuristic string slicing, edits or
unsend reconstruction. Sources: github.com/ReagentX/imessage-exporter and
 github.com/dgelessus/python-typedstream (types/foundation.py, archiving.py).
"""
from __future__ import annotations

import argparse
import base64
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import importlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time

from storage import Archive

DEFAULT_DATABASE = Path('~/Library/Messages/chat.db')
MAX_BODY_BYTES = 512 * 1024
MAX_TEXT_CHARS = 256 * 1024
DECODER_POLICY = 'attributed-body-v1'
MAX_MESSAGES = 100000
MAX_BYTES = 64 * 1024 * 1024
EPOCH = datetime(2001, 1, 1, tzinfo=timezone.utc)
REQUIRED = {'message': {'guid', 'date', 'is_from_me', 'handle_id'},
            'handle': {'id'}, 'chat': {'guid', 'chat_identifier'},
            'chat_message_join': {'message_id', 'chat_id'}}
OPTIONAL_MESSAGE = {'text', 'attributedBody', 'service', 'associated_message_guid',
                    'associated_message_type', 'type', 'item_type', 'group_action_type',
                    'date_edited', 'date_read', 'date_delivered', 'date_retracted',
                    'is_unsent', 'is_deleted', 'message_summary_info', 'thread_originator_guid'}
KNOWN_TABLES = set(REQUIRED) | {'chat_handle_join', 'attachment', 'message_attachment_join'}
ACCESS_REASON = ('Messages database is unavailable. On the authorized Mac, allow Full Disk Access '
                 'for the collector host and check Messages/iCloud sync and database access.')


class MacMessagesError(RuntimeError):
    def __init__(self, message, error_code='read_failed'):
        super().__init__(message)
        self.error_code = error_code


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def _hash(value):
    return hashlib.sha256(_json(value).encode('utf-8')).hexdigest()


def apple_timestamp(value):
    """Return UTC ISO timestamp or None for unset/corrupt/out-of-range values."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = Decimal(str(value))
        if not number.is_finite() or number <= 0:
            return None
        if number >= 1_000_000_000_000:
            number /= 1_000_000_000
        stamp = EPOCH + timedelta(microseconds=int(number * 1_000_000))
        if stamp.year > 2100:
            return None
        return stamp.isoformat()
    except (InvalidOperation, ValueError, OverflowError):
        return None


def decode_attributed_body(blob):
    """Return (text, status), never raw decoder exceptions or guessed strings.

    Preflight uses the library's iterative data reader before high-level parsing,
    rejecting unknown object classes and excessive event/array/depth counts.
    """
    if not isinstance(blob, bytes) or not blob:
        return '', 'blank'
    if len(blob) > MAX_BODY_BYTES:
        return '', 'attributed_body_too_large'
    try:
        typedstream = importlib.import_module('typedstream')
    except ImportError:
        return '', 'decoder_unavailable'
    try:
        stream = importlib.import_module('typedstream.stream')
        archiving = importlib.import_module('typedstream.archiving')
        foundation = importlib.import_module('typedstream.types.foundation')
        allowed = {b'NSAttributedString', b'NSMutableAttributedString', b'NSObject',
                   b'NSString', b'NSMutableString', b'NSDictionary', b'NSMutableDictionary',
                   b'NSNumber', b'NSValue', b'NSArray', b'NSMutableArray', b'NSData', b'NSMutableData'}
        depth, count, first_class = 0, 0, None
        with stream.TypedStreamReader.from_data(blob) as reader:
            for event in reader:
                count += 1
                if count > 20000:
                    raise ValueError()
                event_name = type(event).__name__
                if event_name == 'SingleClass':
                    name = event.name
                    if first_class is None:
                        first_class = name
                    if name not in allowed:
                        raise ValueError()
                if event_name in {'BeginObject', 'BeginArray', 'BeginStruct'}:
                    depth += 1
                    if depth > 64:
                        raise ValueError()
                    if event_name == 'BeginArray' and event.length > 4096:
                        raise ValueError()
                elif event_name in {'EndObject', 'EndArray', 'EndStruct'}:
                    depth -= 1
        if first_class not in {b'NSAttributedString', b'NSMutableAttributedString'}:
            raise ValueError()
        root = typedstream.unarchive_from_data(blob)
        if type(root) is not archiving.GenericArchivedObject or root.clazz.name != first_class:
            raise ValueError()
        classes, clazz = [], root.clazz
        while clazz is not None:
            if clazz.version != 0:
                raise ValueError()
            classes.append(clazz.name)
            clazz = clazz.superclass
            if len(classes) > 3:
                raise ValueError()
        if classes not in ([b'NSAttributedString', b'NSObject'],
                           [b'NSMutableAttributedString', b'NSAttributedString', b'NSObject']):
            raise ValueError()
        if not root.contents or root.contents[0].encodings != [b'@'] or len(root.contents[0].values) != 1:
            raise ValueError()
        string = root.contents[0].values[0]
        # Exact types avoid the library's isinstance support for unknown subclasses.
        if type(string) not in (foundation.NSString, foundation.NSMutableString):
            raise ValueError()
        text = string.value
        if not isinstance(text, str) or len(text) > MAX_TEXT_CHARS:
            raise ValueError()
        return text, 'attributed_body_decoded'
    except Exception:
        return '', 'attributed_body_unsupported'


@contextmanager
def _snapshot(path):
    db = None
    try:
        requested = Path(path).expanduser().absolute()
        if not requested.is_file():
            raise MacMessagesError(ACCESS_REASON, 'database_unavailable')
        db = sqlite3.connect(requested.as_uri() + '?mode=ro', uri=True, timeout=5)
        db.row_factory = sqlite3.Row
        db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 2 * MAX_BODY_BYTES + 4096)
        deadline = time.monotonic() + 30
        db.set_progress_handler(lambda: int(time.monotonic() > deadline), 10000)
        db.execute('PRAGMA query_only=ON')
        db.execute('PRAGMA trusted_schema=OFF')
        db.execute('BEGIN')
        yield db
    except MacMessagesError:
        raise
    except sqlite3.Error as exc:
        if getattr(exc, 'sqlite_errorcode', None) in (sqlite3.SQLITE_TOOBIG, sqlite3.SQLITE_INTERRUPT):
            raise MacMessagesError('Messages read exceeds size or time bounds; no import performed.', 'bounds_exceeded') from None
        raise MacMessagesError(ACCESS_REASON, 'database_unavailable') from None
    except OSError:
        raise MacMessagesError(ACCESS_REASON, 'database_unavailable') from None
    finally:
        if db is not None:
            db.close()


def _schema(db):
    tables = {r['name'] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    schema = {}
    for table in KNOWN_TABLES & tables:
        schema[table] = {r['name'] for r in db.execute('PRAGMA table_info("' + table + '")')}
    if any(table not in schema or not fields <= schema[table] for table, fields in REQUIRED.items()):
        raise MacMessagesError('Unsupported Messages schema: required tables or columns are missing.', 'unsupported_schema')
    if not {'text', 'attributedBody'} & schema['message']:
        raise MacMessagesError('Unsupported Messages schema: no recognized body column.', 'unsupported_schema')
    try:
        for table in ('message', 'handle', 'chat'):
            db.execute('SELECT ROWID FROM "' + table + '" LIMIT 0')
    except sqlite3.Error:
        raise MacMessagesError('Unsupported Messages schema: row identity is unavailable.', 'unsupported_schema') from None
    return schema


def _inspection(db, schema):
    return {'supported': True, 'status': 'checked', 'source': 'apple-messages',
            'database_messages': db.execute('SELECT COUNT(*) FROM message').fetchone()[0],
            'database_chats': db.execute('SELECT COUNT(*) FROM chat').fetchone()[0],
            'schema': {t: sorted(c & (REQUIRED.get(t, set()) | OPTIONAL_MESSAGE |
                                      {'chat_id', 'handle_id', 'message_id', 'attachment_id', 'guid', 'mime_type', 'uti', 'total_bytes', 'transfer_name'}))
                       for t, c in sorted(schema.items())},
            'coverage': 'Local Messages database only; phone sync and history completeness are unverified.',
            'attachments': 'metadata only; no attachment files read',
            'edits': 'observed metadata only; edit and unsend history is not reconstructed',
            'live_mac_verified': False}


def inspect_database(path=DEFAULT_DATABASE):
    with _snapshot(path) as db:
        return _inspection(db, _schema(db))


def _rows(db, query, limit):
    byte_count = 0
    for count, row in enumerate(db.execute(query + ' LIMIT ?', (limit + 1,)), 1):
        byte_count += len(_json(dict(row)).encode('utf-8'))
        if count > limit or byte_count > MAX_BYTES:
            raise MacMessagesError('Messages metadata exceeds configured read bound; no import performed.', 'bounds_exceeded')
        yield row


def _string(value, limit=1024):
    return value if isinstance(value, str) and value.strip() and len(value) <= limit else None


def _read_messages(path=DEFAULT_DATABASE, *, max_messages=MAX_MESSAGES, max_bytes=MAX_BYTES, body_cache=None, attachment_paths=False):
    if type(max_messages) is not int or not 1 <= max_messages <= 1000000 or type(max_bytes) is not int or not 1024 <= max_bytes <= 512 * 1024 * 1024:
        raise MacMessagesError('Invalid Messages read bounds.', 'invalid_configuration')
    with _snapshot(path) as db:
        schema = _schema(db)
        report = _inspection(db, schema)
        gaps = dict(invalid_timestamps=0, missing_message_ids=0, missing_conversations=0,
                    fallback_conversations=0, unavailable_bodies=0, blank_bodies=0,
                    decoded_bodies=0, reused_decoded_bodies=0, oversized_bodies=0, invalid_optional_dates=0,
                    missing_senders=0, edited_metadata=0, reaction_records=0, system_records=0)
        handles = {r['row_id']: _string(r['id']) for r in _rows(db, 'SELECT ROWID AS row_id,id FROM handle', max_messages * 4)}
        chats = {}
        fallback_counts = {}
        for row in _rows(db, 'SELECT ROWID AS row_id,guid,chat_identifier FROM chat', max_messages * 4):
            guid, identifier = _string(row['guid']), _string(row['chat_identifier'])
            cid = guid or ('apple-chat-identifier:' + _hash(identifier) if identifier else None)
            chats[row['row_id']] = (cid, not bool(guid))
            if cid and not guid:
                fallback_counts[cid] = fallback_counts.get(cid, 0) + 1
        memberships = {}
        for row in _rows(db, 'SELECT DISTINCT message_id,chat_id FROM chat_message_join', max_messages * 8):
            memberships.setdefault(row['message_id'], set()).add(row['chat_id'])
        participants = {}
        if {'chat_id', 'handle_id'} <= schema.get('chat_handle_join', set()):
            for row in _rows(db, 'SELECT DISTINCT chat_id,handle_id FROM chat_handle_join', max_messages * 8):
                participant = handles.get(row['handle_id'])
                if participant:
                    participants.setdefault(row['chat_id'], set()).add(participant)
        attachments = {}
        attachment_support = {'message_id', 'attachment_id'} <= schema.get('message_attachment_join', set()) and 'attachment' in schema
        if attachment_support:
            fields = schema['attachment'] & {'guid', 'mime_type', 'uti', 'total_bytes', 'transfer_name'}
            if attachment_paths and 'filename' in schema['attachment']:
                fields.add('filename')
            projection = ','.join('a."' + f + '" AS "' + f + '"' for f in sorted(fields))
            query = 'SELECT DISTINCT j.message_id,a.ROWID AS attachment_row' + (',' + projection if projection else '') + ' FROM message_attachment_join j JOIN attachment a ON a.ROWID=j.attachment_id'
            for row in _rows(db, query, max_messages * 8):
                meta = {'available': False, 'capture': 'metadata_only'}
                for field in fields:
                    value = row[field]
                    if field == 'total_bytes':
                        if type(value) is int and value >= 0:
                            meta[field] = value
                    elif field == 'filename':
                        if _string(value):
                            meta['_source_path'] = value
                    elif _string(value):
                        meta['name' if field == 'transfer_name' else field] = value.replace('\\', '/').rsplit('/', 1)[-1] if field == 'transfer_name' else value
                attachments.setdefault(row['message_id'], []).append(meta)
        report['attachment_metadata_supported'] = attachment_support
        columns = REQUIRED['message'] | (schema['message'] & OPTIONAL_MESSAGE)
        projection = []
        for column in sorted(columns):
            if column in {'text', 'attributedBody', 'message_summary_info'}:
                projection.append('length(CAST("' + column + '" AS BLOB)) AS "' + column + '_bytes"')
                projection.append('CASE WHEN length(CAST("' + column + '" AS BLOB)) <= ' + str(MAX_BODY_BYTES) + ' THEN "' + column + '" ELSE NULL END AS "' + column + '"')
            else:
                projection.append('"' + column + '"')
        cursor = db.execute('SELECT ROWID AS row_id,' + ','.join(projection) + ' FROM message ORDER BY ROWID LIMIT ?', (max_messages + 1,))
        records, identities, byte_count, seen_rows = [], {}, 0, 0
        for raw in cursor:
            seen_rows += 1
            if seen_rows > max_messages:
                raise MacMessagesError('Messages read exceeds configured row bound; no import performed.', 'bounds_exceeded')
            row = dict(raw)
            guid = _string(row['guid'])
            if not guid:
                gaps['missing_message_ids'] += 1
                continue
            timestamp = apple_timestamp(row['date'])
            if timestamp is None:
                gaps['invalid_timestamps'] += 1
                continue
            associated_type = row.get('associated_message_type')
            reaction = type(associated_type) is int and (associated_type == 1000 or 2000 <= associated_type <= 2007 or 3000 <= associated_type <= 3007)
            system = not reaction and (associated_type not in (None, 0, 2, 3) or any(row.get(k) not in (None, 0) for k in ('type', 'item_type', 'group_action_type')) or row.get('is_unsent') == 1 or row.get('is_deleted') == 1 or row.get('date_retracted') not in (None, 0))
            record_type = 'reaction' if reaction else 'system' if system else 'message'
            meta = {'guid': guid, 'record_type': record_type,
                    'date_precision': 'nanoseconds' if row['date'] >= 1_000_000_000_000 else 'seconds',
                    'apple_date': row['date']}
            for flag in ('is_unsent', 'is_deleted'):
                if row.get(flag) == 1:
                    meta[flag] = True
            if row.get('date_retracted') not in (None, 0):
                meta['retraction_metadata_present'] = True
            for field in ('associated_message_guid', 'thread_originator_guid', 'service'):
                if _string(row.get(field)):
                    meta[field] = row[field]
            if associated_type is not None and type(associated_type) is int:
                meta['associated_message_type'] = associated_type
            for field in ('date_edited', 'date_read', 'date_delivered', 'date_retracted'):
                value = row.get(field)
                if value not in (None, 0):
                    converted = apple_timestamp(value)
                    meta[field] = converted
                    if converted is None:
                        gaps['invalid_optional_dates'] += 1
            for field in ('attributedBody', 'message_summary_info'):
                data = row.get(field)
                size = row.get(field + '_bytes') or 0
                if size:
                    meta[field + '_bytes'] = size
                    meta[field + '_sha256'] = hashlib.sha256(data).hexdigest() if isinstance(data, bytes) else None
            if row.get('date_edited') not in (None, 0) or row.get('message_summary_info_bytes'):
                meta['edit_history_status'] = 'metadata_only'
                gaps['edited_metadata'] += 1
            text = row.get('text') if isinstance(row.get('text'), str) else ''
            if record_type != 'message':
                text, body_status = '', 'non_message_event'
                gaps['reaction_records' if reaction else 'system_records'] += 1
            elif len(text) > MAX_TEXT_CHARS:
                text, body_status = '', 'text_too_large'
                gaps['oversized_bodies'] += 1
            elif text.strip():
                body_status = 'plain_text'
            elif row.get('attributedBody_bytes'):
                cached = (body_cache or {}).get(meta.get('attributedBody_sha256'))
                if isinstance(cached, str) and len(cached) <= MAX_TEXT_CHARS:
                    text, body_status = cached, 'attributed_body_decoded'
                    gaps['reused_decoded_bodies'] += 1
                else:
                    text, body_status = decode_attributed_body(row.get('attributedBody'))
                if body_status == 'attributed_body_decoded':
                    meta['decoder_policy'] = DECODER_POLICY
                if row['attributedBody_bytes'] > MAX_BODY_BYTES:
                    body_status = 'attributed_body_too_large'
                gaps['decoded_bodies' if body_status == 'attributed_body_decoded' else 'unavailable_bodies'] += 1
            elif row.get('text_bytes', 0) and row['text_bytes'] > MAX_BODY_BYTES:
                text, body_status = '', 'text_too_large'
                gaps['oversized_bodies'] += 1
            else:
                text, body_status = '', 'blank'
                gaps['blank_bodies'] += 1
            meta['body_status'] = body_status
            direction = 'sent' if row['is_from_me'] == 1 else 'received' if row['is_from_me'] == 0 else 'unknown'
            sender = 'self' if direction == 'sent' else handles.get(row['handle_id'])
            if not sender:
                sender = 'unknown'
                gaps['missing_senders'] += 1
            valid_chats = []
            for chat_id in sorted(memberships.get(row['row_id'], [])):
                cid, fallback = chats.get(chat_id, (None, False))
                if cid and (not fallback or fallback_counts[cid] == 1):
                    valid_chats.append((chat_id, cid, fallback))
            if not valid_chats:
                gaps['missing_conversations'] += 1
                continue
            for chat_id, cid, fallback in valid_chats:
                record = {'id': 'apple-message:' + _hash([guid, cid]), 'conversation_id': cid,
                          'timestamp': timestamp, 'sender': sender, 'direction': direction, 'text': text,
                          'participants': sorted(participants.get(chat_id, set())),
                          'attachments': sorted(attachments.get(row['row_id'], []), key=_json),
                          'apple_metadata': dict(meta, conversation_identity='chat_identifier' if fallback else 'chat_guid'),
                          # Private, opaque source evidence permits a future decoder
                          # repair even after Apple's live row has changed. Never AI input.
                          'source_blobs': {field: {'encoding': 'base64', 'data': base64.b64encode(row[field]).decode('ascii')}
                                           for field in ('attributedBody', 'message_summary_info')
                                           if isinstance(row.get(field), bytes) and 0 < len(row[field]) <= MAX_BODY_BYTES}}
                if record_type != 'message' and isinstance(row.get('text'), str):
                    record['source_event_text'] = row['text']
                prior = identities.get(record['id'])
                if prior is not None:
                    if prior != record:
                        raise MacMessagesError('Conflicting Messages identities; no import performed.', 'identity_conflict')
                    continue
                identities[record['id']] = record
                byte_count += len(_json(record).encode('utf-8'))
                if byte_count > max_bytes:
                    raise MacMessagesError('Messages read exceeds configured byte bound; no import performed.', 'bounds_exceeded')
                records.append(record)
                if fallback:
                    gaps['fallback_conversations'] += 1
        report.update(status='read', examined_rows=seen_rows, normalized_records=len(records), gaps=gaps,
                      health='partial' if any(gaps[k] for k in ('invalid_timestamps', 'missing_message_ids', 'missing_conversations', 'unavailable_bodies', 'blank_bodies', 'oversized_bodies')) else 'ready')
        return sorted(records, key=lambda r: (r['timestamp'], r['id'])), report


def read_messages(path=DEFAULT_DATABASE, *, max_messages=MAX_MESSAGES, max_bytes=MAX_BYTES, body_cache=None, attachment_paths=False):
    try:
        return _read_messages(path, max_messages=max_messages, max_bytes=max_bytes, body_cache=body_cache,
                              attachment_paths=attachment_paths)
    except MacMessagesError:
        raise
    except Exception:
        raise MacMessagesError('Messages data could not be normalized; private details withheld.', 'invalid_source_data') from None


def _status_path(path):
    path = Path(path).expanduser().absolute()
    if any(p.is_symlink() for p in (path, *path.parents)) or any((p / '.git').is_file() or (p / '.git' / 'HEAD').is_file() for p in path.parents):
        raise MacMessagesError('Collector status must be private and outside Git.', 'invalid_status_path')
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def capture_mac_images(records, root, owner, database, *, limit=20, existing=None):
    """Copy downloaded images only from this Messages database's attachment tree."""
    from attachment_capture import AttachmentCapture, FORMATS, store_image
    attachment_root = Path(database).expanduser().absolute().parent / 'Attachments'
    counts = {'captured': 0, 'unavailable': 0, 'deferred': 0}
    attempted = 0
    cache = AttachmentCapture(root, owner, attachment_root, ocr=False)
    prior = {a.get('media_id'): a for record in (existing or {}).values()
             for a in record.get('attachments', []) if a.get('capture_status') == 'captured'}
    for record in reversed(records):
        for attachment in record.get('attachments', []):
            filename = attachment.pop('_source_path', None)
            attachment['media_id'] = attachment.get('guid') or 'apple-attachment-' + _hash(attachment)
            attachment['capture_status'] = 'metadata'
            mime = attachment.get('mime_type', '')
            if not mime.startswith('image/'):
                continue
            if mime not in FORMATS:
                counts['unavailable'] += 1
                continue
            cached = prior.get(attachment['media_id'])
            if cached and cache._verified(cached):
                attachment.update(cached)
                counts['captured'] += 1
                continue
            attachment['capture_status'] = 'unavailable'
            if not filename:
                counts['unavailable'] += 1
                continue
            source = Path(filename).expanduser().absolute()
            try:
                source.relative_to(attachment_root)
                if (any(p.is_symlink() for p in (source, *source.parents)) or
                        not source.is_file() or source.stat().st_uid != os.getuid()):
                    raise ValueError('Image source unavailable')
                if attempted >= limit:
                    counts['deferred'] += 1
                    continue
                attempted += 1
                attachment.update(store_image(root, owner, source, mime))
                attachment.update(available=True, capture='captured')
                counts['captured'] += 1
            except (ValueError, OSError):
                counts['unavailable'] += 1
    return counts


def _write_status(path, status):
    path = _status_path(path)
    fd, temporary = tempfile.mkstemp(prefix='.mac-status-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as output:
            json.dump(status, output, sort_keys=True)
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def collect(database=DEFAULT_DATABASE, root=None, owner=None, *, check_only=False, status_file=None,
            max_messages=MAX_MESSAGES, max_bytes=MAX_BYTES):
    previous = {}
    if status_file:
        path = _status_path(status_file)
        try:
            if path.exists() and path.stat().st_mode & 0o777 != 0o600:
                raise MacMessagesError('Collector status must have private mode 600.', 'invalid_status_path')
            if path.exists() and path.stat().st_size <= 128 * 1024:
                previous = json.loads(path.read_text())
                if not isinstance(previous, dict):
                    previous = {}
        except (OSError, ValueError):
            previous = {}
    status = {'source': 'apple-messages', 'last_checked_at': datetime.now(timezone.utc).isoformat(),
              'last_success_at': previous.get('last_success_at') if previous.get('owner') == owner else None,
              'owner': owner}
    try:
        if type(max_messages) is not int or max_messages < 1 or type(max_bytes) is not int or max_bytes < 1024:
            raise MacMessagesError('Invalid Messages read bounds.', 'invalid_configuration')
        if check_only:
            inspected = inspect_database(database)
            if inspected['database_messages'] > max_messages:
                raise MacMessagesError('Messages read exceeds configured row bound; no import performed.', 'bounds_exceeded')
            status.update(inspected)
        else:
            if root is None or not isinstance(owner, str) or not owner:
                raise MacMessagesError('Import requires an archive root and owner.', 'invalid_configuration')
            archive = Archive(Path(root))
            existing = {r['id']: {k: v for k, v in r.items() if k not in {'owner', 'source', 'raw_sha256', 'imported_at'}}
                        for r in archive.messages(owner) if r['source'] == 'apple-messages'}
            body_cache = {r['apple_metadata']['attributedBody_sha256']: r['text'] for r in existing.values()
                          if r.get('apple_metadata', {}).get('decoder_policy') == DECODER_POLICY and
                          r['apple_metadata'].get('body_status') == 'attributed_body_decoded' and
                          r['apple_metadata'].get('attributedBody_sha256')}
            records, report = read_messages(database, max_messages=max_messages, max_bytes=max_bytes,
                                           body_cache=body_cache, attachment_paths=True)
            report['image_capture'] = capture_mac_images(records, archive.root, owner, database, existing=existing)
            changed = [r for r in records if existing.get(r['id']) != r]
            imported = {'imported': 0, 'updated': 0, 'duplicates': 0}
            # Immutable normalized import input lives only in a private bounded temporary directory.
            if changed:
                with tempfile.TemporaryDirectory(prefix='mac-messages-import-', dir='/tmp') as temporary:
                    payload = Path(temporary) / 'messages.json'
                    fd = os.open(payload, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                    with os.fdopen(fd, 'w') as output:
                        output.write(_json(changed))
                    imported = archive.import_messages(owner, source='apple-messages', input_path=payload)
            status.update(report, status='imported', imported=imported['imported'],
                          updated=imported['updated'], duplicates=imported['duplicates'] + len(records) - len(changed),
                          missing_from_current_database=len(set(existing) - {r['id'] for r in records}))
            status['last_success_at'] = datetime.now(timezone.utc).isoformat()
    except MacMessagesError as exc:
        status.update(status='error', health='error', error_code=exc.error_code, reason=str(exc))
    except Exception:
        status.update(status='error', health='error', error_code='import_failed',
                      reason='Messages collection/import failed; private details withheld.')
    if status_file:
        _write_status(status_file, status)
    return status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', default=str(DEFAULT_DATABASE))
    parser.add_argument('--root')
    parser.add_argument('--owner')
    parser.add_argument('--check-only', action='store_true')
    parser.add_argument('--status-file')
    parser.add_argument('--max-messages', type=int, default=MAX_MESSAGES)
    parser.add_argument('--max-bytes', type=int, default=MAX_BYTES)
    args = parser.parse_args()
    try:
        result = collect(args.database, args.root, args.owner, check_only=args.check_only, status_file=args.status_file,
                         max_messages=args.max_messages, max_bytes=args.max_bytes)
    except Exception:
        result = {'status': 'error', 'health': 'error', 'reason': 'Collector status could not be saved; private details withheld.'}
    print(json.dumps(result, sort_keys=True))
    return int(result['status'] == 'error')


if __name__ == '__main__':
    raise SystemExit(main())
