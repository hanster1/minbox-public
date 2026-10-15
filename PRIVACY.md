# Privacy model

Minbox handles one of the most personal data sets a person has. This page says
what stays where, who can read it, and where the limits are. Choices are in
[REFERENCE_GUIDE](REFERENCE_GUIDE.md); the pipeline is in [ARCHITECTURE](ARCHITECTURE.md).

## Where data lives

- **On the host computer only**, by default: collector databases, the shared
  archive, correction ledgers and filtered folders. Files use mode 600 and
  folders 700.
- **In the owner's own Google Drive**, only if the owner chooses the Drive
  publisher, and only the filtered output.
- **With a cloud AI**, only what the owner's chosen phone app or agent reads.
  Decide that before setup; filtering happens before anything leaves the host.
- **Never in Git, chat or screenshots**: pairing sessions, OAuth tokens,
  message content, phone numbers, health status files or owner configs.

## What gets filtered out

- Conversations the owner marks as spam or blocks on the phone (Android path),
  which come back if unmarked.
- Hard exclusions: security and one-time codes, password-reset links, and
  opt-out promotional texts.
- Anything the owner corrects through the corrections ledger.

Filtering hides content from derived outputs; the raw archive keeps it so a
mistake can be undone.

## Several people on one computer

Each person gets their own collector, ledger, filtered folder, optional Drive
folder and jobs, and each person's agent should be pointed only at their own
folder.

**Limitation:** when everyone's jobs run under one operating-system account,
this separation is **by setup, not by permissions**. Any program or agent
running as that account, including the administrator's, can technically read
every owner's files. Households that need real isolation should give each
person their own OS account and run their own jobs there. Agree on this
explicitly before adding someone else's messages.

## Consent

Only the phone's owner pairs their phone, and only with their agreement. Never
collect another person's messages without their consent.

## Removing data

Stop and disable the owner's jobs, then delete their collector store, ledger,
filtered folder, marker and any Drive output, and delete their rows from the
shared archive after a backup. Unpair the device in Google Messages.
