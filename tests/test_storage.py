from contextlib import closing
import json
import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path

from storage import Archive, restore


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir="/tmp")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.archive = Archive(self.base / "archive")
        self.message = {"id": "1", "conversation_id": "thread", "timestamp": "2026-10-01T12:00:00-05:00", "sender": "friend", "text": "original", "custom": {"keep": True}}

    def import_data(self, messages, owner="Casey", source="phone"):
        path = self.base / "input.json"
        path.write_text(json.dumps(messages))
        return self.archive.import_messages(owner, source, path)

    def test_dedup_revisions_and_separation(self):
        self.assertEqual(self.import_data([self.message])["imported"], 1)
        self.assertEqual(self.import_data([self.message])["duplicates"], 1)
        changed = {**self.message, "text": "edited"}
        self.assertEqual(self.import_data([changed])["updated"], 1)
        self.import_data([self.message], owner="Jordan")
        self.import_data([self.message], source="other")
        self.assertEqual(len(self.archive.messages("Casey")), 2)
        self.assertEqual(self.archive.messages("Jordan")[0]["text"], "original")
        self.assertEqual(self.archive.messages("Jordan")[0]["custom"], {"keep": True})
        with closing(sqlite3.connect(self.archive.db)) as db:
            rows = db.execute("SELECT payload FROM revisions WHERE owner='Casey' AND source='phone' ORDER BY revision").fetchall()
        self.assertEqual([json.loads(row[0])["text"] for row in rows], ["original", "edited"])
        self.assertEqual(self.archive.status()["messages"], 3)
        self.assertEqual((self.archive.root / "Jordan").stat().st_mode & 0o777, 0o700)

    def test_invalid_input_does_not_mutate(self):
        for bad in ({**self.message, "timestamp": "2026-10-01T12:00:00"}, {"id": "2"}):
            with self.assertRaises(ValueError):
                self.import_data([self.message, bad])
            self.assertFalse(self.archive.root.exists())
        with self.assertRaises(ValueError):
            self.import_data([self.message], owner="invalid owner")
        self.import_data([self.message])
        before = sorted(path.relative_to(self.archive.root) for path in self.archive.root.rglob("*"))
        with self.assertRaises(ValueError):
            self.import_data([self.message, {"id": "bad"}])
        self.assertEqual(before, sorted(path.relative_to(self.archive.root) for path in self.archive.root.rglob("*")))
        self.assertEqual(len(self.archive.messages("Casey")), 1)

    def test_owners_are_explicit_and_existing_case_binding_is_preserved(self):
        self.archive.init()
        self.assertEqual(self.archive.status()['owners'], {})
        self.import_data([self.message], owner='Casey')
        self.assertEqual(set(self.archive.status()['owners']), {'Casey'})
        with self.assertRaisesRegex(ValueError, 'differs only by case'):
            self.import_data([self.message], owner='casey')
        self.assertEqual(self.archive.status()['messages'], 1)

    def test_jsonl(self):
        path = self.base / "input.jsonl"
        path.write_text(json.dumps(self.message) + "\n" + json.dumps({**self.message, "id": 2}) + "\n")
        self.assertEqual(self.archive.import_messages("Casey", "phone", path)["imported"], 2)
        path.write_text(json.dumps({**self.message, "id": 3}) + "\n")
        self.assertEqual(self.archive.import_messages("Casey", "phone", path)["imported"], 1)

    def test_snapshot_restore_and_tampering(self):
        self.import_data([self.message])
        legacy = self.archive.root / "Casey/briefs/work/000001.json"
        legacy.parent.mkdir(parents=True)
        legacy.write_text('{"purpose":"historical"}')
        snap = self.archive.snapshot(self.base / "snapshot")
        restored = restore(snap, self.base / "restored")
        self.assertEqual(restored.messages("Casey"), self.archive.messages("Casey"))
        self.assertEqual((restored.root / "Casey/briefs/work/000001.json").read_text(), legacy.read_text())
        with self.assertRaises(ValueError):
            restore(snap, restored.root)
        raw = next((snap / "Casey/raw").glob("*"))
        raw.write_text("tampered")
        with self.assertRaises(ValueError):
            restore(snap, self.base / "tampered")
        self.assertFalse((self.base / "tampered").exists())

    def test_snapshot_restores_image_paths_and_preserves_original_evidence(self):
        data = b"\x89PNG\r\n\x1a\nfixture image"
        digest = hashlib.sha256(data).hexdigest()
        self.archive.init(owners=("Casey",))
        with closing(sqlite3.connect(self.archive.db)) as db:
            db.execute("PRAGMA journal_mode=WAL")
        directory = self.archive.root / "Casey" / "attachments"
        directory.mkdir(mode=0o700)
        blob = directory / (digest + ".png")
        blob.write_bytes(data)
        image = dict(media_id="media-one", mime_type="image/png", capture_status="captured",
                     sha256=digest, size_bytes=len(data), local_path=str(blob))
        self.import_data([{**self.message, "attachments": [image]}])
        for name in ("capture-state.json", ".capture.lock", "scratch.png", "credentials.json"):
            (directory / name).write_text("must stay local")
        original_raw = next((self.archive.root / "Casey/raw").glob("*.json")).read_bytes()
        with closing(sqlite3.connect(self.archive.db)) as db:
            revisions = db.execute("SELECT * FROM revisions").fetchall()
        snap = self.archive.snapshot(self.base / "snapshot")
        self.assertEqual([p.name for p in (snap / "Casey/attachments").iterdir()], [blob.name])
        self.assertEqual((snap / "Casey").stat().st_mode & 0o777, 0o700)
        restored = restore(snap, self.base / "restored")
        attachment = restored.messages("Casey")[0]["attachments"][0]
        restored_blob = restored.root / "Casey/attachments" / blob.name
        self.assertEqual(attachment["local_path"], str(restored_blob))
        self.assertEqual(restored_blob.read_bytes(), data)
        self.assertEqual(attachment["sha256"], digest)
        self.assertEqual(restored_blob.stat().st_mode & 0o777, 0o600)
        self.assertEqual(restored_blob.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(next((restored.root / "Casey/raw").glob("*.json")).read_bytes(), original_raw)
        with closing(sqlite3.connect(restored.db)) as db:
            self.assertEqual(db.execute("SELECT * FROM revisions").fetchall(), revisions)
        # A second generation remains independently restorable at another path.
        again = restore(restored.snapshot(self.base / "snapshot2"), self.base / "restored2")
        self.assertTrue(Path(again.messages("Casey")[0]["attachments"][0]["local_path"]).is_file())

    def test_snapshot_attachment_corruption_and_invalid_bindings_rejected_before_restore(self):
        data = b"\x89PNG\r\n\x1a\nfixture"
        digest = hashlib.sha256(data).hexdigest()
        self.import_data([self.message])
        directory = self.archive.root / "Casey/attachments"
        directory.mkdir()
        blob = directory / (digest + ".png")
        blob.write_bytes(data)
        snap = self.archive.snapshot(self.base / "snapshot")
        copy = snap / "Casey/attachments" / blob.name
        copy.write_bytes(b"corrupt")
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            restore(snap, self.base / "corrupt")
        self.assertFalse((self.base / "corrupt").exists())
        manifest_path = snap / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["files"][copy.relative_to(snap).as_posix()] = hashlib.sha256(b"corrupt").hexdigest()
        manifest_path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "differs from filename"):
            restore(snap, self.base / "renamed")
        self.assertFalse((self.base / "renamed").exists())
        blob.write_bytes(b"corrupt")
        with self.assertRaisesRegex(ValueError, "differs from filename"):
            self.archive.snapshot(self.base / "invalid-source")

    def test_restore_missing_captured_blob_does_not_create_destination(self):
        image = dict(media_id="missing", mime_type="image/png", capture_status="captured",
                     sha256="a" * 64, size_bytes=5, local_path="/old/missing.png")
        self.import_data([{**self.message, "attachments": [image]}])
        snap = self.archive.snapshot(self.base / "snapshot")
        with self.assertRaisesRegex(ValueError, "Captured attachment missing"):
            restore(snap, self.base / "missing")
        self.assertFalse((self.base / "missing").exists())

    def test_private_permissions_and_symlink_rejection(self):
        self.archive.init(owners=("Casey",))
        self.assertEqual(self.archive.db.stat().st_mode & 0o777, 0o600)
        linked = self.base / "linked"
        linked.symlink_to(self.archive.root, target_is_directory=True)
        with self.assertRaises(ValueError):
            Archive(linked)
        (self.archive.root / "Casey/raw").rmdir()
        (self.archive.root / "Casey/raw").symlink_to(self.base)
        with self.assertRaises(ValueError):
            self.archive.init()

    def test_snapshot_rejects_traversal_and_symlinks(self):
        self.archive.init()
        snap = self.archive.snapshot(self.base / "snapshot")
        manifest_file = snap / "manifest.json"
        manifest = json.loads(manifest_file.read_text())
        manifest["files"]["../outside"] = "irrelevant"
        manifest_file.write_text(json.dumps(manifest))
        with self.assertRaises(ValueError):
            restore(snap, self.base / "bad")
        del manifest["files"]["../outside"]
        manifest_file.write_text(json.dumps(manifest))
        database = snap / "archive.sqlite3"
        database.rename(self.base / "outside.sqlite3")
        database.symlink_to(self.base / "outside.sqlite3")
        with self.assertRaises(ValueError):
            restore(snap, self.base / "bad")


if __name__ == "__main__":
    unittest.main()


class ClientOwnerTests(unittest.TestCase):
    def test_independent_owner_backup_and_case_collision(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);archive=Archive(root/'archive')
            source=root/'messages.json'
            source.write_text(json.dumps([{'id':'guid','conversation_id':'chat','timestamp':'2026-10-12T12:00:00Z','sender':'tester','text':'https://www.loom.com/share/'+'a'*32}]))
            archive.import_messages('Alex','apple-messages',source)
            self.assertEqual(archive.owner_names(),['Alex'])
            self.assertEqual(archive.status()['owners']['Alex']['messages'],1)
            from loom_capture import LoomCapture
            loom=LoomCapture(archive);loom.discover()
            self.assertEqual(loom.status()['owners']['Alex']['pending'],1)
            snapshot=archive.snapshot(root/'snapshot')
            restored=restore(snapshot,root/'restored')
            self.assertEqual(restored.messages('Alex'),archive.messages('Alex'))
            self.assertTrue(list((restored.root/'Alex/raw').glob('*.json')))
            self.assertFalse((restored.root/'Casey').exists())
            with self.assertRaisesRegex(ValueError,'case'):
                archive.import_messages('alex','apple-messages',source)
            for bad in ['../escape','.hidden','Alex/Office','Alex Office','123']:
                with self.assertRaises(ValueError):archive.import_messages(bad,'apple-messages',source)
