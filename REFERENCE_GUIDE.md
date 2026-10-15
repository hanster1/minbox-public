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

Explain the few choices that affect the user's result.
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
Test harmless incoming and outgoing messages.
Check groups, images, edits, and unsent messages where they matter to the user.
Report history limits and unsupported formats.

Check scheduled imports, sleep behavior, restart, expired pairing, and recovery after disconnection.
Record tests that you cannot complete.
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
| Phone retrieval | Known-message answer and changed-source read | The desktop app answered. |
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

Check each stage separately: collection, filtering, output, phone access, and scheduled updates.
Use a known harmless message for the phone answer test.
Verify its date and source reference.
Then test a changed harmless source from the intended phone conversation or project.
Do not call the full user goal complete based only on collector or Drive success.

Record expected update delay, required desktop approvals, coverage limits, and untested restart or recovery behavior.
A new user must verify their own installation.
Existing Linux trials show that several routes can work; they do not guarantee every account or device.
Mac collection still needs live iPhone/Mac verification.
See [current phone evidence](PHONE_ACCESS.md#observed-evidence-and-limits--october-14-2026).

When an adaptation works, record the problem, change, checks, limits, and rollback in the relevant guide.
Remove obsolete workarounds when their cause no longer applies.
Use [CONTRIBUTING](CONTRIBUTING.md) for source and release checks.

## Choosing phone retrieval

Compare [phone access options](PHONE_ACCESS.md) with the user before choosing a route.
A built-in cloud connector, connected desktop, restricted search service, or manual upload can each be useful.
Custom MCP and OS isolation are options, not prerequisites for all users.
The chosen route must support the user's phone, account, and desired project behavior.
