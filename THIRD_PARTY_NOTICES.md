# Licensing boundaries and dependencies

LICENSE applies to Minbox's original application code and documentation.
`scripts/gmkit-media.patch` and `scripts/gmkit-spam-paging.patch` modify an AGPL-licensed
collector; those patches and the resulting collector remain AGPL-3.0-or-later and are excluded from the MIT grant.
The upstream license is included at licenses/AGPL-3.0.txt.

The collector uses [gmkit](https://github.com/johnlindquist/gmkit), pinned to
`c714f8ea1602d9c61876a87a44f6984ba3aeb4c4`, and its upstream Go dependencies,
including mautrix/gmessages. The 2026-10-13 modification adds bounded full image
capture, phone spam-folder metadata reconciliation and an existing-pairing
refresh candidate tool. The 2026-10-15 spam-paging patch escalates the
Spam & blocked folder request size while the folder response is capped. The builder preserves
upstream LICENSE/NOTICE and adds the dated modification notice. Its output includes
complete modified corresponding source, patch and provenance next to the binaries.
Retain all these artifacts when distributing binaries, and provide corresponding
source to recipients/users as required by the upstream license, including its
network-use provision where applicable. Do not distribute only the executable.
See GMKIT_MEDIA.md for the reproducible build procedure.

Python packages are installed separately into a private virtual environment;
vendored packages/binaries are not included in this repository. Retain their
licenses/notices when redistributing an installed environment:

| Dependency | License | Primary package information |
| --- | --- | --- |
| google-auth | Apache-2.0 | https://pypi.org/project/google-auth/ |
| google-auth-oauthlib | Apache-2.0 | https://pypi.org/project/google-auth-oauthlib/ |
| requests | Apache-2.0 | https://pypi.org/project/requests/ |
| pytypedstream 0.1.0, optional Mac decoder | LGPL-3.0-or-later | https://pypi.org/project/pytypedstream/ |
| requests-oauthlib, transitive | ISC | https://pypi.org/project/requests-oauthlib/ |
| oauthlib, transitive | BSD-3-Clause | https://pypi.org/project/oauthlib/ |

Other transitive packages and locally installed tools retain their own licenses.
Optional Tesseract OCR is invoked as a separate local executable, not bundled.
This list describes direct/selected transitive dependencies, not a replacement
for reviewing the actual resolved dependency set in a binary distribution.
