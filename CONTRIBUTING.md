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

SOURCE_MANIFEST.json tracks the synchronized application files. Public guide files
are maintained here. A source-sync operation must preserve public edits and report
drift; never blindly overwrite them or import private Git history. Integrate shared
fixes deliberately and update the manifest with the verified source transfer.

Full owner_all publication is model-free. Optional work analysis currently uses
Codex's specific JSON transport, schema and flags; adding another runtime provider
requires a real adapter and tests. Any capable local agent may perform installation
regardless of that optional analyzer.

When distributing a patched collector binary, ship its upstream license/notices,
patch, provenance and complete corresponding modified source together, as detailed
in GMKIT_MEDIA.md and THIRD_PARTY_NOTICES.md. Do not relabel it MIT.
