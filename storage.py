"""Private local message archives, immutable imports, and verified snapshots."""
import hashlib
import json
import os
import re
import sqlite3
import tempfile
from datetime import datetime, timezone
from contextlib import contextmanager, closing
from pathlib import Path, PurePosixPath

IMAGE_EXTENSIONS = {"image/jpeg": "jpg", "image/png": "png", "image/gif": "gif", "image/webp": "webp",
                    "image/heic": "heic", "image/heif": "heif", "image/avif": "avif",
                    "image/tiff": "tiff", "image/bmp": "bmp"}
IMAGE_BLOB_NAME = re.compile(r"([0-9a-f]{64})\.(jpg|png|gif|webp|heic|heif|avif|tiff|bmp)")


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def _owner(owner):
    if not isinstance(owner, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,63}', owner):
        raise ValueError('Owner must be a safe identifier beginning with a letter')
    return owner


def _mkdir(path):
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        raise ValueError("Archive directories must not be symlinks")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)


def _write_new(path, data):
    with path.open("xb") as handle:
        os.chmod(path, 0o600)
        handle.write(data)


def _outside_git(path):
    if any((parent / ".git").is_file() or (parent / ".git" / "HEAD").is_file()
           for parent in (path, *path.parents)):
        raise ValueError("Archive data must be outside a Git checkout")


class Archive:
    def __init__(self, root: Path):
        requested = Path(root).expanduser().absolute()
        if any(parent.is_symlink() for parent in (requested, *requested.parents)):
            raise ValueError("Archive root must not be a symlink")
        self.root = requested.resolve()
        _outside_git(self.root)
        self.db = self.root / "archive.sqlite3"

    def owner_names(self):
        names = set()
        if self.root.exists():
            for path in self.root.iterdir():
                if path.is_dir() and (path / 'raw').exists():
                    names.add(_owner(path.name))
        if self.db.exists():
            with self._connect() as db:
                names.update(_owner(row[0]) for row in db.execute('SELECT DISTINCT owner FROM messages'))
        return sorted(names)

    def init(self, owners=None):
        _mkdir(self.root)
        if self.db.is_symlink():
            raise ValueError("Archive database must not be a symlink")
        names = list(owners) if owners is not None else self.owner_names()
        for owner in names:
            _owner(owner)
            if any(path.name.casefold() == owner.casefold() and path.name != owner
                   for path in self.root.iterdir() if path.is_dir()):
                raise ValueError('Owner identifier differs only by case from an existing namespace')
            for name in ("raw",):
                _mkdir(self.root / owner / name)
            (self.root / owner).chmod(0o700)
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS messages (
                    owner TEXT NOT NULL, source TEXT NOT NULL, id TEXT NOT NULL,
                    payload TEXT NOT NULL, raw_sha256 TEXT NOT NULL,
                    imported_at TEXT NOT NULL,
                    PRIMARY KEY (owner, source, id));
                CREATE TABLE IF NOT EXISTS revisions (
                    owner TEXT NOT NULL, source TEXT NOT NULL, id TEXT NOT NULL,
                    revision INTEGER NOT NULL, payload TEXT NOT NULL,
                    raw_sha256 TEXT NOT NULL, imported_at TEXT NOT NULL,
                    PRIMARY KEY (owner, source, id, revision));
                CREATE TABLE IF NOT EXISTS imports (
                    owner TEXT NOT NULL, source TEXT NOT NULL, raw_sha256 TEXT NOT NULL,
                    imported_at TEXT NOT NULL,
                    PRIMARY KEY (owner, source, raw_sha256));
            """)
        self.db.chmod(0o600)

    @contextmanager
    def _connect(self):
        if self.db.is_symlink():
            raise ValueError("Archive database must not be a symlink")
        if not self.db.exists():
            _write_new(self.db, b"")
        db = sqlite3.connect(self.db)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def import_messages(self, owner, source, input_path):
        _owner(owner)
        if not isinstance(source, str) or not source.strip():
            raise ValueError("Source must be a nonempty string")
        raw = Path(input_path).read_bytes()
        text = raw.decode("utf-8-sig")
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            value = [json.loads(line) for line in text.splitlines() if line.strip()]
        if isinstance(value, dict):
            value = [value]  # A one-record JSONL file is also one JSON object.
        if not isinstance(value, list):
            raise ValueError("Input must be a JSON list or JSONL messages")
        normalized = []
        for item in value:
            if not isinstance(item, dict):
                raise ValueError("Each message must be an object")
            payload = dict(item)
            for key in ("id", "conversation_id"):
                if isinstance(payload.get(key), bool) or not isinstance(payload.get(key), (str, int)) or not str(payload[key]):
                    raise ValueError(f"Message requires {key}")
                payload[key] = str(payload[key])
            for key in ("timestamp", "sender", "text"):
                if not isinstance(payload.get(key), str):
                    raise ValueError(f"Message requires string {key}")
            stamp = datetime.fromisoformat(payload["timestamp"].replace("Z", "+00:00"))
            if stamp.utcoffset() is None:
                raise ValueError("Timestamp requires a timezone")
            payload["timestamp"] = stamp.astimezone(timezone.utc).isoformat()
            normalized.append((payload["id"], _json(payload)))
        # Validate the entire document before creating any archive files or rows.
        self.init(owners=(owner,))
        digest = hashlib.sha256(raw).hexdigest()
        raw_path = self.root / owner / "raw" / f"{digest}.json"
        if raw_path.is_symlink():
            raise ValueError("Raw copy must not be a symlink")
        if not raw_path.exists():
            _write_new(raw_path, raw)
        elif raw_path.read_bytes() != raw:
            raise ValueError("Existing raw copy failed integrity check")
        counts = {"imported": 0, "updated": 0, "duplicates": 0, "total": len(normalized), "raw_sha256": digest}
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as db:
            for message_id, payload in normalized:
                key = (owner, source, message_id)
                old = db.execute("SELECT payload FROM messages WHERE owner=? AND source=? AND id=?", key).fetchone()
                if old and old["payload"] == payload:
                    counts["duplicates"] += 1
                    continue
                counts["updated" if old else "imported"] += 1
                revision = db.execute("SELECT COALESCE(MAX(revision), 0)+1 FROM revisions WHERE owner=? AND source=? AND id=?", key).fetchone()[0]
                db.execute("INSERT INTO revisions VALUES (?, ?, ?, ?, ?, ?, ?)", (*key, revision, payload, digest, now))
                db.execute("INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(owner, source, id) DO UPDATE SET payload=excluded.payload, raw_sha256=excluded.raw_sha256, imported_at=excluded.imported_at", (*key, payload, digest, now))
            db.execute("INSERT INTO imports VALUES (?, ?, ?, ?) ON CONFLICT(owner, source, raw_sha256) DO UPDATE SET imported_at=excluded.imported_at", (owner, source, digest, now))
        return counts

    def messages(self, owner):
        _owner(owner)
        if not self.db.exists():
            return []
        with self._connect() as db:
            rows = db.execute("SELECT * FROM messages WHERE owner=?", (owner,)).fetchall()
        result = []
        for row in rows:
            payload = json.loads(row["payload"])
            result.append({**payload, "owner": row["owner"], "source": row["source"], "raw_sha256": row["raw_sha256"], "imported_at": row["imported_at"]})
        return sorted(result, key=lambda item: (item["timestamp"], item["source"], item["id"]))

    def status(self):
        owners = {owner: {"messages": 0, "last_import_at": None, "sources": []} for owner in self.owner_names()}
        if self.db.exists():
            with self._connect() as db:
                for row in db.execute("SELECT owner, COUNT(*) AS count FROM messages GROUP BY owner"):
                    owners[row["owner"]]["messages"] = row["count"]
                for row in db.execute("SELECT owner, source, MAX(imported_at) AS latest FROM imports GROUP BY owner, source"):
                    current = owners[row["owner"]]
                    current["sources"].append(row["source"])
                    current["last_import_at"] = max(current["last_import_at"] or "", row["latest"])
        return {"root": str(self.root), "owners": owners, "messages": sum(item["messages"] for item in owners.values()), "coverage": "Imported records only; capture completeness is unverified"}

    def snapshot(self, dest: Path):
        requested = Path(dest).expanduser().absolute()
        if any(parent.is_symlink() for parent in (requested, *requested.parents)):
            raise ValueError("Snapshot destination must not be a symlink")
        dest = requested.resolve()
        if dest == self.root or self.root in dest.parents:
            raise ValueError("Snapshot destination must be outside the archive")
        if dest.exists() and any(dest.iterdir()):
            raise ValueError("Snapshot destination must be empty")
        if not self.db.exists():
            raise FileNotFoundError("Archive is not initialized")
        _mkdir(dest)
        with self._connect() as source, closing(sqlite3.connect(dest / "archive.sqlite3")) as target:
            source.backup(target)
        (dest / "archive.sqlite3").chmod(0o600)
        # Raw originals, image blobs and briefs are immutable: enumerate after the DB backup
        # so every original referenced by its committed rows is included.
        files = []
        for owner in self.owner_names():
            _mkdir(dest / owner)
            for category in ("raw", "briefs"):
                directory = self.root / owner / category
                if any(parent.is_symlink() for parent in (directory, directory.parent)):
                    raise ValueError("Archive directories must not be symlinks")
                for path in directory.rglob("*"):
                    if path.is_symlink():
                        raise ValueError("Archive files must not be symlinks")
                    if path.is_file():
                        files.append(path)
            directory = self.root / owner / "attachments"
            if directory.is_symlink():
                raise ValueError("Archive directories must not be symlinks")
            if directory.exists():
                # Only immutable content-addressed blobs belong in a snapshot.
                # Download retry state, locks, OCR scratch and credentials do not.
                for path in directory.iterdir():
                    if IMAGE_BLOB_NAME.fullmatch(path.name):
                        if path.is_symlink() or not path.is_file():
                            raise ValueError("Attachment blobs must be regular files")
                        files.append(path)
        for path in files:
            target = dest / path.relative_to(self.root)
            content = path.read_bytes()
            if path.relative_to(self.root).parts[1] == "attachments" and hashlib.sha256(content).hexdigest() != path.stem:
                raise ValueError("Attachment blob checksum differs from filename")
            _mkdir(target.parent)
            _write_new(target, content)
        manifest = {"version": 1, "files": {path.relative_to(dest).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(dest.rglob("*")) if path.is_file()}}
        _write_new(dest / "manifest.json", (_json(manifest) + "\n").encode())
        return dest

    @staticmethod
    def restore(snapshot_path: Path, dest: Path):
        return restore(snapshot_path, dest)


def restore(snapshot_path: Path, dest: Path):
    requested_snapshot = Path(snapshot_path).expanduser().absolute()
    if any(parent.is_symlink() for parent in (requested_snapshot, *requested_snapshot.parents)):
        raise ValueError("Snapshot root must not be a symlink")
    snapshot_path = requested_snapshot.resolve()
    archive = Archive(dest)
    dest = archive.root
    if dest == snapshot_path or snapshot_path in dest.parents or dest in snapshot_path.parents:
        raise ValueError("Restore destination must be separate from snapshot")
    if dest.exists() and any(dest.iterdir()):
        raise ValueError("Restore destination must be empty")
    manifest_path = snapshot_path / "manifest.json"
    if manifest_path.is_symlink():
        raise ValueError("Manifest must not be a symlink")
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("version") != 1 or not isinstance(manifest.get("files"), dict) or "archive.sqlite3" not in manifest["files"]:
        raise ValueError("Invalid snapshot manifest")
    validated = []
    for name, digest in manifest["files"].items():
        path = PurePosixPath(name)
        if path.is_absolute() or not path.parts or path.as_posix() != name or any(part in (".", "..") for part in path.parts) or "\\" in name:
            raise ValueError("Unsafe snapshot path")
        attachment = (len(path.parts) == 3 and path.parts[1] == "attachments" and
                      IMAGE_BLOB_NAME.fullmatch(path.parts[2]))
        if name != "archive.sqlite3" and not (len(path.parts) >= 3 and _owner(path.parts[0]) == path.parts[0] and
                (path.parts[1] in ("raw", "briefs") or attachment)):
            raise ValueError("Unexpected snapshot file")
        if attachment and digest != path.stem:
            raise ValueError("Attachment manifest checksum differs from filename")
        source = snapshot_path.joinpath(*path.parts)
        if any(parent.is_symlink() for parent in (source, *source.parents) if parent != snapshot_path.parent):
            raise ValueError("Snapshot paths must not be symlinks")
        content = source.read_bytes()
        if hashlib.sha256(content).hexdigest() != digest:
            raise ValueError(f"Snapshot checksum mismatch: {name}")
        validated.append((path, content))
    # Validate current-message image references before writing any destination.
    # Historical revisions and raw imports retain their exact original bytes.
    contents = {path.as_posix(): content for path, content in validated}
    rebound = []
    with tempfile.TemporaryDirectory(prefix="minbox-restore-verify-") as temporary:
        checked_path = Path(temporary) / "archive.sqlite3"
        _write_new(checked_path, contents["archive.sqlite3"])
        # Backup contains all committed pages, even if its header retains WAL mode.
        with closing(sqlite3.connect(checked_path.as_uri() + "?mode=ro&immutable=1", uri=True)) as checked:
            for owner, source, message_id, encoded in checked.execute("SELECT owner,source,id,payload FROM messages"):
                payload = json.loads(encoded)
                changed = False
                for item in payload.get("attachments", []):
                    if item.get("capture_status") != "captured":
                        continue
                    digest = item.get("sha256", "")
                    extension = IMAGE_EXTENSIONS.get(item.get("mime_type"))
                    filename = digest + "." + extension if isinstance(digest, str) and extension else ""
                    if not IMAGE_BLOB_NAME.fullmatch(filename):
                        raise ValueError("Invalid captured attachment binding")
                    relative = _owner(owner) + "/attachments/" + filename
                    content = contents.get(relative)
                    if content is None or len(content) != item.get("size_bytes"):
                        raise ValueError("Captured attachment missing or size differs in snapshot")
                    item["local_path"] = str(dest / relative)
                    changed = True
                if changed:
                    rebound.append((_json(payload), owner, source, message_id))
    # Verify all content before populating the destination.
    _mkdir(dest)
    for path, content in validated:
        target = dest.joinpath(*path.parts)
        _mkdir(target.parent)
        _write_new(target, content)
    archive.init()
    if rebound:
        with archive._connect() as db:
            db.executemany("UPDATE messages SET payload=? WHERE owner=? AND source=? AND id=?", rebound)
    return archive
