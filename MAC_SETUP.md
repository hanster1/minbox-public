# Mac / iPhone setup with a local coding agent

Use this technical recipe to collect iPhone texts on an always-on Mac and build
a filtered archive. The owner can then ask a preferred phone AI app questions
about it. Start with [README](README.md). Finish with the phone checks in
[PHONE_ACCESS](PHONE_ACCESS.md). Use [REFERENCE_GUIDE](REFERENCE_GUIDE.md) for
storage choices, access choices and privacy boundaries.

**Prerequisites:** an installed coding agent CLI with a capable reasoning model
and working model access; the owner's ordinary Mac login; Python 3.11+ with
sqlite3; Git; private runtime storage; and iPhone messages synced to Messages on
this Mac. The Mac needs an available logged-in session for scheduled collection.
The support report alone can use standard-library Python 3.9+.
For the Drive recipe in section 6, also prepare the application in GOOGLE_SETUP.md.
Drive is one publication option. A different phone access path needs its own
implementation and acceptance checks.

**Agent:** run the commands and inspect the results. **Owner:** handle sign-in,
account consent, macOS permission prompts and phone checks. Commands below are
references for the agent, not a command checklist for the owner.

The read-only adapter, images and per-user installer are fixture-tested on Linux.
Live Mac/iPhone permissions, synchronization, attachment access and launchd remain
unverified. Do not call this a complete phone backup. This independent installation
uses the owner's Mac and Google account; no remote server is required.

## Start from the repository

Use any installed, signed-in CLI-capable coding agent that can read/edit files and
run local commands. The agent performs technical setup; the owner handles account
consent, Apple permissions and phone checks. No ZIP or prepared source folder is
required. Ask your agent to use this repository:

> Use https://github.com/hanster1/minbox-public to collect my iPhone texts on
> this Mac and build a filtered archive that my preferred phone AI app can use.
> Read AGENTS.md and the platform guides. Inspect existing state, help choose
> an access path, do the technical work and explain each required approval.

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

**Mac owner and iPhone owner:** confirm the intended Apple Account on both devices.
Check that Messages on the Mac shows the expected conversations. Check Messages
in iCloud and text message forwarding as needed for these devices. Wait for the
initial sync. Compare a harmless incoming and outgoing message on **both** devices.
Mac database counts alone do not prove iPhone coverage.
**Agent:** do not request Apple passwords. Do not copy another user's database.
Do not change the owner's Apple account automatically.

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

**Mac owner:** if permission is denied, open **System Settings → Privacy & Security →
Full Disk Access**. Approve the actual interpreter or application responsible for
this reader as required by your macOS version. Restart the affected process after
a permission change. Terminal permission can pass an interactive test while the
LaunchAgent interpreter still fails. Test the installed scheduled job separately.
Do not bypass TCC. Do not edit its database or disable protections.
Do not grant unrelated tools broad access. macOS can require an additional
user-visible Messages-data approval.
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

The collector preserves stable message and thread identity. It retains original
normalized imports and content revisions. It reconciles available history within
its bounds, including older edited rows. It imports only new or changed records.
An unchanged poll creates no new raw import or artificial import freshness.
Collector status records liveness separately. Receipts alone do not cause another
AI analysis. Later polls reuse verified binary-body decodes by content hash and
decoder-policy version.

Before publication, inspect the content-free collector report for limits and
body/schema gaps. Default limits are 100,000 message rows and 64 MiB of normalized
records. Use `--max-messages` and `--max-bytes` to adjust collection and installer
LaunchAgent plans. Keep the same limits on later reinstalls. Exceeding a bound
aborts the whole import. Do not describe a bounded import as complete history.

The reader can decode current bodies. It does not reconstruct previous edit
history. It privately retains opaque original attributed-body and edit-history
blobs up to 512 KiB each in immutable normalized imports. These support later
decoder repairs and are never supplied to AI. Oversized blobs are not backed up.
Their recovery needs the original Messages database. This is a bounded archive,
not a complete Apple database backup.

Reaction and system events, recognized unsent messages and undecodable bodies
stay out of AI work notes. A work label cannot override this rule. This path
captures available image bytes. It does not capture non-image attachment bytes.
A missing source row does not prove deletion and does not erase retained evidence.
Unknown retraction behavior needs a fixture and explicit handling before acceptance.

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

**Agent:** replace the email and client path with the owner's actual values locally.
Omit `--host` to keep credentials and the archive on this Mac.
**Owner:** create and name one private folder in your My Drive. Confirm its link.
Select only that folder through the constrained Google Picker. You can rename
it later. The binding uses its stable folder ID.

The helper creates or reuses three native Docs in that root: Start Here,
Corrections and Status. It prepares an owner_all publisher configuration.
The publisher creates yearly message and Loom Docs as needed. This full private
mirror needs no manual Doc IDs or Codex login. The preparation command does not
publish or start jobs. Retries preserve config and Doc identities. They retain
existing Corrections.

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
reads and part/image budgets. Keep defaults until local measurements justify a
trial. Cold proofs still need full reads. For an existing Mac installation, follow
that guide's runtime-refresh and publisher-config digest/rebind procedure.
Do not change JSON and run a saved-settings update without that review.
Linux timings do not prove Mac/iPhone acceptance.

**Mac owner:** explicitly authorize publication of your all-captured filtered
private archive. **Mac coding agent:** run the publisher once.
Verify readback and filtering. Verify a repeat with zero writes and zero model
calls. Then enable the scheduled publisher separately:

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

**Owner, phone or computer:** connect your preferred compatible mobile AI to your
Google Drive yourself. Start Here contains archive links and copyable prompts.
Follow [PHONE_ACCESS](PHONE_ACCESS.md) for final phone acceptance. Ask for a
harmless familiar message with its date and source Doc link. Compare the result
with the phone. Then test a useful archive question and fresh content.
This checks AI access separately from capture and publication. Collection can
run while you defer the check. The phone question-answering goal remains
unverified until it passes. Ordinary URL fetching cannot read private Docs.

For optional correction writeback, verify saved/read-back and applied status.
“Recorded” alone proves neither. Personal labels retain messages in the full
archive. Keep the folder private.

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

Recovery retries only enabled, loaded, stopped jobs. It uses `kickstart` without
`-k`. It respects pauses and never kills busy work. It does not enable jobs
automatically or guess missing settings. A pending installer journal suppresses
health actions. Three safe attempts plus thirty minutes of unresolved essential
outage trigger one human emergency per episode. Auth, TCC, privacy and integrity
failures need human attention immediately. Optional Loom and work-analysis
failures remain local. There are no routine, reminder or recovery emails.
Local monitoring cannot send while the Mac sleeps, loses network or stops running.
External heartbeat remains unproven. Use [MAC_RECOVERY.md](MAC_RECOVERY.md) for
triage and continuation.

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
recovers saved Python, Messages source, collection limits, publisher config and
enabled state from verified installed files. It preserves a disabled publisher.
It refuses inconsistent collector/Loom pause states. Review edited or untracked
files and changed publisher configuration before updating. For an older install
without a publisher-config binding, first do one reviewed `install` with its
exact original settings. The helper does not fetch Git, change dependencies,
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
