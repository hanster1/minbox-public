# Local filtered text folder

`local_archive_export.py` builds a real folder of filtered UTF-8 text files from an existing local Minbox archive. It makes no Google, AI or network calls. This is an optional output for direct computer access or the [read-only search adapter](READ_ONLY_SEARCH.md); it does not replace existing Drive publication.

## Inputs and invocation

Use an existing archive database, the owner's committed local correction ledger, and an explicit phone-folder policy. The correction ledger is mandatory: failure to read it does not fall back to an uncorrected export. This trial implements an existing-installation export, not a complete standalone collector/onboarding path.

```sh
python3 -B -S local_archive_export.py \
  --archive-root /private/minbox-collection \
  --owner Casey \
  --correction-ledger /private/minbox-publisher/corrections.sqlite3 \
  --destination /home/user/Minbox-Filtered \
  --phone-spam-policy spam_and_blocked
```

Adapt the paths, owner and policy to the client's actual installation. The destination must be separate from collection/runtime directories and outside Git; its parent must already be owner-private. Source databases and their parent directories must be private. The tool refuses symlinks, hardlinks, unsafe permissions and unmanaged destination contents rather than overwrite an arbitrary folder.

The source module needs these neighboring Minbox modules: `archive_corrections`, `archive_drive`, `archive_incremental`, `archive_io`, `archive_snapshot`, `owner_archive_publisher`, `phone_spam`, `publisher_status` and `storage`. These imports use the standard library and do not initialize Google credentials. A standalone bundled test runs with Python site packages disabled.

## Filtering and generation behavior

The output uses existing publisher validation/rendering helpers and applies authentication-code/promotional-spam exclusions, matching OCR exclusions, durable spam corrections and undo, and the configured phone Spam & blocked policy. Loom transcripts need a retained origin message. A further phrase-text check avoids exposing excluded content through transcript phrases. Original images, raw files, databases and credentials are not copied into this text-only export.

Corrections reflect the committed local ledger at generation time. An unprocessed change in a remote Corrections Doc is not yet local policy. Phone-folder exclusions reflect imported observations. These freshness boundaries should remain visible to the client.

A complete generation is staged privately beside the selected folder. The exporter rechecks source and correction fingerprints, verifies the existing managed destination, and exchanges directories atomically. It removes stale files from the selected path. Failure before the exchange preserves the old generation; consumers must not call that old generation current just because it still exists.

Current replacement requires Linux `renameat2` support on the destination filesystem. Cross-platform replacement needs separate implementation/testing. Files are at most 100 KiB, total output at most 256 MiB / 5,000 files. The search adapter has separate scan limits and may return partial coverage.

The original source and correction databases are opened read-only; corrections are recomputed in a private backup. SQLite WAL readers may participate in shared-memory coordination or sidecars. This is not a claim of absolutely zero filesystem activity around a live database.

## Keeping it living

Schedule this ordinary program independently of AI sessions. Choose an interval that fits collection cadence and device cost. The Linux trial uses a separate user timer every three minutes; its service disallows new privileges and internet socket families. This is a trial operating choice, not a required interval. Existing collectors and publishers are unchanged.

The folder contains `START_HERE.txt`, message/transcript parts and a hidden manifest with generation time, source/correction fingerprints, file hashes and counts. Monitor the refresh service and manifest age separately from whether the AI app is online. Keep health output content-free.

Readers should reopen the absolute folder path on each fresh request. Atomic exchange changes its inode; a retained working-directory handle, open file, watcher or uploaded copy can point at an older generation. Old bytes already copied to an AI provider are not revoked by local replacement. Test a changed synthetic value and actual updated archive source from the intended phone app.

## Native desktop apps on a headless host

A headless computer may need a persistent graphical session even when the user only interacts from a phone. The trial uses TigerVNC's virtual X display, the native apps and a browser noVNC client over an SSH forward. VNC/web access and app debugging ports listen on loopback only; no public archive endpoint is created. The owner performs sign-in and computer-access consent.

These are user-session components, not a separate OS security boundary. Broad app local execution still runs as that user; Auto Review rules are model-based. An optional isolated environment requires its own restrictions and tests. See [phone access choices](PHONE_ACCESS.md).

On the tested Omarchy installation, the official ChatGPT installer's direct full-upgrade transaction was stopped by Omarchy's update guard. Use the installed Omarchy update workflow and package-management commands rather than bypassing the guard. A remote shell may need the ordinary `OMARCHY_PATH=/usr/share/omarchy` environment. Review installer/update scope with the owner, preserve server services and check them afterward. Do not equate a successful package install or virtual-display launch with unattended phone/reboot acceptance.

## Evidence

Twenty synthetic export tests cover filtering/publisher counts, correction undo, phone observations, source/ledger change refusal, safe atomic replacement, stale removal, path refusals, failed-write preservation and standalone operation. The combined repository suite ran 527 tests with five optional skips and no failures.

A live Linux export produced a private folder with counts matching the current filtered publication, and a scheduled refresh completed successfully. Native ChatGPT/Grok Bot and the remote virtual display were installed/started on the archive host. Grok Bot's first synthetic local read matched the expected value with owner approval. Changed-value, unattended Android, actual archive-answer and reboot checks remain pending. No Google retrieval was used to generate the local folder.
