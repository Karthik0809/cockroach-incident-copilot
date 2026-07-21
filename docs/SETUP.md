# Setup, start to finish

Every step, in order, with the failure modes called out. Budget ~45 minutes
the first time.

---

## 1. CockroachDB Cloud

1. Sign up at [cockroachlabs.cloud](https://cockroachlabs.cloud) — the free
   tier is enough for this project.
2. Create a **Serverless / Basic** cluster on **AWS**, in the same region you
   plan to run Bedrock in (keeps recall latency honest in the demo).
3. **Connect → General connection string.** Copy it. It looks like:
   ```
   postgresql://user:password@host.aws-us-east-1.cockroachlabs.cloud:26257/defaultdb?sslmode=verify-full
   ```
4. Create the database:
   ```sql
   CREATE DATABASE incident_copilot;
   ```
   Then change `/defaultdb` to `/incident_copilot` in your connection string.

Optionally do all of this from the CLI instead:

```bash
brew install cockroachdb/tap/ccloud     # or: curl https://cockroachlabs.cloud/ccloud/install.sh | sh
ccloud auth login
ccloud cluster create serverless incident-copilot --cloud aws --region us-east-1
ccloud cluster list --json
ccloud cluster sql incident-copilot --connection-string
```

> **Vector index syntax.** `CREATE VECTOR INDEX` requires a recent CockroachDB
> version and `SET enable_vector_index = on` (already in the schema file). If
> `python -m scripts.init_db` errors on that statement, check your cluster
> version first — this is the single most likely thing to bite you, and it is a
> one-line fix, so run init_db on day one rather than the night before the
> deadline.

## 2. AWS

1. An AWS account with billing enabled.
2. **Bedrock → Model access** in your chosen region. Request access to:
   - `anthropic.claude-sonnet-5` (reasoning)
   - `amazon.titan-embed-text-v2:0` (embeddings)

   Approval is usually instant but is **per-region** — this is the second most
   common stumble. If you get `AccessDeniedException` on `InvokeModel`, you
   enabled the model in a different region than `AWS_REGION`.
3. Local credentials:
   ```bash
   aws configure          # or export AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY
   aws sts get-caller-identity     # confirm it works
   ```

## 3. Local run

```bash
git clone https://github.com/Karthik0809/cockroach-incident-copilot
cd cockroach-incident-copilot

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-ui.txt

cp .env.example .env               # paste DATABASE_URL, set AWS_REGION
```

Then:

```bash
python -m scripts.init_db    # tables + vector indexes
python -m scripts.seed       # embeds and stores 8 incidents (~16 Bedrock calls)
python -m scripts.eval       # recall quality numbers -- run this before the demo
python -m scripts.demo       # full agent run, end to end
streamlit run app/streamlit_app.py
```

If `eval` shows poor recall, tune `RECALL_MAX_DISTANCE` in `.env`. Lower means
more abstention and fewer false positives; higher means the opposite. Rerun
`eval` after each change — that is the whole point of having it.

## 4. MCP server

1. Cloud Console → your cluster → **Connect → MCP Server**.
2. Create a **read-only** service account and copy its key.
3. ```bash
   export CC_API_KEY="<key>"
   claude          # .mcp.json in this repo is picked up automatically
   ```
4. Verify:
   > "List the tables in incident_copilot and show me the 5 most recent
   > recall_events joined to the incidents they matched."

## 5. Deploy the agent (Lambda)

```bash
sam build -t infra/template.yaml
sam deploy --guided --parameter-overrides DatabaseUrl="$DATABASE_URL"
```

Take the `FunctionUrl` output and check it:

```bash
curl "$FUNCTION_URL/stats"
curl -X POST "$FUNCTION_URL/alert" -H 'content-type: application/json' \
  -d '{"alert":"orders-api p99 200ms -> 25s, CPU flat, db CPU normal"}'
```

## 6. Deploy the UI (ECS Fargate)

```bash
aws ecr create-repository --repository-name incident-copilot
aws secretsmanager create-secret \
  --name incident-copilot/database-url --secret-string "$DATABASE_URL"

# create an ECS cluster + service behind an ALB on port 8501, then:
AWS_ACCOUNT_ID=123456789012 AWS_REGION=us-east-1 ./infra/deploy-ui.sh
```

The ALB DNS name is your **public demo URL** for the submission.

> Faster alternative if you are short on time: push to GitHub and deploy
> `app/streamlit_app.py` on Streamlit Community Cloud, putting `DATABASE_URL`
> in its secrets UI. You still satisfy the AWS requirement through Bedrock,
> Lambda, and S3. The ECS path is the stronger story, but a working URL beats
> a half-finished one.

## Troubleshooting

| Symptom | Cause |
|---|---|
| `AccessDeniedException` on InvokeModel | Model not enabled in `AWS_REGION` |
| `relation "incidents" does not exist` | `scripts/init_db.py` never ran, or ran against a different database |
| `syntax error at or near "VECTOR"` | Cluster version predates vector index support |
| Recall returns nothing for everything | `RECALL_MAX_DISTANCE` too low, or `scripts/seed.py` never ran |
| Recall returns the same incident for everything | `RECALL_MAX_DISTANCE` too high |
| `SSL error` connecting | Connection string missing `?sslmode=verify-full` |
| Lambda times out | Cold start plus several Bedrock calls; timeout is already 120s in the template |
