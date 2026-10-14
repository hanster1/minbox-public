# Minbox public project brief

Provide an adaptable reference that a client's CLI-capable coding agent can use
to get private text collection, filtering and Drive sync working with little
avoidable friction. Include a working implementation, useful considerations and
lessons with evidence and limits. REFERENCE_GUIDE.md explains design choices;
platform guides are concrete recipes for the supplied code. Methods, paths,
schedules and optional features can change with the client's needs. Preserve
privacy, consent, integrity and existing data through adaptation.

The included Android/Linux path uses a pinned read-only Google Messages
collector; the iPhone path reads Messages on the owner's Mac. Both feed the
owner-wide publisher, image handling, corrections and health mechanisms. README
states current support and verification limits. New platforms need implementation
and acceptance work. Optional work analysis and Loom capture are extensions.

The current Google implementation requires exactly drive.file and verifies
account/root/privacy/parent bindings. Preserve existing Docs and source identity.
Each user owns their grants; AI retrieval has separate permissions. Full
publication needs no runtime model. Discuss token-efficient optional analysis,
meaningful health signals and bounded recovery rather than assuming a background
agent or one fixed operating policy is necessary.

Assess success through verified capture, filtering, private native Docs readback,
scheduled operation and useful health, with honest coverage limits. The shipped
monitor uses emergency-only external notifications and fixed bounded recovery;
an adapted design should explain its alert policy and preserve explicit pauses.
Source changes require appropriate checks and review.

Keep credentials, messages, images, databases, provider logs and machine-specific
notes outside Git. This repository has fresh sanitized history. Do not import a
private development repository's history or operator checkpoints.

## Authoritative development source

All new Minbox work belongs in this repository. Retained private development
history is a reference only; do not refresh this project from an older private
copy or maintain two competing implementations. Preserve release checks and
update SOURCE_MANIFEST.json hashes for reviewed source changes. Any required
legacy-only tool or operational context must be accounted for before retiring
its historical repository; private records never migrate into public Git.

## Material ownership

MAINTENANCE.md is the change-location map. Application/client guides and public
website assets live here. Hosted tools and generic deployment operations live in
the operator's private infrastructure notebook. Exact pilot context, receipt paths,
local hosting linkage and inactive session artifacts stay outside Git. The old
private project retains only historical source/branches and pointers; do not use
it to maintain active assets. Source relocation changes no runtime path, service,
Google grant, hosting URL or deployment target.
