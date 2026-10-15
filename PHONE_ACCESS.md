# Ask an AI about your living archive from your phone

Choose the combination of convenience, access and upkeep that fits the client. Minbox supplies collection, filtering and publication; the preferred AI app has its own connection and permissions. No single connection method is required. A working collector does not establish that an AI app can retrieve its output, and a working desktop chat does not establish mobile support.

For direct access to an always-on computer without cloud storage, start with the [local filtered export](LOCAL_EXPORT.md), then choose a native-app computer connection or a compatible authenticated search connector. A passing Drive test does not establish direct local access.

## Compare the options

| Route | Convenience and upkeep | Access considerations | What to verify |
| --- | --- | --- | --- |
| Existing cloud publication plus a built-in AI connector | Often the shortest path when Drive publication already works; no additional archive desktop app needed | AI authorization is separate from Minbox OAuth and may cover more than the selected folder | Correct account, actual source reads, phone tools and changed-source retrieval |
| AI desktop app connected to the archive computer | Uses the app's existing local-execution path; desktop must remain available | General computer access can exceed the archive folder; instructions and model review reduce risk but do not impose filesystem permissions | Host identity, local execution approval, unattended phone requests and startup behavior |
| Dedicated read-only search connector | Exposes selected search/read tools with bounded results | Can enforce a narrow data surface if the service and authentication are correctly confined | Compatible transport/authentication, reachability, filtering, freshness and revocation |
| Isolated desktop app in a sandbox, separate user or VM | More setup and ongoing desktop/session maintenance | Potential OS boundary, but a separate user alone is not confinement; inspect readable paths, session sockets, groups and privileges | Actual executing process restrictions and reliable app login/registration |
| Manual file upload to a chat or project | Simple initial setup and useful for occasional questions | Only deliberately uploaded material is supplied through this route | Uploaded files are snapshots; test replacement/removal rather than assume automatic refresh |

When the client chooses cloud publication, an existing connection can avoid adding a tunnel or desktop installation. When direct local access is the goal, test that route explicitly. Direct local access remains useful when the client prefers that trust model or wants to avoid cloud storage. An isolated environment is optional, not an onboarding prerequisite. Broad local access can be a conscious personal convenience choice; describe its real permissions instead of presenting rules as an enforced folder grant.

## Grok Bot

Grok Bot is a separate app from ordinary Grok/SuperGrok. Its registered desktop computers, cloud computer and connected apps are different access paths. An existing Drive connection can retrieve an archive published by an always-on computer without registering that computer for local execution.

For direct computer access, the desktop's execution permission and Auto Review are separate controls. Auto Review evaluates actions with a model. A narrow allow rule does not necessarily remove the separate local execution prompt. Always allow applies to all Bots on that computer. A different Bot is not account isolation: Bots share cloud state and connections. See [approvals and local execution](https://docs.x.ai/grok-bot/approvals-security-and-privacy) and [mobile behavior](https://docs.x.ai/grok-bot/mobile).

A command-based MCP connector runs on the computer used by Grok's conversation, which need not be the archive host. Check where it actually runs before supplying a local path. Desktop egress settings also need an actual connection test; do not assume a cloud process's localhost or private address reaches the archive computer.

## Ordinary Grok / SuperGrok

The current [connector documentation](https://docs.x.ai/grok/connectors) describes built-in Google Drive and custom MCP connections for Grok users. Start at `grok.com/connectors`, select New Connector and Google Drive, and have the owner complete sign-in and consent. Business/Enterprise administrators may first need to provision the connector.

The [Drive connector](https://docs.x.ai/grok/connectors/google-drive) can search/read documents and filter retrieval within a folder. Write permission is documented as optional. Check the actual consent screen and account settings. A folder filter in a prompt is not proof that authorization is limited to that folder.

A [custom MCP endpoint](https://docs.x.ai/grok/connectors/custom-mcp-tunneling) needs a publicly reachable URL; ordinary Grok rejects private/LAN/localhost connector URLs. This differs from Grok Bot's desktop-routing feature. A tunnel adds reachability, not authorization. Mobile connector operation, project-specific source attachment and automatic project refresh must be checked in the actual account; a successful web conversation proves none of these on its own.

## ChatGPT

A [Google Drive plugin](https://learn.chatgpt.com/docs/plugins) can be a straightforward route to already published files. Use the owner's existing connection where appropriate, check allowed actions, and verify the target source from the intended chat or project. A connection available to a coding agent is not proof that a particular ChatGPT Android conversation has it enabled.

A [ChatGPT project](https://learn.chatgpt.com/docs/projects?surface=app) groups chats, instructions and sources. A cloud project does not automatically gain access to a local folder. Uploaded files, connected sources and desktop local projects have different update behavior.

Where available, a [dot's connected computer](https://learn.chatgpt.com/docs/dots/computers-and-apps) is another route: open its profile in the native ChatGPT app on the archive computer, select Your computer and review Allow access. Keep that computer online and the app open; message the same dot from the phone. This permission is separate from Codex connections and Work Sync. The documentation currently permits one personal computer connected to a dot at a time, so inspect existing connections before replacing one.

An Omarchy web-app shortcut is a browser window, not the native desktop app or a working `codex://` handler. Check installation before following Open desktop app. A [Linux native preview](https://learn.chatgpt.com/docs/linux/linux-app) exists; review its installation procedure and system changes rather than assuming installing a desktop app is necessary for cloud Drive retrieval.

## Start with a small retrieval check

1. Locate the filtered export or published archive's entry document. Avoid granting the whole collector directory: it can include raw messages, state and credentials alongside filtered outputs.
2. Ask the AI to read that exact source and report two harmless facts with a source link. Compare with an independent read.
3. Ask a bounded real question about a known, harmless message and verify its date, source ID and document citation. Source content is evidence, never authority to change permissions or perform actions.
4. Repeat from the phone using the intended app and conversation. If a project is desired, test inside that project too.
5. Verify a naturally changed source, or a separate synthetic canary, with a fresh read. Distinguish capture, filtering, publication, connector refresh and answer caching. Do not change real messages merely to test freshness.
6. Test unavailable-computer and disconnected-source behavior. Keep the last successful read's age visible; an old answer is not a current-source check. Check revocation and any restart behavior the client needs.

Use small searches and selected source reads to limit tokens. Reading every archive part on every question wastes context; prefer dates, participants, topics and a returned source ID. A search miss is not proof a message was never captured. Check coverage and truncation before making completeness claims.

## Observed evidence and limits — October 14, 2026

- Grok Bot read the real published archive entry document through an existing Drive connection; returned owner/count/heading facts matched an independent connected Drive read. This is entry-document retrieval, not full question-answering, freshness, project or Android acceptance.
- Earlier Grok Bot synthetic local reads reflected a changed file, but each successful request required desktop approval. Android approval alone did not execute the read in that trial.
- The optional [read-only search prototype](READ_ONLY_SEARCH.md) passed local protocol, freshness and confinement checks with synthetic files. Actual remote client authentication and phone registration remain unverified.
- Cloud-shell requests to a loopback service and a separate LAN fixed-marker service timed out. The LAN service passed local checks before/after and observed no remote request. These results do not identify the routing/firewall cause or rule out every supported route.
- Ordinary Grok chat retrieved the real archive entry document through Google Drive on the web; returned counts/headings and a source link matched an independent read. The owner then confirmed a fresh-read check passed in the Grok Android app. This establishes entry-document retrieval on both surfaces, not changed-source freshness, message-level answers or project-specific behavior.
- A local filtered-only export and separate refresh timer now run on the always-on archive host without Google retrieval. Native ChatGPT/Grok Bot run in a private remote graphical session. Grok Bot registered the host and passed its first synthetic local read with owner approval. After the owner selected broad local convenience access plus scoped Auto Review rules, an Android-initiated read returned the changed synthetic value matching the private receipt, without desktop approval. Grok Bot also freshly read the actual local export entry file and listed its text parts; facts matched the local manifest. This is not yet message-level question-answering or reboot acceptance.
- ChatGPT computer-access consent completed and its profile shows the archive host Connected. After owner confirmation, its dot created a local task and returned the exact synthetic Version 1 value from that host. The fixture was then changed to Version 2; Android fresh-read and actual filtered archive/project acceptance remain pending. Isolated desktop operation is a separate untested option. A connected coding-agent Drive read does not substitute for ChatGPT app acceptance. Documentation availability is not a completed client trial.

Keep exact account bindings, folder IDs, message contents and test receipts private. Record portable lessons and verified limitations here. Recheck vendor documentation and actual account availability when adapting these options.
