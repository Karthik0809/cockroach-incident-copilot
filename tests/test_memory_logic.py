"""Tests that need neither a database nor AWS credentials.

These cover the parts that are easy to get quietly wrong: what text we embed,
how vectors are serialized for CockroachDB, and how recalled memories are
rendered into the prompt.
"""

import datetime as dt

from src import memory
from src.embeddings import to_pgvector


def test_incident_text_includes_root_cause_when_known():
    """A resolved incident must be findable by cause, not only by symptom."""
    text = memory._incident_text(
        title="Checkout 504s",
        service="checkout-api",
        symptoms="latency climbing, CPU flat",
        root_cause="connection pool exhaustion",
    )
    assert "connection pool exhaustion" in text
    assert "checkout-api" in text
    assert "latency climbing" in text


def test_incident_text_omits_root_cause_when_unknown():
    text = memory._incident_text(
        title="Mystery timeouts",
        service="orders-api",
        symptoms="intermittent 504s",
        root_cause=None,
    )
    assert "root cause" not in text


def test_to_pgvector_is_a_bracketed_literal():
    assert to_pgvector([1.0, -0.5, 0.25]).startswith("[")
    assert to_pgvector([1.0, -0.5, 0.25]).endswith("]")
    assert to_pgvector([1.0, -0.5, 0.25]).count(",") == 2


def test_to_pgvector_preserves_dimension_count():
    vec = [0.001 * i for i in range(1024)]
    assert len(to_pgvector(vec).strip("[]").split(",")) == 1024


def _recollection(distance: float) -> memory.Recollection:
    return memory.Recollection(
        incident_id="00000000-0000-0000-0000-000000000001",
        title="Checkout API 504s during evening peak",
        service="checkout-api",
        severity="SEV1",
        symptoms="p99 climbed to 30s, CPU flat",
        root_cause="connection pool exhaustion",
        resolution="rolled back the retry, raised pool max",
        created_at=dt.datetime(2024, 11, 8, tzinfo=dt.UTC),
        distance=distance,
    )


def test_similarity_is_the_inverse_of_distance():
    assert _recollection(0.2).similarity == 0.8


def test_prompt_block_carries_what_the_agent_needs_to_cite():
    block = _recollection(0.12).as_prompt_block()
    assert "2024-11-08" in block  # so the agent can cite a date
    assert "checkout-api" in block
    assert "connection pool exhaustion" in block
    assert "0.88" in block  # similarity, so the agent can judge the match


def test_prompt_block_is_explicit_about_missing_root_cause():
    unresolved = _recollection(0.3)
    unresolved.root_cause = None
    unresolved.resolution = None
    block = unresolved.as_prompt_block()
    assert "never determined" in block
    assert "none recorded" in block
