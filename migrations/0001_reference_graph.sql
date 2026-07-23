BEGIN;

-- This index is deliberately separate from retrieval: no chunks table, embedding,
-- activation mapping, or corpus metadata is changed by this migration.
CREATE TABLE IF NOT EXISTS reference_graph_documents (
    document_id        TEXT PRIMARY KEY,
    corpus_document_id TEXT NOT NULL,
    act_number         TEXT NOT NULL,
    source_metadata    JSONB NOT NULL,
    loaded_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS reference_graph_provisions (
    document_id  TEXT NOT NULL REFERENCES reference_graph_documents(document_id) ON DELETE CASCADE,
    provision_id TEXT NOT NULL,
    version_id   TEXT NOT NULL,
    parent_id    TEXT,
    kind         TEXT NOT NULL,
    label        TEXT NOT NULL,
    payload      JSONB NOT NULL,
    PRIMARY KEY (document_id, provision_id),
    UNIQUE (document_id, version_id)
);
CREATE INDEX IF NOT EXISTS reference_graph_provisions_parent_idx
    ON reference_graph_provisions (document_id, parent_id);

CREATE TABLE IF NOT EXISTS reference_graph_edges (
    document_id         TEXT NOT NULL REFERENCES reference_graph_documents(document_id) ON DELETE CASCADE,
    edge_id             TEXT NOT NULL,
    source_provision_id TEXT NOT NULL,
    target_provision_id TEXT NOT NULL,
    payload             JSONB NOT NULL,
    PRIMARY KEY (document_id, edge_id)
);
CREATE INDEX IF NOT EXISTS reference_graph_edges_source_idx
    ON reference_graph_edges (document_id, source_provision_id);
CREATE INDEX IF NOT EXISTS reference_graph_edges_target_idx
    ON reference_graph_edges (document_id, target_provision_id);

CREATE TABLE IF NOT EXISTS reference_graph_unresolved (
    document_id         TEXT NOT NULL REFERENCES reference_graph_documents(document_id) ON DELETE CASCADE,
    candidate_id        TEXT NOT NULL,
    source_provision_id TEXT NOT NULL,
    reason_code         TEXT NOT NULL,
    payload             JSONB NOT NULL,
    PRIMARY KEY (document_id, candidate_id)
);

COMMIT;
