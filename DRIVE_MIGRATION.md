# Existing archive permission migration

Use this agent recipe to replace an existing broad Google grant with `drive.file`
while preserving the filtered archive. This applies only to the Drive path.
The end goal is useful archive answers in the owner's preferred phone AI app.
Start with [README](README.md). Use [PHONE_ACCESS](PHONE_ACCESS.md) for final phone
acceptance and [REFERENCE_GUIDE](REFERENCE_GUIDE.md) for choices and privacy.

**Prerequisites:** a working coding agent CLI with a capable reasoning model,
access to the existing installation, and the matching application from
GOOGLE_SETUP.md. **Agent:** perform technical migration. **Owner:** handle
sign-in, revocation, fresh consent and Picker approvals. Keep private bytes out
of chat and Git.

**Agent:** record the owner's active schedules and pauses. Pause that owner's
publisher timers and matching health recovery components. Leave read-only
collection running. Preserve other owners and explicit pauses.
Run `drive_migration.py inventory --owner OWNER` on the collection computer.
It inventories only registered folders, Docs and chunks. Keep its JSON outside
Git. It contains metadata and digests, not message contents or credentials.
The helper does not pause jobs, revoke grants or obtain consent.

Google revocation invalidates all tokens and scopes for that account in the app's
Cloud project. Inventory affected integrations first. **Owner:** retire the old
grant. Then obtain fresh `drive.file` consent. Do not revoke the old token after
obtaining its replacement. Existing archive items that are not associated with
the app can need explicit Picker approval as well as the root. The migration
picker is limited to that fixed archive inventory. New users select one folder.

**Agent:** use `drive_migration.py apply --owner OWNER` for the cutover.
It accepts an object through stdin with `inventory` and `credential_envelope`
keys. Supply the private inventory and fresh credential envelope locally.
Never use chat input for these bytes. The helper proves the refresh grant without
requesting a narrower refresh scope. It verifies every known private destination.
It runs the registered full and optional work publishers with staged configs.
Only then does it replace credentials and configs.

Folder and Doc IDs, corrections, ledgers and chunk manifests stay in place.
A failed migration retains the fresh private grant for retry. A revoked old
credential is not usable rollback. Verify the cutover before restoring schedules.
Restore only schedules that were active and monitoring pauses that were present
before migration.

The helper finds registered publisher configs in the standard Linux layout.
Use explicit `--config-dir` when appropriate. A custom Mac layout needs reviewed
adaptation. Do not assume the default inventory covers arbitrary configurations.

Verify private publication and readback. Then test the owner's intended phone AI
app with an existing known question and fresh content through
[PHONE_ACCESS](PHONE_ACCESS.md). Grant migration alone does not prove AI access.
Keep private files private if retrieval fails.

[Enable Google Picker API](https://console.cloud.google.com/apis/library/picker.googleapis.com).
[Google's per-file scopes](https://developers.google.com/workspace/drive/api/guides/api-specific-auth).
[Desktop Picker](https://developers.google.com/workspace/drive/picker/guides/desktop-mobile-picker).
[Revocation semantics](https://developers.google.com/identity/protocols/oauth2/native-app#tokenrevoke).
