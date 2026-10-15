# Minbox checkpoint — October 14, 2026

## Active goal

Help the user set up their text archive through their own agent CLI on an always-on computer.
The goal is useful answers from their preferred AI phone app.
README is the beginner entry. Technical guides support that journey.

## Latest documentation work

The guides now start with prerequisites and distinguish owner actions from agent tasks.
Drive is one option, not the goal.
Normal setup has three checkpoints: collection, agreed filtering, and one useful phone answer with a source.
Agent tools check schedules and completed-run status. Extra file-change and restart tests are diagnostics, not owner setup steps.
Writing uses short sentences and consistent terms, with roughly 80% STE alignment as a style target, not a certified score.
Site source and the generated Drive guide use the same goal.
No site deployment or runtime update is included in this documentation pass.

## Implemented evidence

- Android/Linux collection and private Drive output have worked in an existing installation. Mac/iPhone is fixture-tested; live operation remains unverified.
- Linux local export and scheduled refresh work from an existing archive and correction ledger. Fresh local-only onboarding needs adaptation.
- Grok Bot and ChatGPT returned changed synthetic values from Android through direct computer access. Grok Bot also passed owner-reported Android message, Loom, and image retrieval checks. ChatGPT real archive answers, project behavior, and reboot persistence remain unverified.
- The read-only search prototype passed local tests. Remote phone registration is unverified.
- The reset-link repair is installed. All 24 detected sources were absent from refreshed local output. Original data stayed intact. Local-model filtering is an option, not an included backend.

## Recommended direction

Prefer testing connected-computer apps: Grok Bot, ChatGPT dot, and conditionally Claude Cowork.
This can avoid Drive publication and connector-refresh delays; comparative speed is not measured.
Official Claude guidance says desktop Dispatch is closed to new users; no Cowork trial has passed.
README and PHONE_ACCESS now distinguish recommended trials, account limits, and actual evidence.
No application code, runtime, or website deployment changed in this recommendation update.

## Keep normal setup short

The owner clarified that exploratory file-change and repeated retrieval tests should not become client onboarding requirements.
Reuse passing evidence on established paths. Investigate only new integrations, changed conditions, or concrete failures.
Essential permission and privacy checks remain. Existing trials still have partial evidence; the shorter checklist does not prove new capabilities.

## Optional follow-up choices

README now offers restart/power-return recovery, bounded automatic repair and email escalation, selected content coverage, and backup restoration.
REFERENCE_GUIDE separates included image/Loom behavior from potential audio, document, video, and link extraction extensions.
HEALTH_ALERTS explains agent-assisted repair and the missing automatic monitoring of local export and AI connections.
These are optional choices after basic setup, not added mandatory onboarding steps.
Loom is grouped with the other optional content types; skip it when not wanted.
The Mac installer currently bundles Loom with collection via --enable; documentation states that a no-Loom Mac path needs adaptation.
No runtime, device restart, notification delivery, or new media support changed in this documentation update.

## Options presentation and push gate

Before setup, the agent presents one compact menu of content and service options.
It confirms selections and labels each as included, optional, needing adaptation, or unavailable for the selected route.
Explain image files separately from OCR and distinguish local capture, output, and phone AI access.

The owner requires actual Grok Bot Android use before any push: useful archive answers, Loom transcripts, and original image retrieval.
The owner clarified that images from retained messages should be included by default, with text-only as an option.
No individual image approval list is required.
The owner confirmed the Android acceptance gate passed: messages, Loom transcripts, and original image retrieval/display.
Desktop checks and earlier synthetic file reads do not satisfy this owner-specific publication gate.
Archy reports a saved archive skill and durable-memory pointer for natural-language questions without host/path details.
With owner approval, Google Drive and Google Docs plugins were removed account-wide from Grok Bot for this test.
Cloud files, source archives, and publisher jobs remain intact. Reconnection uses the normal plugin setup and owner sign-in if needed.
Archy reports updated skill and durable memory for default image inclusion, OCR limits, and filtered-folder-only retrieval.
The owner confirmed original image retrieval and display worked in Grok Bot on Android with Drive and Docs disconnected.
No push is authorized by recording the gate.

## Next actions

Guide files, heading links, HTML navigation, and the release inventory pass checks.
Latest generated-guide checks pass: 18 tests, no failures.
Broader tests were not repeated for these guidance changes.
Independent review found no remaining material issue after corrections.
The owner-specific Grok Bot Android checks are complete. Changes are ready for publication review; do not add routine retrieval tests.
Keep credentials, exact bindings, and receipts private.
Google branding retry remains separate: October 15 after 3:20 PM US/Central, Branding → View issues → “I have fixed the issues” → Proceed.
Ownership verification succeeded; no verification approval or established Drive-policy violation exists.
Changes remain local until publication is authorized.

## Local image export update

Local export now includes captured images from retained messages by default.
`--text-only` omits originals and preserves available OCR.
Excluded messages never contribute images. Image files use verified owner-root bindings, private permissions, size, signature and hash checks.
Images are linked from their messages and take part in atomic replacement and withdrawal.
Text and OCR rules do not perform visual privacy review.
Tests: 537 tests run, 8 skipped, no failures; release inventory and whitespace checks passed.
The reviewed exporter is installed on the Linux trial host. A live generation succeeded with images, message links and file hashes verified. Scheduled refresh is active.
The owner confirmed Android image retrieval/display, message answers, and Loom transcript answers passed.
These results apply to this Grok Bot installation. Project behavior, reboot persistence, and enforced folder isolation remain unverified.

Pre-publication review added reusable saved archive guidance for natural-language questions and explained image-refresh disk activity.
No extra owner test was added. The unchanged-output optimization below supersedes the earlier refresh-cost note.

## Unchanged local export optimization

Current filters, rendering, source-image checks, correction checks and destination verification run each time.
Identical output with unchanged export settings and correction policy skips generation writes and directory replacement.
Importer observation times alone do not force a rebuild. Changed output, settings or corrections still rebuild atomically.
An unchanged receipt has a fresh `checked_at`; generation time stays unchanged. Health guidance distinguishes these times.
Source and image reads and small private policy-backup writes remain.
Tests: 542 tests run, 8 skipped, no failures; release inventory and whitespace checks passed.
Installed the reviewed exporter on the Linux trial host. An actual unchanged run preserved the manifest, generation ID, directory inode, and every output file inode and modification time.
The run returned `unchanged` with a new `checked_at`; its scheduled timer was resumed. No phone retest was needed because output bytes were unchanged.
