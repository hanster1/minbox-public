# Client onboarding

Before setup, present [the options menu](README.md#choose-what-is-included).
Explain what this recipe includes and confirm the owner's content and service choices together.
Do not silently include or omit images, OCR, Loom, or optional notifications.

Use this guide to collect texts on an always-on computer and build a filtered
archive. The end goal is useful answers in the owner's preferred phone AI app.
Start with [README](README.md) for the full path. Use
[PHONE_ACCESS](PHONE_ACCESS.md) to choose and test phone access.

**Owner:** bring your own installed coding agent CLI with a capable reasoning
model and working model access. Keep the collection computer available for its
scheduled jobs. Handle account consent, phone pairing and device permission
prompts yourself. **Agent:** perform the technical steps below.

Drive is one storage and retrieval option. The Drive sections are recipes for
the supplied publisher. They are required only when that path is selected.
Use [REFERENCE_GUIDE](REFERENCE_GUIDE.md) for choices and privacy boundaries.
A local filtered export or another access path needs its own acceptance checks.

This is a technical recipe for the supplied implementation. Adapt example paths
and schedules to the owner. Preserve account bindings, privacy checks and script
prerequisites. A different platform needs implementation and acceptance work.

The agent does the technical work on the client's own always-on computer. Read
AGENTS.md, inspect existing state and choose the supported phone/host combination.
Use the actual owner namespace, email and paths; Casey below is fictional.
For family installations, review [multiple-owner boundaries](REFERENCE_GUIDE.md#multiple-owners-on-one-computer).
Keep pairing sessions, corrections, export jobs, and phone-agent access bound to the correct person.

## Before consent

**Agent:** confirm these prerequisites before device or account consent:

- A working coding agent CLI with a capable reasoning model and local command access.
- A supported phone and computer combination.
- Python 3.11+ with sqlite3, Git and private runtime storage outside the checkout.
- For the Android collector build, Go 1.25+ and the tools in GMKIT_MEDIA.md.
- For Drive, a matching Desktop OAuth client JSON and the APIs in GOOGLE_SETUP.md.

Check GOOGLE_SETUP.md before asking for Google consent. Routine collection and
full publication need no model calls. The setup agent needs usable model access.

For **iPhone on Mac**, use MAC_ONBOARDING_AGENT.md and MAC_SETUP.md. For **Android
on Linux**, use the sequence below. Android on Mac/Windows is not implemented.
Existing installations go through the appropriate recovery guide first.

## Android on Linux

**Agent:** use a normal Linux user account with a per-user systemd manager.
Inspect existing jobs and bindings before changing them. Use a separate client
login for each independent owner.

**Computer (collection host), agent:** build the pinned collector with Go 1.25+.
Follow GMKIT_MEDIA.md. Keep its binary, upstream license, notices, modified source
and provenance together outside Git. The builder does not install or pair.
Inspect the build output. Then install its gmcli binary into
`~/.local/lib/minbox-text-archive/bin/`.

Prepare the application and empty owner archive only when no existing runtime
requires recovery. From the reviewed checkout, agent reference commands are:

```bash
umask 077
archive_app="$HOME/.local/lib/minbox-text-archive"
archive_root="$HOME/.local/share/minbox-text-archive"
mkdir -p "$archive_app/bin" "$HOME/.config/minbox-text-archive/owners" \
  "$HOME/.config/minbox-text-archive/publishers" "$HOME/.config/systemd/user"
python3 -m venv "$archive_app/.venv"
"$archive_app/.venv/bin/python" -m pip install -r requirements-google.txt
cp ./*.py "$archive_app/"
"$archive_app/.venv/bin/python" archive_cli.py --root "$archive_root" init --owner Casey
```

Inspect `/usr/bin/python3` used by import/health/history service templates; require
Python 3.11+ or adapt those installed templates to the private venv interpreter.
Install the needed collector, import, backfill, owner-archive and health templates
from `services/`; optional scoped work and Loom jobs are not prerequisites.
Reload the user manager. Do not enable jobs before their checks below pass.

**Computer (collection host), owner:** open an isolated private Firefox window.
Sign into your Google account at
`https://accounts.google.com/AccountChooser?continue=https://messages.google.com/web/config`.
Open Developer Tools → Network → All. Reload the configuration page. Select its
`config` document request. Choose Copy → Copy as cURL.
This request contains credentials. Keep it on the clipboard for direct stdin
transfer. Never put it in chat.

**Computer (same host), agent:** use the available clipboard command (`wl-paste`
on Wayland or `xclip -selection clipboard -o` on X11) to pipe those bytes directly
into the collector's parser. Do not execute the copied cURL. For Wayland:

```bash
wl-paste --no-newline | "$HOME/.local/lib/minbox-text-archive/bin/gmcli" \
  --store "$HOME/.local/state/minbox-text-archive-collectors/Casey" \
  auth google --cookies-file -
wl-copy --clear
```

Clear the clipboard on failure too; use a shell trap when orchestrating this.
Keep the session directory 0700 and session file 0600. If clipboard tooling is
unavailable, arrange private stdin transfer locally; do not ask the user to paste
cookies into the agent conversation. Upstream reference:
[Google Messages authentication](https://docs.mau.fi/bridges/go/gmessages/authentication.html).

**Phone (owner's Android phone), owner:** open Google Messages and approve the
exact pairing emoji shown by the collector. **Computer:** close the private setup
window and competing Google Messages web tabs. Google allows one active Messages
computer per account. Browser sign-in and Drive consent are separate.

**Computer, agent:** start only the installed read-only collector service.
Check its existing `gmcli.sock`. Require connected true, auth_expired false,
offline false and send_mode off. The supplied service runs
`--read-only=true serve --idle-exit 0`. Never use `--auto`. Keep sending off.
Import once with `archive_cli.py import-gmkit Casey PRIVATE_GMCLI_DB`.
Inspect counts and coverage gaps without private content. Ask the owner to compare
one approved captured message on the phone and in the archive.
Do not print private history.

## Add another person on an existing host

Use this when an Android collection host already runs Minbox for one person and
another household member wants their own archive. A person can simply tell
their agent, running on the host: **"get my text messages set up on Minbox"**.
The agent follows this section. Only one step needs the person: scanning a QR
code with their own phone.

**Agent checklist before starting**

- You are on the collection host, as the account that already runs Minbox, in a
  reviewed checkout that includes `scripts/add-owner`.
- The collector binary, `local_archive_export.py`, the shared archive database
  and the `minbox-text-collector@`, `minbox-text-import@` and
  `minbox-text-backfill@` templates are installed (the recipe above).
- You know the new owner's capitalized name, for example `Casey`.
- Set `MINBOX_PROTECTED_OWNERS` (comma-separated) to every owner whose setup was
  built by hand, so the script always refuses them. It also refuses any owner
  with an existing pairing, publisher, ledger, non-empty folder or running unit
  that it did not create. Do not work around a refusal; ask the host's administrator.
- The person has Google Messages as the default SMS app on an online Android
  phone, and a terminal (PowerShell on Windows works) that can `ssh` to the host.

**1. Prepare (agent).** Safe to rerun; `--dry-run` changes nothing.

```bash
scripts/add-owner Casey --dry-run
scripts/add-owner Casey
```

It creates, only for that owner and with mode 700/600: the collector store
`~/.local/state/minbox-text-archive-collectors/Casey/`, a marker
`~/.config/minbox-text-archive/owners/Casey/owner.json`, an empty correction
ledger, and `~/Minbox/Casey/Filtered/`. Once per host it installs the shared
`minbox-owner-filtered-export@` service and timer.

**2. Pair the phone (person).** An agent chat window usually cannot show a
scannable QR code, so give the person this to paste into their own terminal:

```bash
ssh -t COLLECTION_HOST "PATH_TO_CHECKOUT/scripts/add-owner Casey --pair"
```

On the phone: Google Messages → profile picture → Device pairing → QR code
scanner, then scan. When the terminal reports pairing, the person tells the
agent "done". If the code is garbled, enlarge the window or shrink the font and
rerun. The cookie-based pairing in the section above is the fallback; never ask
for cookies in chat.

**3. Start and verify (agent).**

```bash
scripts/add-owner Casey --enable
scripts/add-owner Casey --status
journalctl --user -u minbox-text-import@Casey -n 20 --no-pager
```

Healthy: the collector is active, imports run without errors, and
`~/Minbox/Casey/Filtered` has files within about ten minutes. Ask the person to
send themselves a test text and confirm it appears in the next export. Older
history fills in gradually and is not guaranteed to be complete.

**Troubleshooting.** `REFUSED … not created by add-owner`: stop and ask.
`Not paired yet`: repeat step 2. `needs a real terminal`: the pairing command
ran without `ssh -t` or inside a chat tool. An expired pairing needs a person to
move the old `session.json` aside first; the script never deletes it. Never use
`--auto` or turn off `--read-only`.

**Privacy.** Every owner has separate files, but all run under one OS account,
so separation is by setup, not by permissions. Each person's agent should read
only that person's folder. See
[multiple owners](REFERENCE_GUIDE.md#multiple-owners-on-one-computer).
Health alerts for a new owner need a separate, reviewed change to the shared
health configuration.

## Private Drive connection

**Computer, owner:** before connecting Google, create a new empty private Drive
folder. Give it any name you want. Copy its folder link. During Minbox setup,
confirm that link, authorize your own Google account and select that exact folder.
You can safely rename it later; Minbox binds to its stable ID. All managed files
and child folders remain inside it.

**Computer, agent:** provision the local owner with the private client file:

```bash
"$HOME/.local/lib/minbox-text-archive/.venv/bin/python" connect_owner.py \
  --owner Casey --account-email OWNER_GOOGLE_EMAIL \
  --client-file /private/path/desktop-oauth-client.json \
  --archive-root "$HOME/.local/share/minbox-text-archive"
```

For Mac use its documented private support/venv/config paths instead. Omit
`--host` and `--activate` for independent local provisioning. Google consent is
interactive; do not automate acceptance. Inspect the returned private config.
Run `owner_publish_cli.py --config PRIVATE_CONFIG` with the venv interpreter.
Verify the account and actual `drive.file` grant. Verify root/parent privacy and
native Docs readback. Provisioning preserves existing IDs and rejects unexpected
rebinding.

Google's permission is per-file selected/app-created access, not a recursive
folder sandbox. Minbox separately enforces the chosen root and managed parents.
Manually inserted unrelated files are neither automatically authorized nor imported.
Existing broad grants use DRIVE_MIGRATION.md before fresh limited consent.

Confirm that the first owner_all publication completed with verified output.
Keep default performance settings during normal setup. Use
[publication performance](OWNER_ARCHIVE.md#publication-performance) only for slow runs or tuning.
Do not add cold/warm benchmarks to every installation.
Use this computer's private config and reviewed installed runtime; the examples
are optional settings, not universal onboarding defaults.

## Schedules and health

**Computer, agent:** after live checks, enable only the verified owner jobs:

```bash
systemctl --user enable --now minbox-text-collector@Casey.service \
  minbox-text-import@Casey.timer minbox-text-backfill@Casey.timer \
  minbox-owner-archive@Casey.timer
```

Create a private mode-0600 health config in a mode-0700 directory.
Use the owner, verified publisher status and optional backfill status paths from
HEALTH_ALERTS.md. Start with `delivery.type: none`. Run the local check.
Review the result before explicitly enabling the health timer.
Preserve existing pauses and delivery settings during repair. External emergency
delivery is optional. The owner chooses it and consents to its test.
Without delivery configured, emergency incidents remain local.

Inspect the per-user schedule, persistence settings, and available completed-run status.
Do not change sleep or security settings silently. Let health monitoring observe later runs.
Keep idle-repeat benchmarks and restart/outage drills for tuning, a new access design, or a reported failure.
Report any pending first automatic run without making the owner wait through unrelated tests. A service
being active is not proof of complete phone history. History/media queues are
bounded; pending/unavailable items stay explicit.

## Optional Android Spam & blocked synchronization

Explain the whole-folder scope in PHONE_SPAM.md before enabling this policy.
The protocol cannot reliably distinguish manual reports, automatic spam and
block-only actions. The owner must choose the all-Spam-&-blocked policy.
Verify the updated collector/import signal. Then set the private owner
publishers' `phone_spam_policy` to `spam_and_blocked`.
This removes whole conversations from current Drive views and managed images.
Local originals remain. Moving the conversation out of that phone folder can
restore eligible content after fresh status confirmation and archive sync.
Explain this reversal. Test both directions with a harmless disposable phone
conversation if the owner agrees. The default is off. Never enable this Android
policy for iPhone. Never bypass missing metadata. Record event propagation that
remains unverified.

## Optional AI connection

**Owner, phone or computer:** connect your preferred compatible AI app yourself.
For the Drive path, use the Google account that contains the archive. The app has
separate permissions. They can be broader than Minbox's. Use the Start Here Doc's
prompt.

Follow [PHONE_ACCESS](PHONE_ACCESS.md) for final phone acceptance. Ask the AI to
answer one useful question about a familiar topic, preferably involving a recent message.
Check the answer and source from the phone. This also checks the actual AI connection.
The agent handles collection, filtering, and schedule checks without extra owner tests. You can defer it while collection runs;
the phone question-answering goal remains unverified until it passes.
Keep files private if access fails. Correction writeback is optional. Verify
both saved/read-back and applied status; “recorded” alone does not prove either.

Leave a private local checkpoint with source revision, owner-bound stages,
checks, coverage gaps, pending approvals and one next action. No message bodies,
credentials or private account/Drive IDs belong in the repository handoff.
