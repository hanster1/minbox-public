# Phone deletions

When the owner deletes a text on the Android phone, the Linux collector can
notice and leave that text out of the filtered archive. Nothing is ever removed
from the raw archive; deletion is a flag that derived outputs respect.

Start with [README](README.md). Spam and blocked conversations are handled
separately; see [PHONE_SPAM](PHONE_SPAM.md).

## How it works

1. `scripts/gmkit-phone-deletions.patch` adds a background scan to the collector.
   Every 30 minutes it re-reads a few conversations from the phone, newest first,
   in bounded pages, and records which stored messages are still there.
2. A message is only judged if it falls inside the window the phone actually
   returned and is more than a minute older than the scan.
3. A message is flagged deleted only after **two consecutive** scans miss it.
   A failed, timed-out or empty read records nothing for that conversation, and a
   scan that would mark more than max(5, 20%) of the judged messages missing is
   treated as a broken phone response and also records nothing.
4. If a flagged message reappears on the phone, the flag clears.
5. Archive import carries the flag as `phone_deleted_at`; snapshots and the local
   export skip flagged messages and report how many were withheld.

Evidence lives in schema v7 tables `message_presence` and `deletion_scan_state`.
The migration is additive and idempotent; existing rows are unchanged.
An older collector without these tables never marks anything deleted.

## Limits

- Deleting a **whole conversation** is not detected by this scan.
- Only the Android/Google Messages path is covered. The Mac path is unchanged.
- Detection can lag by several scan cycles on large archives.

## Recommended rollout

1. Back up the collector database and the archive with SQLite `.backup`.
2. Build with [GMKIT_MEDIA](GMKIT_MEDIA.md) and swap in the new collector only.
3. **Watch-only for at least a day:** keep the previous import/export code so
   nothing changes downstream. Check
   `SELECT COUNT(*) FROM message_presence WHERE deleted_at>0` and spot-check any
   flagged messages on the phone.
4. Then update the import/export code. The next cycle withholds flagged texts.
5. Rollback: restore the previous collector binary and Python files. The v7
   tables are harmless to older builds.
