BEGIN;

-- Additive deployment-mirror identity. The API continues to read validated
-- promoted artifacts; this digest set proves a PostgreSQL load came from the
-- exact same four-file representation.
ALTER TABLE reference_graph_documents
    ADD COLUMN IF NOT EXISTS artifact_hashes JSONB NOT NULL DEFAULT '{}'::jsonb;

COMMIT;
