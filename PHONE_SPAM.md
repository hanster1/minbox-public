# Android phone spam and Drive removal

This optional technical guide helps the owner's installed coding agent connect
Android folder choices to archive filtering. It supports the path from paired
texts to answers in the owner's preferred AI phone app. Start with the
[beginner path](README.md#get-started). Use
[phone acceptance](PHONE_ACCESS.md#start-with-a-small-retrieval-check) for the
complete phone-answer test.

The Google Messages protocol exposes the phone's Spam & blocked folder state.
It cannot reliably confirm an exact manual Report spam tap. This folder can
include automatically filtered spam and conversations blocked without reporting.
The supported policy excludes the **whole Spam & blocked folder**.
It does not promise manual-report-only filtering.
The policy is optional. An absent policy or `off` changes nothing.

With `phone_spam_policy: "spam_and_blocked"`, reviewed positive collector
observations create durable owner/source/conversation exclusions. Both publishers
filter those conversations before model input or image upload. Full message
chunks, optional work messages/notes and dependent Loom views remove that content.
Withdrawn old message chunks are blanked.

Matching managed Drive images are permanently deleted. Deletion requires private
account, root, parent, identity and checksum checks. A durable journal tracks
retries. Unrelated messages and images remain intact.

Local originals, revisions and images are retained. Eligible content can return
when the collector confirms normal folder status through a fresh read-only lookup.
Ordinary events, missing conversations, failed scans and old responses cannot
restore content. Other archive corrections and filters still apply.
Restored images can receive new Drive links.

Independent snapshots and old installations must honor current exclusions before
publishing. This feature does not erase those copies.

## Enable after owner consent and collector checks

**Owner:** Choose whether to exclude the whole Spam & blocked folder.
An explicit manual-report-only request requires a different supported design.
Do not proceed with this policy as a substitute.

**Agent, on the archive computer:**

1. Build and install the reviewed collector through [GMKIT_MEDIA.md](GMKIT_MEDIA.md).
   Preserve its AGPL source and notices.
2. Verify connection and sending off.
   Confirm the new SQLite metadata tables and scan coverage.
3. Run the existing owner import.
   Inspect safe `phone_spam` counts for signal support and new exclusions.
   These counts contain no bodies or IDs.
   An old collector cannot support this policy.
   Never infer a signal from a missing conversation, archive action or deletion.
4. Set `phone_spam_policy: "spam_and_blocked"` in every full/work publisher for that owner.
   Use the reviewed owner configuration.
   Keep configs private.
   Preserve actual account, root and Doc bindings.
   Preserve budgets and explicit pauses.
   Do not enable this policy on iPhone.
5. Run publication.
   Verify text removal and managed image deletion.
   Restore prior schedules without removing explicit pauses.

A failed deletion retains its journal and prevents acknowledgment of successful
publication. Normal retries reconcile it. Authorization, privacy and integrity
failures require human attention under [HEALTH_ALERTS.md](HEALTH_ALERTS.md).
Background publishers and imports skip a busy owner until their next scheduled run.
They do not change success status or produce lock-wait failures.

**Owner, on the Android phone:** For live acceptance, report a benign disposable
conversation as spam. First have the agent verify its archive text and image.

**Agent, on the archive computer:** Verify removal of that exact observed
conversation from current Drive text views.
Verify that its managed image files are gone.
Check that unrelated content and local originals remain.
Verify that later import and idle cycles cannot republish the conversation.

**Owner, on the Android phone:** Move that conversation out of Spam & blocked.

**Agent, on the archive computer:** Verify a fresh normal-status confirmation.
Check that eligible text and images return without duplicates.
Check that unrelated content remains unchanged.
Fixture tests alone do not prove event delivery from a particular phone.

## Practical limits

Incoming updates usually propagate promptly. The collector also scans folder
metadata every five minutes. Import schedules, publication schedules and ongoing
work add delay.

The SDK scan has a 500-conversation cap and reports incomplete coverage.
It cannot prove that every existing phone spam conversation was seen.
Restoration uses bounded rotating lookups of known excluded conversations.
It does not infer normal status from absence or depend on the inbox list cap.

Rewriting native Google Docs removes current archive content.
It does not erase prior Doc versions. Google does not permit deletion of individual
native-Doc revisions. Erasing that history requires replacing affected Docs and
deleting old files. This changes links and is outside this policy.
AI chat answers, provider caches and independent backups are separate copies.

The feature requires an explicit policy and live acceptance.
Do not claim unattended phone-to-Drive deletion works before testing the installation.
A passing deletion test alone does not prove fresh answers in the AI phone app.
