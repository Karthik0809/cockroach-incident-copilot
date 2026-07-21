"""The memory layer. Everything the agent knows lives here, in CockroachDB.

Four kinds of memory, one database, one transaction boundary:

  episodic   -- incidents table       : what happened, verbatim
  semantic   -- lessons table         : what we concluded, with confidence
  working    -- sessions/steps tables : what the agent is doing right now
  meta       -- recall_events table   : which memories fired, and did they help

Because the embeddings sit in the same cluster as the operational rows, a
resolution and its vector commit together. There is no window where the
semantic index disagrees with the system of record.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from typing import Any, Iterator

import psycopg
from psycopg.rows import dict_row

from . import config
from .embeddings import embed, to_pgvector


# ---------------------------------------------------------------- connections


@contextlib.contextmanager
def connect() -> Iterator[psycopg.Connection]:
    """One short-lived connection. CockroachDB is fine with this from Lambda,
    and it keeps us honest about transaction scope."""
    conn = psycopg.connect(config.require_database_url(), row_factory=dict_row)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# -------------------------------------------------------------------- records


@dataclass
class Recollection:
    """A past incident the agent surfaced for the situation at hand."""

    incident_id: str
    title: str
    service: str
    severity: str
    symptoms: str
    root_cause: str | None
    resolution: str | None
    created_at: Any
    distance: float

    @property
    def similarity(self) -> float:
        return 1.0 - self.distance

    def as_prompt_block(self) -> str:
        return (
            f"[{self.created_at:%Y-%m-%d}] {self.title} ({self.service}, {self.severity}) "
            f"-- similarity {self.similarity:.2f}\n"
            f"  symptoms:   {self.symptoms}\n"
            f"  root cause: {self.root_cause or 'never determined'}\n"
            f"  resolution: {self.resolution or 'none recorded'}"
        )


@dataclass
class Lesson:
    lesson_id: str
    statement: str
    confidence: float
    distance: float


# ------------------------------------------------------------------- schema io


def init_schema(sql_path: str) -> None:
    with open(sql_path, encoding="utf-8") as fh:
        ddl = fh.read()
    with connect() as conn:
        conn.execute(ddl)


# --------------------------------------------------------------- write memory


def remember_incident(
    *,
    title: str,
    service: str,
    symptoms: str,
    severity: str = "SEV3",
    root_cause: str | None = None,
    resolution: str | None = None,
    external_id: str | None = None,
) -> str:
    """Write an incident and its embedding in a single transaction."""
    vec = to_pgvector(embed(_incident_text(title, service, symptoms, root_cause)))
    with connect() as conn:
        row = conn.execute(
            """
            INSERT INTO incidents
                (external_id, title, service, severity, symptoms,
                 root_cause, resolution, resolved_at, embedding)
            VALUES (%s, %s, %s, %s, %s, %s, %s,
                    CASE WHEN %s IS NULL THEN NULL ELSE now() END, %s)
            ON CONFLICT (external_id) DO UPDATE SET
                root_cause = excluded.root_cause,
                resolution = excluded.resolution,
                embedding  = excluded.embedding
            RETURNING id
            """,
            (
                external_id,
                title,
                service,
                severity,
                symptoms,
                root_cause,
                resolution,
                resolution,
                vec,
            ),
        ).fetchone()
    return str(row["id"])


def remember_lesson(incident_id: str, statement: str, confidence: float = 0.6) -> str:
    vec = to_pgvector(embed(statement))
    with connect() as conn:
        row = conn.execute(
            """
            INSERT INTO lessons (incident_id, statement, confidence, embedding)
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            (incident_id, statement, confidence, vec),
        ).fetchone()
    return str(row["id"])


# ---------------------------------------------------------------- read memory


def recall_incidents(
    query: str, k: int | None = None, service: str | None = None
) -> list[Recollection]:
    """Semantic recall over episodic memory, via the distributed vector index."""
    k = k or config.RECALL_K
    vec = to_pgvector(embed(query))

    sql = """
        SELECT id, title, service, severity, symptoms, root_cause,
               resolution, created_at,
               embedding <=> %s AS distance
        FROM incidents
        WHERE embedding IS NOT NULL
    """
    params: list[Any] = [vec]
    if service:
        sql += " AND service = %s"
        params.append(service)
    sql += " ORDER BY embedding <=> %s LIMIT %s"
    params.extend([vec, k])

    with connect() as conn:
        rows = conn.execute(sql, params).fetchall()

    return [
        Recollection(
            incident_id=str(r["id"]),
            title=r["title"],
            service=r["service"],
            severity=r["severity"],
            symptoms=r["symptoms"],
            root_cause=r["root_cause"],
            resolution=r["resolution"],
            created_at=r["created_at"],
            distance=float(r["distance"]),
        )
        for r in rows
        if float(r["distance"]) <= config.RECALL_MAX_DISTANCE
    ]


def recall_lessons(query: str, k: int = 3) -> list[Lesson]:
    """Semantic recall over distilled lessons, ranked by similarity AND trust.

    A lesson the agent has been burned by shouldn't outrank a lesson that has
    held up five times, even if the wording matches better -- hence the
    confidence term in the ORDER BY.
    """
    vec = to_pgvector(embed(query))
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT id, statement, confidence, embedding <=> %s AS distance
            FROM lessons
            WHERE embedding IS NOT NULL
            ORDER BY (embedding <=> %s) - (confidence * 0.15)
            LIMIT %s
            """,
            (vec, vec, k),
        ).fetchall()
    return [
        Lesson(
            lesson_id=str(r["id"]),
            statement=r["statement"],
            confidence=float(r["confidence"]),
            distance=float(r["distance"]),
        )
        for r in rows
    ]


# ------------------------------------------------------------- working memory


def open_session(alert_text: str, service: str | None = None) -> str:
    with connect() as conn:
        row = conn.execute(
            "INSERT INTO sessions (alert_text, service) VALUES (%s, %s) RETURNING id",
            (alert_text, service),
        ).fetchone()
    return str(row["id"])


def append_step(session_id: str, role: str, content: str) -> int:
    """Durable append to working memory. If the Lambda dies mid-run, the
    transcript is still on disk in three regions."""
    with connect() as conn:
        row = conn.execute(
            """
            INSERT INTO session_steps (session_id, step_no, role, content)
            VALUES (
                %s,
                (SELECT coalesce(max(step_no), 0) + 1
                   FROM session_steps WHERE session_id = %s),
                %s, %s
            )
            RETURNING step_no
            """,
            (session_id, session_id, role, content),
        ).fetchone()
        conn.execute(
            "UPDATE sessions SET updated_at = now() WHERE id = %s", (session_id,)
        )
    return int(row["step_no"])


def get_session(session_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        session = conn.execute(
            "SELECT * FROM sessions WHERE id = %s", (session_id,)
        ).fetchone()
        if not session:
            return None
        steps = conn.execute(
            "SELECT step_no, role, content, created_at FROM session_steps "
            "WHERE session_id = %s ORDER BY step_no",
            (session_id,),
        ).fetchall()
    return {**session, "steps": steps}


def close_session(session_id: str, status: str = "resolved") -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE sessions SET status = %s, updated_at = now() WHERE id = %s",
            (status, session_id),
        )


# ---------------------------------------------------------------- meta memory


def log_recall(
    session_id: str,
    similarity: float,
    incident_id: str | None = None,
    lesson_id: str | None = None,
) -> str:
    with connect() as conn:
        row = conn.execute(
            """
            INSERT INTO recall_events (session_id, incident_id, lesson_id, similarity)
            VALUES (%s, %s, %s, %s) RETURNING id
            """,
            (session_id, incident_id, lesson_id, similarity),
        ).fetchone()
    return str(row["id"])


def mark_recall_helpful(recall_event_id: str, helpful: bool) -> None:
    """Human feedback closes the loop: a confirmed lesson gains confidence,
    a refuted one loses it, and future retrievals reflect that."""
    with connect() as conn:
        conn.execute(
            "UPDATE recall_events SET was_helpful = %s WHERE id = %s",
            (helpful, recall_event_id),
        )
        if helpful:
            conn.execute(
                """
                UPDATE lessons SET
                    times_confirmed = times_confirmed + 1,
                    confidence = least(1.0, confidence + 0.1),
                    last_used_at = now()
                WHERE id = (SELECT lesson_id FROM recall_events WHERE id = %s)
                """,
                (recall_event_id,),
            )
        else:
            conn.execute(
                """
                UPDATE lessons SET
                    times_refuted = times_refuted + 1,
                    confidence = greatest(0.0, confidence - 0.15),
                    last_used_at = now()
                WHERE id = (SELECT lesson_id FROM recall_events WHERE id = %s)
                """,
                (recall_event_id,),
            )


def stats() -> dict[str, int]:
    with connect() as conn:
        return conn.execute(
            """
            SELECT
                (SELECT count(*) FROM incidents)      AS incidents,
                (SELECT count(*) FROM lessons)        AS lessons,
                (SELECT count(*) FROM sessions)       AS sessions,
                (SELECT count(*) FROM recall_events)  AS recalls
            """
        ).fetchone()


# --------------------------------------------------------------------- helpers


def _incident_text(
    title: str, service: str, symptoms: str, root_cause: str | None
) -> str:
    """What we actually embed. Root cause is included when known so that a
    resolved incident is findable by cause, not just by symptom."""
    parts = [f"service: {service}", f"title: {title}", f"symptoms: {symptoms}"]
    if root_cause:
        parts.append(f"root cause: {root_cause}")
    return "\n".join(parts)
