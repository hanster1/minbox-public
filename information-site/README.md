# Public information site

This folder is the canonical authored source for the public Minbox information,
privacy and terms pages. Edit the HTML and CSS directly; there is no JavaScript
or build step. This site contains no archive, account connection or upload flow.

The existing public URLs and OAuth application branding remain unchanged:

- [Homepage](https://minbox-text-archive.vercel.app/)
- [Privacy](https://minbox-text-archive.vercel.app/privacy.html)
- [Terms](https://minbox-text-archive.vercel.app/terms.html)

`vercel.json` serves `dist/`. The `.vercelignore` upload allowlist includes only
`vercel.json` and the four authored files in `dist/`; new assets must be reviewed
and explicitly allowed. Keep credentials, `.env` files, `.vercel` project linkage,
archives, account identifiers and private hosting runbooks outside this folder
and public Git. `.gitignore` excludes local environment and Vercel linkage files.

Before publishing, check the HTML navigation and stylesheet links, privacy claims
against current source, and the repository's public release checks. Source edits
and this relocation do not deploy or change the live site. See the repository's
[maintenance guidance](../MAINTENANCE.md) for source maintenance; hosting account
and deployment details belong in a private operator runbook.
