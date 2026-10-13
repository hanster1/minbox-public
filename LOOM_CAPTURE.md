# Automatic Loom transcripts

`archive_cli.py loom-capture` discovers Loom share/embed links in every owner's
archived messages and attempts at most five due videos per run. The five-minute
user timer runs this command. `loom-status` (optionally `--owner OWNER`) reports
safe aggregate counts and worker timestamps, with no content or video URLs.
Operational retrieval/schema failures return nonzero; permission denial and
transcripts still processing remain explicit per-video queue statuses.

Only canonical HTTPS www.loom.com share pages are requested. Redirects are
rejected. Capture requires the page's referenced transcript metadata, viewer
permission and visible transcript, and downloads only referenced HTTPS
cdn.loom.com assets. It does not log in or bypass passwords. Each request has a
20-second timeout and 10 MiB response limit. Signed asset URLs and page HTML are
never saved. A removed/private/restricted video retains previous saved evidence
but is marked denied/unavailable for the current retrieval attempt.

The dedicated SQLite queue keeps owner/video identity, canonical source URL,
first discovery, attempts, retry time, current status, failure age and last good
revision. Separate origins preserve every source message and conversation.
Successful videos are checked daily; failures retry hourly, network failures in
15 minutes. A local file lock prevents simultaneous capture writers. Every
completed run records worker freshness, including runs with no due videos.

Raw transcript JSON and optional valid VTT captions are immutable, SHA256-named
files under OWNER/raw/loom with private permissions. Only validated, nonempty
phrase JSON becomes a capture. Normalized phrases, timestamp seconds, text,
language/version and provenance are saved in immutable revisions. A semantic
phrase hash avoids revisions for changes only to JSON formatting. SQLite and raw
files are included in the existing verified snapshot/restore workflow.

Search remains a JSON list and adds distinct `loom-transcript` matches with
revision citations and original message references. Evidence previews annotate
selected source messages with their saved transcripts; topic classification
remains pending review. Captures do not add synthetic messages or change Google
Messages import counts or freshness.

Install the two `services/minbox-text-loom.*` files in the user systemd directory
and place loom_capture.py alongside archive_cli.py/storage.py in the existing
private application install. Reload systemd and enable/start the timer. Runtime
archive content remains outside Git. Authentication-only/private Loom transcripts
are not supported by this public-viewer capture path.
