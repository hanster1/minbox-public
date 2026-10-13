# Existing archive permission migration

Use `drive_migration.py inventory --owner OWNER` on the collection host to inventory
only registered folders, Docs and chunks. Keep its JSON outside Git. It includes
metadata/digests, never message contents or credentials. The setup agent coordinates the migration: record prior schedules/pauses, pause
that owner's publisher timers and matching health recovery components, then take
the inventory while read-only collection continues. The helper does not pause
jobs, revoke grants or obtain consent. Preserve other owners and explicit pauses.

Google revocation invalidates all tokens/scopes for that account in the app's Cloud
project; do not revoke an old token after obtaining its replacement. Inventory
affected integrations first, retire the old grant, then obtain fresh `drive.file`
consent. Existing archive items not already associated with this app may need
explicit Picker approval as well as the root. The migration picker is filtered
to that fixed archive inventory; new users select one folder only.

`drive_migration.py apply --owner OWNER` accepts its private inventory and fresh
credential envelope through stdin as an object with `inventory` and
`credential_envelope` keys. These are private files/bytes, never chat input. It proves the refresh grant without asking for
a narrower refresh scope, verifies every known private destination, then runs the registered
full/optional work publishers using staged configurations before replacing credentials and
configs. Folder/Doc IDs, corrections, ledgers and chunk manifests stay in place.
A failed migration retains the fresh private grant for retry and never assumes a
revoked old credential is usable rollback. Restore only prior active schedules and
prior monitoring pauses after verifying the cutover.

The helper discovers registered publisher configs in the standard Linux layout
(or explicit `--config-dir`). A custom Mac layout requires reviewed adaptation;
do not assume its default inventory covers arbitrary configurations.

[Enable Google Picker API](https://console.cloud.google.com/apis/library/picker.googleapis.com).
[Google's per-file scopes](https://developers.google.com/workspace/drive/api/guides/api-specific-auth).
[Desktop Picker](https://developers.google.com/workspace/drive/picker/guides/desktop-mobile-picker).
[Revocation semantics](https://developers.google.com/identity/protocols/oauth2/native-app#tokenrevoke).
