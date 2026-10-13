"""Bounded, public-viewer Loom transcript capture with immutable provenance."""
import fcntl
import hashlib
import json
import math
import re
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit, quote
from storage import _mkdir, _write_new, _json, _owner

MAX_BYTES = 10 * 1024 * 1024
LINK = re.compile(r'https?://(?:www\.)?loom\.com/(?:share|embed)/([a-fA-F0-9]{32})(?=$|[\s/?#.,;:)\]}>"\'])')


class CaptureError(Exception):
    def __init__(self, status):
        self.status = status
        super().__init__(status)


def canonical(video_id):
    return 'https://www.loom.com/share/' + video_id


def links(text):
    return sorted({match.group(1).lower() for match in LINK.finditer(text)})


def _allowed(url, asset=False):
    p = urlsplit(url)
    return (p.scheme == 'https' and p.hostname == ('cdn.loom.com' if asset else 'www.loom.com')
            and p.port in (None, 443) and not p.username and not p.password
            and (asset or bool(re.fullmatch(r'/share/[0-9a-f]{32}', p.path)) and not p.query and not p.fragment))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise CaptureError('unavailable')


def fetch(url, asset=False):
    if not _allowed(url, asset):
        raise CaptureError('unavailable')
    try:
        request = urllib.request.Request(url, headers={'User-Agent': 'FamilyTextArchive/1.0'})
        with urllib.request.build_opener(NoRedirect).open(request, timeout=20) as response:
            if response.status != 200 or response.geturl() != url:
                raise CaptureError('unavailable')
            data = response.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                raise CaptureError('invalid_transcript')
            return data
    except urllib.error.HTTPError as error:
        raise CaptureError('denied' if error.code in (401, 403) else 'unavailable') from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise CaptureError('network_error') from None


def metadata(page, video_id):
    try:
        text = page.decode('utf-8')
        match = re.search(r'window\.__APOLLO_STATE__\s*=\s*', text)
        if not match:
            raise CaptureError('unavailable')
        state, _ = json.JSONDecoder().raw_decode(text[match.end():])
        video = state.get('RegularUserVideo:' + video_id)
        if not isinstance(video, dict):
            raise CaptureError('unavailable')
        if video.get('show_transcript_to_viewer') is not True or video.get('viewerNeedsPermission') is not False:
            raise CaptureError('denied')
        for key in ('passwordProtected', 'isPasswordProtected', 'requiresPassword', 'requiresLogin', 'isPrivate', 'needsPassword', 'viewerNeedsPassword'):
            if video.get(key) is True:
                raise CaptureError('denied')
        root = state.get('ROOT_QUERY', {})
        refs = [value.get('__ref') for key, value in root.items()
                if key.startswith('fetchVideoTranscript(') and isinstance(value, dict)]
        details = [state.get(ref) for ref in refs if isinstance(ref, str)]
        details = [item for item in details if isinstance(item, dict) and item.get('video_id') == video_id]
        if len(details) != 1:
            raise CaptureError('not_ready')
        item = details[0]
        if item.get('transcription_status') != 'success':
            raise CaptureError('not_ready')
        if not isinstance(item.get('source_url'), str) or not _allowed(item['source_url'], True):
            raise CaptureError('unavailable')
        caption = item.get('captions_source_url')
        if caption and (not isinstance(caption, str) or not _allowed(caption, True)):
            raise CaptureError('unavailable')
        return item
    except (ValueError, TypeError, AttributeError):
        raise CaptureError('unavailable') from None


def normalize(raw):
    try:
        data = json.loads(raw)
        if not isinstance(data, dict) or isinstance(data.get('schemaVersion'), bool) or not isinstance(data.get('schemaVersion'), (str, int)):
            raise ValueError()
        phrases = data['phrases']
        if not isinstance(phrases, list) or not phrases:
            raise ValueError()
        result = []
        for phrase in phrases:
            ts, value, ranges = phrase['ts'], phrase['value'], phrase['ranges']
            if isinstance(ts, bool) or not isinstance(ts, (float, int)) or not math.isfinite(ts) or ts < 0 or not isinstance(value, str) or not isinstance(ranges, list):
                raise ValueError()
            result.append({'ts': ts, 'value': value, 'ranges': ranges})
        if not any(p['value'].strip() for p in result):
            raise ValueError()
        _json(result)
        return result, '\n'.join(p['value'] for p in result)
    except (ValueError, KeyError, TypeError, UnicodeError):
        raise CaptureError('invalid_transcript') from None


class LoomCapture:
    def __init__(self, archive, fetcher=fetch):
        self.archive, self.fetcher = archive, fetcher
        archive.init()
        with archive._connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS loom_queue (
                    owner TEXT NOT NULL, video_id TEXT NOT NULL, source_url TEXT NOT NULL,
                    status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                    discovered_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    last_attempt_at TEXT, next_attempt_at TEXT NOT NULL,
                    last_success_at TEXT, current_revision INTEGER, last_error TEXT,
                    failure_since TEXT, PRIMARY KEY(owner,video_id));
                CREATE TABLE IF NOT EXISTS loom_origins (
                    owner TEXT NOT NULL, video_id TEXT NOT NULL, source TEXT NOT NULL,
                    message_id TEXT NOT NULL, conversation_id TEXT NOT NULL,
                    PRIMARY KEY(owner,video_id,source,message_id));
                CREATE TABLE IF NOT EXISTS loom_revisions (
                    owner TEXT NOT NULL, video_id TEXT NOT NULL, revision INTEGER NOT NULL,
                    transcript_sha256 TEXT NOT NULL, captions_sha256 TEXT,
                    semantic_sha256 TEXT NOT NULL, phrases TEXT NOT NULL, text TEXT NOT NULL,
                    language TEXT, version TEXT, captured_at TEXT NOT NULL, source_url TEXT NOT NULL,
                    PRIMARY KEY(owner,video_id,revision));
                CREATE TABLE IF NOT EXISTS loom_worker (
                    id INTEGER PRIMARY KEY CHECK(id=1), last_completed_at TEXT,
                    operational_failures INTEGER NOT NULL DEFAULT 0);
            ''')

    def discover(self, now=None):
        now = now or datetime.now(timezone.utc)
        stamp = now.isoformat()
        with self.archive._connect() as db:
            for owner in self.archive.owner_names():
                for message in self.archive.messages(owner):
                    for video in links(message['text']):
                        db.execute('INSERT OR IGNORE INTO loom_queue(owner,video_id,source_url,status,discovered_at,updated_at,next_attempt_at) VALUES(?,?,?,\'pending\',?,?,?)', (owner, video, canonical(video), stamp, stamp, stamp))
                        db.execute('INSERT OR IGNORE INTO loom_origins VALUES(?,?,?,?,?)', (owner, video, message['source'], message['id'], message['conversation_id']))

    def _raw(self, owner, raw, suffix):
        digest = hashlib.sha256(raw).hexdigest()
        directory = self.archive.root / owner / 'raw' / 'loom'
        _mkdir(directory)
        path = directory / (digest + suffix)
        if path.is_symlink():
            raise ValueError('Loom raw file must not be a symlink')
        if path.exists():
            if path.read_bytes() != raw:
                raise ValueError('Loom raw integrity check failed')
        else:
            _write_new(path, raw)
        return digest

    def run(self, now=None):
        now = now or datetime.now(timezone.utc)
        lock = self.archive.root / 'loom.lock'
        if lock.is_symlink():
            raise ValueError('Loom lock must not be a symlink')
        with lock.open('a+b') as handle:
            lock.chmod(0o600)
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError('Loom capture already running') from None
            return self._run(now)

    def _run(self, now):
        self.discover(now)
        stamp = now.isoformat()
        with self.archive._connect() as db:
            due = db.execute('SELECT * FROM loom_queue WHERE next_attempt_at<=? ORDER BY next_attempt_at,owner,video_id LIMIT 5', (stamp,)).fetchall()
        failures = 0
        for row in due:
            status, error = 'captured', None
            try:
                info = metadata(self.fetcher(row['source_url']), row['video_id'])
                raw = self.fetcher(info['source_url'], asset=True)
                if len(raw) > MAX_BYTES:
                    raise CaptureError('invalid_transcript')
                phrases, text = normalize(raw)
                # Captions are optional; an inaccessible caption does not discard a valid transcript.
                caption_sha = None
                if info.get('captions_source_url'):
                    try:
                        captions = self.fetcher(info['captions_source_url'], asset=True)
                        if len(captions) <= MAX_BYTES and captions.decode('utf-8-sig').startswith('WEBVTT'):
                            caption_sha = self._raw(row['owner'], captions, '.vtt')
                    except (CaptureError, UnicodeError):
                        pass
                raw_sha = self._raw(row['owner'], raw, '.json')
                semantic = hashlib.sha256(_json(phrases).encode()).hexdigest()
                with self.archive._connect() as db:
                    old = db.execute('SELECT revision,semantic_sha256 FROM loom_revisions WHERE owner=? AND video_id=? ORDER BY revision DESC LIMIT 1', (row['owner'], row['video_id'])).fetchone()
                    revision = old['revision'] if old else 0
                    if not old or old['semantic_sha256'] != semantic:
                        revision += 1
                        db.execute('INSERT INTO loom_revisions VALUES(?,?,?,?,?,?,?,?,?,?,?,?)', (row['owner'], row['video_id'], revision, raw_sha, caption_sha, semantic, _json(phrases), text, str(info.get('language', '')), str(info.get('version', '')), stamp, row['source_url']))
                    db.execute('UPDATE loom_queue SET current_revision=?,last_success_at=? WHERE owner=? AND video_id=?', (revision, stamp, row['owner'], row['video_id']))
            except CaptureError as exc:
                status, error = exc.status, exc.status
                failures += status in ('network_error', 'invalid_transcript', 'unavailable')
            delay = timedelta(hours=24 if status == 'captured' else 1) if status != 'network_error' else timedelta(minutes=15)
            with self.archive._connect() as db:
                db.execute('UPDATE loom_queue SET status=?,attempts=attempts+1,updated_at=?,last_attempt_at=?,next_attempt_at=?,last_error=?,failure_since=? WHERE owner=? AND video_id=?', (status, stamp, stamp, (now + delay).isoformat(), error, None if status == 'captured' else row['failure_since'] or stamp, row['owner'], row['video_id']))
        with self.archive._connect() as db:
            db.execute('INSERT INTO loom_worker VALUES(1,?,?) ON CONFLICT(id) DO UPDATE SET last_completed_at=excluded.last_completed_at,operational_failures=excluded.operational_failures', (stamp, failures))
        return {**self.status(), 'attempted': len(due), 'operational_failures': failures}

    def status(self, owner=None):
        if owner:
            _owner(owner)
        with self.archive._connect() as db:
            rows = db.execute('SELECT owner,status,COUNT(*) AS count FROM loom_queue' + (' WHERE owner=?' if owner else '') + ' GROUP BY owner,status', (owner,) if owner else ()).fetchall()
            worker = db.execute('SELECT last_completed_at,operational_failures FROM loom_worker WHERE id=1').fetchone()
            origins = db.execute('SELECT COUNT(*) FROM loom_origins' + (' WHERE owner=?' if owner else ''), (owner,) if owner else ()).fetchone()[0]
        return {'owners': {o: {r['status']: r['count'] for r in rows if r['owner'] == o} for o in ([owner] if owner else self.archive.owner_names())}, 'origin_count': origins, 'worker': dict(worker) if worker else None}

    def transcripts(self, owner):
        _owner(owner)
        with self.archive._connect() as db:
            rows = db.execute('SELECT r.* FROM loom_revisions r JOIN loom_queue q ON r.owner=q.owner AND r.video_id=q.video_id AND r.revision=q.current_revision WHERE r.owner=? ORDER BY r.video_id', (owner,)).fetchall()
            result = []
            for row in rows:
                item = dict(row)
                item['phrases'] = json.loads(item['phrases'])
                item['type'] = 'loom-transcript'
                item['citation'] = f"archive://{quote(owner, safe='')}/loom/{item['video_id']}/revision/{item['revision']}"
                item['origin_messages'] = [dict(r) for r in db.execute('SELECT source,message_id AS id,conversation_id FROM loom_origins WHERE owner=? AND video_id=? ORDER BY source,message_id', (owner, item['video_id']))]
                for origin in item['origin_messages']:
                    origin['citation'] = 'archive://' + '/'.join(quote(s, safe='') for s in (owner, origin['source'], origin['id']))
                result.append(item)
        return result

    def annotate(self, messages, owner):
        transcripts = self.transcripts(owner)
        result = []
        for message in messages:
            item = dict(message)
            saved = [t for t in transcripts if any(o['source'] == item['source'] and o['id'] == item['id'] for o in t['origin_messages'])]
            if saved:
                item['loom_transcripts'] = saved
            result.append(item)
        return result
