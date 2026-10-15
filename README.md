# Minbox: ask your AI phone app about your text messages

Use your own agent CLI on an always-on computer to build a filtered text message archive.
Then ask your preferred AI phone app questions about that archive.

Minbox helps you and your agent reach that result. It provides working code, setup guides, options, and lessons from real installations.
Your agent does the technical work. You choose what to collect, what to exclude, and which AI service to use.

## What you need first

1. **An always-on computer.** Keep it powered, connected to the internet, and available for scheduled work.
2. **An installed agent CLI with access to a strong reasoning model.** It must read files, run commands, and install software with your approval.
3. **Your phone and access to your messaging account.** You complete pairing and permission prompts yourself.
4. **An AI app on your phone.** Its account must support the connection you choose for the archive.
5. **Private storage and a privacy choice.** Decide which messages may reach a cloud AI before setup begins.

An *agent CLI* is a coding assistant that you run in a terminal on your computer.
A chat subscription does not install the CLI for you.
Check whether your plan or API account supports the chosen CLI.
Check usable model access and any usage costs before setup.
Strong reasoning is useful for setup and repairs. Routine collection and rule-based filtering do not require an AI model.

Check your device combination with your agent:

| Your devices | Included collection path | What still needs checking |
| --- | --- | --- |
| Android with Google Messages and a Linux computer | Pair a read-only Google Messages collector | Live operation has worked. Your installation still needs its own tests. |
| iPhone and a Mac with Messages synchronization | Read Messages on your Mac | Automated tests pass. Live iPhone/Mac operation still needs verification. |
| Other combinations | Adaptation or another collector | The supplied code does not implement Android collection on Mac or Windows. |

Phone pairing applies to the Android path. The iPhone path uses Messages synchronization and Mac permissions.
Sleep, disconnection, expired pairing, or limited history can interrupt collection.
An always-on computer does not guarantee complete message history.

## Start with your agent

On the always-on computer, open your installed agent CLI.
Give it this prompt:

> Use https://github.com/hanster1/minbox-public as a reference to set up my filtered text message archive.
> The goal is to ask my preferred AI phone app useful questions about my messages.
> Read README.md, AGENTS.md, and the relevant setup guides.
> Check my phone, computer, model access, existing installation, and AI app.
> Explain the privacy and connection choices in simple language.
> Help me choose what to collect and filter before exposing message content.
> Do the authorized technical work and preserve existing data.
> Tell me when I must act on the computer or phone.
> Use the simplest supported path and reuse completed checks.
> Check collection, filtering, and one useful answer from my phone.
> Keep extra diagnostic tests for failures or new integrations.

You do not need to run every command in this repository yourself.
Your agent can select a supported recipe or adapt it to your needs.
An adaptation may need new code and tests. These guides do not make every device or AI account compatible.

## The setup path

### 1. Choose your privacy level and connection

Decide which originals your setup agent may inspect.
A cloud-backed agent can send tool results to its model provider, even when its CLI runs locally.

Choose which messages the answering AI may receive.
For stricter privacy, consider local-model filtering before releasing a separate text folder.
That option needs an added model integration; it is not included in the exporter.
Read [privacy and filtering choices](REFERENCE_GUIDE.md#who-sees-the-originals).

Then choose a connection with your agent.

**Our recommended first route is a connected-computer app, when the account supports it.**
Start with these options:

| App | Recommendation and current evidence |
| --- | --- |
| Grok Bot | First option to try from our Linux/Android trials. Changed-file and real entry-file reads passed. Full archive answers remain unverified. |
| ChatGPT dot | Another first option. Changed-file reads from Android passed. Real archive answers remain unverified. |
| Claude Cowork | Conditional option to investigate. The local-desktop Dispatch route is closed to new users; existing users can test it. No Minbox trial has passed. |

These are recommendations to test, not guarantees of support or speed.
Direct reads can avoid Drive publication and connector-refresh delays.
Collection, filtering, and the AI's own response time still matter.
This retrieval route needs no separate Drive connection.
This does not make the AI model local or limit its access to one folder.
See [current availability and tests](PHONE_ACCESS.md#recommended-options-to-try-first).

Other routes remain useful:

| Connection | Main advantage | Main tradeoff |
| --- | --- | --- |
| AI desktop app connected to your computer | Can read current local files from a phone conversation | Computer access can include more than the filtered folder. |
| Private cloud archive and the AI app's connector | Convenient when your account already supports it | Cloud storage and AI access need separate permissions. |
| A restricted search connector | Can expose only selected search and read functions | Requires more setup, authentication, and compatibility tests. |
| Manual file upload | Simple for occasional questions | Files are snapshots. Updates need another upload. |

See [phone access options](PHONE_ACCESS.md) before committing to a route.
Google Drive is one option. It is not the purpose of Minbox or a requirement for every design.
The included Drive path has the most complete setup recipe.
The local exporter currently needs an existing archive and correction ledger.
A new installation without Drive needs agent adaptation; no complete automatic recipe is supplied for it.

### 2. Connect your messages

Your agent installs the collector and checks its status for your devices.
You complete sign-in, pairing, and device permissions.

Use [Android/Linux setup](ONBOARDING.md) or [iPhone/Mac setup](MAC_ONBOARDING_AGENT.md).
If you chose Drive, also use [Google setup](GOOGLE_SETUP.md).

**Essential check 1, agent:** Confirm that a captured message reached the archive.
Check its date and source ID through the local tools.
Report missing history or unsupported content. No separate incoming/outgoing test sequence is needed on an established path.

### 3. Build and check the filtered archive

Your agent keeps originals separate from the output used for answers.
The supplied rules exclude authentication codes, recognizable password-reset links, and clear promotional spam.
Explicit corrections and optional phone spam exclusions add control.
No filter guarantees that all private data is removed.

Agree on the filter policy. Let the agent check it within the agreed privacy boundary.
Use [filtering choices](REFERENCE_GUIDE.md#filtering-and-useful-views), [archive behavior](OWNER_ARCHIVE.md), and the optional [local text export](LOCAL_EXPORT.md).

**Essential check 2, agent:** Confirm that the agreed filters are applied before sharing output.
Reuse local filter checks and review a small output sample where permitted.
Include image text and transcripts when used. You do not need to inspect every message.

### 4. Connect your AI phone app

Your agent helps configure the route selected in step 1.
You complete that AI service's sign-in and access consent.

Connect the approved filtered output through the selected route.
An AI project does not automatically read a local folder.

**Essential check 3, owner:** Ask one useful question from your phone.
Choose a familiar topic, preferably involving a recent message.
Check that the answer is right and includes its source.
Use the intended project or conversation. A separate desktop chat test is unnecessary.

### 5. Check updates and ongoing operation

Your agent schedules collection, filtering, and any output updates.
It also sets up health checks suited to your computer.

Your agent checks the schedule and available completed-run status in the background.
Agree on expected update delays and any desktop approval requirements.
Do not repeat successful file-read checks or run restart drills during normal setup.

**Finish when:** Messages arrive, the agreed filters are applied, and your phone gives a useful answer with a source.
Your agent should leave updates scheduled and explain any unresolved issue.
Extra refresh, restart, or disconnection tests belong in [troubleshooting](PHONE_ACCESS.md#troubleshooting-and-new-integrations).
Use them only for a new integration, an unresolved requirement, or a specific failure.
The routes tried so far have partial evidence; recommendations do not make every installation a proven path.

## Optional checks after basic setup

Choose only the options that matter to you. These do not add steps to every installation.
Your agent can reuse setup results and automate routine checks.

| Optional goal | A useful check |
| --- | --- |
| Recover after restart or power loss | Start with one planned restart. Confirm that pairing, scheduled jobs, and the connected AI app recover as expected. |
| Repair routine failures and request help | Use bounded automatic retries. Confirm that persistent failures needing owner action can send a private email. |
| Use more message content | Check one example of each content type you care about. Image storage alone does not prove that the phone AI can read the image. |
| Recover lost data | Keep an independent backup and check restoration if recovery matters to you. |

For restart recovery, include any disk unlock or user login the computer requires.
A computer that restarts successfully may still need its desktop app opened.
Use real outage observations when available; a planned restart does not prove every power-loss case.

For health alerts, your agent checks collection, filtered-output age, and Drive publication when used.
The current monitor may need added checks for local export or the AI connection.
If an issue needs you, open your agent CLI and ask it to diagnose and repair the installation.
See [recovery and alert options](HEALTH_ALERTS.md#optional-reliability-checks-and-agent-assisted-repair).

For content choices, start with [the optional coverage menu](REFERENCE_GUIDE.md#optional-content-coverage).
Optional content can include images, Loom transcripts, voice notes, documents, videos, and linked pages.
Choose only what you use. Loom capture is needed only for users who want answers about Loom videos.
The reference guide distinguishes existing implementations from features that need added support.

## Where to go next

| You need | Read |
| --- | --- |
| Choices, privacy, health, and efficient AI use | [Reference guide](REFERENCE_GUIDE.md) |
| AI app routes and phone tests | [Phone access](PHONE_ACCESS.md) |
| A separate local text folder | [Local export](LOCAL_EXPORT.md) |
| A restricted search service | [Read-only search prototype](READ_ONLY_SEARCH.md) |
| Repair an existing installation | [Android recovery](ANDROID_RECOVERY.md) or [Mac recovery](MAC_RECOVERY.md) |
| Detailed archive and filter behavior | [Archive reference](OWNER_ARCHIVE.md) and [phone spam policy](PHONE_SPAM.md) |
| Health checks and alerts | [Health reference](HEALTH_ALERTS.md) |
| Optional Loom transcripts | [Loom capture](LOOM_CAPTURE.md) |
| Develop or maintain Minbox | [Contribution checks](CONTRIBUTING.md), [maintenance map](MAINTENANCE.md), and [collector source](GMKIT_MEDIA.md) |

## Terms used in these guides

- **Original archive:** Private collected messages and history kept on your computer.
- **Filtered archive:** The selected output you permit an AI service to read.
- **Connector:** A connection that lets an AI app search or read a source.
- **Publication:** Updating readable output, such as private Google Docs.
- **Freshness:** How recently the source or output was updated and read.
- **Source ID:** A stable reference that helps you find the original message.

Keep messages, credentials, and private installation notes outside this public repository.
Never make the archive public to fix a connection problem.
See the [license](LICENSE) and [third-party notices](THIRD_PARTY_NOTICES.md) for software terms.
