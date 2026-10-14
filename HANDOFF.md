# Minbox session checkpoint

This public repository is the canonical application, onboarding/repair and
information-site source. MAINTENANCE.md maps hosted operations to their separate
home. Keep private history, runtime state and account bindings outside this Git
history. Minbox code is MIT; collector changes retain upstream AGPL obligations.

## Latest result

Portable publication guidance now lives in
[OWNER_ARCHIVE.md](OWNER_ARCHIVE.md#publication-performance), discovered through
AGENTS.md, README and both platform setup/recovery paths. It covers defaults and
bounds, cold/warm measurements, retry-aware comparisons, opt-in concurrent reads,
part/image budgets, preserved identities, rollback and completed-run acceptance.
Mac guidance distinguishes checkout updates from installed code and requires
reviewed config-digest rebinds with exact saved settings after active jobs finish.
Android recovery links the common procedure rather than duplicating it.

The code supports at most three unchanged-output revision reads, paced to one
logical launch per second; the default remains sequential. Proof/hash/age checks,
privacy checks, correction reads, guarded writes and full readback remain.
Warm changed outputs can reuse verified structure; uncertain writes are never
blindly replayed. Full publication is model-free; work analysis stays optional.
Phone spam exclusions retain originals and stable source/Doc identities.

## Verification and limits

Fresh-clone verification: 491 tests ran, five optional skips and no failures.
Release/link checks cover 122 files and 87 inventoried source/test files;
reachable-history private-marker review passed. Linux full publication
completed in 3m04s and an automatic repeat in 4m33s; imports caught up, prior jobs
and recovery settings were restored, and health was clear. These are observations,
not throughput guarantees or independent-client acceptance.

Cold/changed reads remain sequential and the owner lock remains. Historical image
backlog drainage, live Mac/iPhone operation, independent onboarding, natural
renewal, reboot/offline catch-up and independent backup need further acceptance.
Private bindings and rollback/timing receipts stay outside Git. No website or
new runtime deployment is part of this documentation checkpoint.

Next: observe scheduled/cold latency and perform independent client/device
acceptance when available.
