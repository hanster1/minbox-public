# Minbox public source checkpoint

This is the canonical project for application code, client onboarding/repair and
information-site source. It has fresh sanitized history and is public at
https://github.com/hanster1/minbox-public. Minbox code uses MIT; collector changes
retain upstream AGPL and complete corresponding-source distribution requirements.
MAINTENANCE.md maps source, private hosting procedures and runtime state to their
separate homes. The retained private historical repository is reference only;
never merge its private history or replace current fixes with old source.

## Current implementation

Android phone-folder synchronization is opt-in `spam_and_blocked` and covers
whole conversations, including automatic spam and block-only entries. Both
publishers exclude these sources before AI/image input. Current Drive text and
managed images are withdrawn; local originals remain. Fresh, explicit normal
conversation status can restore eligible content. Missing/stale/async responses
cannot clear exclusions. Text Doc IDs stay stable; restored images may receive
new IDs. Native Docs version history is not erased by current-content rewrites.
See PHONE_SPAM.md for consent, propagation and bounded restoration checks.

Publishing now maintains private account/owner/root/parent-bound document proofs.
Matching desired hashes use revision-only probes for up to 24 hours after full
verification. Changed, expired, future or cold proofs require structural body
reads and guarded writes/readback. Corrections, privacy checks and image deletion
journals remain fresh. Partial successful document proofs survive interrupted
passes without acknowledging the whole generation prematurely.
Spam-image withdrawal resolves historical identities with one fresh, bounded
managed-folder listing instead of individual searches for already absent images.
Incomplete listings fall back to exact searches; deletion still requires fresh
identity/checksum checks, a durable journal and independent absence confirmation.

Optional work analysis shares overlapping approved context once per batch.
Explicit spam/personal/mixed corrections gate source bodies and context before
AI calls; undo can reuse matching historical analysis. Messages and Looms share
one per-run call budget, including failed attempts. Existing analysis fingerprints
remain compatible for ordinary unchanged sources. Full-owner publication uses no
model. Recovery preserves manual holds and configured budgets.

## Validation and operational limits

459 Python tests pass with five optional skips. Release checks pass for 122 files
and 87 inventoried source/test files. Reviewed tests cover cache restart reuse,
selective rewrites, external edits, slow-probe expiry, unsupported structures,
uncertain writes/persistence failure, exclusion restoration and shared call limits.
A synthetic overlapping-context fixture shrank serialized input by about 70%;
this is an input-byte measurement, not measured billed-token savings.

Reviewed Android activation has verified capture, full Drive readback and managed
image withdrawal on a consenting hosted installation, preserving private bindings.
Real phone-to-Drive unspam restoration still needs a benign acceptance check.
Incremental publishing and compact analysis inputs are installed on that hosted
installation with reviewed module hashes and private rollback receipts. Live cold
and cached publication passes succeeded; unchanged Docs used revision probes and
spam-image withdrawal used a complete folder scan. Existing schedules and health
pauses were restored, with collection uninterrupted. Historical image uploads
are still draining; changed large Docs and daily full verification can remain
slow. Exact client bindings, timings and request counts stay in private receipts.
Live Mac/iPhone acceptance, independent Linux setup, next-day Android renewal,
host reboot and phone-offline catch-up remain unverified. Historical media capture
is bounded and incomplete. External heartbeat and independent encrypted backup
remain separate work. Private rollout/rollback receipts belong outside Git.

Current source changes are checkpointed locally; this task does not push or deploy
the information site. The original public preparation CI passed Python 3.11/3.13;
that earlier CI run does not verify these later local commits.

Next: observe image-backlog completion and scheduled cache reuse; perform the
remaining client acceptance checks when their required devices are available.
