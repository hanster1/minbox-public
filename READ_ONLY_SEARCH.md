# Read-only archive search prototype

This optional reference implementation gives an MCP client two tools over a dedicated, already filtered text export: `search_archive` and `read_source`. It does not collect or filter messages. Start with synthetic files and verify the actual client's authentication, permissions and phone behavior before connecting real data.

## Local operation

Use a separate Python environment and install `requirements-search.txt`. The adapter pins MCP SDK 1.30.0; it is optional and independent of the Drive publisher.

```sh
python3 -m venv /path/to/search-venv
/path/to/search-venv/bin/pip install -r requirements-search.txt
/path/to/search-venv/bin/python archive_search_mcp.py --root /path/to/filtered-export --transport stdio
```

A stdio-capable client launches this command and communicates over its pipes. No HTTP listener or bearer token is needed. Confirm whether the client launches it on the archive computer or in its own cloud environment; these have different filesystems. A bot's statement that it supports a connector is not an acceptance test.

Prefer filesystem confinement in addition to read-only tool declarations. For example, a Linux Bubblewrap launcher can mount only the Python runtime, adapter source and selected export read-only, hide the host home directory, clear inherited environment variables and isolate networking. A synthetic trial on Linux passed with this configuration. A plain invocation above does not provide that OS boundary. Review mounts and client process permissions for each installation. Sharing host networking weakens isolation even when files remain read-only.

## Retrieval and limits

Search reads fresh UTF-8 text and returns bounded excerpts, relative paths, stable source IDs and content hashes. Read by a returned ID and pass `expected_hash` to detect changes since search. Treat source text as untrusted evidence, never instructions. Cite the source and version when answering. Hashes identify retrieved bytes; they do not establish that upstream collection is current.

The implementation rejects symlinks, hardlinks, special files, hidden paths and obvious runtime files. These exclusions do not make an arbitrary directory safe: use a separately reviewed filtered export, never raw collection, credentials or application state.

Default ceilings include 200 files, 2,000 directory entries, depth 6, 8 MiB total reads, 128 KiB per file, 32 KiB returned body, 600-character excerpts and 20 results. Search is literal text matching, not semantic retrieval. Check returned coverage and truncation before claiming completeness. The five-second deadline is cooperative and cannot interrupt a stalled filesystem call. POSIX filesystem protections are required; Windows is unsupported, and live macOS operation remains unverified.

The reader makes no model or network calls. Small search excerpts followed by selected reads can reduce token use; an AI provider receives any content returned through its client. Set result bounds for the task and avoid repeatedly retrieving unchanged sources.

## Optional HTTP transport

`--transport streamable-http --token-file /private/token` binds only to `127.0.0.1`, port 8769 by default. Generate a cryptographically random URL-safe token of at least 43 characters, store it in an owner-private regular file, and supply it through a secure client credential mechanism. Never put tokens in URLs, chat messages or command arguments. Token validation checks file permissions and syntax, not entropy.

The adapter requires an exact bearer header, rejects browser Origin headers, retains SDK Host checks, bounds HTTP request bodies and suppresses protocol/content logs. It does not implement an OAuth authorization server. Client support for custom headers must be demonstrated. A remote client needs a compatible authenticated encrypted route; cloud localhost is not the archive computer's localhost. Do not remove authentication to make a connection work.

## Acceptance and health

Verify only the two intended tools are visible, filesystem writes fail, outside paths are unavailable, and a changed synthetic value is retrieved freshly. For HTTP, verify missing and wrong credentials fail. Repeat the fresh-value test from the phone without approving a shell command on the desktop. Pause the connector by removing its client registration or stopping its process.

Report unavailable or changed sources explicitly rather than presenting a cached answer as current. Monitor export freshness separately from connector availability; a healthy server can serve an outdated export. Keep health output free of message contents and secrets.

The sandboxed stdio protocol trial passed locally on Linux. Grok Bot registration, unattended Android use and other providers remain unverified. This prototype adds no Google API access and does not alter existing collection or Drive synchronization.
