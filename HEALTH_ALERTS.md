# Archive recovery and emergency notifications

This technical guide helps the owner's installed coding agent keep the always-on
archive computer working. It supports the path from paired texts to useful answers
in the owner's preferred AI phone app. Start with the [beginner path](README.md#start-with-your-agent).
Use [phone acceptance](PHONE_ACCESS.md#start-with-a-small-retrieval-check) to test
answers. Healthy local services alone do not prove phone access.

**Owner:** Choose whether to receive emergency notices.
Choose and verify the destination.
Approve any account sign-in or consent.

**Agent:** Install and check the monitor below. Preserve the owner's explicit pauses.
No background AI is needed for this controller.

For health signals and recovery choices, see
[the reference guide](REFERENCE_GUIDE.md#health-that-tells-the-owner-something-useful).
This document describes the supplied Linux controller's implemented policy,
including fixed thresholds and delivery behavior. Other designs can use it as a
working example. Documentation changes do not change controller behavior.
Mac has a separate monitor in [MAC_SETUP.md](MAC_SETUP.md).

## Optional reliability checks and agent-assisted repair

Offer these after the basic setup works, according to the owner's needs.
They are not a required outage drill for every installation.

### Restart and power-loss recovery

Start with a planned restart when the owner wants this check.
Confirm that the pairing remains valid and enabled collection jobs resume.
Check the filtered output and any selected Drive publisher.
For direct phone access, include the AI desktop app and its computer registration.
Note any disk unlock, user login, or manual app launch still required.
The operating system's startup settings and the AI app's session can fail independently.

Use an actual outage record when available to assess power-return behavior and catch-up.
A planned restart does not establish recovery after every abrupt power loss.
Report any unverified case without extending normal onboarding into repeated drills.

### Safe recovery and an email that leads to action

The included controller uses ordinary code for reviewed, bounded recovery actions.
It does not need an agent model running on every poll.
Keep explicit pauses, account checks, and privacy guards intact.
Automatic retries should not re-pair accounts, change filters, or weaken permissions.

For the selected route, consider these operational checks:

- Collection remains connected and imports complete.
- Filtering or export completes and the last good output is recent enough.
- Drive publication completes when Drive is used.
- The connected AI app is available when that status can be checked reliably.

The current Linux controller covers collector, import, and configured publisher jobs.
The separate local exporter and AI connection are not automatically included.
Local export can report a successful unchanged check without replacing its files.
Monitor its last completed successful run or `checked_at` receipt, not generation age alone.
An agent can add suitable completed-run checks for the local exporter and connection checks for the AI app.
A healthy job status does not prove that every sensitive message was filtered correctly.
Do not release raw output to work around a filtering failure.

Configure optional email only with the owner's chosen recipient and consent.
One harmless delivery test confirms the destination.
For ordinary failures, try limited recovery before sending a persistent-issue notice.
Account, privacy, or integrity failures can need owner action immediately.
The implemented thresholds and notice policy are described below.
Keep message content and credentials out of alerts.

The owner can give their installed CLI this prompt after an alert:

> Diagnose the Minbox issue described in this alert on this computer.
> Inspect local status and safe diagnostics without exposing messages or credentials.
> Preserve my archive, filters, account bindings, and deliberate pauses.
> Repair what you can within my authorization.
> Ask me only for account or device actions you cannot perform.
> Confirm that the failed stage is working again and explain anything unresolved.

A local monitor cannot email while its computer or network is fully offline.
Use independent monitoring if notification during that outage matters.
A successful email test does not prove that every future failure will be detected.

## Agent installation

`health_monitor.py` observes the Linux archive computer; `health_recovery.py` runs bounded, allowlisted
recovery actions. Both use the Python standard library.
The supplied user timer runs once a minute.
Install `health_monitor.py` alongside `archive_cli.py` under `~/.local/lib/minbox-text-archive`.
Install `health_recovery.py` and `publisher_status.py` with the application modules.
Install the two units under `~/.config/systemd/user/`.
Reload user units.
Enable and start `minbox-text-health.timer`, unless it has an explicit pause.
The notification destination is configured separately. Recovery can restart an
enabled collector to reconnect; it never re-pairs a phone or changes send permissions.

Store the private config at `~/.config/minbox-text-archive/health.json` with mode 0600.
Set its containing directory to mode 0700.
Keep it outside this repository:

```json
{
  "owners": ["Casey"],
  "delivery": {"type": "none"},
  "publishers": [{
    "name": "Casey", "kind": "owner_all",
    "status_file": "~/.local/share/minbox-text-archive/publishers/Casey-full/status.json"
  }],
  "backfills": [{
    "owner": "Casey",
    "status_file": "~/.local/state/minbox-text-archive-backfill/Casey.last-run.json"
  }]
}
```

Use the actual provisioned `status_file` from the private publisher config; the
example above matches default local Linux provisioning.
Use custom paths in monitoring too.
Defaults are archive `~/.local/share/minbox-text-archive/archive.sqlite3`,
collectors `~/.local/state/minbox-text-archive-collectors`, and state directory
`~/.local/state/minbox-text-archive-health`. Optional config keys `archive`,
`collectors`, and `state_dir` override them. Owner names must consist of letters,
numbers, underscores or hyphens. Numeric collector labels in output follow the
configured owner order; keep that order stable while incidents are pending.
For two owners, set `owners` to `["Casey", "Jordan"]`.
This names monitored collection owners; it does not create local filtered exports or separate answering-agent profiles.
Configure and monitor each selected [local export](LOCAL_EXPORT.md#one-local-export-per-owner) independently.
Set `auto_enroll` to `true` for automatic inclusion.
An account is included when its pairing file, collector database or enabled collector unit exists.
Accounts with none of these are skipped. Existing databases keep an account monitored if pairing is later lost.
Notifications name the configured archive owner when a collector needs attention.
These are archive owner names, never message sender/contact identities. All use
the one configured recipient.

## Emergency notice policy

Normal operation is silent.
Failed checks first trigger safe recovery or enter the local maintenance report.
Emergency notices request human action for these conditions:

- Expired pairing or Google authorization.
- Privacy, account or integrity failures.
- Low disk space.
- An essential capture, import or full-Drive-publication outage unresolved after three recovery attempts and thirty minutes.

Missing observability that cannot be recovered also escalates after thirty minutes. A disabled schedule is never
automatically enabled; after thirty minutes it requires an operator decision.

Only one successfully delivered notice is sent per component episode.
The controller sends no reminders, transient-failure notices or recovery emails.
A relapse retains notification
deduplication until six continuous healthy hours have closed the episode. Failed
email delivery retries without marking the notice delivered. Notices contain only
fixed operational wording, configured archive owner names and recovery counts.
Message bodies, contacts, source IDs, credentials and provider error text stay out.

The optional work analysis, history backfill and Loom coverage enter local
maintenance status while the full owner archive remains available. Their ordinary
worker failures or deferred inputs do not email the owner. A privacy/integrity or
authorization failure remains a human-action condition for any configured component.

## Agent delivery setup and checks

Replace `delivery` with one schema below.
Use actual private credentials and the owner's verified destination.
Do not commit the filled config:

```json
{"type":"smtp", "host":"SMTP_HOST", "port":465, "security":"ssl",
 "from":"SENDER", "to":"DESTINATION", "username":"USERNAME", "password":"PASSWORD"}
```

SMTP defaults to `security: "ssl"` (port 465); it also supports
`security: "starttls"` (port 587), with certificate validation. `username`/`password` may be omitted for servers that
allow authenticated local policy without a login. Unencrypted SMTP is rejected.

```json
{"type":"ntfy", "url":"https://NTFY_HOST/PRIVATE_TOPIC", "token":"TOKEN"}
```

The ntfy token is optional; HTTPS is required and redirects are rejected. Use a private topic.
Configure suitable server access controls. Topic URLs and credentials
never appear in checker output. Delivery exceptions are represented by a fixed
`failed` status without exception details.

Run a local check without notifications or incident-state changes:

```sh
python3 health_monitor.py --config ~/.config/minbox-text-archive/health.json --check-only
```

After configuring the destination, send a harmless delivery test:

```sh
python3 health_monitor.py --config ~/.config/minbox-text-archive/health.json --test-notification
```

**Owner:** Confirm receipt of the test.

**Agent:** Record the result without archive content.
The delivery test contains no archive data and does not modify incident state.
Without either flag, checks update state, run eligible recovery actions, and attempt emergency notifications.
`delivery.type: "none"` suppresses delivery while preserving local emergency state.
The local `health.json` report is written regardless of notification success;
its `delivery_configured` field distinguishes awaiting setup from delivery errors.
Normal runs exit 1 for unhealthy observations or failed delivery.
They exit 2 for checker setup or state failures.
They exit 0 for a healthy run or an overlapping run skipped because the lock is held.
Systemd may therefore record a failed health service
when the underlying archive is unhealthy.
Inspect its sanitized JSON output.

## Observations and bounded recovery

The monitor checks these local signals:

- Collector service and import timer active/enabled status.
- Import service `Result`. Inactive/success is normal.
- Status RPC authentication, connection/offline state and send mode.
- Source and derived SQLite `quick_check`.
- Last import run older than ten minutes.
- Collector session file existence and mode 0600.
- Disk space below 2 GiB or 5%.

Missing source message IDs are hashed into private state and checked against
archive IDs. A record missing continuously for ten minutes raises a backlog
incident. This observation period also handles initial backfill.
Notifications contain no source IDs, contact names, message bodies or source errors.
Quiet conversations are healthy. `last_event_ms` is not a freshness check.

Recovery state persists privately across timer runs and restarts. Enabled stopped
timers are started; failed/stale publisher, import, history and Loom workers are
started without blocking the monitor. Collector disconnection gets five minutes
before a reconnect restart. Each component gets three controller attempts.
Cooldowns are 60 seconds, five minutes and fifteen minutes. Existing worker timers keep
performing their normal reconciliation retries. A queued start does not prove recovery.
The next completed observation must verify health. Active workers are
not restarted. The controller stops an unsafe sending collector or corrupt collector database once.
It then requests human review.
Archive integrity and disk failures block further automatic recovery writes.

Publisher status distinguishes `started_at`, heartbeat/phase, completed-attempt
`checked_at`, and verified `last_publication_at`/`last_success_at`. A failed attempt
updates freshness and a fixed failure category but retains the last verified
source generation and counts. Active full-owner publication has a bounded
600-second service deadline; work publication retains 360 seconds. Large Docs
reads get 90 seconds per HTTP attempt; reads retry at most three times. Writes
remain single-attempt and reconcile by fresh revision-guarded reads on the next run.
One verified output readback is consumed once rather than redundantly downloading
the same output again. Account, folder, privacy and correction checks remain fresh.
Unchanged managed Docs use persistent, account/folder-bound revision proofs to
avoid full body downloads between full verifications, which expire after 24 hours.

Optional work analysis retains its two-failure circuit breaker. Retryable failures
can make three durable half-open probes on cooldown, at most one per publisher
run; reported failure usage and unknown usage are counted. Success closes the
breaker. Explicit analysis holds and zero-call budgets remain paused. Exhaustion,
unrecognized failures and oversized inputs stay in local maintenance status,
without bypassing classification or including unresolved sources in work exports.
The owner-wide primary mirror does not depend on analysis.
Messages and Loom transcripts share the configured per-run model-call limit;
failed attempts consume that limit too. Explicit spam, personal and mixed
corrections exclude their source bodies and context before model requests. Undo
can reuse matching historical analysis. Approved overlapping context appears once
per batch; unchanged evidence keeps its existing analysis cache.

## Preserve explicit pauses

Private config may include:

```json
"recovery": {"enabled": true, "paused_components": ["publisher_1"]}
```

Slots follow the stable health configuration order. `paused_components` can also
contain the exact owned service name. Explicit pauses suppress recovery/escalation
for that component; disabled jobs are never enabled by recovery. Do not reorder
owner/publisher slots during an open episode. A stopped health timer remains
stopped until an operator resumes it.

`--check-only` observes the system and writes only the sanitized health report.
It does not run recovery, update incident state or send mail. Private
`state.json` and `health.json` record component issues, attempts, cooldowns,
maintenance states and human escalation. They use mode 0600 in a mode 0700 directory.
A lock prevents overlapping monitor runs.
Keep these files outside Git.
Automated fixes are fixed reviewed actions, not generated code deployed by a
background model. New repair policies require source review and failure tests.

## Coverage and outage limits

Quiet conversations are healthy. Source-to-archive backlog uses observed source
IDs rather than message age. A disconnected collector does not establish that
unseen texts arrived on the phone, and a successful import does not prove complete
phone coverage. This local controller cannot alert during archive-host power loss or a
complete network outage; independent external heartbeat monitoring remains a
separate requirement. Independent encrypted backup and tested restore also remain
separate from local operational recovery.

## Optional Gmail emergency delivery

**Owner:** Choose email delivery.
Create a Google app password with two-step verification enabled.
On the Linux archive computer, enter it privately through stdin to
`configure_gmail.py --address OWNER_GMAIL_ADDRESS`.
Do not put the password in command arguments, chat or Git.
Confirm receipt separately.

**Agent:** Assist without viewing or recording the password.
This setup sends one harmless delivery test.
It saves SMTP settings only after acceptance.
The address is selected by the owner; no recipient is embedded in source. Mac
uses its separate private monitor delivery settings in MAC_SETUP.md.

Changing the Google password can revoke the app password. Broken delivery remains
pending locally; it cannot send through a broken sender. See
[Google app passwords](https://support.google.com/accounts/answer/185833).

## Loom capture monitoring

Set `loom_monitor` to `true` after the Loom collector is installed and has run.
This checks its enabled/active timer, service failures, and completed-run age
(over fifteen minutes). Transcripts pending or failing for an hour raise a
per-account local maintenance incident, including failed refreshes of previously saved
transcripts. No video titles, URLs, or transcript content enter these alerts.

## Private publisher monitoring

**Agent:** Add installed publishers to the private health configuration:

```json
"publishers": [{"name": "alex-work", "status_file": "~/.local/share/minbox-text-archive/pilot/alex-analysis.last-run.json"}]
```

Each name must contain only letters, numbers, underscores or hyphens. The monitor
checks `minbox-archive-publisher@<name>.timer` is enabled and active, its service
`Result`, and the configured status file's `checked_at` age (over ten minutes).
`analysis_failed_or_paused` and deferred inputs enter local maintenance status;
completed publication failure and verified publication progress drive recovery.
Status files contain only operational fields. Reports use fixed numbered slots,
never source content or document identities. Preserve private delivery credentials when adding monitored owners or publishers.

## Owner-wide publication and older history

Owner-wide publishers use `kind: "owner_all"`, `name: "Casey"` (or another
configured owner) and their actual config status_file path in `publishers`.
This selects minbox-owner-archive@NAME; omitted kind preserves work publishers.
Add `backfills: [{"owner":"Casey","status_file":"/private/path/Casey.last-run.json"}]`
for the older-history timer/worker. Checks cover stopped schedules, failed runs,
status older than twenty minutes and threads paused after repeated failures.
Caps/endpoints remain coverage limits, not claims of full history. Notification
wording uses fixed numbered history labels and contains no conversation identities.
