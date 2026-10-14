# Client onboarding

The agent does the technical work on the client's own always-on computer. Read
AGENTS.md, inspect existing state and choose the supported phone/host combination.
Use the actual owner namespace, email and paths; Casey below is fictional.

## Before consent

Confirm a working CLI-capable agent, a supported OS, Python 3.11+ with sqlite3,
Git, private runtime storage outside the checkout and a matching Desktop OAuth
client JSON. Check GOOGLE_SETUP.md before asking for Google consent. Runtime
collection/full publication require no model subscription; the setup agent needs working local command and model access.

For **iPhone on Mac**, use MAC_ONBOARDING_AGENT.md and MAC_SETUP.md. For **Android
on Linux**, use the sequence below. Android on Mac/Windows is not implemented.
Existing installations go through the appropriate recovery guide first.

## Android on Linux

Use a normal user account and per-user systemd manager. Inspect existing jobs and
bindings before changing them. Keep one owner per independent client login.

**Computer (collection host), agent:** build the pinned collector following
GMKIT_MEDIA.md with Go 1.25+. Keep the emitted binary, upstream license/notices,
modified corresponding source and provenance together outside Git. The builder
never installs or pairs automatically. Inspect the exact build output before
installing its gmcli binary into `~/.local/lib/minbox-text-archive/bin/`.

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

**Computer (collection host), owner:** use an isolated private Firefox window
for the upstream cookie-based authentication flow. Sign into your Google account
at `https://accounts.google.com/AccountChooser?continue=https://messages.google.com/web/config`.
In Developer Tools → Network → All, reload the configuration page and select its
`config` document request; choose Copy → Copy as cURL. This request contains
credentials: keep it on the clipboard for direct stdin transfer, never in chat.

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

**Computer, agent:** start only the installed read-only collector service and
verify status through its existing `gmcli.sock`: connected true, auth_expired
false, offline false and send_mode off. The supplied service runs
`--read-only=true serve --idle-exit 0`. Never use `--auto` or enable sending.
Import once with `archive_cli.py import-gmkit Casey PRIVATE_GMCLI_DB`; inspect
sanitized counts/gaps. Confirm owner-approved benign incoming/outgoing texts match
on the phone and in the archive without printing private history.

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
interactive; do not automate acceptance. Inspect the returned private config and
run `owner_publish_cli.py --config PRIVATE_CONFIG` with the venv interpreter.
Verify the account, actual `drive.file` grant, root/parent privacy and native Docs
readback. Provisioning preserves existing IDs and rejects unexpected rebinding.

Google's permission is per-file selected/app-created access, not a recursive
folder sandbox. Minbox separately enforces the chosen root and managed parents.
Manually inserted unrelated files are neither automatically authorized nor imported.
Existing broad grants use DRIVE_MIGRATION.md before fresh limited consent.

Before enabling the owner_all schedule, follow
[publication performance](OWNER_ARCHIVE.md#publication-performance): establish a
verified first run and warm repeat, inspect actual completed timestamps, and
measure locally before tuning concurrent reads, part sizes or image attempts.
Use this computer's private config and reviewed installed runtime; the examples
are optional settings, not universal onboarding defaults.

## Schedules and health

**Computer, agent:** after live checks, enable only the verified owner jobs:

```bash
systemctl --user enable --now minbox-text-collector@Casey.service \
  minbox-text-import@Casey.timer minbox-text-backfill@Casey.timer \
  minbox-owner-archive@Casey.timer
```

Create a private 0600 health config in a 0700 directory before starting its timer.
Use the owner, verified publisher status and optional backfill status paths in
HEALTH_ALERTS.md. Start with `delivery.type: none`; run the local check, then
explicitly enable the health timer after review. Preserve existing pauses/delivery
on repair. External emergency delivery is optional, owner-selected and tested only
with consent. Without delivery configured, emergency incidents remain local.

Check per-user manager persistence after logout/reboot; do not assume lingering
or disable sleep/security silently. Verify actual scheduled new capture and Drive
publication, plus an idle repeat with zero writes/model calls. Observe renewal,
restart and offline catch-up where practical and record untested checks. A service
being active is not proof of complete phone history. History/media queues are
bounded; pending/unavailable items stay explicit.

## Optional Android Spam & blocked synchronization

Explain the whole-folder scope in PHONE_SPAM.md before enabling this policy.
The protocol cannot reliably distinguish manual reports from automatic spam or
block-only actions. After the owner chooses the all-Spam-&-blocked policy and the
updated collector/import signal is verified, set the private owner publishers'
`phone_spam_policy` to `spam_and_blocked`. This removes whole conversations from
current Drive views and managed images, while local originals remain. Moving
the conversation out of that phone folder restores eligible content after a fresh
status confirmation and archive sync. Explain this reversal and test both directions. Default
is off; never enable this Android policy for iPhone or bypass missing metadata.
Perform a benign disposable phone-conversation acceptance check if the owner
agrees, and record unverified event propagation honestly.

## Optional AI connection

**Owner, phone or computer:** connect your preferred compatible AI app to the
Google account containing the archive yourself. The app's Drive permissions are
separate and may be broader than Minbox's. Use the Start Here Doc's prompt.

Explain this optional check: ask the AI to quote a harmless recent text you
recognize and include its date and source Doc link, then compare it with your
phone. This checks the AI connector separately from Minbox capture/publication.
Skipping it does not block setup or collection. Keep files private if it fails.
Corrections/writeback tests are also optional; recorded and applied differ.

Leave a private local checkpoint with source revision, owner-bound stages,
checks, coverage gaps, pending approvals and one next action. No message bodies,
credentials or private account/Drive IDs belong in the repository handoff.
