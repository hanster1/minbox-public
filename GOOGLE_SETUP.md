# Google application prerequisite

The agent must confirm this before opening consent. Minbox needs a Google Cloud
application with a **Desktop app OAuth client** and the Drive, Docs and Google
Picker APIs enabled in the same project. Each user authorizes their own account;
never reuse another user's refresh token or collector session.

A maintainer may supply the matching Desktop client JSON privately. Otherwise,
**computer, owner:** create/select a Google Cloud project, configure Google Auth
Platform audience/branding, enable the three APIs, then create/download a Desktop
OAuth client. The agent can guide these console actions but the owner performs
sign-in and approves project/account changes. Store the client JSON outside Git
with mode 0600; provide its path, not its contents, to the agent.

Use only `https://www.googleapis.com/auth/drive.file`. The local helper opens a
loopback consent/picker flow and verifies the actual refreshed scope and account.
It does not infer Google Cloud publishing state from a working token. An External
application in Testing can issue seven-day refresh grants for these permissions;
verify production eligibility/status before calling it unattended setup. Existing
application configuration is independent of a user's grant.

The helper uses Google's native folder picker; the Google-owned access page shows
the permission type, while Minbox and the picker identify the selected folder.
The owner creates/names a private folder first. Arbitrary files added under that
folder do not inherit app authorization. Follow ONBOARDING.md or MAC_SETUP.md;
use DRIVE_MIGRATION.md for an existing broad grant.

Official references:

- [Desktop OAuth setup](https://developers.google.com/identity/protocols/oauth2/native-app).
- [Google Drive scopes](https://developers.google.com/workspace/drive/api/guides/api-specific-auth).
- [Native desktop Google Picker](https://developers.google.com/workspace/drive/picker/guides/desktop-mobile-picker).
- [Google Cloud APIs library](https://console.cloud.google.com/apis/library).
