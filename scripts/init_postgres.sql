-- Enable vector support in the database
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Drop the table if it exists (for clean initialization)
DROP TABLE IF EXISTS document_embeddings CASCADE;

-- Create the secure table
CREATE TABLE document_embeddings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id VARCHAR(50) NOT NULL,
    clearance_level INT NOT NULL, -- 1=Intern, 2=Engineer, 3=Executive
    departments VARCHAR(50)[] NOT NULL, -- Array of departments allowed to view
    projects VARCHAR(50)[] DEFAULT '{}', -- Array of projects (empty = open to all in department)
    content TEXT NOT NULL,
    embedding vector(768), -- Matches nomic-embed-text dimensions
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Index for high-speed vector retrieval using HNSW
-- Cosine distance is used as it is standard for text embeddings
CREATE INDEX IF NOT EXISTS document_embeddings_hnsw_idx 
ON document_embeddings USING hnsw (embedding vector_cosine_ops);

-- Enable Row-Level Security (RLS)
ALTER TABLE document_embeddings ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_embeddings FORCE ROW LEVEL SECURITY;

-- Enable pgcrypto extension for cryptographic functions (hmac-sha256)
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Cryptographic helper: Base64url Encoder
CREATE OR REPLACE FUNCTION base64url_encode(input_bytes BYTEA) RETURNS TEXT AS $$
DECLARE
    b64 TEXT;
BEGIN
    b64 := encode(input_bytes, 'base64');
    b64 := translate(b64, '+/', '-_');
    b64 := rtrim(b64, '=');
    b64 := replace(b64, E'\n', ''); -- Remove line breaks
    RETURN b64;
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- Cryptographic helper: Base64url Decoder
CREATE OR REPLACE FUNCTION base64url_decode(input_str TEXT) RETURNS TEXT AS $$
DECLARE
    b64 TEXT;
    decoded BYTEA;
BEGIN
    b64 := translate(input_str, '-_', '+/');
    -- Re-add base64 padding
    CASE length(b64) % 4
        WHEN 2 THEN b64 := b64 || '==';
        WHEN 3 THEN b64 := b64 || '=';
        ELSE NULL;
    END CASE;
    BEGIN
        decoded := decode(b64, 'base64');
        RETURN convert_from(decoded, 'UTF-8');
    EXCEPTION WHEN OTHERS THEN
        RAISE EXCEPTION 'Invalid base64url encoding';
    END;
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- JWT Signature Verification Function
CREATE OR REPLACE FUNCTION verify_jwt_signature(token TEXT, secret TEXT) RETURNS TEXT AS $$
DECLARE
    parts TEXT[];
    msg TEXT;
    sig_got TEXT;
    sig_expected TEXT;
    payload_json TEXT;
BEGIN
    parts := string_to_array(token, '.');
    IF cardinality(parts) <> 3 THEN
        RAISE EXCEPTION 'Invalid JWT format: must have exactly 3 parts';
    END IF;
    
    msg := parts[1] || '.' || parts[2];
    sig_got := parts[3];
    
    -- Compute expected signature using HMAC-SHA256
    sig_expected := base64url_encode(hmac(msg::bytea, secret::bytea, 'sha256'));
    
    -- Verify match
    IF sig_got <> sig_expected THEN
        RAISE EXCEPTION 'JWT cryptographic signature verification failed';
    END IF;
    
    -- Decode and return JSON payload
    payload_json := base64url_decode(parts[2]);
    RETURN payload_json;
END;
$$ LANGUAGE plpgsql STRICT;

-- Secure session manager: decodes token, validates cryptography, and binds claims to local transaction
CREATE OR REPLACE FUNCTION set_secure_session(jwt_token TEXT) RETURNS BOOLEAN AS $$
DECLARE
    secret TEXT := 'super-secure-shared-secret-key-12345'; -- Shared secret key
    payload_json TEXT;
    val_org_id TEXT;
    val_clearance INT;
    val_departments TEXT;
    val_projects TEXT;
BEGIN
    -- 1. Verify token signature
    payload_json := verify_jwt_signature(jwt_token, secret);
    
    -- 2. Verify token expiration
    IF (payload_json::json->>'exp')::bigint < extract(epoch from now())::bigint THEN
        RAISE EXCEPTION 'JWT token has expired';
    END IF;
    
    -- 3. Extract core identity claims
    val_org_id := payload_json::json->>'org_id';
    val_clearance := (payload_json::json->>'clearance_level')::integer;
    
    IF val_org_id IS NULL OR val_clearance IS NULL THEN
        RAISE EXCEPTION 'JWT is missing required claims (org_id, clearance_level)';
    END IF;
    
    -- 4. Extract department and project arrays and convert to comma-separated text
    SELECT string_agg(val, ',') INTO val_departments
    FROM json_array_elements_text(payload_json::json->'departments') AS val;
    
    SELECT string_agg(val, ',') INTO val_projects
    FROM json_array_elements_text(payload_json::json->'projects') AS val;
    
    -- 5. Bind claims to local transaction context
    PERFORM set_config('aegis.org_id', val_org_id, true);
    PERFORM set_config('aegis.clearance', val_clearance::text, true);
    PERFORM set_config('aegis.departments', COALESCE(val_departments, ''), true);
    PERFORM set_config('aegis.projects', COALESCE(val_projects, ''), true);
    
    RETURN true;
EXCEPTION WHEN OTHERS THEN
    -- Clear security context on error to prevent leakage
    PERFORM set_config('aegis.org_id', '', true);
    PERFORM set_config('aegis.clearance', '0', true);
    PERFORM set_config('aegis.departments', '', true);
    PERFORM set_config('aegis.projects', '', true);
    RAISE;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Create policy to enforce multi-dimensional RBAC + ABAC + Org isolation using cryptographically validated parameters
CREATE POLICY secure_document_access ON document_embeddings
    FOR ALL
    USING (
        -- 1. Hard Tenant Isolation
        org_id = current_setting('aegis.org_id', true)
        
        -- 2. Hierarchical Clearance Verification
        AND clearance_level <= COALESCE(NULLIF(current_setting('aegis.clearance', true), ''), '0')::integer
        
        -- 3. Compartment (Department) Overlap
        AND (
            departments && string_to_array(COALESCE(NULLIF(current_setting('aegis.departments', true), ''), ''), ',')::varchar[]
        )
        
        -- 4. Specific Project ACL (if document is tagged with a project, user must be on that project)
        AND (
            projects IS NULL 
            OR cardinality(projects) = 0 
            OR projects && string_to_array(COALESCE(NULLIF(current_setting('aegis.projects', true), ''), ''), ',')::varchar[]
        )
    );

-- Create non-superuser role for application traffic
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'app_user') THEN
        CREATE ROLE app_user WITH LOGIN PASSWORD 'app_password';
    END IF;
END
$$;

-- Grant permissions to the application user
GRANT ALL PRIVILEGES ON TABLE document_embeddings TO app_user;

-- Grant execution permissions on crypto functions to the application user
GRANT EXECUTE ON FUNCTION base64url_encode(BYTEA) TO app_user;
GRANT EXECUTE ON FUNCTION base64url_decode(TEXT) TO app_user;
GRANT EXECUTE ON FUNCTION verify_jwt_signature(TEXT, TEXT) TO app_user;
GRANT EXECUTE ON FUNCTION set_secure_session(TEXT) TO app_user;

-- =============================================================================
-- AEGIS USERS TABLE (for frontend authentication)
-- =============================================================================
CREATE TABLE IF NOT EXISTS aegis_users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username VARCHAR(100) NOT NULL UNIQUE,
    email VARCHAR(255) NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role VARCHAR(50) NOT NULL DEFAULT 'intern',
    org_id VARCHAR(50) NOT NULL DEFAULT 'org_alpha',
    clearance_level INT NOT NULL DEFAULT 1,
    departments VARCHAR(50)[] NOT NULL DEFAULT '{}',
    projects VARCHAR(50)[] NOT NULL DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- =============================================================================
-- CHAT SESSIONS TABLE
-- =============================================================================
CREATE TABLE IF NOT EXISTS chat_sessions (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES aegis_users(id) ON DELETE CASCADE,
    title VARCHAR(500) NOT NULL DEFAULT 'New Chat',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS chat_sessions_user_id_idx ON chat_sessions(user_id);
CREATE INDEX IF NOT EXISTS chat_sessions_updated_at_idx ON chat_sessions(updated_at DESC);

-- =============================================================================
-- CHAT MESSAGES TABLE
-- =============================================================================
CREATE TABLE IF NOT EXISTS chat_messages (
    id UUID PRIMARY KEY,
    session_id UUID NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    role VARCHAR(20) NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    file_refs JSONB NOT NULL DEFAULT '[]',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS chat_messages_session_id_idx ON chat_messages(session_id);
CREATE INDEX IF NOT EXISTS chat_messages_created_at_idx ON chat_messages(created_at ASC);

-- Grant access to app_user
GRANT ALL PRIVILEGES ON TABLE aegis_users TO app_user;
GRANT ALL PRIVILEGES ON TABLE chat_sessions TO app_user;
GRANT ALL PRIVILEGES ON TABLE chat_messages TO app_user;

-- =============================================================================
-- DEFAULT TEST USERS (bcrypt hash of 'password123' for all users)
-- Hash generated with bcrypt rounds=12
-- =============================================================================
-- Password for all test users: password123
INSERT INTO aegis_users (username, email, password_hash, role, org_id, clearance_level, departments, projects)
VALUES
  (
    'alice_intern',
    'alice@org-alpha.internal',
    '$2b$12$X5W.1SHtheizJ2IMctwimeMKXZcPvguMBqbXkwSMzpK.u.DSCp8c6',
    'intern',
    'org_alpha',
    1,
    ARRAY['Engineering', 'Support'],
    ARRAY[]::VARCHAR(50)[]
  ),
  (
    'bob_engineer',
    'bob@org-alpha.internal',
    '$2b$12$X5W.1SHtheizJ2IMctwimeMKXZcPvguMBqbXkwSMzpK.u.DSCp8c6',
    'engineer',
    'org_alpha',
    2,
    ARRAY['Engineering'],
    ARRAY['CoreEngine']
  ),
  (
    'carol_hr',
    'carol@org-alpha.internal',
    '$2b$12$X5W.1SHtheizJ2IMctwimeMKXZcPvguMBqbXkwSMzpK.u.DSCp8c6',
    'hr',
    'org_alpha',
    2,
    ARRAY['HR'],
    ARRAY['CompensationReview']
  ),
  (
    'dave_executive',
    'dave@org-alpha.internal',
    '$2b$12$X5W.1SHtheizJ2IMctwimeMKXZcPvguMBqbXkwSMzpK.u.DSCp8c6',
    'executive',
    'org_alpha',
    3,
    ARRAY['Executive', 'Finance', 'Engineering'],
    ARRAY['Mergers', 'CoreEngine']
  )
ON CONFLICT (email) DO NOTHING;

