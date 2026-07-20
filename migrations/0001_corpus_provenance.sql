BEGIN;

CREATE TABLE IF NOT EXISTS corpus_documents (
    document_id          TEXT PRIMARY KEY,
    act_number           TEXT NOT NULL,
    act_title            TEXT NOT NULL,
    language             TEXT NOT NULL,
    asset_key            TEXT NOT NULL,
    sha256               TEXT NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    byte_size            BIGINT NOT NULL CHECK (byte_size > 0),
    page_count           INTEGER NOT NULL CHECK (page_count > 0),
    source_url           TEXT NOT NULL,
    detail_url           TEXT NOT NULL DEFAULT '',
    timeline_date        TEXT NOT NULL DEFAULT '',
    timeline_type        TEXT NOT NULL DEFAULT '',
    metadata_scraped_at  TIMESTAMPTZ,
    document_kind        TEXT NOT NULL DEFAULT 'reprint',
    lifecycle_status     TEXT NOT NULL CHECK (
        lifecycle_status IN ('registered', 'extracted', 'active', 'superseded', 'blocked')
    ),
    registered_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (document_id, sha256),
    UNIQUE (document_id, act_number, language)
);

CREATE INDEX IF NOT EXISTS corpus_documents_act_language_idx
    ON corpus_documents (act_number, language, lifecycle_status);
CREATE INDEX IF NOT EXISTS corpus_documents_sha256_idx
    ON corpus_documents (sha256);

CREATE TABLE IF NOT EXISTS document_sources (
    source_id             BIGSERIAL PRIMARY KEY,
    document_id           TEXT NOT NULL REFERENCES corpus_documents(document_id),
    source_url            TEXT NOT NULL,
    observed_at           TIMESTAMPTZ NOT NULL,
    http_etag             TEXT NOT NULL DEFAULT '',
    http_last_modified    TEXT NOT NULL DEFAULT '',
    response_content_type TEXT NOT NULL DEFAULT '',
    UNIQUE (document_id, source_url, observed_at)
);

CREATE TABLE IF NOT EXISTS extraction_runs (
    extraction_id         TEXT PRIMARY KEY,
    document_id           TEXT NOT NULL REFERENCES corpus_documents(document_id),
    extractor             TEXT NOT NULL,
    extractor_version     TEXT NOT NULL,
    configuration_hash    TEXT NOT NULL CHECK (configuration_hash ~ '^[0-9a-f]{64}$'),
    chunk_set_hash        TEXT NOT NULL CHECK (chunk_set_hash ~ '^[0-9a-f]{64}$'),
    chunk_count           INTEGER NOT NULL CHECK (chunk_count >= 0),
    sidecar_asset_key     TEXT,
    sidecar_sha256        TEXT CHECK (sidecar_sha256 IS NULL OR sidecar_sha256 ~ '^[0-9a-f]{64}$'),
    sidecar_byte_size     BIGINT CHECK (sidecar_byte_size IS NULL OR sidecar_byte_size > 0),
    sidecar_format        TEXT,
    status                TEXT NOT NULL CHECK (status IN ('pending', 'ready', 'failed', 'superseded')),
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (extraction_id, document_id)
);

CREATE TABLE IF NOT EXISTS active_corpus_documents (
    act_number            TEXT NOT NULL,
    language              TEXT NOT NULL,
    document_id           TEXT NOT NULL,
    extraction_id         TEXT NOT NULL,
    activated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (act_number, language),
    FOREIGN KEY (document_id, act_number, language)
        REFERENCES corpus_documents(document_id, act_number, language),
    FOREIGN KEY (extraction_id, document_id)
        REFERENCES extraction_runs(extraction_id, document_id)
);

CREATE TABLE IF NOT EXISTS corpus_activation_history (
    activation_id         BIGSERIAL PRIMARY KEY,
    act_number            TEXT NOT NULL,
    language              TEXT NOT NULL,
    document_id           TEXT NOT NULL REFERENCES corpus_documents(document_id),
    extraction_id         TEXT NOT NULL REFERENCES extraction_runs(extraction_id),
    previous_document_id  TEXT REFERENCES corpus_documents(document_id),
    previous_extraction_id TEXT REFERENCES extraction_runs(extraction_id),
    action                TEXT NOT NULL CHECK (action IN ('activate', 'rollback')),
    activated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE chunks ADD COLUMN IF NOT EXISTS document_id TEXT;
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS extraction_id TEXT;
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS content_sha256 TEXT;
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS page_start INTEGER;
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS page_end INTEGER;
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS chunk_ordinal INTEGER;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chunks_document_fk') THEN
        ALTER TABLE chunks ADD CONSTRAINT chunks_document_fk
            FOREIGN KEY (document_id) REFERENCES corpus_documents(document_id) NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chunks_extraction_document_fk') THEN
        ALTER TABLE chunks ADD CONSTRAINT chunks_extraction_document_fk
            FOREIGN KEY (extraction_id, document_id)
            REFERENCES extraction_runs(extraction_id, document_id) NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chunks_content_sha256_check') THEN
        ALTER TABLE chunks ADD CONSTRAINT chunks_content_sha256_check
            CHECK (content_sha256 IS NULL OR content_sha256 ~ '^[0-9a-f]{64}$') NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chunks_page_bounds_check') THEN
        ALTER TABLE chunks ADD CONSTRAINT chunks_page_bounds_check
            CHECK (
                (page_start IS NULL AND page_end IS NULL)
                OR (page_start >= 1 AND page_end >= page_start)
            ) NOT VALID;
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS chunks_extraction_ordinal_uidx
    ON chunks (extraction_id, chunk_ordinal)
    WHERE extraction_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS chunks_document_section_idx
    ON chunks (document_id, section_number)
    WHERE document_id IS NOT NULL;

COMMIT;
