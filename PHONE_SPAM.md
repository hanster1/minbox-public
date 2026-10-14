# Android phone spam and Drive removal

The available Google Messages protocol exposes Spam & blocked folder state,
not a reliable receipt of an exact manual Report spam tap. That folder can include
automatically filtered spam and conversations blocked without reporting.
The supported policy is therefore **exclude the whole Spam & blocked folder**,
not a manual-report-only promise. It is opt-in; absence or `off` changes nothing.

When `phone_spam_policy` is `spam_and_blocked`, positive reviewed collector
observations create durable owner/source/conversation exclusions. Both publishers
filter those threads before model input or image upload. Full message chunks,
optional work messages/notes and dependent Loom views reconcile without their
content. Old message chunks are blanked when withdrawn. Matching managed Drive
images are permanently deleted with private-account/root/parent/identity/checksum
checks and a durable retry journal; unrelated messages and images remain intact.

Local originals, revisions and images are retained. Moving a conversation out of
Spam & blocked restores eligible content after the collector confirms its normal
folder status with a fresh, read-only lookup. Ordinary events, missing threads,
failed scans and old responses cannot restore it. Other explicit archive
corrections and filters still apply. Restored images may receive new Drive links.
Earlier independent snapshots and old installations must honor the current
exclusions before publishing; they are not erased by this feature.

## Enable after owner consent and collector checks

1. Explain the all-Spam-&-blocked scope and obtain the owner's choice. Do not
   substitute it for an explicit manual-report-only request.
2. Build/install the reviewed collector using GMKIT_MEDIA.md, preserving its
   AGPL source/notices. On the actual collection computer, verify connection and
   sending off; confirm the new SQLite metadata tables and scan coverage.
3. Run the existing owner import. Its safe `phone_spam` counts report signal support
   and new exclusions without bodies or IDs. An old collector cannot support this
   policy. Never manufacture a signal from a missing thread or archive/deletion.
4. Under reviewed owner configuration, set `phone_spam_policy: "spam_and_blocked"`
   in every full/work publisher for that owner. Keep configs private and preserve
   actual account/root/Docs bindings, budgets and pauses. Do not enable on iPhone.
5. Run and verify publication and image deletion, then restore prior schedules.
   A failed deletion retains its journal and does not acknowledge successful
   publication. Normal retries reconcile it; auth/privacy/integrity failures need
   human attention under HEALTH_ALERTS.md. Busy publishing/imports serialize per owner.

**Phone (owner's Android phone):** for live acceptance, report a benign disposable
conversation as spam after its archive text/image has been verified. **Computer
(collection host), agent:** verify that exact observed conversation disappears
from current Drive text views, its managed image files are gone, unrelated content
remains, local originals remain and later import/idle cycles cannot republish it.
Then, on the phone, move that conversation out of Spam & blocked. Verify that a
fresh normal-status confirmation restores its eligible text and images, without
duplicates or changes to unrelated content. Fixture tests alone do not prove a particular phone's event propagation.

## Practical limits

Incoming updates normally propagate promptly; the collector also scans folder
metadata every five minutes. Import/publication schedules and ongoing work add
latency. The SDK scan has a 500-conversation cap and reports incomplete coverage;
it cannot prove every existing phone spam thread was seen. Restoration uses
bounded, rotating lookups of known excluded conversations rather than inferring
normal status from absence or relying on the inbox list cap.

Rewriting native Google Docs removes current archive content but does not erase
Google's prior Doc versions. Google does not allow deleting individual native-Doc
revisions. Erasing that history would require replacing entire affected Docs and
deleting their old files, changing links; that is outside this policy. Existing AI
chat answers/provider caches and independent backups are also separate copies.

The feature is implemented behind an explicit policy and needs live acceptance
before claiming unattended phone-to-Drive deletion works for an installation.
