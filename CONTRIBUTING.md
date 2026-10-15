# Improve the path from messages to phone answers

Every contribution should help the user or their agent reach the [Minbox goal](README.md).
Keep setup practical, privacy choices clear, and technical limits honest.
Do not assume Google Drive is the only route.

## Write clear guidance

Use familiar words and consistent names for the same thing.
Start each guide with its role in the setup path.
Distinguish owner actions from agent tasks.
Put detailed commands in the relevant reference, not in every introduction.

Aim for roughly 80% alignment with ASD-STE100 writing principles.
This is a practical style target, not a certified compliance score.
Use the [official ASD-STE100 reference](https://www.asd-ste100.org/assets/files/ASD-STE100_ISSUE9.pdf) when checking the rules.

- Aim for at most 20 words in procedural sentences and 25 in descriptions.
- Give one instruction per sentence.
- Start instructions with a direct action.
- Prefer active voice and specific subjects.
- Define technical terms before relying on them.
- Keep necessary code names, commands, and interface labels exact.
- State conditions before the action that depends on them.
- Preserve useful technical detail and safety constraints when shortening prose.

Do not claim a measured compliance percentage from a sentence-length check alone.
The full standard also covers vocabulary, word meanings, and other writing rules.

## Keep client setup short

Use a few meaningful checkpoints on established paths: collection, filtering, and a useful phone answer.
Do not turn exploratory experiments into default owner tasks.
Keep changed-file, repeated-read, restart, and outage tests in focused troubleshooting.
Let the agent reuse passing results and check routine status with tools.
A new connector or security boundary still needs appropriate integration checks.

## Review code and data boundaries

Preserve owner identity, existing data, corrections, deliberate pauses, and private account bindings.
Use synthetic examples for regression tests.
Do not commit live messages, credentials, media, support dumps, or private notes.
A documentation change does not establish live device or AI phone compatibility.
Record those checks separately with results that contain no message content.

This repository is the authoritative source.
Do not copy an older private implementation or import its Git history.
The optional analyzer uses Codex's JSON transport, schema, and flags.
Other runtime providers need a real adapter and tests.
Any capable CLI can assist with installation.

## Run relevant checks

For code changes, run the relevant regression tests.
For a full source check, run:

```bash
python3 -m unittest discover -s tests -q
python3 scripts/check_public_release.py
```

For documentation changes, check links, facts, reading order, and whitespace.
Use the release checker and `git diff --check`.
Do not rerun the full code suite solely for prose edits.
Review changed commands against the implementation.

`SOURCE_MANIFEST.json` records reviewed application and test files with their hashes.
Public guides have a separate allowlist in the release checker.
After reviewing source changes, refresh existing hashes with:

```bash
python3 scripts/check_public_release.py --refresh-manifest
python3 scripts/check_public_release.py
```

The refresh refuses missing, unexpected, or suspicious files and broken guide links.
It does not add new files to the inventory.
Add reviewed new modules or tests explicitly before refreshing.
Run the relevant checks before committing.

## Publish only reviewed material

Review staged content and reachable history for private data before publication.
Inspect dependency licenses.
Run release checks from a fresh clone before distributing a release.
CI checks synthetic source behavior; it does not prove phone, OAuth, macOS, or provider operation.

A patched collector distribution must include its upstream license, notices, patch, provenance, and complete corresponding modified source.
See [GMKIT_MEDIA](GMKIT_MEDIA.md) and [third-party notices](THIRD_PARTY_NOTICES.md).
Do not relabel the collector as MIT.
