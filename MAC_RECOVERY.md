# Mac recovery and continuation

Use this agent recipe to restore the existing iPhone/Mac collector and filtered
archive. Then check fresh access from the owner's phone AI app.
[README](README.md) gives the full path. [PHONE_ACCESS](PHONE_ACCESS.md) gives
final phone acceptance. [REFERENCE_GUIDE](REFERENCE_GUIDE.md) explains choices
and privacy. Drive repair applies only to the selected Drive path.

**Prerequisites:** the owner's working coding agent CLI with a capable reasoning
model, the actual source checkout and access to the existing private runtime.
The diagnostic launcher needs standard-library Python 3.9+; application repair
needs the Python version in MAC_SETUP.md. **Agent:** perform technical repair.
**Owner:** handle account consent, Apple permission prompts and phone checks.

Use this when setup stops, a scheduled job fails or the owner resumes a later
agent session in the Minbox source folder. Preserve the existing owner **Casey**,
archive, account/folder/Doc bindings, correction history, selected Python and
pauses. Resume the existing installation. Do not start from empty defaults.

## Open the agent and resume

Open the usable coding agent in the actual source checkout. For a new checkout,
MAC_SETUP.md uses `~/Projects/minbox-public`. Say:

> Resume or repair Casey's existing Minbox installation. Read AGENTS.md,
> MAC_ONBOARDING_AGENT.md and MAC_RECOVERY.md. Start with the content-free report,
> preserve the saved owner and settings, diagnose the current stage, and do safe
> technical work. Explain required account approvals and phone checks, and record
> remaining untested acceptance checks.

Replace Casey with the actual saved owner. A usable response is required; auth
status alone is insufficient. Missing global Linux skills do not block recovery.

## Read-only diagnostics first

Run from the repository checkout:

```bash
./mac-repair.sh report --owner Casey
```

The launcher is independent of the application's virtual environment. A selected
standard-library Python 3.9+ can also run:

```bash
python3 mac_support.py report --owner Casey
```

Optional `--home HOME` targets the intended user's actual home; `--bundle PATH`
writes the content-free report to a chosen private location. The report tolerates
a broken venv, config or manifest. It exposes only whitelisted structural/status
facts, never credentials, message/source content, raw logs or account IDs. It is
not proof of live phone sync, Google consent, private Docs access, subscription
quota or complete history. Do not upload other runtime files alongside it.

Use the reported categories to find the next step. Inspect only this owner's
LaunchAgents and sanitized status. A loaded job is not proof of fresh capture;
missing jobs must be reconciled with the saved installation, never guessed into
existence. An explicit pause is an instruction to preserve, not an outage to fix.

| Finding | Agent's next step |
| --- | --- |
| Pending installer journal | Preview journal recovery; verify binding and restore before any update or health action. |
| Broken/missing interpreter | Preserve runtime and determine the saved interpreter/environment; repair dependencies there after diagnosis. |
| TCC/permission or Apple sync issue | Explain the needed owner approval/phone check; verify the actual scheduled reader afterward. |
| Enabled loaded stopped job | Allow bounded health retry or inspect its sanitized exit category; never kill busy work. |
| Missing job, bad binding, modified installed source | Preserve evidence and reconcile against manifest/source; do not overwrite or enable with defaults. |
| Auth, privacy or integrity error | Stop the affected writes/recovery and request the specific owner action; preserve grants and stable IDs. |
| Optional Loom/work-analysis issue | Keep local maintenance status while checking the essential full mirror separately. |
| Slow or stale full publication | Follow [publication performance](OWNER_ARCHIVE.md#publication-performance); distinguish skipped imports, cold proofs and slow revision reads before tuning. |

## Recover an interrupted installer

Use the actual existing archive root and an available application-compatible
Python, from the source checkout. The default path below applies only if that is
where the current installation lives:

```bash
archive_support="$HOME/Library/Application Support/Minbox Text Archive"
archive_data="$archive_support/archive"
python3 mac_setup.py recover --owner Casey --archive-root "$archive_data" --plan
python3 mac_setup.py recover --owner Casey --archive-root "$archive_data"
```

`recover` restores the durable pending installer journal only after its owner,
archive and installation binding are verified. It is not a fresh install and
must not fill in missing settings with destructive defaults. If recovery refuses
an inconsistent binding or reports incomplete rollback, preserve the journal
and inspect locally; do not delete it or force the next install. Health actions
are suppressed while a pending installer journal exists.

Journal rollback restores owned installed source/jobs. It cannot undo already
imported archive data or Google Drive writes. Never delete retained data to make
rollback appear complete, or restore a revoked credential as though it works.

## Repair source and refresh using saved settings

Preserve local edits and source identity. Fix authored source in the checkout,
create focused synthetic fixtures for actual defects, and run relevant tests.
Do not patch tracked installed app files. Restore the existing environment if
needed, then preview and apply a saved-settings update:

```bash
archive_python="$archive_support/venv/bin/python"
"$archive_python" mac_setup.py update --owner Casey --archive-root "$archive_data" --plan
"$archive_python" mac_setup.py update --owner Casey --archive-root "$archive_data"
```

Use the actual customized paths when present. Preserve saved Python, Messages
source, bounds, publisher binding and enabled state. Review inconsistencies and
modified tracked files. Do not reset Git or delete manifests. Do not change
hashes without review. Do not replace credentials or overwrite pauses.
Before Git updates, review the working tree and preserve local edits.
Fetch and reconcile reviewed source revisions. Keep runtime paths unchanged.

For performance configuration changes, use the shared guide's Mac digest/rebind
procedure. A reviewed publisher JSON edit must be rebound with an `install`
that preserves all actual settings and pauses; do not change recorded hashes to
bypass the saved-settings update check.

Verify a harmless new message through scheduled capture. For Drive, verify
native Doc readback and status. Check repeat and idle behavior as relevant.
Use one useful [phone question](PHONE_ACCESS.md#start-with-a-small-retrieval-check) after a repair that affects AI access.
Investigate stale content only if it remains a problem.
Record the actual results. Passing launchctl or source tests alone does not prove
live Mac acceptance.

## Local health and human escalation

```bash
"$archive_python" mac_health.py check --owner Casey --plan
"$archive_python" mac_health.py check --owner Casey
```

The default config is private `config/health-Casey.json` under the support path
(version 1, owner Casey); `--config PRIVATE_FILE` selects a reviewed private config.
State/report are under `health/Casey`. The per-user health label is
`com.minbox-text-archive.health.Casey`, checked every 60 seconds after explicit
`--enable-monitor` activation. Preserve optional delivery and paused settings.

The controller retries only enabled, loaded, stopped jobs. It uses `kickstart`
without `-k`. It never kills busy workers or resumes pauses. It does not enable
jobs automatically or invent missing settings. Three safe attempts and thirty
minutes of unresolved essential capture/import/full-publication outage trigger
one human emergency per episode. Auth, TCC, privacy and integrity failures need
immediate human attention. Optional Loom and work-analysis issues stay local.
No routine, reminder or recovery emails are sent.

Default delivery is none with a local emergency queue. If Casey wants emergency
SMTP/ntfy delivery, configure his chosen destination/credentials privately and
verify delivery explicitly. Do not copy another owner's configuration. This
same-machine monitor cannot promise notification while the Mac sleeps, has no
network or is unavailable; external heartbeat remains unverified.

Finish with a sanitized continuation checkpoint: source identity, current stage,
passing checks, exact unresolved category, required owner action and next step.
Keep private runtime/config/history outside Git. No remote deployment, GitHub
push, site publication or global preference change is part of this repair.
