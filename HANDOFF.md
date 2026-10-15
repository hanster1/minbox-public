# Minbox checkpoint — October 14, 2026

## Active goal

Document useful client choices in this adaptable reference, and test direct
phone access to the filtered archive on an always-on Linux host through Grok
Bot, ordinary Grok/SuperGrok and ChatGPT. The owner clarified that existing
Google Drive retrieval already works; it is not the current acceptance target.
Keep exact accounts, host paths, receipts and credentials outside public Git.

## Implemented and verified

- `local_archive_export.py` builds a separate private filtered text folder from
  local source and committed correction policy, without Google/model calls.
  It reuses publisher helpers, retains exclusions/undo/phone-folder policy,
  verifies complete staged generations and exchanges real directories atomically.
  `LOCAL_EXPORT.md` explains Linux, SQLite coordination, freshness and cache limits.
- Live export matched the filtered publication counts; a separate three-minute
  user timer refreshed it successfully. Existing collection and Drive publication
  were not modified. The local root containing raw collection was not granted.
- Optional bounded reader/MCP prototype and synthetic tests are included locally.
  `PHONE_ACCESS.md` compares convenience, model-reviewed computer access,
  authenticated search, optional OS isolation and snapshot uploads.
- Combined suite: 527 tests, five optional skips, no failures. Independent reviews
  found no material blocker for the scoped trials. Release inventory/link and
  whitespace checks passed before the latest checkpoint edits.
- Owner completed native ChatGPT/Grok Bot/TigerVNC installation. Omarchy blocked
  the official installer's direct upgrade; its supported update and package
  workflow succeeded after supplying the usual SSH-shell OMARCHY_PATH. No reboot.
  SSH/NAS and owner collector remained active.
- Private virtual display/native apps run as transient user services with
  loopback remote view over SSH. Owner signed in to Grok Bot; the host registered
  and its first synthetic local read matched after owner Allow once.
- Owner explicitly chose convenience mode: Always allow on the archive host,
  with Auto Review on and host-scoped read allowances/ask-first rules for other
  actions. The setting and both rules were verified. This grants all Bots broader
  execution as that host user; it is not enforced folder isolation.

## Next acceptance

The synthetic Grok file is Version 2. Owner was asked to initiate a fresh local
read from Android Grok Bot/Archy; compare its code against the private receipt
without approving at the desktop. Then test the actual filtered entry file.
ChatGPT is authenticated; dot onboarding reached local-computer selection.
Owner computer-access consent, fresh file read and Android use remain pending.
Ordinary Grok direct local access needs a compatible reachable MCP endpoint;
its passing Drive web/Android checks are separate evidence. Native reboot
persistence and changed real-source/cache behavior remain unverified.

Earlier cloud-shell loopback/LAN probes timed out; cause unresolved. No public
tunnel, permission bypass, private archive publication or GitHub push occurred.
New source/checkpoints after the previously pushed reference remain local.

## Google verification context

The canonical reference/site update was published earlier. Search Console HTML
tag ownership succeeded October 14. Keep the deployed public tag. Branding retry
is deferred until October 15 after 3:20 PM US/Central: Branding → View issues →
“I have fixed the issues” → Proceed. No verification approval or established
Minbox Drive-policy violation exists; no policy inquiry was sent. Keep this
separate from local-access work.
