# Mac / iPhone setup with a local coding agent

The read-only adapter, images and per-user installer are fixture-tested on Linux.
Live Mac/iPhone permissions, synchronization, attachment access and launchd remain
unverified. Do not call this a complete phone backup. This independent installation
uses the owner's Mac and Google account; no remote server is required.

## Start from the repository

Use any installed, signed-in CLI-capable coding agent that can read/edit files and
run local commands. The agent performs technical setup; the owner handles account
consent, Apple permissions and phone checks. No ZIP or prepared source folder is
required. Ask your agent to use this repository:

> Use https://github.com/hanster1/minbox-public to set up this Mac to sync my
> iPhone text messages to my private Google Drive archive. Read AGENTS.md,
> inspect existing state, do the technical work and explain each approval.

**Mac coding agent:** clone into `~/Projects/minbox-public` if no checkout exists.
Inspect the origin, branch and edits before updating an existing checkout. Use
reviewed current source; preserve local repairs and runtime bindings.

Casey is a generic example: use the intended owner's agreed namespace. Preserve
existing saved namespaces and settings. Read [MAC_ONBOARDING_AGENT.md](MAC_ONBOARDING_AGENT.md)
and begin existing/partial installations with [MAC_RECOVERY.md](MAC_RECOVERY.md).
Shared Linux workflows are optional. Use the ordinary Mac login, never root.

The owner installs/signs into their chosen agent if none is usable; verify one
ordinary response without private history. Login status alone proves neither quota
nor usable model access. Follow that provider's current official setup instructions.
The application needs Python 3.11+ with sqlite3; support reporting works on
standard-library Python 3.9+. Inspect architecture; avoid hardcoded Homebrew paths.
Collection/full publication require no AI runtime; optional work analysis is separate.

Bring only the matching application's Desktop OAuth client JSON privately (0600),
never another owner's refresh grant. Drive, Docs and Picker APIs must be enabled;
verify actual application publishing/test-user status. Report any unknowns honestly.
The commands below are agent references for a fresh standard installation. Existing
installs must reuse their saved paths, source, limits, publisher and pauses.

## 1. Confirm iPhone messages reach Messages on this Mac

**Mac owner and iPhone owner:** verify the Mac and iPhone use the intended Apple Account, that Messages
on the Mac has the expected conversations, and that Messages in iCloud / text
message forwarding is configured as appropriate for his devices. Wait for initial
synchronization. Verify a benign incoming and outgoing message on **both** devices.
Mac database counts alone cannot establish iPhone coverage. Do not request Apple
passwords, copy another user's database, or change his account automatically.

Apple references: [Messages in iCloud on Mac](https://support.apple.com/en-gb/guide/messages/-ichte16154fb/mac)
and [iCloud Messages setup](https://support.apple.com/en-ca/guide/icloud/mm0de0d4528d/1.0/icloud/1.0).

## 2. Prepare private runtime paths and Python

Run from the repository checkout. Replace `python3` if the selected interpreter is
elsewhere. Keep these variables in this shell; they are not credentials.

Fresh installations use `Minbox Text Archive` and `com.minbox-text-archive`
LaunchAgent labels. No live Mac installation exists yet. If an older fixture or
installation has `Family Text Archive` support, stop and review migration of its
archive, credentials, saved settings and old LaunchAgents before installing.
Do not create a new empty archive and assume it contains the retained history;
the installer refuses a fresh install when that legacy support path exists.

```bash
umask 077
archive_checkout="$PWD"
archive_support="$HOME/Library/Application Support/Minbox Text Archive"
archive_data="$archive_support/archive"
archive_legacy_support="$HOME/Library/Application Support/Family Text Archive"
if [ -e "$archive_legacy_support" ] || [ -L "$archive_legacy_support" ]; then
  echo "Legacy Family Text Archive support exists; review migration before continuing."
  exit 1
fi
mkdir -p "$archive_support"
python3 -m venv "$archive_support/venv"
archive_python="$archive_support/venv/bin/python"
mkdir -p "$archive_support/test-tmp"
export TMPDIR="$archive_support/test-tmp"
"$archive_python" -m pip install -r "$archive_checkout/requirements-mac.txt"
"$archive_python" -m unittest discover -s "$archive_checkout/tests" -q
"$archive_python" "$archive_checkout/archive_cli.py" --root "$archive_data" init --owner Casey
```

`pytypedstream` is the optional, pinned, pure Python decoder for modern binary
attributed message bodies. Without it, plain-text records still work, but binary
bodies are reported as unavailable. Unknown formats remain gaps; no guessing text
from arbitrary bytes. [Decoder upstream](https://github.com/dgelessus/python-typedstream).
The selected interpreter's full path is stored in LaunchAgents; don't replace it
with a symlink-resolved path that loses the virtual environment.

## 3. Read-only preflight and macOS permission

```bash
"$archive_python" "$archive_checkout/mac_setup.py" doctor \
  --owner Casey --archive-root "$archive_data" --python "$archive_python"
"$archive_python" "$archive_checkout/mac_messages.py" \
  --owner Casey --root "$archive_data" --check-only
```

The default source is `~/Library/Messages/chat.db`. `--database` supports an
explicit alternate source for debugging, but never copy a live SQLite database
without its WAL or assume a bare file copy is consistent. The reader opens the
source read-only with a transaction; it never sends messages or writes chat.db.
Check-only reports schema/health and makes no archive import.

**Mac owner:** if permission is denied, use **System Settings → Privacy & Security →
Full Disk Access** for the actual interpreter/application responsible for this
reader, as required by his macOS version. Restart the relevant process after a
permission change. Terminal permission may allow an interactive test while the
LaunchAgent's interpreter still fails. Test the installed scheduled job separately.
Do not bypass TCC, edit its database, disable protections or grant unrelated tools
broad access. macOS may require an additional user-visible Messages-data approval.
[Apple privacy settings](https://support.apple.com/en-au/guide/mac-help/mchl211c911f/mac).

`doctor` does not verify Apple identity, sync completeness, Google permissions or
local agent quota/access. These remain explicitly unknown until tested. Unsupported
schema means stop and adapt using column names/types and synthetic fixtures, rather
than guessing fields. Never paste message bodies or database dumps into chat/logs.

## 4. Capture once and inspect locally

```bash
"$archive_python" "$archive_checkout/mac_messages.py" \
  --owner Casey --root "$archive_data" \
  --status-file "$archive_support/collector-status.json"
"$archive_python" "$archive_checkout/archive_cli.py" --root "$archive_data" status
```

The collector preserves stable message/thread identity, original normalized imports
and content revisions. It reconciles bounded available history, including older
edited rows, and imports only new/changed records. An unchanged poll creates no
new raw import or artificial import freshness. Collector status records liveness
separately. Receipts alone do not cause another AI analysis. Previously verified binary-body
decodes are reused by content hash and decoder-policy version on later polls.

Inspect the content-free collector report for limits and body/schema gaps before
publishing. Default limits are 100,000 message rows and 64 MiB of normalized records.
`--max-messages` and `--max-bytes` can adjust bounded collection and installer
LaunchAgent plans (use the same limits on later reinstalls); exceeding
a bound aborts the whole import. Large histories are not silently declared complete. Current
bodies can be decoded; previous edit history is not reconstructed. Opaque original
attributed-body/edit-history blobs up to 512 KiB each are retained privately in
immutable normalized imports for future decoder repairs, never supplied to AI.
Oversized blobs are not backed up; recovering those requires the original Messages
database. This remains a bounded archive, not a complete Apple database backup. Reaction/system
events, recognized unsent messages and undecodable bodies stay out of AI work
notes even if someone marks them work. Available image file bytes are captured; non-image attachment bytes
are not included in this path. Source row disappearance is not proof of deletion and does not silently
erase retained evidence. Unsupported/unknown retraction behavior needs a fixture
and explicit handling before claiming it works.

Privately inspect one incoming, outgoing, group and attributed-body record, plus
an edit and unsend if available. Match benign test messages to what Messages shows;
record results without including their bodies in Git or support transcripts.

## 5. Install collection jobs, then verify launchd

Render the exact commands first. Installation copies authored Python modules into
`$archive_support/app`; configurations, archives and credentials are not copied.

```bash
"$archive_python" "$archive_checkout/mac_setup.py" plan \
  --owner Casey --archive-root "$archive_data" --python "$archive_python"
"$archive_python" "$archive_checkout/mac_setup.py" install \
  --owner Casey --archive-root "$archive_data" --python "$archive_python"
```

This first installation leaves jobs disabled. After Casey's local capture is
verified, explicitly enable collection and linked-Loom capture:

```bash
"$archive_python" "$archive_checkout/mac_setup.py" install \
  --owner Casey --archive-root "$archive_data" --python "$archive_python" --enable
launchctl print "gui/$(id -u)/com.minbox-text-archive.collector.Casey"
launchctl print "gui/$(id -u)/com.minbox-text-archive.looms.Casey"
```

Collection runs every two minutes; Loom capture every five minutes. LaunchAgents
run for the logged-in user, not as system daemons. An always-on Mac still needs an
appropriate logged-in session and available Messages sync; sleep, logout and network
outages can delay capture. Do not change sleep policy without Casey's approval.
Verify status advances and a new benign message imports through the **scheduled**
job. Then verify logout/login or reboot recovery and outage catch-up when practical.
Accessible Loom transcripts need no login; restricted videos remain explicit gaps.

Logs are private under `$archive_support/logs`. Inspect sanitized error codes and
exit status; never upload raw archives/credentials. A process appearing in launchd
is not proof it has permission or is collecting fresh messages.

## 6. Connect Casey's Drive and prepare the full archive

Collection also copies available image attachments from this Mac's Messages
attachment directory into private content-hashed storage. The full publisher
puts retained images in an Attachments child folder under the selected Drive
root and links them from their original messages, including image-only messages.
Local Tesseract OCR is optional and its extracted text is labeled as potentially
inaccurate. Images not yet downloaded by Messages/iCloud and unsupported media
remain explicit gaps. Verify one real incoming image during the Mac acceptance
check; synthetic tests do not prove Apple attachment access or synchronization.

Do this after local collection passes. Casey authorizes his own Google account on
his Mac; never transfer another person's refresh token. Install Google dependencies
into the same private environment, then connect/provision locally:

```bash
"$archive_python" -m pip install -r "$archive_checkout/requirements-google.txt"
"$archive_python" "$archive_checkout/connect_owner.py" \
  --owner Casey --account-email casey-account@example.invalid \
  --client-file /absolute/private/path/desktop-oauth-client.json \
  --archive-root "$archive_data" \
  --publisher-config "$archive_support/config/publisher.json" \
  --runtime-dir "$archive_support/publisher"
```

Replace email/client path with Casey's actual values locally. Omit --host: this
keeps Casey's credentials and archive on his Mac. Casey creates and names one private folder in his own My Drive, confirms its link,
then selects only that folder through the constrained Google Picker. The name is
his choice and can change later: the binding uses the stable folder ID. The helper
creates/reuses three native Docs (Start Here, Corrections, Status) inside that
selected root and an owner_all publisher configuration. Yearly message/Loom Docs are
created dynamically by the publisher. No manual Doc IDs or Codex login are needed
for this full private mirror. This preparation command does not publish or start
jobs. Stable config/Doc identities survive retries; existing Corrections are kept.

A Desktop OAuth client and enabled Google Drive, Docs and Picker APIs are prerequisites.
Fresh authorization must grant exactly `drive.file`, with no Sheets permission.
That grant covers selected/app-created files, not recursive access to arbitrary
files manually added under a folder. Minbox-created descendants are covered;
Minbox separately enforces the selected-root ownership/privacy/parent boundary.
External apps in Testing can require test-user enrollment and issue seven-day
Drive refresh grants. Verify the application's actual status before claiming
unattended authorization is durable; the installer does not infer it offline.
[Google OAuth documentation](https://developers.google.com/identity/protocols/oauth2).

Read [publication performance](OWNER_ARCHIVE.md#publication-performance) before
enabling the schedule. The shared publisher supports optional bounded revision
reads and part/image budgets; keep defaults until local measurements justify a
trial. Cold proofs still need full reads. On an existing Mac installation, follow
the guide's runtime-refresh and publisher-config digest/rebind procedure rather
than changing JSON and blindly running a saved-settings update. Live Linux
timings do not establish Mac/iPhone acceptance.

**Mac owner:** explicitly authorize publishing your all-captured filtered private
archive. **Mac coding agent:** run once, verify readback/filtering, then verify a
repeat with zero writes and zero model calls. Then enable its scheduled publisher separately:

```bash
"$archive_python" "$archive_checkout/owner_publish_cli.py" \
  --config "$archive_support/config/publisher.json"
"$archive_python" "$archive_checkout/mac_setup.py" install \
  --owner Casey --archive-root "$archive_data" --python "$archive_python" --enable \
  --publisher-config "$archive_support/config/publisher.json" --enable-publisher
```

owner_all selects owner_publish_cli.py and Google modules only. The older scoped
six-Doc work publisher remains supported when explicitly configured; its Codex
analysis requirements are separate. Private account/folder checks always apply.
The publisher starts only with explicit --enable-publisher. Offline installer
checks are not a substitute for actual authorized Drive read/write verification.

**Owner, phone or computer:** connect your preferred compatible mobile AI to your own
Google Drive yourself. Start Here contains archive links and copyable prompts. An
optional confidence check asks that AI to quote a familiar benign message with
its date and source Doc link through the authenticated connector. Explain that
this checks the AI connection separately from phone capture and Drive publication;
Casey can skip it without blocking onboarding. Ordinary URL fetching cannot read
private Docs. If trying correction writeback later, verify saved/read-back and
applied status; saying “recorded” alone proves neither. Personal labels retain
messages in the full archive. Keep the folder private.

## 7. Enable and verify local health monitoring

After core scheduled capture and publication checks pass, enable monitoring with
an explicit install plan using the same verified interpreter, archive, source,
collection bounds and publisher configuration already in use. The commands below
apply to the standard settings established above; retain any customized settings
instead of replacing them with defaults:

```bash
"$archive_python" "$archive_checkout/mac_setup.py" install --owner Casey \
  --archive-root "$archive_data" --python "$archive_python" --enable \
  --publisher-config "$archive_support/config/publisher.json" --enable-publisher \
  --enable-monitor --plan
"$archive_python" "$archive_checkout/mac_setup.py" install --owner Casey \
  --archive-root "$archive_data" --python "$archive_python" --enable \
  --publisher-config "$archive_support/config/publisher.json" --enable-publisher \
  --enable-monitor
"$archive_python" "$archive_checkout/mac_health.py" check --owner Casey --plan
"$archive_python" "$archive_checkout/mac_health.py" check --owner Casey
```

The per-user `com.minbox-text-archive.health.Casey` job checks every 60 seconds.
Its private default config is `$archive_support/config/health-Casey.json` with
version 1 and owner Casey; state/report live under `$archive_support/health/Casey`.
Optional delivery and paused settings stay private. Default delivery is none:
human-required notices queue locally until Casey chooses a private SMTP or ntfy
configuration. Do not copy another installation's destinations or credentials.
Later `update` commands recover and preserve the saved monitor setting; runtime
enable flags belong to an explicit reviewed `install`, not a source update.

Recovery only retries enabled, loaded, stopped jobs using `kickstart` without
`-k`. It respects pauses, never kills busy work, auto-enables jobs or guesses a
missing job's settings. A pending installer journal suppresses health actions.
Three safe attempts plus thirty minutes of unresolved essential outage lead to
one human emergency per episode; auth, TCC, privacy and integrity failures require
human attention immediately. Optional Loom/work-analysis failures remain local.
There are no routine, reminder or recovery emails. Local monitoring cannot send
while the Mac sleeps, loses network, or stops running; external heartbeat remains
unproven. See [MAC_RECOVERY.md](MAC_RECOVERY.md) for triage and continuation.

## Troubleshooting and safe updates

Inspect Git status, origin and the intended branch, fetch, then review the incoming
revision before updating. Fast-forward only when appropriate; preserve local fixes
and reconcile divergence deliberately. Never reset or force an update. Source
updates and dependency updates are separate from runtime recovery.

From the new checkout, use the existing private Python environment to run tests,
preview the installed refresh, then apply it:

```bash
archive_support="$HOME/Library/Application Support/Minbox Text Archive"
archive_python="$archive_support/venv/bin/python"
mkdir -p "$archive_support/test-tmp"
export TMPDIR="$archive_support/test-tmp"
"$archive_python" -m unittest discover -s tests -q
"$archive_python" mac_setup.py update --owner Casey \
  --archive-root "$archive_support/archive" --plan
"$archive_python" mac_setup.py update --owner Casey \
  --archive-root "$archive_support/archive"
```

Use the actual existing environment/archive paths if customized. The update
recovers the saved Python, Messages source, collection limits, publisher config
and enabled state from verified installed files. It preserves a disabled publisher
and refuses inconsistent collector/Loom pause states. Edited or untracked files
and changed publisher configuration need review before updating. Older installs
without a publisher-config binding need one reviewed `install` with their exact
original settings first. The helper does not fetch Git, change dependencies,
request Google consent or publish messages as a test.

Source compilation and read-only preflight happen before the application refresh.
An installation failure restores the previous tracked files and jobs; an explicit
rollback-incomplete result requires local inspection. This does not roll back
archive content or Google Docs, and successful launchctl calls do not prove live
message capture or Drive access. After updating, verify scheduled collector status
and Drive Publisher Status advance, and record the actual results. Dependency
changes require separate reviewed installation into the existing environment.

- **Interactive works, launchd fails:** inspect the actual ProgramArguments Python,
  logged-in user, Full Disk Access context, status-file freshness and launchd exit
  status. Launchd has an explicit PATH but not your shell profile. Reinstall from
  the checkout after changes; edit the checkout, not tracked installed copies.
- **No messages / wrong history:** verify Apple identity and sync in Messages,
  source path, database schema, bounded coverage and iPhone forwarding. Do not
  treat a successful SQLite connection as a complete phone export.
- **Binary bodies unavailable:** check typedstream import using the selected Python,
  pinned dependency, reported format/size reason and Mac schema. Retain bounded original blobs in the private archive; recover oversized originals
  only from an owner-authorized consistent Messages database backup. Build a minimal synthetic fixture for any decoder change.
- **Model unavailable / analysis paused:** verify the configured Codex executable
  works in the scheduled environment and uses Casey's login. Inspect the actual
  analysis error before resetting any failure hold; do not loop expensive retries.
- **Google failures:** distinguish OAuth/expired refresh credentials, disabled Docs
  API, wrong account, non-private folder or moved/shared Docs. Reconnect as Casey
  without overwriting a different owner's credentials. Never paste tokens.
- **Installer refuses modified tracked files:** preserve/review the local changes
  and installation manifest. Do not blindly overwrite them or delete the archive.
  Reconcile authored source in the checkout; update hashes only after reviewing
  the exact tracked change. Do not manipulate another application's LaunchAgents.
- **Already stopped job / launchctl error:** inspect this installation's labels
  with `launchctl print gui/UID/LABEL`. Distinguish absent jobs from permission or
  session failures. The installer restores tracked files/jobs on failed updates;
  if rollback reports a problem, inspect this owner’s collector, Loom, publisher and health labels before retrying.

To stop and remove this installation's jobs while preserving archive, credentials,
logs, caches, virtual environment and installed code:

```bash
"$archive_python" "$archive_checkout/mac_setup.py" uninstall \
  --owner Casey --archive-root "$archive_data" --python "$archive_python"
```

One owner installation per Mac login is currently supported. Use separate OS user
accounts for independent clients; owner namespaces alone are not an access-control
boundary. Local snapshots are recovery copies, not independent encrypted offsite
backup. This setup affects only the owner's Mac.

## Copyable agent prompt

> Let's get Casey set up on Minbox. Read AGENTS.md and
> MAC_ONBOARDING_AGENT.md, then inspect this Mac and resume the current stage.
> Use owner Casey and my ordinary Mac login. Do the necessary technical work;
> ask me only for missing identity/account details and required Apple/Google
> approvals or benign phone checks. Keep private history and credentials local,
> preserve existing settings and IDs, and leave a tested continuation checkpoint.

For an interruption or later failure, use the recovery prompt in
[MAC_RECOVERY.md](MAC_RECOVERY.md).
