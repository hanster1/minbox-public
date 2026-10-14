# Android recovery on the collection computer

Start with existing bindings and sanitized status. Inspect the owner's collector
unit, its existing socket status, import/publisher status and local health report.
Do not print session JSON, raw logs, copied cookies or message bodies. Confirm
phone connectivity with the owner before inferring an authentication failure.

For repeated owner-publication timeouts, inspect the private publisher's fixed
`phase` and `heartbeat_at` fields. Stages distinguish corrections, images,
document verification and final status without exposing source or Doc identities.
An import or work publisher that exits successfully with `owner_busy` has skipped
work while the full publisher holds the owner lock; check completed timestamps.

If large managed Docs time out even on revision probes, review the owner's
supported `max_document_bytes` setting. A smaller bound such as `100000` retains
existing part IDs, creates additional parts and updates Start Here through the
normal guarded publisher. Sources can move between parts; originals, correction
bindings and native Doc history remain. Save a private config rollback and a
sanitized render preview before applying it. The existing large Docs still need
successful guarded reads before they shrink, so retain verified partial progress.
`max_image_attempts: 1` can also reduce image work ahead of text publication, but
does not establish that the image backlog is draining. Verify complete publication,
import catch-up and a subsequent scheduled run before claiming recovery.

An explicit operator repair can supply the canonical previous body to
`DocsClient.replace_verified` only when it matches a fresh bound verification
proof. The revision-guarded literal replacement must report exactly one match
and pass full structural readback. An uncertain write is not acknowledged or
blindly replayed; let the normal publisher reconcile it.

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
