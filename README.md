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
> Verify a real answer and an updated source from my phone before calling the setup complete.

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

Then choose a connection with your agent:

| Connection | Main advantage | Main tradeoff |
| --- | --- | --- |
| Private cloud archive and the AI app's connector | Convenient when your account already supports it | Cloud storage and AI access need separate permissions. |
| AI desktop app connected to your computer | Can read current local files from a phone conversation | Computer access can include more than the filtered folder. |
| A restricted search connector | Can expose only selected search and read functions | Requires more setup, authentication, and compatibility tests. |
| Manual file upload | Simple for occasional questions | Files are snapshots. Updates need another upload. |

See [phone access options](PHONE_ACCESS.md) before committing to a route.
Google Drive is one option. It is not the purpose of Minbox or a requirement for every design.
The included Drive path has the most complete setup recipe.
The local exporter currently needs an existing archive and correction ledger.
A new installation without Drive needs agent adaptation; no complete automatic recipe is supplied for it.

### 2. Connect your messages

Your agent installs and tests the collector for your devices.
You complete sign-in, pairing, and device permissions.

Use [Android/Linux setup](ONBOARDING.md) or [iPhone/Mac setup](MAC_ONBOARDING_AGENT.md).
If you chose Drive, also use [Google setup](GOOGLE_SETUP.md).

**Check:** A harmless new message reaches the local archive with its date and source ID.
Your agent also reports missing history or unsupported content.

### 3. Build and check the filtered archive

Your agent keeps originals separate from the output used for answers.
The supplied rules exclude authentication codes, recognizable password-reset links, and clear promotional spam.
Explicit corrections and optional phone spam exclusions add control.
No filter guarantees that all private data is removed.

Review examples that should remain and examples that should be excluded.
Use [filtering choices](REFERENCE_GUIDE.md#filtering-and-useful-views), [archive behavior](OWNER_ARCHIVE.md), and the optional [local text export](LOCAL_EXPORT.md).

**Check:** The output retains useful messages and excludes the agreed sensitive examples.
Check text extracted from images and transcripts too.

### 4. Connect your AI phone app

Your agent helps configure the route selected in step 1.
You complete that AI service's sign-in and access consent.

Start with a harmless test file before granting access to the real archive.
An AI project does not automatically read a local folder.
A desktop success does not prove that the phone app can use the same connection.

**Check:** From your phone, ask about a known message.
Verify the answer, date, and source reference against the archive.
Use the intended project or conversation if that matters to you.

### 5. Check updates and ongoing operation

Your agent schedules collection, filtering, and any output updates.
It also sets up health checks suited to your computer.

Test a harmless changed source from your phone.
Check that the AI reads the new version rather than repeating an old answer.
Agree on expected update delays and any desktop approval requirements.

**Finish when:** You can get a correct, source-backed answer from your phone and retrieve an updated source.
Scheduled operation must also work. Record untested restart, recovery, or coverage checks.
A running collector alone does not complete this goal.

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
| Optional video transcripts | [Loom capture](LOOM_CAPTURE.md) |
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
