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
and complete-source distribution instructions. CI is prepared with pinned Actions
and Python 3.11/3.13; GitHub execution has not occurred.
Live Mac/iPhone acceptance, independent Linux client setup, natural next-day
Android renewal, host reboot and phone-offline catch-up remain unverified.
Historical media capture is bounded and incomplete; external host heartbeat and
independent encrypted backup remain separate work.

GitHub publication is pending. Next: run the release checks, review the public
contents and license notices, then publish the reviewed new repository when
explicitly authorized. Client-specific checkpoints stay private outside Git.
