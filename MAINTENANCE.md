# Where Minbox changes belong

This repository is the primary Minbox project. Start here for product work.
Each active source or procedure has one authoritative home:

| What needs changing | Where to change it |
| --- | --- |
| Capture, images, filtering, publication, consent, recovery policy | Application code in this repository |
| Client onboarding and repair instructions | This repository's ONBOARDING, MAC_SETUP and recovery guides |
| Public homepage, privacy policy and terms | `information-site/` in this repository |
| Hosted-server tools, service administration and website deployment procedure | The operator's private infrastructure notebook; the maintainer uses the separate `alfred` project |
| Account/folder bindings, credentials, installed state and owner-specific operating notes | Private runtime/local storage outside Git |
| Old experiments and initial migration evidence | Retained private historical repository; reference only |

For the maintainer's hosted installation, the private notebook's entry points are
`docs/minbox-hosting.md`, `docs/minbox-information-site.md` and
`scripts/minbox/pair-owner.sh`. Independent clients use their own computer and
this repository's portable guides; that notebook is not an installation dependency.

Edit and test application source here, then perform a reviewed update of the
installed application. The installed directory's legacy name is not a different
product or a source checkout. Do not rename runtime directories, credentials,
owner namespaces or Drive IDs merely to match the repository name. Never edit an
installed copy as the new source master or refresh this project from older code.

The website source also lives here. A source edit does not publish the site;
publication is a separate authorized operation. Preserve the existing Google
OAuth branding URLs and hosting target during source moves. CLI login, local
hosting linkage and owner Google grants are separate and stay outside public Git.

Private context cannot be inferred from cloning this repository. Keep exact
account/configuration details and rollback receipts in private local notes. Do
not paste them into public issues or merge private Git history. The historical
repository remains retained until its remaining branches and operational evidence
are accounted for; it is not another place to maintain the active application.
