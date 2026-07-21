# 🪳 Incident Copilot

**An on-call agent whose memory lives in CockroachDB — and gets better every time it's used.**

[![CI](https://github.com/Karthik0809/cockroach-incident-copilot/actions/workflows/ci.yml/badge.svg)](https://github.com/Karthik0809/cockroach-incident-copilot/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)

Submission for the **CockroachDB × AWS Hackathon: Build with Agentic Memory**.

---

## The idea

Most "agent with memory" demos store a chat transcript in a table and call it
memory. That is a log, not a memory — nothing about the agent's behavior changes
because of it.

Incident Copilot is built the other way around. It is an on-call agent that
handles production alerts, and **it is useless without its memory**. Its entire
value is knowing what *this specific team* saw the last time something looked
like this:

> This matches **INC-1041** from 2024-11-08 — `checkout-api`, same signature:
> latency climbing while CPU stays flat. That was connection pool exhaustion
> from a retry that leaked a connection on the timeout path. You shipped a retry
> wrapper to `orders-api` nine days ago. **Check pool utilization first.**

Then it writes what it learned back, so the next engineer gets that for free.

## Four kinds of memory, one database

| Memory | Table | What it holds |
|---|---|---|
| **Episodic** | `incidents` | What happened, verbatim, + a `VECTOR(1024)` embedding |
| **Semantic** | `lessons` | Generalizable conclusions, with a confidence score |
| **Working** | `sessions`, `session_steps` | What the agent is doing *right now*, durably |
| **Meta** | `recall_events` | Which memories fired, and whether they helped |

The fourth is what makes this a **loop** instead of a lookup. Every retrieval is
recorded. Human thumbs-up/down adjusts a lesson's `confidence`, and recall ranks
by similarity **and** trust:

```sql
ORDER BY (embedding <=> $1) - (confidence * 0.15)
```

Bad memories decay. Good ones get stickier. A memory system without this just
accumulates.

## Why CockroachDB specifically

- **Vectors and rows commit in one transaction.** A resolution and its embedding
  are written together. With a bolted-on vector store there is always a window
  where the index disagrees with the system of record — and an agent retrieving
  during that window recalls something that isn't true. That is a correctness
  problem, not a performance one.
- **Working memory outlives the process.** Serverless agents get killed
  mid-reasoning. Steps are appended durably, so a session is resumable and
  auditable rather than lost with the container.
- **No maintenance window.** Memory going read-only during an upgrade means the
  on-call agent goes blind exactly when incidents cluster.
- **Multi-region.** Same recall latency wherever the agent runs.

## Architecture

```
                  ┌──────────── AWS ────────────┐
  alert ─────────▶│  Lambda                     │
                  │    │                        │
                  │    ├─▶ Bedrock: Titan  ─── embed
                  │    ├─▶ Bedrock: Claude ─── reason (tool use)
                  │    └─▶ S3            ─── postmortems
                  └────┬────────────────────────┘
                       │  recall (vector index)  ▲
                       ▼                         │ record_finding
              ┌──── CockroachDB Cloud ───────────┴──┐
              │  incidents · lessons                │
              │  sessions · session_steps           │
              │  recall_events ──▶ confidence feedback
              └─────────────────────────────────────┘
                       ▲
                       └── Claude Code / Cursor, read-only via MCP
```

Full diagram and data flow: **[`docs/architecture.md`](docs/architecture.md)**.

---

## CockroachDB tools used

### 1. Distributed Vector Indexing
Both `incidents` and `lessons` carry a `VECTOR(1024)` column (Titan Text
Embeddings V2) with a distributed cosine vector index:

```sql
CREATE VECTOR INDEX idx_incidents_embedding
    ON incidents (embedding vector_cosine_ops);
```

Recall runs as an ordinary `ORDER BY embedding <=> $1` — see
[`src/memory.py`](src/memory.py) (`recall_incidents`, `recall_lessons`). The
agent calls this on *every* alert before it reasons. No separate vector store,
no reindexing step, no consistency gap.

### 2. Cloud Managed MCP Server
Connected read-only at `https://cockroachlabs.cloud/mcp` and used from Claude
Code to design and audit the memory layer: verifying `ORDER BY <=>` actually
hits the vector index, inspecting `recall_events` while tuning thresholds, and —
the demo moment — watching the agent commit a memory at runtime and then
querying it back from a completely separate client.
Config is checked in at [`.mcp.json`](.mcp.json); the exact prompts used are in
[`mcp/README.md`](mcp/README.md).

### 3. ccloud CLI
Cluster provisioning and connection-string retrieval during setup — see
[`docs/SETUP.md`](docs/SETUP.md).

### 4. Agent Skills
Schema and index design followed the open-source CockroachDB Agent Skills
guidance on query/schema design.

## AWS services used

| Service | Role |
|---|---|
| **Amazon Bedrock** — Claude Sonnet 5 | The reasoning loop, with native tool use over the memory tools ([`src/agent.py`](src/agent.py)) |
| **Amazon Bedrock** — Titan Embed Text V2 | 1024-dim embeddings for every incident and lesson ([`src/embeddings.py`](src/embeddings.py)) |
| **AWS Lambda** | Serverless agent execution behind a Function URL ([`src/lambda_handler.py`](src/lambda_handler.py)) |
| **Amazon ECS Fargate** | Hosts the Streamlit demo UI ([`Dockerfile`](Dockerfile)) |
| **Amazon S3** | Postmortem document storage |
| **AWS Secrets Manager** | `DATABASE_URL` injection — never baked into an image |
| **AWS SAM / CloudFormation** | Infrastructure as code ([`infra/template.yaml`](infra/template.yaml)) |

---

## Quick start

Full walkthrough with failure modes: **[`docs/SETUP.md`](docs/SETUP.md)**.

**Prerequisites:** Python 3.12+, a CockroachDB Cloud cluster (free tier is
enough), and AWS credentials with Bedrock model access enabled **in your
region**.

```bash
git clone https://github.com/Karthik0809/cockroach-incident-copilot
cd cockroach-incident-copilot

python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements-ui.txt

cp .env.example .env        # paste your DATABASE_URL, set AWS_REGION

make init                   # create tables + vector indexes
make seed                   # embed and store 8 historical incidents
make eval                   # measure recall quality
make demo                   # watch the agent recall, reason, and write back
make ui                     # http://localhost:8501
```

Every target also works as a plain command — see the [`Makefile`](Makefile).

## Measuring recall quality

Retrieval *is* the product here, so it gets a number instead of a vibe.
[`scripts/eval.py`](scripts/eval.py) runs 10 alerts, each deliberately worded to
name a **different service** than the incident it should match — so lexical
overlap can't carry it.

```bash
make eval
```

```
  recall@1     …
  recall@k     …
  MRR          …
  abstention   …
```

Two of the ten are **control cases with no correct answer**. Those matter most:
a memory system that returns something confident for "the espresso machine is
making a grinding noise" is worse than one that says nothing, and precision-only
scoring would hide that. Tune `RECALL_MAX_DISTANCE` in `.env` and re-run.

## Deploying

### Agent (Lambda)

```bash
sam build -t infra/template.yaml
sam deploy --guided --parameter-overrides DatabaseUrl="$DATABASE_URL"

curl -X POST "$FUNCTION_URL/alert" -H 'content-type: application/json' \
  -d '{"alert":"orders-api p99 200ms -> 25s, CPU flat, db CPU normal"}'
```

| Route | Purpose |
|---|---|
| `POST /alert` | Run the agent on an alert |
| `GET /session?id=` | Replay a session's full reasoning trace |
| `GET /recalls?id=` | Which memories fired during that session |
| `POST /feedback` | Mark a recall helpful/unhelpful — reinforces or decays it |
| `GET /stats` | Memory counters |

### Demo UI (ECS Fargate)

```bash
aws secretsmanager create-secret \
  --name incident-copilot/database-url --secret-string "$DATABASE_URL"

AWS_ACCOUNT_ID=123456789012 AWS_REGION=us-east-1 ./infra/deploy-ui.sh
```

Builds the image, pushes to ECR, registers
[`infra/ecs-task-definition.json`](infra/ecs-task-definition.json), and waits
for the service to stabilize.

### Inspect memory from Claude Code (MCP)

```bash
export CC_API_KEY="<read-only service account key from the Cloud Console>"
claude   # then: "show the 10 most recent recall_events joined to incidents"
```

## Development

```bash
make test    # 38 tests -- no database or AWS credentials required
make lint    # ruff check + format check
```

CI ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) runs lint, format
check, tests, `sam validate --lint`, and a Docker build on every push.

**Dependencies are split on purpose.** `requirements.txt` is what SAM packages
into the Lambda; `requirements-ui.txt` adds Streamlit for the UI. Streamlit's
tree (pyarrow, pandas, numpy, altair, pydeck, PIL) is ~260MB unzipped — over
Lambda's 250MB limit on its own — so a UI dependency leaking into the core file
breaks the deploy. CI and `tests/test_packaging.py` both fail if it does.

---

## The demo worth watching

1. `make seed` loads 8 real-shaped historical incidents.
2. Send an alert about **orders-api** — a service with *zero* history.
3. The agent recalls **INC-1041** from `checkout-api` — a different service, but
   the same failure signature — and names connection pool exhaustion.
4. It writes the new incident and a new lesson back to memory.
5. Query it from Claude Code over MCP. It's there, committed, with its vector.
6. Send a *related* alert. The agent now cites the incident it just handled.

Step 6 is the whole point. The agent got better between two runs, and the thing
that changed was the database.

Shot-by-shot recording plan: [`docs/VIDEO_SCRIPT.md`](docs/VIDEO_SCRIPT.md).

## Layout

```
src/memory.py                    the memory layer -- all four memory types
src/agent.py                     Bedrock tool-use loop: recall -> reason -> write back
src/embeddings.py                Titan embeddings
src/lambda_handler.py            AWS Lambda entry point
src/config.py                    environment configuration
schema/001_schema.sql            tables + distributed vector indexes
scripts/init_db.py               apply the schema
scripts/seed.py                  embed and store historical incidents
scripts/demo.py                  one full agent run, end to end
scripts/eval.py                  recall quality benchmark
data/incidents.json              8 seed incidents with root causes and lessons
data/eval_alerts.json            10 eval alerts, 2 of them controls
tests/                           38 tests, no DB or AWS creds needed
app/streamlit_app.py             demo UI: run, search, replay, give feedback
requirements.txt                 core deps -- what SAM packages into the Lambda
requirements-ui.txt              UI deps, kept out of the Lambda (see below)
Dockerfile                       UI image (non-root, healthchecked)
infra/template.yaml              SAM template for the Lambda
infra/ecs-task-definition.json   Fargate task definition for the UI
infra/deploy-ui.sh               build -> ECR -> ECS rollout
.mcp.json                        CockroachDB managed MCP server, read-only
mcp/README.md                    MCP setup + the prompts actually used
docs/SETUP.md                    full setup walkthrough + troubleshooting
docs/architecture.md             diagram and data flow
docs/SUBMISSION.md               Devpost answers
docs/VIDEO_SCRIPT.md             2:50 recording plan
```

## License

MIT — see [LICENSE](LICENSE).
