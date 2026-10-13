# Android recovery on the collection computer

Start with existing bindings and sanitized status. Inspect the owner's collector
unit, its existing socket status, import/publisher status and local health report.
Do not print session JSON, raw logs, copied cookies or message bodies. Confirm
phone connectivity with the owner before inferring an authentication failure.

Respect paused jobs. The monitor already retries enabled components with bounded
cooldowns; active workers are not killed. Do not open a second collector or normal
Google Messages web session to diagnose the first one. Media CLI connects only
to the existing managed daemon and must never auto-start one.

For a broken application environment, preserve the archive/config/sessions, repair
the checkout/venv and relevant installed modules from reviewed source, run focused
synthetic checks, then restart only affected owned jobs. Never initialize a new
archive or substitute credentials to bypass a failure.

An existing-pairing token refresh can be attempted using the explicit candidate
helper in GMKIT_MEDIA.md. Stop that owner's collector, preserve the private input,
write a new bounded candidate, compare pairing bindings, then deliberately promote
only a validated candidate and verify the restarted read-only connection. Failure
must leave the active credential unchanged. This is an operator repair tool,
not an automatic permission to modify credentials.

If fresh pairing is required, use the isolated private Firefox procedure in
ONBOARDING.md on the collection computer, with the owner's phone emoji approval.
Close setup/competing tabs afterward. Drive authorization repair is separate:
retain account/root/Doc IDs and use limited consent or DRIVE_MIGRATION.md. Never
make files public or revoke a newly minted grant as a second migration step.

Verify browser closure, collector restart, actual fresh capture/private publication
and restored prior schedules. Leave private rollback/checkpoint facts and mark
natural renewal, reboot or offline catch-up unverified until observed. Notifications
are limited to human-required emergencies under HEALTH_ALERTS.md.
