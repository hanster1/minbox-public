# Pinned Android full-media collector

`scripts/gmkit-media.patch` modifies official gmkit v0.4.0 commit
`c714f8ea1602d9c61876a87a44f6984ba3aeb4c4`. The changes retain gmkit's AGPL-3.0
license. The builder produces its license, modification notice, complete modified
source archive, patch, binary and SHA-256 provenance together outside Git.
Keep those artifacts together when distributing a modified binary; make the
corresponding source available to recipients and users of the modified service.
The patch is authored source suitable for public release; it contains no account
protocol data, keys, credentials or message history.

Build with an installed Go 1.25 or later toolchain:

```sh
python3 scripts/build_gmkit_media.py --output /tmp/gmkit-media-build --go /path/to/go
```

An optional `--source /path/to/gmkit` accepts a clean checkout of exactly the
pinned commit with the official HTTPS origin. The builder verifies the commit,
applies the patch with `git apply --check`, runs focused Go tests, then builds.
It uses locked Go dependencies and refuses module-file updates. The builder
never installs the binary, touches a collector account, or downloads a toolchain.
Dependency downloads may occur when the Go module cache is empty.

The CLI now calls `media.download` on the existing daemon rather than opening a
second phone connection. The CLI directly dials the configured socket and never
auto-starts a daemon. If the managed collector is unavailable, media capture
fails within the socket connection timeout and retries through the normal import
cooldown; it cannot create an unmanaged collector with different send settings.
Read-only collection remains permitted; no text, reaction
or message-send operation is added. A daemon running an older binary must be
restarted deliberately after an approved installation before the new CLI can
use the extended response.

Stored `raw_proto` is decoded privately as `UpdateEvents`. Only the requested
message and its `MessageInfo` media entries are used. Each image without a full
media ID/key requests `GetFullSizeImage(messageID, actionMessageID)` over the
existing daemon connection. A shared twelve-second window polls fresh stored
metadata without holding a database transaction or the global live-operation
lock. Thumbnail IDs/keys are never treated as full capture. New history imports
retain action identity; existing richer protocol snapshots survive stripped
history imports. Old rows without protocol/action identity remain coverage gaps
until ordinary capture or backfill provides the metadata.

`--json` includes legacy first-file fields and `attachments`, with each part's
`attachment_id`, `media_id` when present, `mime_type`, `capture_status`, and, when
captured, `path`, `bytes`, `capture_kind: "full"`. `--out FILE` writes the first
part there and subsequent parts to `FILE.part-N`; unavailable parts keep their
identity and status without a path. Clients must validate these private files
and retain unavailable parts for later retry. Keys and raw protocol never appear
in the response. The collector supports at most 32 parts per message; this is an
explicit coverage limit.

Upstream libgm exposes no cancellation for its full-image request or download.
Caller deadlines are bounded, and each operation has per-client inflight dedup
and a cap of eight, including timed-out operations until the underlying call
returns. A permanently hung transport can consume those slots until daemon
restart; it does not permit unbounded retry goroutines. RPC work has an eighteen
second deadline. A phone response, valid file and local archive verification
remain necessary for live acceptance; synthetic tests do not prove phone access.

## Existing-session refresh candidate helper

The build also produces `minbox-refresh-session`. It is an explicit recovery tool
for an already paired account, never a collection-time automatic repair. Stop the
owner's managed collector before using it. Give it an existing private session
and a new candidate path in an existing directory owned by the current UID with
mode 0700:

```sh
timeout 50s /path/to/minbox-refresh-session --input /private/session.json \
  --candidate /private/recovery/session-candidate.json --timeout 45s
```

Input must be a regular current-UID private file; input/output paths must stay
outside Git and cannot use symlink ancestors. The candidate cannot already exist.
The helper changes `TachyonExpiry` only in memory to force the upstream existing
pairing's token refresh, uses the existing browser/mobile/session/key bindings,
and emits only a fixed JSON status. SDK logging is discarded. It never creates a
pairing, sends a message, replaces an active credential, or enables a service.

Only an `AuthTokenRefreshed` event with a nonempty token and future expiry can
produce the atomic mode-0600 candidate. Every SDK binding field must match the
original normalized snapshot exactly; only `tachyon_token`, `tachyon_expiry`,
`tachyon_ttl`, and returned `cookies` can change. Unknown original JSON fields
are preserved. Failure never persists the forced zero expiry. The SDK's connect
request itself cannot be cancelled, so the helper has a 45-second process deadline
and should also be run with an external timeout. A separate operator must verify
the candidate and deliberately promote it, restart the same read-only managed
collector, and verify the owner's connection. A candidate is not proof of working
phone collection. Tests use fixture JSON and make no account/network calls.

## Phone spam-folder metadata

The patched collector preserves exact numeric conversation status and records
positive SPAM_FOLDER (5) and BLOCKED_FOLDER (6) observations in an owner-store
`phone_spam_conversations` ledger. Incoming conversation events and a five-minute
metadata-only scan use the existing paired connection; no phone folder changes,
message sending or second collector are introduced. Archived, deleted, unknown
and missing conversations never become spam by inference. Positive observations
remain sticky despite later stale normal-folder events.

The SDK exposes folder state, not the Android user's exact Report spam action.
Spam can be automatic; blocked conversations can be blocked without reporting.
The separate Drive publication policy must be explicitly chosen and enabled.
Its current supported value is `spam_and_blocked`; `off` is the default.

Scans are capped at 500 conversations, with explicit snapshot/capped/pending/failed
coverage recorded in `phone_spam_scan_state`. The SDK's public method does not
support cursor traversal or cancellation. One in-flight scan maximum and caller
deadlines bound retries; a permanently hung SDK request needs collector recovery.
Never interpret absence or a capped scan as proof of complete phone coverage.
The library and native Docs revision limitations remain explicit in PHONE_SPAM.md.
