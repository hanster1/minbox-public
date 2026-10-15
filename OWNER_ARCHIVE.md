# Owner-wide private text archive

This technical guide covers optional Google Drive publication on the always-on
archive computer. Drive is one route to answers in the owner's preferred AI phone
app. Start with the [beginner path](README.md#start-with-your-agent).
Use [phone acceptance](PHONE_ACCESS.md#start-with-a-small-retrieval-check) to check
answers from the phone.

The owner chooses the destination and approves account access. The owner's
installed coding agent performs the technical steps below. Owner actions are
marked explicitly. The full publisher needs no runtime AI.

The normal private view includes captured personal, work, mixed and unclassified
conversations that pass the filters. It does not wait for AI classification or a
review queue. The optional work view keeps narrower eligibility rules, its
analysis cache and existing citations.

Files are named `OWNER Text Archive`, for example `Casey Text Archive`, in the
owner's restricted Google Drive folder. The Start Here Doc links yearly Messages
Docs, continuation parts, retained-origin Loom transcripts, the designated
Corrections Doc and Publisher Status. Stable source/message IDs support citations.
A chronological index makes date coverage visible. Optional work outputs may
live in a managed private child folder. Filtered source bodies, phone pairing
credentials and OAuth tokens never enter the published Docs.

## Filtering and corrections

Local filters exclude authentication codes, recognized password-reset links and
clear opt-out promotional spam before publication. These rules cannot detect every
secret or scam. See the [privacy guidance](REFERENCE_GUIDE.md) before exposing an
archive to a setup agent or an AI app. Explicit spam corrections are durable, including when
the entry disappears from the input Doc. A work/personal correction cannot bypass
an active spam correction; use an explicit undo. Personal corrections retain a
text in the full private view while withdrawing it from work exports.

Use the existing Corrections Doc when migrating from a work pilot.
Initialize the full-view ledger once from a consistent SQLite backup of the old ledger.
Preserve correction and undo history.
Never overwrite the full ledger on later runs.
Configure its actual folder separately from work outputs.
If it moves to the archive root, set `corrections_folder_id` in both publisher configurations to that verified root.
Keep work outputs bound to the work subfolder.
Both publishers read that same input. Neither publisher writes it.
Only currently referenced correction targets enter the bounded registry; growing
history does not require feeding every captured message through a classifier.

## Install

**Owner:** Create the private root first. Choose or rename it freely.
Approve selected-folder consent during onboarding.

**Agent:** Use `connect_owner.py` through [ONBOARDING.md](ONBOARDING.md) on Linux
or [MAC_SETUP.md](MAC_SETUP.md) on macOS.
The helper verifies exactly `drive.file`.
It provisions the owner-bound private guide, Corrections Doc, status Doc and config.
Enable Drive, Docs and Picker APIs for the matching Desktop OAuth application.
For existing broad grants, follow [DRIVE_MIGRATION.md](DRIVE_MIGRATION.md).
Preserve existing IDs and correction history.
Do not recreate documents or relabel scopes.

The examples are schemas for inspection, not a substitute for verified onboarding.
Keep the resulting config outside Git with mode 0600. The manifest creates/reuses
bounded yearly Docs with retry identities; existing chunk IDs remain allowlisted
so obsolete chunks can be cleared. Use Corrections rather than editing managed
message Docs by hand.

```sh
python3 owner_publish_cli.py --config /private/path/OWNER-full.json
```

On Linux use the existing application virtual environment and install the
minbox-owner-archive@ units.
Preserve explicit pauses when enabling schedules.
Configuration path is
`~/.config/minbox-text-archive/publishers/OWNER-full.json`.

```sh
systemctl --user daemon-reload
systemctl --user enable --now minbox-owner-archive@OWNER.timer
```

It checks sources and corrections every two minutes. Outputs use guarded writes
and readback; status acknowledges only after outputs and input revision are
verified. Unchanged evidence produces zero Drive writes and zero AI calls.
Private document verification caches keep content hashes and Google revision IDs,
not message bodies. After a full verification, unchanged outputs need only a small
revision check for up to 24 hours. Changed revisions, expired proofs and first runs
require full reads. A warm changed output can reuse verified structure only at
its unchanged revision; writes remain revision-guarded and require full exact
structural readback. Corrections and destination permissions are checked afresh.
Cache state is bound to the owner, Google account and configured folders outside
Git. Removing it safely returns publication to full verification.
Spam-image cleanup resolves old image references against a fresh paged listing
of the managed image folder, avoiding separate searches for images already gone.
Deletion identity checks and pending-deletion reconciliation remain mandatory.
Files remain private, editable and bound to the owner/account/folder on every run.
The mirror normalizes line endings and visibly escapes characters Google strips;
original archive evidence stays unchanged. Native reads omit bulky formatting
metadata while retaining control/structure checks. Message/Loom parts default to
700000 UTF-8 bytes; oversized individual texts use cited continuations. See
[publication performance](#publication-performance) before tuning those bounds
or enabling concurrent revision checks.

**Owner:** Configure an authenticated AI Drive connector in your preferred AI app.
Search for the exact Start Here title.
Ask for original IDs and timestamp citations. Ordinary public URL fetch cannot read
these private files. Mobile connector availability still depends on the AI account.
The owner approves this separate connection after archive setup. Start Here
is a user-facing guide with a copyable owner-specific prompt and an explicitly
optional retrieval confidence check. Collection and publication can run without
that check. The full setup still needs a known-message answer and a fresh-read
test from the phone. A successful Drive publication alone does not complete the
owner's goal. See [PHONE_ACCESS.md](PHONE_ACCESS.md) and [ONBOARDING.md](ONBOARDING.md).

## Publication performance

**Agent:** Use this procedure before scheduling a new `owner_all` publisher or repairing slow publication. It applies to the shared
Python publisher on Linux and macOS; use the actual owner's environment, config
and installed source. No other computer's tools, credentials, global agent
instructions or private operating notes are prerequisites.

### Establish what is slow

Keep defaults for a small archive that completes comfortably. First publication
and expired proofs require full verification; concurrent revision checks cannot
accelerate that work. Complete an initial verified publication to create verification proofs.
Then measure an unchanged repeat. An idle repeat needs zero output writes and
zero AI calls, but still makes verification requests.

Record elapsed time, chunk count, cold versus warm proofs, completed timestamps,
sanitized failure categories and pending image counts. Use private status fields
`phase` and `heartbeat_at` to distinguish validation, images, `revision_prefetch`,
`output_verification` and final status. A heartbeat proves activity, not completion.
An import/work job exiting zero with `owner_busy` skipped work while the full
publisher held the owner lock; check actual completed import/publication times.

Some native Docs requests can be slow even when asking only for a revision ID.
A timeout alone does not establish quota throttling or an authentication failure.
Inspect explicit rate-limit/authentication errors and collector connectivity
before changing credentials. Do not re-pair a working phone to repair slow Docs.

### Tune the existing private configuration

These are optional fields in the existing owner_all publisher JSON, not flags
for `connect_owner.py` or `owner_publish_cli.py`. Merge only reviewed fields;
never replace the complete config with this table or copy another owner's file.

| Field | Default | Supported values | When to consider it |
| --- | --- | --- | --- |
| `revision_probe_workers` | `1` | Integer `1` through `3` | Many unchanged parts whose independent revision reads accumulate delays. |
| `max_document_bytes` | `700000` | Integer `1024` through `700000` | Smaller Message/Loom parts; `100000` is a measured repair option, not a universal default. |
| `max_image_attempts` | `5` | Integer `1` through `20` | Reduce new image attempts ahead of text publication; `1` can bound that work. |

Change one setting at a time when possible.
Keep a private rollback copy with mode 0600.
Preserve owner, account, root, Doc and correction bindings.
Do not regenerate consent or initialize another archive.
Do not delete verification proofs or weaken privacy checks.

**Existing Mac installations:** Git changes do not update installed Python modules.
Wait for active owned jobs to finish before applying `update` or `install`.
These commands briefly unload and reload managed jobs. They can interrupt active publication.
First follow the saved-settings `update --plan` procedure in
[MAC_SETUP.md](MAC_SETUP.md#troubleshooting-and-safe-updates).
Then apply the reviewed `update` while the publisher JSON still matches its recorded digest.
A later config edit changes that digest.
Review a new `plan`/`install` to bind the reviewed JSON again.
Preserve the exact interpreter, archive, Messages source, collection limit, publisher and enabled/paused settings. Do not bypass the digest check or reinstall with
fresh defaults. The same reconciliation applies when rolling back a config edit.
Use [MAC_RECOVERY.md](MAC_RECOVERY.md) for inconsistent or interrupted installs.

### Compare bounded revision checks

For a read-only comparison, first verify the normal account, root and parent binding.
Use only allowlisted output `GET` requests for `fields=revisionId`.
Exclude Corrections from the benchmark.
Never create disposable archive replacements.
Never log access tokens, Doc IDs or bodies.
Do not use `owner_publish_cli.py` as a read-only tool.
That command can publish changed content.

Compare the same parts sequentially.
Then compare them with up to three workers. Include all
parts when a small sample misses the stalls. Reverse the order for a second
comparison because earlier requests can warm Google's backend. Use comparable timeouts, retry policies and finite overall budgets.
Record failures and elapsed time. A faster pass with more unresolved requests is not a verified win.
Keep at most three reads in flight and one logical request launch per second;
the transport's bounded read retries are separate. Never run competing full publishers.
Do not interrupt busy work.
Restore prior job states after the experiment.

If measurements support a trial, merge this fragment into the existing private
config after the reviewed runtime update:

```json
{
  "revision_probe_workers": 3
}
```

Only fresh proofs matching the desired chunk hash qualify. Workers read revisions;
they do not write documents or cache proofs. Results are confined to one run,
consumed once and checked against the current exact proof/hash/age. They cannot
extend the 24-hour full-verification age. Changed revisions still require strict
reads; changed outputs retain guarded writes and full post-write readback.
Corrections, guide/status verification and full structural reads stay sequential.
The owner lock remains, so imports still wait until publication releases it.

### Smaller parts and image budgets

Smaller parts retain existing Doc IDs, source originals, correction bindings and
native history, but create more parts and more requests. Sources can move between
parts, so an old link can refer to changed content. Before migrating, keep a private rollback copy.
Preview rendered part counts and coverage without Drive writes.
Use copied correction state for the preview.
Do not change the live ledger for a preview.
Existing large Docs still need successful guarded reconciliation before they
shrink. Preserve verified partial progress.
Let the normal publisher finish all parts and Start Here.
A partial migration is not complete publication.

For a new large archive, consider the part size before creating large Docs;
still measure the result rather than assuming more, smaller Docs are faster.
The configured part size does not lower the separate 700000-byte guide/status
ceiling. Reducing image attempts does not disable verified-image checks or prove
that the pending backlog is draining. Attempts are newest-first; repeated failures
can consume the budget and delay older images. Revisit a reduced budget once text
publication stabilizes, using actual media progress and remaining runtime margin.
Keep pending/unavailable media explicit.

The optional `DocsClient.replace_verified(previous_text=...)` path is an advanced
operator repair. It is not an automatic onboarding step.
The canonical old body must match a fresh bound proof.
The single literal replacement must have a revision guard.
The response must report exactly one match.
Full structural readback is required.
Never blindly repeat an uncertain write.
Do not substitute a differently formatted export for that old body.

### Accept or roll back using completed work

Record original job and recovery pauses before maintenance.
Preserve all explicit pauses.
Pause only affected publication schedules and matching recovery actions if needed. Keep collection
running during read-only benchmarks and publication trials; a reviewed runtime
refresh can briefly unload jobs after busy work finishes. Never kill a busy
publisher. Restore prior states after the trial.
Use the actual platform scheduler; Linux systemd commands are not Mac commands.

Accept a tuning change only after all these checks pass:

- A complete publication reports `run_state: succeeded` and `phase: complete`.
- Its `checked_at` and `last_publication_at` advance.
- Imports catch up after the owner lock releases.
- A later automatic publication succeeds with useful margin under its actual runtime budget.

The provided Linux service budget is 600 seconds; inspect the actual Mac jobs
rather than assuming that deadline applies there. Verify local health afterward.
Do not raise staleness thresholds to silence an alert.
Do not clear failures or extend deadlines for that purpose. Preserve pending-media and untested-device limits.

If the trial is slower or less reliable, restore the reviewed config (worker
value `1`, or omit the field) and prior schedules, retaining archives, manifests,
proofs and private receipts. Removing the field does not undo a part migration or
already completed Drive writes. Keep one concrete next action for unresolved work.

One Linux installation completed full publication in 3m04s and an automatic
repeat in 4m33s after bounded concurrent checks, following 9m48s runs and repeated
timeouts. Those are observations, not a throughput promise. Provider latency,
cold proofs, changed content and media work still affect duration. The common
code has synthetic coverage; live Mac/iPhone acceptance remains unverified.

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

Defaults: 10 batches/run, 2 fetches/batch, 50 records/fetch, 120-second budget,
30-second socket timeout and 10 batches/thread. The timer runs every five minutes.
Network, authorization and send safety are checked before each batch.
Interrupted calls wait 330 seconds. The server can continue until its 300-second timeout.
Inspect source progress before retrying. No-progress is `available_endpoint_or_stalled`, not complete.
Repeated failures pause; caps and zero-timestamp threads remain explicit gaps.
Resolve their causes before deliberate retries.
Review the private checkpoint.
Do not erase progress or retry without a limit. Never run another backfill client in
parallel with this worker. New known conversations enroll on later runs.

The protocol exposes no definitive end-of-history marker and initial conversation
discovery can omit threads. Full phone history, archived discovery, all SMS/MMS/RCS
cases, attachment bytes and independent encrypted backup remain unproven.

## Health

Monitor both collection and the owner-wide publisher. Add the full publisher to private
`health.json` with `kind: "owner_all"`, `name: "OWNER"` and its private status file.
Add backfills with `owner` and the `.last-run.json` path beside its checkpoint.
Existing delivery settings remain unchanged. Deferred work-analysis input alerts
wait thirty minutes, allowing normal bounded analysis/backfill to catch up.
See HEALTH_ALERTS.md. Quiet chats are healthy; process uptime is not proof of capture.

## Android phone spam exclusions

An explicitly enabled `phone_spam_policy: "spam_and_blocked"` excludes whole
Google Messages conversations observed in the phone's Spam & blocked folder.
See PHONE_SPAM.md for the signal, setup and limits. Local originals and revisions
remain; the publisher removes current Drive text and dependent outputs and
permanently deletes matching managed image files. Exclusions prevent ordinary
history/backfill or stale updates from republishing them. Moving a conversation
out of the phone folder restores eligible content only after a fresh, guarded
status confirmation; retained originals supply its texts and images. This is separate
from a Corrections Doc spam label, which remains a publication filter.
