"""Central configuration, read from the environment."""

import os

from dotenv import load_dotenv

load_dotenv()

# CockroachDB Cloud connection string (postgresql://...&sslmode=verify-full)
DATABASE_URL = os.environ.get("DATABASE_URL", "")

# AWS / Bedrock
#
# AWS_PROFILE names which entry in ~/.aws/credentials to use. Set it. Without
# it boto3 silently falls back to the [default] profile, which on a work laptop
# is usually an employer's account -- so a personal side project quietly bills
# the company and runs under a corporate identity. Explicit beats implicit here.
#
# Leave it unset only where there is no credentials file at all and an attached
# role is the intended identity: Lambda, ECS, EC2. AWS_ALLOW_DEFAULT_PROFILE=1
# opts out of the check for any other case.
AWS_PROFILE = os.environ.get("AWS_PROFILE", "")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
EMBED_MODEL_ID = os.environ.get("EMBED_MODEL_ID", "amazon.titan-embed-text-v2:0")
CHAT_MODEL_ID = os.environ.get("CHAT_MODEL_ID", "us.amazon.nova-pro-v1:0")

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


def _running_on_aws() -> bool:
    """True inside Lambda/ECS/App Runner, where an attached role is correct
    and no credentials file exists to be ambiguous about."""
    return any(
        os.environ.get(var)
        for var in (
            "AWS_LAMBDA_FUNCTION_NAME",
            "AWS_EXECUTION_ENV",
            "ECS_CONTAINER_METADATA_URI",
            "ECS_CONTAINER_METADATA_URI_V4",
        )
    )


def aws_session():
    """The one place a boto3 session is built.

    Refuses to fall through to the [default] profile on a developer machine.
    That fallback is invisible when it happens and only shows up later in
    someone else's billing console.
    """
    import boto3

    if AWS_PROFILE:
        return boto3.Session(profile_name=AWS_PROFILE, region_name=AWS_REGION)

    if _running_on_aws() or os.environ.get("AWS_ALLOW_DEFAULT_PROFILE") == "1":
        return boto3.Session(region_name=AWS_REGION)

    if os.environ.get("AWS_ACCESS_KEY_ID"):
        return boto3.Session(region_name=AWS_REGION)

    raise RuntimeError(
        "AWS_PROFILE is not set, so boto3 would fall back to the [default]\n"
        "profile in ~/.aws/credentials -- which may not be the account you\n"
        "intend to bill.\n\n"
        "  Set up a profile:   aws configure --profile personal\n"
        "  Then in .env:       AWS_PROFILE=personal\n\n"
        "Check which account a profile maps to with:\n"
        "  aws sts get-caller-identity --profile personal\n\n"
        "If the default profile really is correct, set AWS_ALLOW_DEFAULT_PROFILE=1."
    )


def require_database_url() -> str:
    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL is not set. Copy .env.example to .env and paste your "
            "CockroachDB Cloud connection string."
        )
    return DATABASE_URL
