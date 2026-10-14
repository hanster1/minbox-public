# Minbox text archive

Minbox is an adaptable reference for coding agents setting up private text
collection, filtering and Google Drive sync on a client's computer. It includes
a working implementation, concrete setup recipes and documented operating lessons.
Start with [the reference guide](REFERENCE_GUIDE.md) for design choices, health
checks and efficient AI use; tailor the approach to the client's environment.

The included implementation keeps captured texts and available images in a
private Google Drive folder. A preferred AI app can search it through its own
Drive connection. Collection and full archive publication require no AI model.

## Get started

On the computer you will leave running, open a coding agent that can run local
commands, such as Codex or Claude Code, and give it this prompt:

> Use https://github.com/hanster1/minbox-public to set up this computer to sync
> my text messages to my private Google Drive archive. Read the project's
> AGENTS.md and REFERENCE_GUIDE.md, inspect any existing setup, adapt the
> approach to my computer and preferences, and do the technical work. Explain
> clearly when I need to act on this computer versus my phone.

For a supported implementation path, the agent clones the project, checks your
platform, prepares private runtime storage, guides account consent and verifies scheduled collection/publication.
You choose the archive folder's name and may rename it later.

This is the primary Minbox project. No ZIP or pre-created source directory is
required.
A chat subscription alone does not provide local CLI access. Grok or another
agent can perform setup if its actual environment supports local files/commands;
Minbox does not assume any provider has a particular CLI.

## Compatibility and owner actions

| Phone | Always-on collection computer | Status |
| --- | --- | --- |
| Android with Google Messages | Linux with a per-user systemd session | Live phone-to-Drive capture and images verified; independent client installation still needs acceptance. |
| iPhone | Mac with Messages synchronized to that iPhone | Adapter, images, installer and recovery fixture-tested; live macOS/iPhone acceptance still required. |

Android collection on Mac and Windows is not implemented. Sleep, phone
connectivity, account revocation and host outages can interrupt capture.

You complete Google sign-in/consent and phone pairing yourself. iPhone owners also
approve the Mac's Messages access. A matching Desktop OAuth application with
Drive, Docs and Picker APIs enabled is required; obtain its client configuration
privately or create your own using [GOOGLE_SETUP.md](GOOGLE_SETUP.md). An agent
must check this prerequisite before promising an unattended installation.

Minbox requests Google's `drive.file` permission. Google authorizes selected and
app-created files; Minbox separately enforces its chosen archive root. Files you
manually add inside that folder do not automatically gain authorization. Read
[ONBOARDING.md](ONBOARDING.md) for the setup sequence and limits.

Connect Grok, Claude or another compatible AI app yourself using its settings.
That app has its own permissions. An explicitly optional retrieval check can
confirm that it finds a familiar message; skipping it does not block Minbox.

## What it preserves

Messages retain source IDs, dates and revisions. Authentication codes and clear
promotional spam are filtered from published Docs. Available original images are
verified, stored privately and linked to their messages; optional local OCR is
labeled as machine-extracted text. Missing/unsupported media stays an explicit
coverage gap. This is a bounded archive, not a complete phone backup.

Reviewed health actions retry ordinary failures. Only unresolved emergencies
requiring human action are eligible for notifications; no routine, reminder or
recovery mail. External delivery is separately configured and tested with consent.
A local monitor cannot notify during complete host/network failure.

## Guides and development

- [Adaptation, design choices and lessons](REFERENCE_GUIDE.md), including health signals and AI/token budgets.
- [Agent setup entry](AGENTS.md), [onboarding](ONBOARDING.md) and [Google application setup](GOOGLE_SETUP.md).
- [Mac setup](MAC_SETUP.md), [Mac repair](MAC_RECOVERY.md) and [Android recovery](ANDROID_RECOVERY.md).
- [Phone spam exclusions](PHONE_SPAM.md), [archive behavior](OWNER_ARCHIVE.md), [health policy](HEALTH_ALERTS.md), [collector source](GMKIT_MEDIA.md).
- [Publication performance and tuning](OWNER_ARCHIVE.md#publication-performance), including bounded revision reads, part sizes and completed-run verification.
- [Where to make changes](MAINTENANCE.md), [website source](information-site/README.md).
- [Development and release checks](CONTRIBUTING.md), [license](LICENSE) and [third-party notices](THIRD_PARTY_NOTICES.md).

Run `python3 -m unittest discover -s tests -q` for synthetic regression checks.
Runtime archives, credentials, images and machine-specific checkpoints belong
outside Git. Read-only support reports help an agent resume without uploading
message history. Never make archive files public to solve an AI access problem.
