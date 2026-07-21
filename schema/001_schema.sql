-- Incident Copilot :: agentic memory schema
-- CockroachDB (PostgreSQL compatible). Vector columns + distributed vector index.
--
-- Design note: episodic memory (what happened), semantic memory (what we learned),
-- and working memory (what the agent is doing right now) all live in ONE database.
-- No separate vector store, so a resolution and its embedding commit in the same
-- transaction and can never drift apart.

SET enable_vector_index = on;

------------------------------------------------------------------------------
-- 1. EPISODIC MEMORY :: raw incidents the agent has lived through
------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS incidents (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    external_id     STRING UNIQUE,
    title           STRING NOT NULL,
    service         STRING NOT NULL,
    severity        STRING NOT NULL DEFAULT 'SEV3',
    symptoms        STRING NOT NULL,
    root_cause      STRING,
    resolution      STRING,
    resolved_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Titan Text Embeddings V2 @ 1024 dims
    embedding       VECTOR(1024),
    INDEX idx_incidents_service (service, created_at DESC)
);

-- Distributed vector index: semantic recall stays fast as memory grows.
CREATE VECTOR INDEX IF NOT EXISTS idx_incidents_embedding
    ON incidents (embedding vector_cosine_ops);

------------------------------------------------------------------------------
-- 2. SEMANTIC MEMORY :: durable lessons distilled from incidents
------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS lessons (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    incident_id     UUID REFERENCES incidents(id) ON DELETE CASCADE,
    statement       STRING NOT NULL,
    -- how much the agent trusts this lesson; reinforced on each confirmation
    confidence      FLOAT NOT NULL DEFAULT 0.5,
    times_confirmed INT NOT NULL DEFAULT 0,
    times_refuted   INT NOT NULL DEFAULT 0,
    last_used_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    embedding       VECTOR(1024),
    INDEX idx_lessons_incident (incident_id)
);

CREATE VECTOR INDEX IF NOT EXISTS idx_lessons_embedding
    ON lessons (embedding vector_cosine_ops);

------------------------------------------------------------------------------
-- 3. WORKING MEMORY :: per-session agent state, survives process death
------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sessions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    alert_text      STRING NOT NULL,
    service         STRING,
    status          STRING NOT NULL DEFAULT 'open',
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS session_steps (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    step_no         INT NOT NULL,
    role            STRING NOT NULL,        -- user | assistant | tool | memory
    content         STRING NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (session_id, step_no),
    INDEX idx_steps_session (session_id, step_no)
);

------------------------------------------------------------------------------
-- 4. RECALL AUDIT :: which memories were retrieved, and did they help?
--    This is what turns retrieval into a feedback loop instead of a lookup.
------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS recall_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    incident_id     UUID REFERENCES incidents(id) ON DELETE SET NULL,
    lesson_id       UUID REFERENCES lessons(id) ON DELETE SET NULL,
    similarity      FLOAT NOT NULL,
    was_helpful     BOOL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    INDEX idx_recall_session (session_id)
);
