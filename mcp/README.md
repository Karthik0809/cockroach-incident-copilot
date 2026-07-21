# CockroachDB Cloud Managed MCP Server

The MCP server is how a *human* (or a coding agent like Claude Code) inspects
and audits the same memory the Incident Copilot agent is writing at runtime.
Nothing here is a custom proxy — this is the managed endpoint from the Cloud
Console, in read-only mode.

## Setup

1. CockroachDB Cloud Console → your cluster → **Connect** → **MCP Server**.
2. Create a service account with **read-only** access to this database.
3. Copy the generated config into your client:

   - Claude Code: `.mcp.json` in the repo root, or `claude mcp add`
   - Cursor: `.cursor/mcp.json`
   - VS Code: `.vscode/mcp.json`

See [`config.example.json`](config.example.json) for the shape.

## What we actually used it for

| Task | Prompt to the agent |
|---|---|
| Schema review before shipping | "Inspect the incidents table and tell me if the vector index will be used by an ORDER BY `<=>` query" |
| Verifying recall quality | "Show the 10 most recent recall_events joined to incidents, with similarity" |
| Finding untrusted lessons | "Which lessons have been refuted more often than confirmed?" |
| Confirming the memory loop works | "Count incidents created by the agent (external_id IS NULL) vs seeded" |

That last one is the demo moment: you watch the agent write a new memory, then
query it back through MCP from a completely separate client.

## Safety

The service account is read-only, so an agent connected over MCP can inspect
memory but cannot corrupt it. Writes only happen through the application's own
typed tool surface in `src/agent.py`. All MCP access is audit-logged in the
Cloud Console.
