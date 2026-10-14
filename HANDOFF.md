# Public source checkpoint

Prepared as a separate sanitized source project with fresh history. Application
source and synthetic fixtures come through an explicit inventory; private operator
documents, account bindings, runtime data and private Git history are excluded.
The source manifest tracks exported file hashes; it is not proof of authenticity.

Validation: 382 synthetic Python tests pass, with five optional skips. The release
checker verifies 84 shared source hashes, the explicit public-file inventory,
credential-shaped content, private Drive links and relative guide links. It passed
for 109 files and correctly rejected unexpected-source and modified-source probes.
An independent review checked known private identifiers with zero matches.
A separate fresh local clone passed all 382 tests (five optional skips) and the
109-file release check. Its only history is the new public preparation commits,
with a GitHub noreply author address; private history was not copied.

Minbox's original code is MIT-licensed; the collector patch retains upstream AGPL
and complete-source distribution instructions. GitHub CI passed on Python 3.11 and 3.13 for the first published checkpoint
`92dac0c`, including regression and release hygiene checks. Run:
https://github.com/hanster1/minbox-public/actions/runs/38471975891.
Live Mac/iPhone acceptance, independent Linux client setup, natural next-day
Android renewal, host reboot and phone-offline catch-up remain unverified.
Historical media capture is bounded and incomplete; external host heartbeat and
independent encrypted backup remain separate work.

The owner authorized public GitHub publication and selected this repository as
the default for all future Minbox work. Canonical development now happens here;
legacy private source/history stays retained until remaining tools, operational
context and deployment dependencies are accounted for. It must not overwrite
new public fixes or contribute its private history.

Publication verified: https://github.com/hanster1/minbox-public is public,
default branch main, and remote main matched local checkpoint `92dac0c`.
The retained private repository's checkpoint was also pushed and verified;
its visibility remains private. Next: address live client acceptance gaps.
Client-specific checkpoints stay private outside Git.

## Useful-material relocation

Canonical website source now lives in information-site/ with updated current
platform, image, permission and optional-AI wording. Existing OAuth branding and
URLs were preserved. MAINTENANCE.md maps each kind of future change to one home.
Hosted tools/operating procedures moved to the private infrastructure notebook;
exact pilot notes, original operating notes and an inactive Vercel session receipt
were preserved outside Git. Ignored local site linkage was moved byte-for-byte.
No live runtime, consent, pairing, site deployment or old-project deletion occurred.
The historical repository and unique validation branch/worktree remain retained.

Relocation validation passed: 382 Python tests (five optional skips), the
118-file release check, static HTML/navigation/upload-boundary checks and byte-
exact local linkage verification. Private original notes were hash-verified.
Hosted helper tests used synthetic clipboard/SSH commands only. Source changes
are checkpointed locally; website publication is a separate future operation.

## Android phone-folder exclusions and restoration

Implemented opt-in `phone_spam_policy: spam_and_blocked`: reviewed numeric phone
folder observations create current owner/conversation exclusions. Both publishers
filter before model/image inputs under a shared owner operation lock. Current
Drive text/derived views are rebuilt and stale chunks blanked; matching managed
images use guarded permanent deletion and crash-safe reconciliation. Historical
source-ID moves remain excluded while the conversation is excluded. Local
originals and revisions remain, as requested.

Moving a conversation out of Spam & blocked restores eligible content only after
an explicit matching, fresh GetConversation response reports normal status 1/2/4.
The request must begin at least a minute after the latest positive observation;
newer spam wins. Missing threads, nil/error responses, normal asynchronous events,
caps and stale replay cannot clear exclusions. Targeted lookups rotate through
20 known exclusions per five-minute cycle within one shared 30-second budget and
one pending SDK request. Startup and recurring metadata reconciliation run before
and independently of history import; connection/fatal-event gates prevent requests
after logout. Lifecycle and request races pass Go race tests. Historical evidence and restoration state remain durable.
Work-analysis cache scope includes the active set even when it becomes empty.
Restored images may get new Drive IDs; text Doc IDs remain stable.

417 Python tests pass (five optional skips); pinned Go tests and both binaries
build with locked dependencies. Complete AGPL source/provenance bundles are
prepared outside Git. Release checks pass for 121 files and 86 manifested source
files. Synthetic restoration tests cover text across years, retained images,
pending-deletion recovery, Loom origins, stale replay and reblocking.

The owner explicitly approved all Spam & blocked, including automatic spam and
block-only conversations, and requested restoration on removal from that folder.
That scope decision is resolved. Runtime rollout and real phone/Drive acceptance
must be recorded separately; fixtures do not prove live propagation. Enable only
for explicitly consenting owners, preserve their private account/root/Doc bindings,
pauses and budgets. Native Docs history is not erased by current-content rewrites.
See PHONE_SPAM.md. Private installation receipts and exact bindings stay outside Git.
