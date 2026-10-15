# Create a local filtered archive folder

Use this output when an AI connection will read files from the always-on computer.
Your agent creates and maintains the folder. You choose what the AI may read.
Return to [the setup path](README.md#the-setup-path) for the full journey.

`local_archive_export.py` exports filtered UTF-8 text from an existing Minbox archive.
Available image files from retained messages are included by default.
It makes no Google, model, or network calls.
It can run alongside Drive publication, but does not require Drive calls to generate the folder.

This exporter is an existing-installation tool, not a complete local-only installer.
It needs a local archive and committed correction ledger.
A fresh installation without those inputs needs adaptation by your agent.
The current folder replacement code requires Linux.

Read [privacy choices](REFERENCE_GUIDE.md#who-sees-the-originals) before setup.
A cloud setup agent can receive originals returned by its tools.
An answering app with broad computer access can also read beyond this folder.
Local-model filtering is an optional added integration, not part of this exporter.

## Inputs and invocation

This section is for the agent.
Use the existing archive database, committed correction ledger, and agreed phone spam policy.
If the ledger cannot be read, the exporter refuses to release uncorrected output.

```sh
python3 -B -S local_archive_export.py \
  --archive-root /private/minbox-collection \
  --owner Casey \
  --correction-ledger /private/minbox-publisher/corrections.sqlite3 \
  --destination /home/user/Minbox-Filtered \
  --phone-spam-policy spam_and_blocked
```

Replace the example paths and owner with the actual installation values.
Agree on the spam policy with the owner.
Keep the destination separate from collection and runtime directories.
Keep it outside Git.
Its parent directory must already be private to the owner.
Source databases and their parent directories must also be private.

The tool refuses symlinks, hardlinks, unsafe permissions, and unmanaged destination contents.
It does not overwrite an arbitrary existing folder.

These neighboring Minbox modules are required:
`archive_corrections`, `archive_drive`, `archive_incremental`, `archive_io`,
`archive_snapshot`, `owner_archive_publisher`, `phone_spam`, `publisher_status`, and `storage`.
They use Python's standard library for this path and do not initialize Google credentials.
A standalone automated test runs with Python site packages disabled.

## Filtering and generation behavior

The output applies the existing publisher rules and validation helpers:

- Authentication-code and recognizable password-reset-link exclusions.
- Clear promotional-spam exclusions.
- Matching checks on message text, image text, and rendered transcript phrases.
- Committed spam corrections and undo operations.
- The selected phone Spam & blocked policy.

Loom transcripts need a retained origin message.
By default, the output contains text, available OCR, and captured images from retained messages.
Use `--text-only` to omit image files.
The user does not need to approve each image.
Images from excluded messages are omitted.
Raw databases, credentials, and unrelated source files are not copied.
No rule set guarantees that all sensitive content is removed.

Corrections reflect the committed local ledger at generation time.
An unprocessed remote Corrections Doc change is not yet local policy.
Phone spam exclusions reflect imported phone observations.
Make both update limits visible to the owner.

The exporter prepares a complete private generation beside the selected folder.
It rechecks source and correction fingerprints before replacement.
It also verifies the existing managed destination.
Then it exchanges the directories atomically, so readers see a complete generation.
Stale files disappear from the selected path.
A failure before exchange preserves the old generation; label that output with its actual age.

Replacement needs Linux `renameat2` support on the destination filesystem.
Other platforms need their own replacement implementation and tests.
Text limits are 100 KiB per file. Images are bounded separately at 20 MiB each.
Text is bounded at 256 MiB per generation.
A generation with images is bounded at 1 GiB total.
The output is bounded at 5,000 files.
The search adapter has separate limits and can return partial coverage.

Source and correction databases are opened read-only.
Corrections are recomputed in a private database backup.
SQLite WAL readers can still participate in shared-memory or sidecar coordination.
Read-only access does not mean zero filesystem activity around a live database.

## Optional image files

Choose original images separately from OCR.
By default, the exporter copies verified captured image bytes into the same filtered folder.
Each message names its exported image file. File names use the image hash, not a raw source path.
The exporter checks the owner attachment root, file permissions, size, image type, and content hash.
Missing or invalid captured files stop replacement and preserve the previous generation.
Uncaptured attachments remain coverage gaps.

Message and OCR filters do not examine the whole picture.
They can miss sensitive visual details, including text that OCR did not recognize.
Explain that limit when presenting the image option.
Optional local image models can add visual filtering, but this exporter does not include one.
Do not claim that a retained image has passed visual privacy review.

The answering app must be able to retrieve and attach a file from the computer.
A local path in an answer is not a viewable image on the phone.
Use one requested image to check that delivery works.
Copies sent to the AI service leave the local computer.
Removing an image from a later export does not retract earlier provider copies.

## Keeping it living

Schedule the exporter independently of AI sessions.
Choose an interval suited to message collection and computer resources.
The Linux trial used a separate user timer every three minutes.
Its service blocked new privileges and internet socket families.
Those are tested choices, not required settings for every client.

The folder contains `START_HERE.txt`, message parts, transcript parts, available image files, and a hidden manifest.
The manifest records generation time, counts, source fingerprints, correction fingerprints, and file hashes.
Check the refresh service and manifest age separately from AI app availability.
Keep message content out of health reports.

Readers must reopen the absolute folder path for fresh requests.
Directory exchange changes its inode, the filesystem's directory identity.
Old open handles, working directories, watchers, or uploads can retain an earlier generation.
A local replacement does not retract content already copied to an AI provider.

Use one [useful phone question](PHONE_ACCESS.md#start-with-a-small-retrieval-check) as the normal connection check.
Let the agent inspect generation time and scheduled-run status.
Use a changed sample only when diagnosing stale reads or a new integration.

## Native desktop apps on a headless host

A headless computer has no normal interactive desktop session.
Some AI desktop apps still need a graphical session for login and computer access.
The trial used TigerVNC, a virtual display, and a noVNC browser view over SSH.
VNC, web access, and app debugging ports listened on loopback only.
No public archive endpoint was created.
The owner completed sign-in and computer-access consent.

This session ran as the host user; it was not an OS security boundary.
Broad execution still allowed access as that user.
Auto Review rules were model-based.
An isolated environment needs separate restrictions and tests.
See [phone connection choices](PHONE_ACCESS.md).

On Omarchy, the official ChatGPT installer attempted a full upgrade.
Omarchy's update guard stopped that direct transaction.
The supported Omarchy update and package workflow then succeeded.
A remote shell needed `OMARCHY_PATH=/usr/share/omarchy`.
Use the installed update workflow rather than bypassing its guard.
Review system changes with the owner and check existing services afterward.
A successful installation does not prove unattended phone or reboot operation.

## Evidence

Synthetic tests cover filter parity, correction undo, phone observations, safe replacement, and failure preservation.
They also check path restrictions, source changes, standalone operation, and reset links across text and image-text fields.
The live security repair removed every detected reset-link source from the refreshed local output.
This does not prove that all possible secrets or opaque links are detected.

A Linux trial created and refreshed the local folder without Google retrieval.
Its counts matched the corresponding filtered publication before the later security repair.
Grok Bot read the real entry file correctly.
Grok Bot and ChatGPT both returned changed test values from Android without desktop approval.
Their actual message answers, project behavior, and reboot persistence remain unverified.
See [phone trial evidence](PHONE_ACCESS.md#observed-evidence-and-limits--october-14-2026) for route-specific limits.
