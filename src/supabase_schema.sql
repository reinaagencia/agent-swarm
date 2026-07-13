-- ═══════════════════════════════════════════════════════════════
-- Esquema GBrain — Cerebro de Memoria Vectorial del Enjambre
-- Base de datos: Supabase (PostgreSQL + pgvector)
-- 
-- Dimensiones del embedding: 384 (BAAI/bge-small-en-v1.5 via fastembed)
-- Modelo local, sin dependencia de API externa.
-- ═══════════════════════════════════════════════════════════════

-- ════════════════════════════════════════════════════════════════
-- MIGRACIÓN: Si la tabla ya existe con VECTOR(1536), migrar a 384
-- ════════════════════════════════════════════════════════════════
-- Descomentar SOLO si se migra desde VECTOR(1536):
-- DROP TRIGGER IF EXISTS trg_update_keywords ON agent_memory;
-- DROP FUNCTION IF EXISTS update_keywords_trigger() CASCADE;
-- DROP FUNCTION IF EXISTS match_agent_memory(VECTOR(1536), TEXT, INT, FLOAT) CASCADE;
-- DROP FUNCTION IF EXISTS insert_agent_memory(VARCHAR, TEXT, VECTOR(1536), JSONB) CASCADE;
-- DROP INDEX IF EXISTS idx_agent_memory_embedding;
-- ALTER TABLE agent_memory DROP COLUMN IF EXISTS embedding;
-- ALTER TABLE agent_memory ADD COLUMN embedding VECTOR(384);
-- ════════════════════════════════════════════════════════════════

-- 1. Habilitar extensiones
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- 2. Tabla de memoria de agentes
-- Usa VECTOR(384) para coincidir con el modelo local BAAI/bge-small-en-v1.5
CREATE TABLE IF NOT EXISTS agent_memory (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_type VARCHAR(255) NOT NULL,
    content TEXT NOT NULL,
    embedding VECTOR(384),            -- Vector semántico local (fastembed, 384 dims)
    keywords TSVECTOR,                -- Para búsqueda Full Text (BM25)
    metadata JSONB DEFAULT '{}',      -- Metadatos extras
    created_at TIMESTAMPTZ DEFAULT now()
);

-- 3. Índices para búsqueda rápida
CREATE INDEX IF NOT EXISTS idx_agent_memory_embedding
    ON agent_memory USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

CREATE INDEX IF NOT EXISTS idx_agent_memory_keywords
    ON agent_memory USING GIN (keywords);

CREATE INDEX IF NOT EXISTS idx_agent_memory_created
    ON agent_memory (created_at DESC);

-- 4. Trigger para mantener keywords sincronizado con content
CREATE OR REPLACE FUNCTION update_keywords_trigger() RETURNS TRIGGER AS $$
BEGIN
    NEW.keywords := to_tsvector('spanish', COALESCE(NEW.content, ''));
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_update_keywords ON agent_memory;
CREATE TRIGGER trg_update_keywords
    BEFORE INSERT OR UPDATE ON agent_memory
    FOR EACH ROW EXECUTE FUNCTION update_keywords_trigger();

-- 5. Función RPC para Búsqueda Híbrida (RRF — Reciprocal Rank Fusion)
-- Combina similitud de coseno (vectorial local 384d) con relevancia de texto completo
-- CORREGIDO: Casting explícito a DOUBLE PRECISION para evitar type mismatch
CREATE OR REPLACE FUNCTION match_agent_memory(
    query_embedding VECTOR(384),
    query_text TEXT,
    match_limit INT DEFAULT 5,
    similarity_threshold FLOAT DEFAULT 0.5
)
RETURNS TABLE (
    id UUID,
    content TEXT,
    task_type VARCHAR,
    metadata JSONB,
    similarity DOUBLE PRECISION,
    rrf_score DOUBLE PRECISION
)
LANGUAGE plpgsql
AS $$
DECLARE
    k_constant DOUBLE PRECISION := 60.0;
BEGIN
    RETURN QUERY
    WITH semantic AS (
        SELECT
            am.id,
            am.content,
            am.task_type,
            am.metadata,
            1.0 - (am.embedding <=> query_embedding) AS sim_score
        FROM agent_memory am
        WHERE 1.0 - (am.embedding <=> query_embedding) > similarity_threshold::DOUBLE PRECISION
        ORDER BY am.embedding <=> query_embedding
        LIMIT match_limit * 2
    ),
    fulltext AS (
        SELECT
            am.id,
            am.content,
            am.task_type,
            am.metadata,
            ts_rank(am.keywords, plainto_tsquery('spanish', query_text)) AS rank_score
        FROM agent_memory am
        WHERE am.keywords @@ plainto_tsquery('spanish', query_text)
        ORDER BY rank_score DESC
        LIMIT match_limit * 2
    ),
    semantic_ranked AS (
        SELECT *, ROW_NUMBER() OVER (ORDER BY sim_score DESC) AS rn
        FROM semantic
    ),
    fulltext_ranked AS (
        SELECT *, ROW_NUMBER() OVER (ORDER BY rank_score DESC) AS rn
        FROM fulltext
    )
    SELECT
        COALESCE(s.id, f.id) AS id,
        COALESCE(s.content, f.content) AS content,
        COALESCE(s.task_type, f.task_type) AS task_type,
        COALESCE(s.metadata, f.metadata)::JSONB AS metadata,
        COALESCE(s.sim_score, 0.0)::DOUBLE PRECISION AS similarity,
        (COALESCE(1.0 / (k_constant + s.rn), 0.0) +
         COALESCE(1.0 / (k_constant + f.rn), 0.0))::DOUBLE PRECISION AS rrf_score
    FROM semantic_ranked s
    FULL OUTER JOIN fulltext_ranked f ON s.id = f.id
    ORDER BY rrf_score DESC
    LIMIT match_limit;
END;
$$;

-- 6. Función de inserción de memoria
CREATE OR REPLACE FUNCTION insert_agent_memory(
    p_task_type VARCHAR,
    p_content TEXT,
    p_embedding VECTOR(384),
    p_metadata JSONB DEFAULT '{}'
) RETURNS UUID
LANGUAGE plpgsql
AS $$
DECLARE
    new_id UUID;
BEGIN
    INSERT INTO agent_memory (task_type, content, embedding, metadata)
    VALUES (p_task_type, p_content, p_embedding, p_metadata)
    RETURNING id INTO new_id;
    RETURN new_id;
END;
$$;
