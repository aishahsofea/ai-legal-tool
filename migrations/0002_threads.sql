BEGIN;

CREATE TABLE IF NOT EXISTS threads (
    id         TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL,
    title      TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS threads_user_updated_idx
    ON threads (user_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS thread_turns (
    thread_id       TEXT NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
    turn_index      INTEGER NOT NULL CHECK (turn_index >= 0),
    query           TEXT NOT NULL,
    response        TEXT NOT NULL,
    citations       JSONB NOT NULL DEFAULT '[]'::jsonb,
    commentary      JSONB,
    currency_labels JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (thread_id, turn_index)
);

COMMIT;
