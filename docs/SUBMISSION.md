# Devpost submission — draft answers

Paste-ready. **Fill the `TODO` placeholders with your real URLs and numbers
before submitting.** Do not submit numbers you have not actually measured.

---

## Project name

Incident Copilot — an on-call agent whose memory gets better every time it's used

## Elevator pitch (200 chars)

An on-call AI agent with four kinds of memory in CockroachDB. It recalls what
your team saw last time, acts on it, and writes back what it learned.

## Links

| Field | Value |
|---|---|
| Repository | https://github.com/Karthik0809/cockroach-incident-copilot |
| Demo app | `TODO` — ALB DNS or Streamlit URL |
| Video | `TODO` — public YouTube/Vimeo, under 3:00 |
| License | MIT, detected in the About section |

---

## Inspiration

Most "agent with memory" projects store a chat transcript and call it memory.
That's a log — nothing about the agent's behavior changes because of it.

We wanted an agent that is *useless* without its memory. On-call is the perfect
case: the value of a good incident responder isn't general reasoning, it's
having seen this failure signature before. That knowledge exists in a
company — scattered across postmortems, Slack threads, and one senior engineer's
head — and it evaporates when they're on vacation.

## What it does

You give it an alert. It recalls similar past incidents by meaning rather than
keyword, cites what actually fixed them, tells you plainly when memory has
nothing, and writes what it learned back so the next engineer inherits it.

The demo case: seed the system with eight historical incidents, then send an
alert about `orders-api` — a service with **zero** history. The agent surfaces
an incident from `checkout-api`, a completely different service, because the
*signature* matches: latency climbing while CPU stays flat, shortly after a
retry change. It names connection pool exhaustion. Then it commits the new
incident to memory, and the next related alert cites the memory it just made.

## How we built it — four kinds of memory, one database

| Memory | Table | Holds |
|---|---|---|
| Episodic | `incidents` | What happened, verbatim, + `VECTOR(1024)` |
| Semantic | `lessons` | Generalizable conclusions, with a confidence score |
| Working | `sessions`, `session_steps` | What the agent is doing right now, durably |
| Meta | `recall_events` | Which memories fired, and whether they helped |

The fourth is what makes it a loop rather than a lookup. Every retrieval is
recorded. Human thumbs-up/down adjusts a lesson's `confidence`, and
`recall_lessons` ranks by similarity **and** trust:

```sql
ORDER BY (embedding <=> $1) - (confidence * 0.15)
```

Bad memories decay. Good ones get stickier. A memory system without this just
accumulates.

---

## CockroachDB tools used

### Distributed Vector Indexing
`incidents` and `lessons` each carry a `VECTOR(1024)` column (Titan Text
Embeddings V2) with a distributed cosine index. Recall is an ordinary
`ORDER BY embedding <=> $1` (`src/memory.py`), called by the agent on every
alert before it reasons.

**Why it mattered:** the resolution and its embedding commit in the **same
transaction**. With a bolted-on vector store there is always a window where the
index disagrees with the system of record — and an agent that retrieves during
that window recalls something that isn't true. That's not a performance
problem, it's a correctness one, and it's the reason this project isn't
Postgres + a separate vector DB.

### Cloud Managed MCP Server
Connected read-only at `https://cockroachlabs.cloud/mcp` from Claude Code, and
used to:
- verify `ORDER BY <=>` actually hits the vector index rather than scanning
- inspect `recall_events` to check retrieval quality while tuning thresholds
- watch the agent commit a memory at runtime, then query it back from a
  completely separate client — the moment that proves the loop is real

Config in `.mcp.json`; the exact prompts used are in `mcp/README.md`.

### ccloud CLI
Cluster provisioning and connection-string retrieval during setup
(`docs/SETUP.md`). JSON output made it scriptable.

### Agent Skills
Schema and index design followed the open-source CockroachDB Agent Skills
guidance on query and schema design.

## AWS services used

| Service | Role |
|---|---|
| Amazon Bedrock — Claude Sonnet 5 | The reasoning loop, with native tool use over the memory tools (`src/agent.py`) |
| Amazon Bedrock — Titan Embed Text V2 | 1024-dim embeddings for every incident and lesson |
| AWS Lambda | Serverless agent execution behind a Function URL |
| Amazon ECS Fargate | Hosts the demo UI |
| Amazon S3 | Postmortem document storage |
| AWS Secrets Manager | `DATABASE_URL` injection — never baked into the image |
| AWS SAM / CloudFormation | Infrastructure as code |

---

## Challenges

**Knowing when *not* to recall.** Early on the agent produced a confident match
for anything, including nonsense. A false precedent at 3am is worse than no
precedent. We added a distance threshold, an explicit instruction to abstain,
and — critically — two control cases in the eval set with no correct answer, so
abstention is measured rather than assumed.

**Making memory a loop rather than a log.** Writing rows is easy. Making
retrieval *change* because of feedback required the `recall_events` table and
the confidence term in the ranking.

## Accomplishments

- Recall generalizes across services — the point of embeddings over keywords.
- A measured retrieval benchmark (`scripts/eval.py`), not a vibe.
- Working memory survives process death, because it was never in the process.

## What we learned

Putting vectors in the operational database isn't a convenience, it's a
correctness property. Agents retrieve constantly and act on what they retrieve;
an index that lags the system of record produces an agent that confidently
acts on stale truth.

## What's next

Auto-distilling lessons from S3 postmortems; a `pgvector`-side reranker;
memory decay so five-year-old infrastructure advice loses weight on its own.

---

## Feedback on the CockroachDB AI tools

*(Optional field — fill in honestly from your own experience. Genuine, specific
feedback is read by the judges. Things worth commenting on if you hit them: how
clear the vector index syntax and version requirements were, how smooth the MCP
config handoff from the Console was, and whether `ccloud` JSON output was
scriptable enough.)*

`TODO`
