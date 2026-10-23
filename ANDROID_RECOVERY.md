# Android recovery on the collection computer

Use this agent recipe to restore Android collection and the existing filtered
archive. If the repair affects phone access, confirm one useful answer in the owner's AI app.
[README](README.md) gives the full path. [PHONE_ACCESS](PHONE_ACCESS.md) gives the
phone acceptance checks. Use [REFERENCE_GUIDE](REFERENCE_GUIDE.md) for access
choices and privacy boundaries. Drive repair applies only to a selected Drive path.

**Prerequisites:** use the owner's working coding agent CLI and a capable
reasoning model on the collection computer. Retain access to the existing
runtime and private configuration. **Agent:** perform technical repair.
**Owner:** handle account consent, phone pairing and device prompts.

Start with existing bindings and status that contains no private content.
Inspect the owner's collector unit and existing socket status. Inspect import
status, publisher status and the local health report. Do not print session JSON,
raw logs, copied cookies or message bodies. Ask the owner to confirm phone
connectivity before treating the problem as an authentication failure.

For repeated owner-publication timeouts, follow the shared
[publication performance](OWNER_ARCHIVE.md#publication-performance) procedure.
It covers fixed phase/heartbeat diagnostics, skipped `owner_busy` imports,
read-only sequential/concurrent comparisons, supported private config bounds,
smaller-part reconciliation and safe handling of uncertain writes. Use completed
publication/import timestamps and an automatic repeat to verify recovery; do not
infer phone authentication failure from slow native Docs requests.

Respect paused jobs. The monitor already retries enabled components with bounded
cooldowns; active workers are not killed. Do not open a second collector or normal
Google Messages web session to diagnose the first one. Media CLI connects only
to the existing managed daemon and must never auto-start one.

For a broken application environment, preserve the archive, config and sessions.
Repair the checkout, venv and affected installed modules from reviewed source.
Run focused synthetic checks. Then restart only affected jobs for this owner.
Never initialize a new archive or substitute credentials to bypass a failure.

An existing-pairing token refresh can be attempted using the explicit candidate
helper in GMKIT_MEDIA.md. Stop that owner's collector, preserve the private input,
write a new bounded candidate, compare pairing bindings, then deliberately promote
only a validated candidate and verify the restarted read-only connection. Failure
must leave the active credential unchanged. This is an operator repair tool,
not an automatic permission to modify credentials.

If fresh pairing is required, use the isolated private Firefox procedure in
[ONBOARDING.md](ONBOARDING.md#android-on-linux) on the collection computer, with the owner's phone emoji approval.
Do not reuse a signed-in Chrome profile for browser-cookie pairing; that setup
has lost the collector login after pairing.
Close setup/competing tabs afterward. Drive authorization repair is separate:
retain account/root/Doc IDs and use limited consent or DRIVE_MIGRATION.md. Never
make files public or revoke a newly minted grant as a second migration step.

Confirm that setup browser windows are closed. Verify the restarted collector.
Verify fresh capture and private publication for the chosen path. Restore only
the schedules that were active before repair. Test fresh phone access through
[PHONE_ACCESS](PHONE_ACCESS.md). Keep rollback and checkpoint facts private.
Mark natural renewal, reboot and offline catch-up unverified until observed.
HEALTH_ALERTS.md limits notifications to emergencies that need human action.
