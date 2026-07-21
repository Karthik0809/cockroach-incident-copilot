# Video script — 2:50

The rule for this video: **show the database changing**. Judges have watched a
hundred chat demos. Almost none of them show memory being written and then read
back from a different client.

Record at 1080p+. Bump your terminal font size — it will be watched on a laptop.

---

### 0:00–0:20 · The problem

> "Most agent-memory demos store a chat transcript in a table. That's a log, not
> a memory — nothing about the agent changes because of it.
>
> This is an on-call agent that is *useless* without its memory. Its whole value
> is knowing what this team saw the last time something looked like this."

*On screen:* the README title, then the four-memory-types table.

### 0:20–0:40 · The memory model

> "Four kinds of memory, all in one CockroachDB cluster. Episodic — what
> happened. Semantic — what we concluded, with a confidence score. Working —
> what the agent is doing right now. And meta — which memories fired, and
> whether they actually helped."

*On screen:* scroll `schema/001_schema.sql`, pausing on `VECTOR(1024)` and
`CREATE VECTOR INDEX`.

### 0:40–1:00 · Seeded memory

> "I've seeded eight real historical incidents. Each one is embedded through
> Bedrock Titan and stored with its vector — in the same transaction as the row."

*On screen:* run `python -m scripts.seed`, let the incidents scroll past.

### 1:00–1:40 · The recall moment — **the most important 40 seconds**

> "Now an alert about `orders-api`. This service has *zero* history. Nothing
> about it is in memory."

*On screen:* paste the alert in the UI, hit Run.

> "It found an incident from `checkout-api` — a completely different service.
> Not because of matching words, but because the signature matches: latency
> climbing while CPU stays flat, right after a retry change. It names connection
> pool exhaustion, and it cites the date."

*Zoom in on the citation.* Let it sit on screen. Don't rush this.

### 1:40–2:05 · The write-back, proven from a second client

> "And it just wrote what it learned back into memory. Here's the part that
> matters — I'll query it from Claude Code over the CockroachDB MCP server. A
> completely separate client, read-only."

*On screen:* switch to Claude Code, ask:
> "Show me incidents created in the last 5 minutes, with whether they have an
> embedding."

*The new row is there, with its vector.* This is the shot that proves it's real.

### 2:05–2:25 · The loop closing

> "Every retrieval is logged. I mark this one helpful — that raises the lesson's
> confidence, and it ranks higher next time. Mark one unhelpful and it decays.
> Bad memories sink on their own."

*On screen:* click 👍 in the Replay tab, then show the confidence value changing.

### 2:25–2:40 · Measured, not asserted

> "Retrieval quality is the whole product, so it gets a number. Ten alerts, each
> worded differently from the incident it should match. Two are controls with no
> correct answer — because an agent that confidently matches *everything* is
> worse than one that admits it doesn't know."

*On screen:* `python -m scripts.eval`, land on the final metrics block.

### 2:40–2:50 · Close

> "CockroachDB for all four memory types with distributed vector indexing, the
> managed MCP server for auditing, Bedrock for reasoning and embeddings, Lambda
> and Fargate on AWS. Repo's public, MIT licensed."

*On screen:* architecture diagram, then the repo URL held for 3 seconds.

---

## Checklist before uploading

- [ ] Under 3:00
- [ ] **Public** (not private) on YouTube or Vimeo — unlisted is fine
- [ ] No credentials, connection strings, or account IDs visible anywhere
- [ ] Terminal font large enough to read on a laptop
- [ ] Audio levels checked — bad audio reads as low effort
- [ ] The MCP query at 2:05 is visible and legible; that's your proof shot
