# Architecture

How Minbox turns texts on a phone into answers in a phone AI app. Start with
[README](README.md); setup steps are in [ONBOARDING](ONBOARDING.md).

```
Android phone ──pairing──▶ collector (gmkit, read-only) ──▶ collector DB (per owner)
iPhone ──Messages sync──▶ Mac Messages DB ──────────────────┐        │
                                                             ▼        ▼ import
                                            shared archive (rows tagged by owner)
                                                             │
                              phone spam/blocked + corrections ledger (per owner)
                                                             │ filter
                                ┌────────────────────────────┴─────────────┐
                                ▼                                          ▼
                      local filtered folder                      Google Drive folder
                      ~/Minbox/<Owner>/Filtered                  (optional publisher)
                                │                                          │
             agent on the host / read-only search tool        phone AI app with Drive access
```

## Components

| Stage | What runs | Code |
| --- | --- | --- |
| Collect (Android) | Patched [gmkit](https://github.com/johnlindquist/gmkit) collector, read-only, one per owner, as a user service | `scripts/build_gmkit_media.py`, `services/minbox-text-collector@.service` |
| Collect (iPhone) | Reader for the Mac Messages database | `mac_messages.py`, `mac_setup.py` |
| Import | Copies new collector rows into the shared archive, tagged by owner | `archive_cli.py`, `storage.py`, `services/minbox-text-import@.*` |
| Backfill | Asks the phone for older history in small steps | `history_backfill.py`, `services/minbox-text-backfill@.*` |
| Filter | Removes phone spam/blocked conversations, hard exclusions and owner corrections | `phone_spam.py`, `archive_corrections.py`, `archive_incremental.py` |
| Export | Writes plain-text filtered files to a local folder | `local_archive_export.py` |
| Publish (optional) | Writes filtered files to the owner's own Drive folder | `owner_archive_publisher.py`, `archive_drive.py` |
| Answer | An agent on the host reads the folder, or a read-only search tool serves it | `archive_search_mcp.py`, [READ_ONLY_SEARCH](READ_ONLY_SEARCH.md) |
| Watch | Health checks and optional alert email | `health_monitor.py`, [HEALTH_ALERTS](HEALTH_ALERTS.md) |

## Design rules

- **Read-only toward the phone.** The collector never sends messages.
- **The raw archive only grows.** Spam, corrections and other exclusions are
  flags that derived outputs respect; they can be reversed.
- **Guarded reconciliation.** Phone-side state is applied only from complete,
  plausible responses; a capped or failed read never removes anything.
- **Per-owner everything.** Collector store, ledger, export folder, publisher
  and jobs are bound to one owner name.
- **No secrets or content in Git.** Runtime state lives under `~/.local`,
  `~/.config` and the export folder, with private file modes.

## Adding people

`scripts/add-owner` prepares another owner on an existing Android host. See
[ONBOARDING](ONBOARDING.md) and [PRIVACY](PRIVACY.md).
