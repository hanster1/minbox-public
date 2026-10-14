# Archive recovery and emergency notifications

`health_monitor.py` observes the Linux archive computer; `health_recovery.py` runs bounded, allowlisted
recovery actions. Both use the Python standard library.
The supplied user timer runs once a minute. Install the script alongside
`archive_cli.py` under `~/.local/lib/minbox-text-archive` and the two units under
`~/.config/systemd/user/`. Reload user units, then enable/start
`minbox-text-health.timer`. Install `health_recovery.py` and `publisher_status.py` with the application modules.
The notification destination is configured separately. Recovery can restart an
enabled collector to reconnect; it never re-pairs a phone or changes send permissions.

Store the private config at `~/.config/minbox-text-archive/health.json`, mode 0600,
with its containing directory mode 0700. Keep it outside this repository:

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
example above matches default local Linux provisioning. Custom paths must be
reflected in monitoring. Defaults are archive `~/.local/share/minbox-text-archive/archive.sqlite3`,
collectors `~/.local/state/minbox-text-archive-collectors`, and state directory
`~/.local/state/minbox-text-archive-health`. Optional config keys `archive`,
`collectors`, and `state_dir` override them. Owner names must consist of letters,
numbers, underscores or hyphens. Numeric collector labels in output follow the
configured owner order; keep that order stable while incidents are pending.
Set `owners` to `["Casey", "Jordan"]` and
`auto_enroll` to `true` to include each account once its pairing file, collector
database, or enabled collector unit exists. Accounts with none of those are
skipped. Existing databases keep an account monitored if pairing is later lost.
Notifications name the configured archive owner when a collector needs attention.
These are archive owner names, never message sender/contact identities. All use
the one configured recipient.

Normal operation is silent. Failed checks first trigger safe recovery or enter the
local maintenance report. Email is reserved for human action: expired pairing or
Google authorization, privacy/account/integrity failures, low disk space, or an
essential capture/import/full-Drive-publication outage still unresolved after
three recovery attempts and thirty minutes. Missing observability that cannot be
recovered also escalates after thirty minutes. A disabled schedule is never
automatically enabled; after thirty minutes it requires an operator decision.

Only one successfully delivered notice is sent per component episode. No reminder,
transient failure, or recovery emails are sent. A relapse retains notification
deduplication until six continuous healthy hours have closed the episode. Failed
email delivery retries without marking the notice delivered. Notices contain only
fixed operational wording, configured archive owner names and recovery counts.
Message bodies, contacts, source IDs, credentials and provider error text stay out.

The optional work analysis, history backfill and Loom coverage enter local
maintenance status while the full owner archive remains available. Their ordinary
worker failures or deferred inputs do not email the owner. A privacy/integrity or
authorization failure remains a human-action condition for any configured component.

Replace `delivery` with either of these schemas using actual private credentials
and a verified destination. Do not commit the filled config:

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

The ntfy token is optional; HTTPS is required and redirects are rejected. Use a
private topic with suitable server access controls. Topic URLs and credentials
never appear in checker output. Delivery exceptions are represented by a fixed
`failed` status without exception details.

Run a local check without notifications or incident-state changes:

```sh
python3 health_monitor.py --config ~/.config/minbox-text-archive/health.json --check-only
```

After configuring the destination, explicitly send a harmless delivery test:

```sh
python3 health_monitor.py --config ~/.config/minbox-text-archive/health.json --test-notification
```

The delivery test contains no archive data and does not modify incident state.
Without either flag, checks update state, run eligible recovery actions, and attempt emergency notifications.
`delivery.type: "none"` suppresses delivery while preserving local emergency state.
The local `health.json` report is written regardless of notification success;
its `delivery_configured` field distinguishes awaiting setup from delivery errors.
Normal runs exit 1 for unhealthy observations or failed delivery, 2 for checker
setup/state failures, and 0 for a healthy run (including overlapping runs skipped
because the lock is held). Systemd may therefore record a failed health service
when the underlying archive is unhealthy; consult its sanitized JSON output.

Checks include collector service and import timer active/enabled status, import
service `Result` (inactive/success is normal), status RPC authentication,
connection/offline and send mode, source/derived SQLite `quick_check`, last import
run older than ten minutes, collector session file existence and mode 0600,
and disk space below 2 GiB or 5%. Missing source message IDs are hashed into private
state and checked against archive IDs; a record missing continuously for ten
minutes raises a backlog incident. This observation grace also handles initial
backfill. No source IDs, contact names, message bodies or source errors enter notifications.
Quiet conversations are healthy; `last_event_ms` is not a freshness check.

Recovery state persists privately across timer runs and restarts. Enabled stopped
timers are started; failed/stale publisher, import, history and Loom workers are
started without blocking the monitor. Collector disconnection gets five minutes
before a reconnect restart. Each component gets three controller attempts, with
60-second, five-minute and fifteen-minute cooldowns. Existing worker timers keep
performing their normal reconciliation retries. Queuing a start is not proof of
recovery: the next completed observation must verify health. Active workers are
not restarted. An unsafe sending collector or corrupt collector database is
quarantined by stopping that collector once, then escalated for human review.
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

Private config may include:

```json
"recovery": {"enabled": true, "paused_components": ["publisher_1"]}
```

Slots follow the stable health configuration order. `paused_components` can also
contain the exact owned service name. Explicit pauses suppress recovery/escalation
for that component; disabled jobs are never enabled by recovery. Do not reorder
owner/publisher slots during an open episode. A stopped health timer remains
stopped until an operator resumes it.

`--check-only` performs observations and writes only the sanitized health report;
it never executes recovery, updates incident state or sends mail. Private
`state.json` and `health.json` record component issues, attempts, cooldowns,
maintenance states and human escalation. They use mode 0600 in a mode 0700
directory and a lock prevents overlapping monitor runs. Keep these outside Git.
Automated fixes are fixed reviewed actions, not generated code deployed by a
background model. New repair policies require source review and failure tests.

Quiet conversations are healthy. Source-to-archive backlog uses observed source
IDs rather than message age. A disconnected collector does not establish that
unseen texts arrived on the phone, and a successful import does not prove complete
phone coverage. This local controller cannot alert during archive-host power loss or a
complete network outage; independent external heartbeat monitoring remains a
separate requirement. Independent encrypted backup and tested restore also remain
separate from local operational recovery.

## Optional Gmail emergency delivery

After the owner chooses email delivery, create a Google app password (two-step
verification required). On the Linux archive computer, pass it privately on stdin
to `configure_gmail.py --address OWNER_GMAIL_ADDRESS`; do not put the password in
command arguments, chat or Git. This explicit setup sends one harmless delivery
test and saves SMTP settings only after acceptance. Confirm receipt separately.
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

Add installed publishers to the private health configuration:

```json
"publishers": [{"name": "alex-work", "status_file": "~/.local/share/minbox-text-archive/pilot/alex-analysis.last-run.json"}]
```

Each name must contain only letters, numbers, underscores or hyphens. The monitor
checks `minbox-archive-publisher@<name>.timer` is enabled and active, its service
`Result`, and the configured status file's `checked_at` age (over ten minutes).
`analysis_failed_or_paused` and deferred inputs enter local maintenance status;
completed publication failure and verified publication progress drive recovery.
Status files contain only operational fields. Reports use fixed numbered slots,
never source content or document identities. Keep private delivery credentials
unchanged when adding monitored owners or publishers.

## Owner-wide publication and older history

Owner-wide publishers use `kind: "owner_all"`, `name: "Casey"` (or another
configured owner) and their actual config status_file path in `publishers`.
This selects minbox-owner-archive@NAME; omitted kind preserves work publishers.
Add `backfills: [{"owner":"Casey","status_file":"/private/path/Casey.last-run.json"}]`
for the older-history timer/worker. Checks cover stopped schedules, failed runs,
status older than twenty minutes and threads paused after repeated failures.
Caps/endpoints remain coverage limits, not claims of full history. Notification
wording uses fixed numbered history labels and contains no conversation identities.
