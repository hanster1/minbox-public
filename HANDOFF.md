# Minbox session checkpoint

This public repository is the canonical home for application, onboarding/repair
and information-site source. MAINTENANCE.md maps private hosting procedures and
runtime state to their separate homes. Retain the historical private repository
for reference; never merge its private history or overwrite current fixes.
Minbox code is MIT; collector changes retain upstream AGPL and complete-source
requirements in THIRD_PARTY_NOTICES.md and GMKIT_MEDIA.md.

## Completed

Opt-in Android `spam_and_blocked` synchronization withdraws whole conversations
and managed images from current Drive views while retaining local originals.
Fresh, explicit normal phone status restores eligible content; missing/stale
responses cannot clear exclusions. Text Doc IDs remain stable. Native Docs
version history is retained. See PHONE_SPAM.md for scope and consent.

Private owner/account/folder-bound document proofs let unchanged outputs use
revision probes for up to 24 hours after full verification. Changed outputs can
reuse fresh bound geometry or an explicit operator-provided previous body for
revision-guarded repair; new content still requires full exact structural readback. Expired/cold outputs require structural reads. Corrections,
privacy checks and deletion journals remain fresh. Spam-image withdrawal uses
one bounded fresh folder scan; incomplete listings fall back to exact searches.

Optional work analysis shares approved context once per batch, excludes explicit
spam/personal/mixed inputs before AI, and shares one messages/Loom call budget,
including failures. Undo can reuse matching history. Full publication uses no AI.

## Verification and limits

477 Python tests passed, five optional skips. Release checks passed for 122 files
and 87 inventoried source/test files. Reviewed Linux installation and live cold/
cached publishing passed. The latest smaller-part migration completed full
verification and one automatic repeat under the normal ten-minute limit. Prior
schedules and recovery pauses were restored; import/work catch-up passed. The
repeat took about 9m48s, so provider-latency margin remains narrow.
Collection continued. Private bindings, timings and rollback receipts remain
outside Git. Historical image uploads remain pending; backlog drainage is
unverified. Large Docs and daily verification can remain slow.
ANDROID_RECOVERY.md describes smaller-part migration and scoped image-attempt limits for repeated timeouts.
Website source was not deployed.

Real phone unspam restoration, Mac/iPhone and independent client setup, renewal,
reboot and offline catch-up need further acceptance. Media coverage is bounded;
external heartbeat and independent encrypted backup remain separate work.

Next: observe scheduled publication latency and image backlog progress, then
perform remaining client acceptance checks when their devices are available.
