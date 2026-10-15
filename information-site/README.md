# Public information pages

These pages introduce the [Minbox goal](../README.md): useful phone AI answers about a filtered text archive.
They also explain privacy and terms.
The site does not collect messages, connect accounts, or accept uploads.

Edit the HTML and CSS in `dist/` directly.
These are authored source files. There is no JavaScript or build step.
Use the same clear terms and short sentences as the main guides.

Keep the existing public URLs:

- [Homepage](https://minbox-text-archive.vercel.app/)
- [Privacy](https://minbox-text-archive.vercel.app/privacy.html)
- [Terms](https://minbox-text-archive.vercel.app/terms.html)

`vercel.json` serves `dist/`.
The `.vercelignore` allowlist includes only that config and the four authored files in `dist/`.
Review and explicitly allow any new assets.
The static site needs no environment file.
Keep credentials, private accounts, archive content, and hosting notes outside public source.
Local `.vercel/` linkage stays ignored.

Before publication, check navigation, stylesheet links, and privacy statements against the code.
Run the repository's [release checks](../CONTRIBUTING.md).
Preserve the homepage's Google Search Console verification tag.
Source edits do not deploy the site or change OAuth branding settings.
Use the private operator runbook for hosting operations.
See [MAINTENANCE](../MAINTENANCE.md) for source ownership.
