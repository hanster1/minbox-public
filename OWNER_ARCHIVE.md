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

Use an authenticated AI Drive connector, search the exact Start Here title, and
ask for original IDs/timestamp citations. Ordinary public URL fetch cannot read
these private files. Mobile connector availability still depends on the AI account.
Users configure their preferred AI app themselves after Minbox setup. Start Here
is a user-facing guide with a copyable owner-specific prompt and an explicitly
optional retrieval confidence check; skipping that check does not block onboarding
or ongoing archive collection/publication. See ONBOARDING.md.

## Publication performance

Local coding agents should use this procedure before enabling a new owner_all
publisher's schedule, or when repairing slow publication. It applies to the shared
Python publisher on Linux and macOS; use the actual owner's environment, config
and installed source. No other computer's tools, credentials, global agent
instructions or private operating notes are prerequisites.

### Establish what is slow

Keep defaults for a small archive that completes comfortably. First publication
and expired proofs require full verification; concurrent revision checks cannot
accelerate that work. Complete an initial verified publication to seed proofs,
then measure an unchanged repeat. An idle repeat needs zero output writes and
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

Change one setting at a time when possible. Preserve a private config rollback,
mode 0600 and owner/account/root/Doc/correction bindings. Do not regenerate consent,
initialize another archive, delete verification proofs or weaken privacy checks.

**Existing Mac installations:** Git changes do not update installed Python modules.
Wait for active owned jobs to finish before applying `update` or `install`; these
commands briefly unload/reload managed jobs and can interrupt active publication.
First use the reviewed saved-settings `update --plan`, then `update` procedure in
[MAC_SETUP.md](MAC_SETUP.md#troubleshooting-and-safe-updates) while the existing
publisher JSON still matches its recorded digest. A later config edit changes
that digest: review a new `plan`/`install` using every exact preserved interpreter,
archive, Messages source, collection limit, publisher and enabled/paused setting
to rebind the reviewed JSON. Do not bypass the digest check or reinstall with
fresh defaults. The same reconciliation applies when rolling back a config edit.
Use [MAC_RECOVERY.md](MAC_RECOVERY.md) for inconsistent or interrupted installs.

### Compare bounded revision checks

For a read-only comparison, first verify the normal account/root/parent binding,
then use only allowlisted output `GET` requests for `fields=revisionId`. Exclude
Corrections from the benchmark. Never create disposable archive replacements,
log access tokens/Doc IDs/bodies, or treat `owner_publish_cli.py` as a read-only
tool: that command can publish changed content.

Compare the same parts sequentially and with up to three workers. Include all
parts when a small sample misses the stalls. Reverse the order for a second
comparison because earlier requests can warm Google's backend. Keep timeouts,
retry policy and a finite overall budget comparable; record failures as well as
elapsed time. A faster pass with more unresolved requests is not a verified win.
Keep at most three reads in flight and one logical request launch per second;
the transport's bounded read retries are separate. Never run competing full
publishers, interrupt busy work or leave jobs paused after the experiment.

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
parts, so an old link can refer to changed content. Before migrating, keep a
private rollback and preview rendered part counts/coverage without Drive writes,
using copied correction state rather than changing the live ledger for a preview.
Existing large Docs still need successful guarded reconciliation before they
shrink. Preserve verified partial progress and let the normal publisher finish
all parts and Start Here; a partial migration is not complete publication.

For a new large archive, consider the part size before creating large Docs;
still measure the result rather than assuming more, smaller Docs are faster.
The configured part size does not lower the separate 700000-byte guide/status
ceiling. Reducing image attempts does not disable verified-image checks or prove
that the pending backlog is draining. Attempts are newest-first; repeated failures
can consume the budget and delay older images. Revisit a reduced budget once text
publication stabilizes, using actual media progress and remaining runtime margin.
Keep pending/unavailable media explicit.

The optional `DocsClient.replace_verified(previous_text=...)` path is an advanced
operator repair, not automatic onboarding: it requires the canonical old body
to match a fresh bound proof, a revision-guarded single literal replacement,
exactly one reported match and full structural readback. Never blindly replay an
uncertain write or substitute a differently formatted export for that old body.

### Accept or roll back using completed work

Preserve original job/recovery pauses before maintenance. Pause only affected
publication schedules and matching recovery actions if needed. Keep collection
running during read-only benchmarks and publication trials; a reviewed runtime
refresh can briefly unload jobs after busy work finishes. Never kill a busy
publisher. Restore prior states after the trial.
Use the actual platform scheduler; Linux systemd commands are not Mac commands.

Accept a tuning change only after a complete publication reports
`run_state: succeeded`, `phase: complete` and advanced `checked_at` and
`last_publication_at`, imports catch up after the lock releases, and a subsequent
automatic publication succeeds with useful margin under its real runtime budget.
The provided Linux service budget is 600 seconds; inspect the actual Mac jobs
rather than assuming that deadline applies there. Verify local health afterward.
Do not raise staleness thresholds, clear failures or extend deadlines just to
silence an alert. Preserve pending-media and untested-device limits.

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
