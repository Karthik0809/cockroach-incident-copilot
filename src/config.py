"""Central configuration, read from the environment."""

import os

from dotenv import load_dotenv

load_dotenv()

# CockroachDB Cloud connection string (postgresql://...&sslmode=verify-full)
DATABASE_URL = os.environ.get("DATABASE_URL", "")

# AWS / Bedrock
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
EMBED_MODEL_ID = os.environ.get("EMBED_MODEL_ID", "amazon.titan-embed-text-v2:0")
CHAT_MODEL_ID = os.environ.get("CHAT_MODEL_ID", "us.anthropic.claude-sonnet-5")

EMBED_DIMS = int(os.environ.get("EMBED_DIMS", "1024"))

# Retrieval tuning
RECALL_K = int(os.environ.get("RECALL_K", "4"))
# Cosine distance above this is treated as "not actually related".
#
# 0.70 is measured, not guessed. Against the eval set on Titan V2 embeddings,
# the correct incident ranks #1 in 8/8 cases, but the correct answers span
# 0.426-0.795 while the nearest wrong answer spans 0.543-0.871 and the control
# alerts (which should match nothing) sit at 0.710 and 0.821. 0.70 keeps 7/8
# correct answers and leaks no controls. 0.80 would recover the last case but
# starts admitting a control -- a false precedent at 3am is worse than a miss.
RECALL_MAX_DISTANCE = float(os.environ.get("RECALL_MAX_DISTANCE", "0.70"))

# Optional: S3 bucket for postmortem documents
S3_BUCKET = os.environ.get("S3_BUCKET", "")


def require_database_url() -> str:
    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL is not set. Copy .env.example to .env and paste your "
            "CockroachDB Cloud connection string."
        )
    return DATABASE_URL
