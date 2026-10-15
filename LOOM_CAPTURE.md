# Automatic Loom transcripts

This optional technical guide adds Loom transcripts to the text archive.
It supports answers about linked videos in the owner's preferred AI phone app.
It is not required for text collection or phone access.
Offer it with the other [optional content sources](REFERENCE_GUIDE.md#optional-content-coverage).
Skip its setup, monitoring, and verification when the owner does not use Loom.
Start with the [beginner path](README.md#start-with-your-agent).
Use [phone acceptance](PHONE_ACCESS.md#start-with-a-small-retrieval-check) to test
answers from the finished archive.

**Owner:** Choose whether to include transcripts from Loom links in captured texts.
This feature uses public-viewer access. It does not support transcripts that
require sign-in or private access.

**Agent:** Install and check this extension on the always-on archive computer.
Preserve existing collection, archive data and explicit pauses.

The Linux Loom service is optional and can be omitted.
The current Mac installer couples Loom startup to collector startup through `--enable`.
For a Mac without Loom, the agent must adapt that installation path before applying it.
Do not describe the current Mac command as an independent Loom opt-in.
See [Mac setup](MAC_SETUP.md#5-install-collection-jobs-then-verify-launchd) for the bundled command.

## Capture behavior and access limits

`archive_cli.py loom-capture` discovers Loom share/embed links in every owner's
archived messages. It attempts at most five due videos per run.
The five-minute user timer runs this command.
`loom-status` reports safe aggregate counts and worker timestamps.
Use optional `--owner OWNER` to select an owner.
Status output contains no content or video URLs.
Retrieval and schema failures return nonzero.
Permission denial and transcripts still processing remain explicit per-video queue
statuses.

Only canonical HTTPS www.loom.com share pages are requested.
Redirects are rejected. Capture requires referenced transcript metadata, viewer
permission and a visible transcript. Downloads use only referenced HTTPS
cdn.loom.com assets. Capture does not log in or bypass passwords.
Each request has a 20-second timeout and 10 MiB response limit.
Signed asset URLs and page HTML are never saved.
A removed, private or restricted video retains previously saved evidence.
Its current retrieval attempt is marked denied or unavailable.

## Evidence, retries and storage

The dedicated SQLite queue records owner/video identity and the canonical source
URL. It also records first discovery, attempts, retry time, current status,
failure age and last good revision.
Separate origins preserve every source message and conversation.
Successful videos are checked daily.
Failures retry hourly. Network failures retry in 15 minutes.
A local file lock prevents simultaneous capture writers.
Every completed run records worker freshness, even when no videos are due.

Raw transcript JSON and optional valid VTT captions are immutable SHA256-named
files under `OWNER/raw/loom`. They have private permissions.
Only validated, nonempty phrase JSON becomes a capture.
Immutable revisions contain normalized phrases, timestamp seconds, text,
language/version and provenance.
A semantic phrase hash prevents new revisions for JSON formatting changes alone.
SQLite and raw files use the existing verified snapshot and restore workflow.

Search remains a JSON list. It adds distinct `loom-transcript` matches with
revision citations and original message references.
Evidence previews annotate selected source messages with their saved transcripts.
Topic classification remains pending review.
Captures do not create synthetic messages.
They do not change Google Messages import counts or freshness.

## Agent installation

1. Install both `services/minbox-text-loom.*` files in the user systemd directory.
2. Place `loom_capture.py` beside `archive_cli.py` and `storage.py` in the existing private application install.
3. Reload systemd.
4. Enable and start the timer, unless the owner has explicitly paused it.
5. Check a completed capture run and `loom-status`.
6. Configure optional [Loom monitoring](HEALTH_ALERTS.md#loom-capture-monitoring) after the collector has run.

Keep runtime archive content outside Git.
A successful capture does not prove retrieval through the AI phone app.
Test that access separately through [PHONE_ACCESS.md](PHONE_ACCESS.md).
