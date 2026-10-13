# Development and release checks

Keep source changes generic and preserve runtime owner identity and private Drive
bindings. Add synthetic failure/regression fixtures for behavioral changes. Never
commit live messages, credentials, media, support dumps or private operator notes.

Run from the checkout:

```bash
python3 -m unittest discover -s tests -q
python3 scripts/check_public_release.py
```

Before publication, review staged content and all reachable history for private
data, inspect dependency licenses and run checks from a fresh clone. CI is a
synthetic source check; it does not prove phone, OAuth, macOS or provider behavior.
Record live acceptance separately with content-free results.

This repository is the authoritative development source. SOURCE_MANIFEST.json
records the reviewed application and synthetic-test inventory and file hashes;
public guides are separately allowlisted in the release checker. After reviewing
source edits, refresh the hashes with:

```bash
python3 scripts/check_public_release.py --refresh-manifest
python3 scripts/check_public_release.py
```

The refresh refuses missing, unexpected or suspicious files and broken guide
links; it does not add new files to the inventory automatically. A reviewed new
module/test must be added explicitly to the manifest before refreshing. Run the
relevant regression checks before committing. Do not copy from an older private
source tree or import its Git history. Account for retained legacy-only tools and
operational guidance privately before retiring that repository.

Full owner_all publication is model-free. Optional work analysis currently uses
Codex's specific JSON transport, schema and flags; adding another runtime provider
requires a real adapter and tests. Any capable local agent may perform installation
regardless of that optional analyzer.

When distributing a patched collector binary, ship its upstream license/notices,
patch, provenance and complete corresponding modified source together, as detailed
in GMKIT_MEDIA.md and THIRD_PARTY_NOTICES.md. Do not relabel it MIT.
