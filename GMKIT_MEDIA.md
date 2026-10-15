# Pinned Android full-media collector

Use this agent recipe to build the read-only Android collector for the supplied
Linux path. It collects texts and available images for a filtered archive.
The end goal is useful answers in the owner's preferred phone AI app.
Start with [README](README.md). Follow ONBOARDING.md for installation and pairing.
Use [PHONE_ACCESS](PHONE_ACCESS.md) for final phone acceptance and
[REFERENCE_GUIDE](REFERENCE_GUIDE.md) for choices and privacy. Drive publication
is a separate option; building this collector does not connect a phone AI app.

**Prerequisites:** the owner's installed coding agent CLI with a capable reasoning
model; Python 3.11+; Git; Go 1.25+; and a private build output location outside Git.
An empty Go module cache can require dependency downloads.
**Agent:** build, inspect and install only within the authorized setup or repair.
**Owner:** handle account consent, phone pairing and device prompts.

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

Optional `--source /path/to/gmkit` accepts a clean checkout of the pinned commit.
It must use the official HTTPS origin. The builder verifies the commit.
It checks the patch with `git apply --check`. It applies the patch, runs focused
Go tests and builds the binaries. It uses locked Go dependencies and refuses
module-file updates. It does not install binaries, touch a collector account or
download a toolchain. An empty Go module cache can require dependency downloads.

The CLI calls `media.download` on the existing daemon. It opens no second phone
connection. It connects directly to the configured socket and never starts a
daemon automatically. If the managed collector is unavailable, media capture
fails within the socket connection timeout. It retries through the normal import
cooldown. It cannot create an unmanaged collector with different send settings.
Read-only collection remains permitted. The patch adds no text, reaction or
message-send operation. After an approved installation, deliberately restart an
older daemon before the new CLI uses the extended response.

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

The build also produces `minbox-refresh-session`. Use it only for explicit
recovery of an already paired account. It is not automatic collection repair.
Stop the owner's managed collector first. Supply the existing private session.
Choose a new candidate path in an existing mode-0700 directory owned by the
current UID:

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
metadata-only scan use the existing paired connection. Metadata reconciliation
starts before ordinary history import and continues independently during it.
One scanner owns the bounded request slot; disconnected/logout/fatal sessions
stop new requests and cleanup cancels and joins the loop before closing resources.
No phone folder changes,
message sending or second collector are introduced. Archived, deleted, unknown
and missing conversations never become spam by inference. Positive observations
remain excluded despite later stale normal-folder events. A bounded rotating
read-only `GetConversation` lookup of known exclusions can confirm restoration
only for normal statuses (1, 2 or 4), with a request started after the latest spam
observation and the safety delay. A newer spam observation wins the race.
The ledger retains active/restored state and history rather than deleting rows.

The SDK exposes folder state. It does not identify the Android user's exact
Report spam action. Spam can be automatic. A blocked conversation need not have
been reported. The owner must choose the separate Drive publication policy.
The agent must enable it explicitly. Its supported value is `spam_and_blocked`.
The default is `off`.

Scans are capped at 500 conversations, with explicit snapshot/capped/pending/failed
coverage recorded in `phone_spam_scan_state`. The SDK's public method does not
support cursor traversal or cancellation. One in-flight scan maximum and caller
deadlines bound retries; a permanently hung SDK request needs collector recovery.
Targeted restoration checks share the request budget and retain original request
timestamps across caller timeouts. Never interpret absence, a nil response or a
capped scan as proof of restoration or complete phone coverage.
The library and native Docs revision limitations remain explicit in PHONE_SPAM.md.
