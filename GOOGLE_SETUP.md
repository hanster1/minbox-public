# Google application prerequisite

Use this guide only if the owner selects the supplied Drive publication path.
It prepares private Google access for the filtered archive. The end goal is useful
answers in the owner's preferred phone AI app. Start with [README](README.md).
Use [PHONE_ACCESS](PHONE_ACCESS.md) for final phone acceptance.
[REFERENCE_GUIDE](REFERENCE_GUIDE.md) explains storage choices and privacy.

**Prerequisites:** the owner has a working coding agent CLI with a capable
reasoning model on the collection computer. For Drive, prepare a Google Cloud
application with a **Desktop app OAuth client**. Enable the Drive, Docs and Google
Picker APIs in that same project. **Agent:** check these before opening consent.
**Owner:** perform sign-in, account consent and device prompts. Each owner must
authorize their own account. Never reuse another owner's refresh token or
collector session.

A family can share the computer while choosing different output routes.
A Drive publisher does not create a [local filtered folder](LOCAL_EXPORT.md#one-local-export-per-owner) automatically.
When removing one owner's Drive setup, preserve other owners' grants, folders, jobs, and shared app registration.
Keep the departing owner's local correction ledger if local export still uses it.

## Shared Minbox app or your own app

A shared Minbox Cloud application can avoid a separate Cloud project for each
owner. It shares the app registration. Each owner still completes consent for
their own account and stores their grant locally. It does not share accounts,
refresh tokens or Drive contents. The maintainer manages branding, publishing
status and enabled APIs.

This repository supplies no public client-configuration download. It does not
establish that Minbox has completed Google verification. Before choosing this
path, confirm app availability with the maintainer. Confirm its current audience
and verification status. Agree on a trusted private delivery method. Keep client
credentials and user grants out of public Git. Even a verified application needs
normal Google consent and owner device/account actions.

A maintainer can supply the matching Desktop client JSON privately. Otherwise,
**computer, owner:** create or select a Google Cloud project. Configure Google
Auth Platform audience and branding. Enable the three APIs. Create and download
a Desktop OAuth client. The agent can guide the console actions. The owner must
sign in and approve project/account changes. Store the client JSON outside Git
with mode 0600. Give the agent its path, not its contents.

## Current implementation constraints

Use only `https://www.googleapis.com/auth/drive.file`. The local helper opens a
loopback consent and Picker flow. It verifies the actual refreshed scope and
account. A working token does not prove the Google Cloud publishing status.
An External application in Testing can issue seven-day refresh grants for these
permissions. Verify production eligibility and status before treating the grant
as durable unattended access. Application configuration and user grants are
separate.

The helper uses Google's native folder picker. The Google-owned access page
shows the permission type. Minbox and the picker identify the selected folder.
**Owner:** create and name a private folder first. Files manually added under it
do not inherit app authorization. Minbox separately checks its selected root and
managed parents. Follow ONBOARDING.md or MAC_SETUP.md for connection.
Use DRIVE_MIGRATION.md for an existing broad grant.

After publication passes, test the separate phone AI connection through
[PHONE_ACCESS](PHONE_ACCESS.md). Google consent alone does not prove phone access.
Do not make private files public to fix retrieval.

Official references:

- [Desktop OAuth setup](https://developers.google.com/identity/protocols/oauth2/native-app).
- [Google Drive scopes](https://developers.google.com/workspace/drive/api/guides/api-specific-auth).
- [Native desktop Google Picker](https://developers.google.com/workspace/drive/picker/guides/desktop-mobile-picker).
- [Google Cloud APIs library](https://console.cloud.google.com/apis/library).
