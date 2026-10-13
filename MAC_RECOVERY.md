# Mac recovery and continuation

Use this when setup stops, a scheduled job fails, or the owner opens a later local coding-agent session in his Minbox source folder. Recovery preserves the existing
owner **Casey**, archive, account/folder/Doc bindings, correction history, selected
Python and pauses. It does not restart onboarding from empty defaults.

## Open the agent and resume

Open the available usable coding agent in `~/Projects/minbox-text-archive` and say:

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

Use actual customized paths when present. Saved Python, Messages source, bounds,
publisher binding and enabled state must survive. Review inconsistencies and
modified tracked files; do not reset Git, delete manifests, change hashes blindly,
replace credentials, or overwrite pauses. Git updates require reviewed clean or
preserved local state and deliberate reconciliation; fetch and reconcile reviewed source revisions while runtime paths remain unchanged.

Verify a benign scheduled fresh capture and native Doc readback/status afterward,
plus relevant repeat/idle behavior. Record what actually passed; successful
launchctl or source tests alone do not establish live Mac acceptance.

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

The controller retries only enabled, loaded, stopped jobs with `kickstart`
without `-k`; it never kills busy workers, resumes pauses, auto-enables jobs or
invents missing job settings. Three safe attempts and thirty minutes of unresolved
essential capture/import/full-publication outage trigger one human emergency per
episode. Auth/TCC/privacy/integrity require immediate human attention. Optional
Loom/work analysis stays local; no routine, reminder or recovery emails are sent.

Default delivery is none with a local emergency queue. If Casey wants emergency
SMTP/ntfy delivery, configure his chosen destination/credentials privately and
verify delivery explicitly. Do not copy another owner's configuration. This
same-machine monitor cannot promise notification while the Mac sleeps, has no
network or is unavailable; external heartbeat remains unverified.

Finish with a sanitized continuation checkpoint: source identity, current stage,
passing checks, exact unresolved category, required owner action and next step.
Keep private runtime/config/history outside Git. No remote deployment, GitHub
push, site publication or global preference change is part of this repair.
