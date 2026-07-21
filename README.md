# 🪳 Incident Copilot

**An on-call agent whose memory lives in CockroachDB — and gets better every time it's used.**

Submission for the CockroachDB × AWS Hackathon: *Build with Agentic Memory*.

---

## The idea

Most "agent with memory" demos store a chat transcript in a table and call it
memory. That is a log, not a memory — nothing about the agent's behavior changes
because of it.

Incident Copilot is built the other way around. It is an on-call agent that
handles production alerts, and **it is useless without its memory**. Its entire
value is knowing what *this specific team* saw the last time something looked
like this:

> "This matches INC-1041 from 2024-11-08 — checkout-api, same signature: latency
> climbing while CPU stays flat. That was connection pool exhaustion from a retry
> that leaked a connection on the timeout path. You shipped a retry wrapper to
> orders-api nine days ago. Check pool utilization first."

Then it writes what it learned back, so the next engineer gets that for free.

## Four kinds of memory, one database

| Memory | Table | What it holds |
|---|---|---|
| **Episodic** | `incidents` | What happened, verbatim, + a `VECTOR(1024)` embedding |
| **Semantic** | `lessons` | Generalizable conclusions, with a confidence score |
| **Working** | `sessions`, `session_steps` | What the agent is doing *right now*, durably |
| **Meta** | `recall_events` | Which memories fired, and whether they helped |

The last one is what makes it a loop instead of a lookup. Every retrieval is
recorded; human feedback raises or lowers a lesson's `confidence`; and
`recall_lessons` ranks by similarity **and** trust. Bad memories decay. Good ones
get stickier.

## Why CockroachDB specifically

- **Vectors and rows commit in one transaction.** A resolution and its embedding
  are written together. With a bolted-on vector store there is always a window
  where the index disagrees with the system of record — and an agent retrieving
  during that window recalls something that isn't true.
- **Working memory outlives the process.** Serverless agents get killed
  mid-reasoning. Steps are appended durably, so a session is resumable and
  auditable rather than lost with the container.
- **No maintenance window.** Memory going read-only during an upgrade means the
  on-call agent goes blind exactly when incidents cluster.
- **Multi-region.** Same recall latency wherever the agent runs.

## Architecture

Full diagram and data flow: [`docs/architecture.md`](docs/architecture.md).

```
alert → Lambda → [ recall via vector index ] → Bedrock (Claude) → answer
                          ↑                                          ↓
                  CockroachDB memory  ←──── record_finding (new memory)
```

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
Code to design and audit the memory layer: reviewing whether `ORDER BY <=>`
actually hits the vector index, inspecting `recall_events` to check retrieval
quality, and — the demo moment — watching the agent write a new memory at
runtime and then querying it back from a completely separate client.
Setup and the exact prompts used: [`mcp/README.md`](mcp/README.md).

### 3. Agent Skills / ccloud CLI *(supporting)*
Schema and index design followed the open-source CockroachDB Agent Skills
guidance on query/schema design; `ccloud` was used to provision the cluster and
pull connection strings during setup.

## AWS services used

| Service | Role |
|---|---|
| **Amazon Bedrock** — Claude Sonnet 5 | The agent's reasoning loop, with native tool use over the memory tools ([`src/agent.py`](src/agent.py)) |
| **Amazon Bedrock** — Titan Embed Text V2 | 1024-dim embeddings for every incident and lesson ([`src/embeddings.py`](src/embeddings.py)) |
| **AWS Lambda** | Serverless agent execution behind a Function URL ([`src/lambda_handler.py`](src/lambda_handler.py)) |
| **Amazon ECS Fargate** | Hosts the Streamlit demo UI |
| **Amazon S3** | Postmortem document storage |
| **AWS SAM / CloudFormation** | Infrastructure as code ([`infra/template.yaml`](infra/template.yaml)) |

---

## Run it locally

**Prerequisites:** Python 3.12+, a CockroachDB Cloud cluster (the free tier is
enough), and AWS credentials with Bedrock model access enabled in your region.

```bash
git clone https://github.com/Karthik0809/cockroach-incident-copilot
cd cockroach-incident-copilot

python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env        # paste your DATABASE_URL and set AWS_REGION

python -m scripts.init_db   # create tables + vector indexes
python -m scripts.seed      # embed and store 8 historical incidents
python -m scripts.demo      # watch the agent recall, reason, and write back
```

Then the UI:

```bash
streamlit run app/streamlit_app.py
```

### Inspect memory from Claude Code (MCP)

[`.mcp.json`](.mcp.json) is checked in, so the CockroachDB Cloud managed MCP
server is available the moment you open this repo in Claude Code or Cursor:

```bash
export CC_API_KEY="<read-only service account key from the Cloud Console>"
claude   # then ask: "show the 10 most recent recall_events joined to incidents"
```

Read-only by design — see [`mcp/README.md`](mcp/README.md).

### Deploy the agent (Lambda)

```bash
sam build -t infra/template.yaml
sam deploy --guided --parameter-overrides DatabaseUrl="$DATABASE_URL"
```

### Deploy the demo UI (ECS Fargate)

```bash
aws secretsmanager create-secret \
  --name incident-copilot/database-url --secret-string "$DATABASE_URL"

AWS_ACCOUNT_ID=123456789012 AWS_REGION=us-east-1 ./infra/deploy-ui.sh
```

Builds the [`Dockerfile`](Dockerfile), pushes to ECR, registers
[`infra/ecs-task-definition.json`](infra/ecs-task-definition.json), and waits for
the service to stabilize. `DATABASE_URL` arrives via Secrets Manager — it is
never baked into the image.

### Tests

```bash
pytest        # 21 tests, no database or AWS credentials required
ruff check .
```

CI ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) runs lint, format
check, tests, `sam validate --lint`, and a Docker build on every push.

The stack outputs a Function URL:

```bash
curl -X POST "$FUNCTION_URL/alert" \
  -H 'content-type: application/json' \
  -d '{"alert":"orders-api p99 200ms -> 25s, CPU flat, db CPU normal"}'
```

---

## The demo worth watching

1. `scripts/seed.py` loads 8 real-shaped historical incidents.
2. Send an alert about **orders-api** — a service with *zero* history.
3. The agent recalls **INC-1041** from `checkout-api` — a different service, but
   the same failure signature — and names connection pool exhaustion.
4. It writes the new incident and a new lesson back to memory.
5. Query it from Claude Code over MCP. It's there, committed, with its vector.
6. Send a *related* alert. The agent now cites the incident it just handled.

Step 6 is the whole point. The agent got better between two runs, and the thing
that changed was the database.

## Layout

```
src/memory.py                    the memory layer -- all four memory types
src/agent.py                     Bedrock tool-use loop: recall -> reason -> write back
src/embeddings.py                Titan embeddings
src/lambda_handler.py            AWS Lambda entry point
schema/001_schema.sql            tables + distributed vector indexes
scripts/                         init_db, seed, demo
app/streamlit_app.py             demo UI
tests/                           21 tests, no DB or AWS creds needed
Dockerfile                       demo UI image (non-root, healthchecked)
infra/template.yaml              SAM template for the Lambda
infra/ecs-task-definition.json   Fargate task def for the UI
infra/deploy-ui.sh               build -> ECR -> ECS rollout
.mcp.json                        CockroachDB managed MCP server, read-only
mcp/                             MCP setup + the prompts we actually used
docs/architecture.md             diagram and data flow
```

## License

MIT — see [LICENSE](LICENSE).
