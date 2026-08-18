BEGIN;

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS rag_schema_migrations (
    version TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS rag_sources (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    source_key TEXT NOT NULL UNIQUE,
    source_type TEXT NOT NULL,
    title TEXT NOT NULL,
    source_path TEXT,

    content_hash CHAR(64) NOT NULL,
    raw_content TEXT NOT NULL,

    revision INTEGER NOT NULL DEFAULT 1,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT rag_sources_key_not_empty_check
        CHECK (length(btrim(source_key)) > 0),

    CONSTRAINT rag_sources_title_not_empty_check
        CHECK (length(btrim(title)) > 0),

    CONSTRAINT rag_sources_content_not_empty_check
        CHECK (length(btrim(raw_content)) > 0),

    CONSTRAINT rag_sources_type_check
        CHECK (
            source_type IN (
                'project_document',
                'source_code',
                'claude_chat',
                'decision',
                'test_result'
            )
        ),

    CONSTRAINT rag_sources_hash_check
        CHECK (
            content_hash ~ '^[0-9a-f]{64}$'
        ),

    CONSTRAINT rag_sources_revision_check
        CHECK (revision > 0),

    CONSTRAINT rag_sources_metadata_object_check
        CHECK (jsonb_typeof(metadata) = 'object')
);

CREATE TABLE IF NOT EXISTS rag_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    source_id UUID NOT NULL,
    parent_id UUID,

    chunk_level TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,

    content TEXT NOT NULL,
    content_hash CHAR(64) NOT NULL,
    token_count INTEGER,

    embedding_status TEXT NOT NULL DEFAULT 'not_applicable',
    embedding vector(1024),
    embedding_model TEXT,
    embedding_error TEXT,

    search_vector TSVECTOR GENERATED ALWAYS AS (
        to_tsvector('simple', content)
    ) STORED,

    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT rag_chunks_source_fk
        FOREIGN KEY (source_id)
        REFERENCES rag_sources(id)
        ON DELETE CASCADE,

    CONSTRAINT rag_chunks_id_source_unique
        UNIQUE (id, source_id),

    CONSTRAINT rag_chunks_parent_same_source_fk
        FOREIGN KEY (parent_id, source_id)
        REFERENCES rag_chunks(id, source_id)
        ON DELETE CASCADE,

    CONSTRAINT rag_chunks_position_unique
        UNIQUE (
            source_id,
            chunk_level,
            chunk_index
        ),

    CONSTRAINT rag_chunks_level_check
        CHECK (
            chunk_level IN ('parent', 'child')
        ),

    CONSTRAINT rag_chunks_index_check
        CHECK (chunk_index >= 0),

    CONSTRAINT rag_chunks_content_not_empty_check
        CHECK (length(btrim(content)) > 0),

    CONSTRAINT rag_chunks_hash_check
        CHECK (
            content_hash ~ '^[0-9a-f]{64}$'
        ),

    CONSTRAINT rag_chunks_token_count_check
        CHECK (
            token_count IS NULL
            OR token_count >= 0
        ),

    CONSTRAINT rag_chunks_metadata_object_check
        CHECK (jsonb_typeof(metadata) = 'object'),

    CONSTRAINT rag_chunks_structure_check
        CHECK (
            (
                chunk_level = 'parent'
                AND parent_id IS NULL
                AND embedding_status = 'not_applicable'
                AND embedding IS NULL
                AND embedding_model IS NULL
                AND embedding_error IS NULL
            )
            OR
            (
                chunk_level = 'child'
                AND parent_id IS NOT NULL
                AND embedding_status IN (
                    'pending',
                    'ready',
                    'failed'
                )
            )
        ),

    CONSTRAINT rag_chunks_embedding_state_check
        CHECK (
            (
                embedding_status = 'not_applicable'
                AND embedding IS NULL
                AND embedding_model IS NULL
                AND embedding_error IS NULL
            )
            OR
            (
                embedding_status = 'pending'
                AND embedding IS NULL
                AND embedding_error IS NULL
            )
            OR
            (
                embedding_status = 'ready'
                AND embedding IS NOT NULL
                AND embedding_model IS NOT NULL
                AND embedding_error IS NULL
            )
            OR
            (
                embedding_status = 'failed'
                AND embedding IS NULL
                AND embedding_error IS NOT NULL
            )
        )
);

CREATE INDEX IF NOT EXISTS rag_sources_type_idx
    ON rag_sources(source_type);

CREATE INDEX IF NOT EXISTS rag_sources_path_idx
    ON rag_sources(source_path)
    WHERE source_path IS NOT NULL;

CREATE INDEX IF NOT EXISTS rag_sources_updated_at_idx
    ON rag_sources(updated_at DESC);

CREATE INDEX IF NOT EXISTS rag_chunks_source_idx
    ON rag_chunks(source_id);

CREATE INDEX IF NOT EXISTS rag_chunks_parent_idx
    ON rag_chunks(parent_id)
    WHERE parent_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS rag_chunks_embedding_status_idx
    ON rag_chunks(embedding_status)
    WHERE chunk_level = 'child';

CREATE INDEX IF NOT EXISTS rag_chunks_search_vector_idx
    ON rag_chunks
    USING GIN(search_vector);

CREATE INDEX IF NOT EXISTS rag_chunks_embedding_hnsw_idx
    ON rag_chunks
    USING hnsw (embedding vector_cosine_ops)
    WHERE (
        chunk_level = 'child'
        AND embedding_status = 'ready'
        AND embedding IS NOT NULL
    );

CREATE OR REPLACE FUNCTION rag_set_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS rag_sources_set_updated_at
    ON rag_sources;

CREATE TRIGGER rag_sources_set_updated_at
BEFORE UPDATE ON rag_sources
FOR EACH ROW
EXECUTE FUNCTION rag_set_updated_at();

INSERT INTO rag_schema_migrations (
    version,
    description
)
VALUES (
    '001',
    'Initial RAG sources and parent-child chunk schema'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;