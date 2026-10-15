# Minbox purpose and project boundaries

Help a user get intelligent answers about their filtered text message archive from their preferred AI phone app.
Their own agent CLI performs setup on their always-on computer.
The repository supplies reference code, practical choices, and lessons that reduce setup problems.

## The user journey

Start with [README](README.md).
State the prerequisites first: an always-on computer and an installed CLI with access to a strong reasoning model.
Then guide the agent and owner through these stages:

1. Choose what data the setup agent and answering AI may see.
2. Connect the user's messaging device or synchronized message source.
3. Collect messages and preserve private originals.
4. Build and check a separate filtered archive.
5. Connect the chosen AI phone app through a suitable route.
6. Ask one useful question from the phone while the agent checks schedules and health status.

The agent handles technical work. The owner handles device and account approvals.
Explain alternatives and tradeoffs in simple language.
Do not require one storage provider or connection architecture for every client.
Adaptation can require new code and live tests.

## Working implementation and limits

Android/Linux uses a pinned read-only Google Messages collector.
iPhone/Mac uses Messages synchronized to the owner's Mac.
The Mac path is fixture-tested; live operation still needs verification.
Other platforms need implementation and tests.

The included Drive path has the most complete setup recipe.
Local text export and a read-only search prototype provide more choices.
The local exporter needs an existing archive and correction ledger.
It is not a complete new-installation recipe without Drive.
See [PHONE_ACCESS](PHONE_ACCESS.md) for verified routes and remaining gaps.

Full collection and rule-based output require no runtime model calls.
Optional work analysis and Loom capture are extensions.
Local-model filtering is an adaptation option, not a shipped backend.
Preserve privacy, consent, source integrity, and explicit pauses with every route.
For Drive, retain exact `drive.file` scope and account, root, and parent checks.

## Completion and maintenance

Collection, filtering, storage, and phone retrieval are separate checks.
Normal setup has three checkpoints: collection works, agreed filtering applies, and the intended phone app gives a useful source-backed answer.
The agent checks schedules and available completed-run status without adding owner tasks.
Reuse passing checks. Keep changed-file, restart, and outage experiments in troubleshooting.
Use extra diagnostics only for new integrations, changed conditions, or a specific failure.
Record unsupported or untested behavior honestly.
Use ordinary programs for scheduled work and limited recovery.
Explain alert coverage and any gaps in monitoring.

Use short sentences, clear terms, and direct steps throughout the repository.
Keep the desired phone result visible in every supporting guide.
Use [CONTRIBUTING](CONTRIBUTING.md) for writing and release checks.

## Authoritative development source

Make new Minbox changes here.
Retained private development history is a reference, not a competing implementation.
Do not refresh this project from an older private copy or import its history.
Update source hashes in `SOURCE_MANIFEST.json` after reviewed code changes.
Keep messages, media, credentials, databases, and private operator notes out of Git.

## Material ownership

[MAINTENANCE](MAINTENANCE.md) maps each change to its source.
Client guides, application code, and public information pages belong here.
Hosting operations belong in the operator's private infrastructure notebook.
Private account bindings and runtime receipts stay outside public source.
Editing or moving source does not change a running installation or deploy the website.
