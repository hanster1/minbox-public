# Owner-wide private text archive

The normal private view contains **all currently captured owner conversations**,
including personal, work, mixed and unclassified texts. It does not wait for AI
classification. The separate optional work view keeps its narrower eligibility rules,
reusable analysis cache and existing citations. No mandatory review queue.

Files are named `OWNER Text Archive`, for example `Casey Text Archive`, in the
owner's restricted Google Drive folder. The Start Here Doc links yearly Messages
Docs, continuation parts, retained-origin Loom transcripts, the designated
Corrections Doc and Publisher Status. Stable source/message IDs support citations.
A chronological index makes date coverage visible. Optional work outputs may
live in a managed private child folder. Filtered source bodies, phone pairing
credentials and OAuth tokens never enter the published Docs.

## Filtering and corrections

Local filters exclude authentication/verification codes and clear opt-out
promotional spam before publication. They are conservative rules, not proof that
every scam is recognized. Explicit spam corrections are durable, including when
the entry disappears from the input Doc. A work/personal correction cannot bypass
an active spam correction; use an explicit undo. Personal corrections retain a
text in the full private view while withdrawing it from work exports.

Use the existing designated Corrections Doc when migrating an owner from a work
pilot. Initialize the new full-view ledger once with SQLite's consistent backup
of the old ledger, preserving correction/undo history; never overwrite the full
ledger on later runs. Configure its actual folder separately from work outputs. When it moves to the
owner archive root, set corrections_folder_id in both publisher configurations
to that verified root; the work outputs remain bound to the work subfolder. Both publishers read that same input; neither writes it.
Only currently referenced correction targets enter the bounded registry; growing
history does not require feeding every captured message through a classifier.

## Install

Use `connect_owner.py` as described in ONBOARDING.md (Linux) or MAC_SETUP.md
(macOS). The helper handles selected-folder consent, verifies exactly `drive.file`,
and provisions the owner-bound private guide, corrections and status Docs/config.
The user creates the private root first and may name or rename it freely. Drive,
Docs and Picker APIs must be enabled for the matching Desktop OAuth application.
Existing broad grants require DRIVE_MIGRATION.md; preserve existing IDs and
correction history rather than manually recreating documents or relabeling scopes.

The examples are schemas for inspection, not a substitute for verified onboarding.
Keep the resulting config mode 0600 outside Git. The manifest creates/reuses
bounded yearly Docs with retry identities; existing chunk IDs remain allowlisted
so obsolete chunks can be cleared. Use Corrections rather than editing managed
message Docs by hand.

```sh
python3 owner_publish_cli.py --config /private/path/OWNER-full.json
```

On Linux use the existing application virtual environment and install the
minbox-owner-archive@ units. Configuration path is
`~/.config/minbox-text-archive/publishers/OWNER-full.json`.

```sh
systemctl --user daemon-reload
systemctl --user enable --now minbox-owner-archive@OWNER.timer
```

It checks sources and corrections every two minutes. Outputs use guarded writes
and readback; status acknowledges only after outputs and input revision are
verified. Unchanged evidence produces zero Drive writes and zero AI calls.
Files remain private, editable and bound to the owner/account/folder on every run.
The mirror normalizes line endings and visibly escapes characters Google strips;
original archive evidence stays unchanged. Native reads omit bulky formatting
metadata while retaining control/structure checks. Docs are limited to700k bytes
per part; oversized individual texts use cited continuations.

Use an authenticated AI Drive connector, search the exact Start Here title, and
ask for original IDs/timestamp citations. Ordinary public URL fetch cannot read
these private files. Mobile connector availability still depends on the AI account.
Users configure their preferred AI app themselves after Minbox setup. Start Here
is a user-facing guide with a copyable owner-specific prompt and an explicitly
optional retrieval confidence check; skipping that check does not block onboarding
or ongoing archive collection/publication. See ONBOARDING.md.

## Available older Android history

The live Google Messages collector stays connected with sending disabled. Initial
capture is shallow. history_backfill.py requests older records through the already
running daemon's Unix socket, never starts a competing phone session or sends.
It enumerates every locally known conversation, including empty ones, with a
private atomic checkpoint and exclusive lock. Source/import/publisher retain
existing identities when older records arrive.

```sh
python3 history_backfill.py --owner Casey --status
systemctl --user enable --now minbox-text-backfill@Casey.timer
```

Defaults:10 batches/run,2 fetches/batch,50 records/fetch,120-second budget,30-second
socket timeout,10 batches/thread. Timer runs every five minutes. Network/auth/send
safety is checked before each batch. Interrupted calls wait330 seconds because the
server can continue up to its300-second timeout; source progress is inspected
before retrying. No-progress is `available_endpoint_or_stalled`, not complete.
Repeated failures pause; caps and zero-timestamp threads remain explicit gaps.
Resolve their causes and review the private checkpoint before deliberate retries;
do not erase progress or loop endlessly. Never run another backfill client in
parallel with this worker. New known conversations enroll on later runs.

The protocol exposes no definitive end-of-history marker and initial conversation
discovery can omit threads. Full phone history, archived discovery, all SMS/MMS/RCS
cases, attachment bytes and independent encrypted backup remain unproven.

## Health

Monitor both collection and the owner-wide publisher. Add the full publisher to
health.json with `kind: "owner_all"`, `name: "OWNER"` and its private status file.
Add backfills with `owner` and the `.last-run.json` path beside its checkpoint.
Existing delivery settings remain unchanged. Deferred work-analysis input alerts
wait thirty minutes, allowing normal bounded analysis/backfill to catch up.
See HEALTH_ALERTS.md. Quiet chats are healthy; process uptime is not proof of capture.
