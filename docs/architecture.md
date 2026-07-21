# Architecture

```mermaid
flowchart TB
    subgraph client["Entry points"]
        UI["Streamlit demo UI<br/>(ECS Fargate)"]
        PD["Alert webhook<br/>(PagerDuty / CloudWatch)"]
        CC["Claude Code / Cursor<br/>via MCP"]
    end

    subgraph aws["AWS"]
        L["AWS Lambda<br/>src.lambda_handler"]
        BR["Amazon Bedrock<br/>Claude Sonnet 5 — reasoning"]
        BE["Amazon Bedrock<br/>Titan Embed V2 — 1024d vectors"]
        S3["Amazon S3<br/>postmortem documents"]
    end

    subgraph crdb["CockroachDB Cloud (multi-region, AWS)"]
        EP["incidents<br/>episodic memory + VECTOR(1024)"]
        SE["lessons<br/>semantic memory + confidence"]
        WM["sessions / session_steps<br/>working memory"]
        RA["recall_events<br/>retrieval audit + feedback"]
        VI["distributed vector index<br/>cosine"]
    end

    UI --> L
    PD --> L
    L --> BR
    L --> BE
    L --> S3
    BE -->|embedding| EP
    BE -->|embedding| SE
    L -->|recall| VI
    VI --> EP
    VI --> SE
    L -->|append step| WM
    L -->|log recall| RA
    RA -->|confidence feedback| SE
    CC -.read-only.-> crdb
```

## The loop

1. An alert arrives at the Lambda.
2. A session row is opened — **working memory now exists on disk**, before any
   reasoning happens. If the Lambda is killed, the trace survives.
3. Claude (Bedrock) calls `recall_similar_incidents`. The alert is embedded via
   Titan, and the vector goes through CockroachDB's distributed vector index.
4. Claude calls `recall_lessons` — ranked by similarity *and* by how often each
   lesson has held up (`confidence`).
5. Claude answers, grounded in what actually fixed the problem last time.
6. Claude calls `record_finding` exactly once. The new incident row and its
   embedding are written **in a single transaction**.
7. Every retrieval is logged to `recall_events`. Human thumbs-up/down adjusts
   lesson confidence, so bad memories decay and good ones get stickier.

## Why this needs CockroachDB specifically

- **One transaction across vector and row.** A resolution and its embedding
  commit together. With a bolted-on vector store there is always a window where
  the index disagrees with the system of record — and an agent that retrieves
  during that window recalls something that is not true.
- **Working memory that outlives the process.** Serverless agents die mid-run.
  Steps are appended durably, so a session is resumable and auditable rather
  than lost with the container.
- **No maintenance window.** Memory that goes read-only during an upgrade means
  an on-call agent goes blind exactly when incidents cluster.
- **Multi-region.** The agent recalls with the same latency wherever it runs.
