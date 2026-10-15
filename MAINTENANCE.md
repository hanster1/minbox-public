# Where to make changes

Make changes that support the [message-to-phone-answer path](README.md#the-setup-path).
Keep one authoritative source for each part.

| Change | Source |
| --- | --- |
| Beginner entry, prerequisites, and setup journey | README.md |
| Design choices, privacy, and efficient AI use | REFERENCE_GUIDE.md |
| Agent responsibilities and project purpose | AGENTS.md and WORKFLOW.md |
| Device setup and repair | ONBOARDING.md, Mac guides, and recovery guides |
| Collection, filtering, output, and health behavior | Application code in this repository |
| AI phone routes and acceptance evidence | PHONE_ACCESS.md |
| Local text output and search prototype | LOCAL_EXPORT.md and READ_ONLY_SEARCH.md |
| Public homepage, privacy, and terms | information-site/ |
| Hosting accounts and deployment operations | Private operator infrastructure notebook |
| Credentials, account bindings, and installation receipts | Private runtime storage outside Git |
| Historical experiments | Retained private history, for reference only |

The maintainer's hosted installation keeps its operational notes in a separate private project.
Clients do not need that project or the maintainer's accounts.

Edit and review application source here before updating an installed runtime.
The installed directory's legacy name does not make it another development source.
Do not rename runtime paths, credentials, owner namespaces, or Drive IDs to match a new project name.
Do not import private history into this repository.

Edit the website's authored HTML and CSS here.
Source edits do not deploy the site.
Preserve public OAuth branding URLs and the ownership verification tag.
Keep hosting credentials and local deployment linkage private.

Use [CONTRIBUTING](CONTRIBUTING.md) for writing, source, and release checks.
Record current development work in HANDOFF.md.
Keep machine inventories, exact account details, and rollback receipts outside public Git.
