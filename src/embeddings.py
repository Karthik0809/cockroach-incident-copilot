"""Amazon Bedrock embeddings (Titan Text Embeddings V2)."""

import json
from functools import lru_cache

import boto3

from . import config


@lru_cache(maxsize=1)
def _client():
    return boto3.client("bedrock-runtime", region_name=config.AWS_REGION)


def embed(text: str) -> list[float]:
    """Return a single embedding vector for `text`."""
    body = json.dumps(
        {
            "inputText": text,
            "dimensions": config.EMBED_DIMS,
            "normalize": True,
        }
    )
    resp = _client().invoke_model(modelId=config.EMBED_MODEL_ID, body=body)
    payload = json.loads(resp["body"].read())
    return payload["embedding"]


def embed_many(texts: list[str]) -> list[list[float]]:
    """Titan has no batch endpoint, so this is a loop -- fine for seed volumes."""
    return [embed(t) for t in texts]


def to_pgvector(vec: list[float]) -> str:
    """CockroachDB accepts a vector literal as a bracketed string."""
    return "[" + ",".join(f"{v:.7f}" for v in vec) + "]"
