# Help the user reach useful answers from their phone

Use this guide to make setup choices with the user.
The goal is a living, filtered text archive that their preferred AI phone app can read.
The user's agent CLI does the technical work on their always-on computer.

Start with [README](README.md). Use this guide when a choice needs more detail.
Read only the technical recipes needed for the selected route.

## How to use this repository

First check the prerequisites: an always-on computer and an installed agent CLI with access to a strong reasoning model.
Check the user's phone, AI app, account features, and existing installation.
Preserve existing messages, corrections, account connections, and deliberate pauses.

Present [the options menu](README.md#choose-what-is-included) before setup.
Explain content and service choices in one compact exchange.
Show what is included in the selected route, what is optional, and what needs adaptation or is unavailable.
Confirm the owner's choices together; reuse decisions already made.
Then do the authorized work. Ask the user for missing facts or device and account actions.
Name the computer or phone for each action.

Use the included code where it fits. Adapt it where necessary.
New platforms and connections need implementation and tests; a guide alone does not add support.

| Type of guidance | How to use it | Example |
| --- | --- | --- |
| User goal | Verify the agreed result | Useful answers from the chosen phone app |
| Code constraint | Preserve it unless you change and test the code | Private Drive folder checks and guarded writes |
| Setup choice | Adapt it to the installation | Storage route, paths, schedules, and alert channel |

The repository provides a working reference, not one mandatory computer configuration.
Google Drive is an output option. It is not the final result.
Keep [phone access](PHONE_ACCESS.md) in the plan from the start.

## Collection and coverage

Choose a message source that works with the user's devices.
The included Android/Linux path pairs a read-only Google Messages collector.
The iPhone/Mac path reads Messages synchronized to the owner's Mac.
Mac background operation still needs live verification.

Use [Android/Linux setup](ONBOARDING.md) or [Mac setup](MAC_SETUP.md).
The source connection and AI connection have separate permissions.
A successful interactive command does not prove that the scheduled job has access.

Keep source IDs and revisions. They support repeat runs, citations, and corrections.
Confirm that one captured message reaches the archive.
Investigate groups, images, edits, or unsent messages only when relevant to the chosen features or a reported gap.
Report history limits and unsupported formats.

Check schedules and available completed-run status with local tools.
Reserve sleep, restart, pairing-expiry, and outage experiments for an actual issue or explicit reliability requirement.
Record relevant known limits without making the owner run every experiment.
A running process, recent row, or connected socket does not prove complete phone coverage.
Do not replace a broken installation with an empty archive.

## Filtering and useful views

Keep originals separate from the filtered output.
This lets the user reverse a mistaken exclusion without losing evidence.
Agree on what may reach an AI service before connecting real content.

The full archive uses Python rules, explicit corrections, and optional phone spam status.
It needs no model calls.
The rules exclude authentication codes, recognizable password-reset links, and clear promotional spam.
They do not detect every secret or sensitive topic.

Check useful retained messages as well as excluded examples.
Broader filters can remove useful context.
Apply the policy to image text, transcripts, and attachments too.
Read [archive behavior](OWNER_ARCHIVE.md) before changing the supplied filters.

[Phone Spam & blocked exclusions](PHONE_SPAM.md) are an optional whole-conversation policy.
Do not infer agreement to that policy from permission to collect texts.
The optional work view has its own classification and correction rules.
A work label cannot override a security exclusion.

### Who sees the originals?

Separate these stages before setup:

| Stage | Possible exposure | Useful control |
| --- | --- | --- |
| Setup and debugging agent | Originals returned by its tools can reach its model provider | Agree on access. Prefer synthetic examples and counts without message content. |
| Routine Python filtering | Original text and available image text stay in the local program | Keep its inputs and outputs separate. This stage makes no model calls. |
| Optional model filtering | The filtering model receives selected content | Choose local inference if originals must remain on the computer. |
| Phone AI answers | Retrieved content reaches the answering provider | Expose only the approved output through suitably restricted access. |

A local CLI can use a cloud model.
“Runs locally” does not mean that model processing stays local.
Later filtering does not undo an earlier disclosure to a setup agent.

Broad computer access can let an answering app read originals outside the filtered folder.
A prompt, folder name, or model-based rule is not an enforced file permission.
Use a restricted connection when that boundary matters.

### Optional local-model privacy filtering

A local model can help develop Python rules from private examples.
It can also classify or redact messages before they enter the released archive.
These are different choices. Reviewed Python rules can run later without a model.
Model filtering at runtime needs local compute and its own quality checks.

This can help with sensitive health discussions, account recovery notices, or confidential work topics.
The supplied exporter does not include a local-model backend.
The optional Codex analyzer is not a local-model backend either.
Your agent would need to add and test that integration.

One possible flow is:

```text
Private originals
  -> Python security exclusions
  -> Local-model classification or redaction
  -> Checked filtered folder
  -> Cloud AI connection and phone answers
```

For local-only processing, check where inference actually runs.
Check for hosted fallback, content telemetry, remote embeddings, and uploaded debug logs.
Keep model prompts, caches, and review queues private too.
Use synthetic examples with a cloud setup agent when originals must stay local.
Return counts and test results rather than private message text.

Bind decisions to the content revision, filter policy, and model version.
Review uncertain cases before release.
A failure must not silently release unfiltered text.
An unchanged older output can remain available, but label its age clearly.

Test the policy with representative private examples on the local computer.
Check for sensitive content that escaped and useful content that was removed.
Text redaction alone does not protect an attached screenshot.
No model or rule set guarantees perfect filtering.

Recognizable password-reset links trigger a hard exclusion in the supplied code.
The containing source and its attachments are withheld.
Reset or recovery wording can identify an opaque shortened link.
An opaque link without identifying context cannot reliably be recognized by these rules.

Refresh existing outputs after a filter change.
Earlier document revisions, provider copies, and cached answers can remain.
Previously uploaded images need a separate withdrawal check.

## Optional content coverage

Present the content types below, with support limits for the selected route, before asking what the user wants.
Do not expect a beginner to know that attachments or transcripts may need separate setup.
All items below are optional, including Loom. Skip Loom setup and verification if the user does not need it.
Choose one representative example for each selected type; do not test the whole menu.
Use an example in the normal phone question where practical.
Check the path from capture through filtering to the answer.
A saved attachment is not necessarily readable by the phone AI.
Explain local capture, filtered output, and phone retrieval separately.
The Drive publisher includes retained captured images; a text-only local export does not include image files.

| Content | Included behavior or current limit | Optional check or extension |
| --- | --- | --- |
| Photos, screenshots, and image-only messages | Available image originals can be captured and published through Drive. Local text export includes available OCR, not image files. | Check whether the chosen AI can read the image or its extracted text. |
| Loom links, only if wanted | Optional capture can include accessible saved transcripts. Restricted videos remain gaps. | Check transcript retrieval and a source timestamp for a video the user can access. |
| Voice notes and audio attachments | The supplied image attachment path does not provide general audio capture or speech transcription. | Add capture and transcription if needed. Decide whether transcription stays local. |
| PDFs and other documents | General document attachment extraction is not included. | Add supported file capture and text extraction, then apply the same privacy filters. |
| Ordinary video attachments | Loom transcript support does not cover arbitrary video files. | Decide whether audio transcription, captions, or visual content is needed. |
| Web links and shared locations or contacts | A link or text is not the same as the linked page, map, or structured card. | Check what the collector retained before adding page retrieval or another parser. |
| Groups, replies, reactions, edits, and unsent messages | Representation varies by source; some events are omitted. Mac collection does not reconstruct full edit history. | Check participant identity and the context needed for the user's questions. Report gaps honestly. |

A transcript or extracted document can contain the same secrets as a message body.
Filter derived text before exposing it to the answering provider.
Keep original media private and preserve source references.
Do not imply that deleting a message on the phone retracts copies already retained elsewhere.
New extraction features need implementation and focused tests before being described as supported.

## Google connection and publication

Use this section only when the user chooses Drive.
[Google setup](GOOGLE_SETUP.md) explains OAuth, Google's account access process.
A maintained shared application can avoid a separate Cloud project for each user.
Each user still grants access to their own account.

Check whether a usable shared client configuration is actually available.
Do not promise a verified public app or public configuration download before it exists.
The alternative is the user's own Google Cloud application.

The included code requires exactly `drive.file`.
Google authorizes selected and app-created files; it does not grant recursive folder access.
Minbox also checks the owner, private root, and managed parent folders.
Keep those checks, document identities, and the designated Corrections input intact.
Never make the archive public to solve retrieval problems.

For performance, measure a completed publication and a later scheduled repeat.
Serialized revision reads and retries can make small archives slow.
That alone is not evidence of provider throttling.
Read [publication performance](OWNER_ARCHIVE.md#publication-performance) before changing limits.

Compare cold and warm runs. Change one relevant setting at a time.
Preserve guarded writes and readback checks.
Check import catch-up after tuning.
A busy or overlap skip is not a completed publication.
Other storage designs need their own permission, update, and retrieval tests.

## Health that tells the owner something useful

Monitor the stages needed for phone answers.
A process check alone is not enough.

| Stage | Useful check | Misleading shortcut |
| --- | --- | --- |
| Collection | Valid connection, source access, and read-only mode | The process is running. |
| Import | Completed import, database integrity, and pending source IDs | The last message is recent. |
| Filtered output | Completed generation, current policy, and readable files | The previous output still exists. |
| Cloud publication, if used | Completed verified output and correct permissions | A skipped run returned success. |
| Phone retrieval | One useful answer from the intended phone app, with a source | The desktop app answered. |
| Schedule and recovery | Automatic repeat and later healthy observation | A restart was requested. |

Use limited, reviewed retries for ordinary failures.
Keep retry counts and cooldown state between runs.
Preserve explicit pauses and avoid interrupting active work.
Notify the owner when action is needed, with one clear next step.
Deduplicate alerts for the same problem.
Keep messages, contacts, credentials, and provider payloads out of alerts.

[Linux health](HEALTH_ALERTS.md) and [Mac setup](MAC_SETUP.md) describe the supplied monitors.
The Linux policy sends external alerts only for unresolved emergencies.
Treat example timings and channels as choices for the user's installation.
Check whether local export and the chosen connector need added monitoring.

Optional analysis or history backlog should not appear as failure of a healthy primary archive.
A local monitor cannot report complete host or network loss.
Consider an independent heartbeat if the user needs that coverage.
Health recovery is not an independent backup. Test restoration separately when needed.
Offer [optional restart and alert checks](HEALTH_ALERTS.md#optional-reliability-checks-and-agent-assisted-repair) after basic setup.
Pairing persistence, background-job startup, and AI desktop-app availability are separate parts of restart recovery.

## Efficient AI and agent use

Use a strong reasoning model for setup choices and difficult repairs.
Use ordinary programs for scheduled collection, filtering, publication, and health checks.
A model session on every poll adds cost without necessarily improving reliability.

Read the relevant guides and source sections instead of loading the whole repository repeatedly.
Use small searches and selected source reads for answers.
Keep private notes on settings, completed checks, gaps, and the next action.
This avoids repeated discovery after a session ends.

For optional AI analysis, define the purpose and permitted input first.
Filter disallowed sources before constructing model requests.
Analyze changed eligible content only when possible.
Reuse decisions only when the source and policy still match.
Limit context, output size, calls, tokens, and retries.
Count failed attempts and unknown usage too.
Stop repeated failing analysis instead of resending the same content indefinitely.

An analysis failure should leave the primary archive available.
The included optional analyzer uses a Codex-specific adapter.
Another provider needs an adapter and tests.
Any capable agent CLI can help install Minbox; that does not make it a compatible runtime analyzer.

## Acceptance and lessons to carry forward

Keep normal setup to three checkpoints: messages arrive, agreed filters apply, and the phone gives a useful source-backed answer.
Let the agent check output age, permissions, schedules, and available completed-run status with tools.
Use the same phone question to check the chosen conversation or project.
Reuse passing evidence; do not ask the owner to reproduce our exploratory tests.
Use [focused diagnostics](PHONE_ACCESS.md#troubleshooting-and-new-integrations) only when a new integration or a concrete problem needs them.
Do not call the full user goal complete based only on collector or Drive success.

Record expected update delay, required desktop approvals, coverage limits, and untested restart or recovery behavior.
Confirm the essential results on the actual installation; do not repeat unrelated tests.
Existing Linux trials show that several routes can work; they do not guarantee every account or device.
Mac collection still needs live iPhone/Mac verification.
See [current phone evidence](PHONE_ACCESS.md#observed-evidence-and-limits--october-14-2026).

When an adaptation works, record the problem, change, checks, limits, and rollback in the relevant guide.
Remove obsolete workarounds when their cause no longer applies.
Use [CONTRIBUTING](CONTRIBUTING.md) for source and release checks.

## Choosing phone retrieval

Compare [phone access options](PHONE_ACCESS.md) with the user before choosing a route.
First consider Grok Bot or ChatGPT dot with connected-computer access.
Claude Cowork is a conditional candidate; its desktop Dispatch route is closed to new users.
Check [current recommendations](PHONE_ACCESS.md#recommended-options-to-try-first) and account eligibility.
Direct reads can avoid Drive publication delays, but full answer quality and reliability still need tests.
A built-in cloud connector, connected desktop, restricted search service, or manual upload can each be useful.
Custom MCP and OS isolation are options, not prerequisites for all users.
The chosen route must support the user's phone, account, and desired project behavior.
