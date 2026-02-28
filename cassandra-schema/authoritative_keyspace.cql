-- ============================================================
-- StrataAI – Authoritative Cassandra Schema
-- Run with: cqlsh -f authoritative_keyspace.cql
--
-- This keyspace holds the deterministic control-plane data:
-- object metadata written by the Python Management API and
-- bucket policies enforced by the Java IAM Service.
-- ============================================================

CREATE KEYSPACE IF NOT EXISTS strataai
    WITH replication = {'class': 'NetworkTopologyStrategy', 'DC1': '3'}
    AND durable_writes = true;


-- ------------------------------------------------------------
-- Authoritative object metadata
-- Written on every successful PutObject (after IAM allow +
-- Lustre write success).  This is the "source of truth".
-- The AI feature store (ai_control keyspace) is derived from
-- these records; never the other way around.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS strataai.object_metadata (
    tenant_id       text,
    bucket          text,
    object_key      text,
    object_version  text,       -- empty string when versioning disabled

    etag            text,
    size_bytes      bigint,
    content_type    text,
    created_ts      timestamp,
    last_modified   timestamp,

    -- Optional user-provided metadata (k/v pairs)
    user_metadata   map<text, text>,

    -- Object tags (e.g. {"project": "analytics", "env": "prod"})
    tags            map<text, text>,

    -- Pointer to the backing Lustre file
    -- Deterministically derived as:
    --   /lustre/tenant/<tenant_id>/<bucket>/<object_key>
    -- Stored here so the MCP layer can find the file without
    -- reconstructing the path from rules.
    storage_ref     map<text, text>,    -- {"lustre_path": "...", "ost_hint": "..."}

    -- Soft-delete / lifecycle markers
    deleted         boolean,
    delete_marker   boolean,

    PRIMARY KEY ((tenant_id, bucket), object_key, object_version)
) WITH CLUSTERING ORDER BY (object_key ASC, object_version DESC)
  AND comment = 'Authoritative object metadata – written by Management API';


-- ------------------------------------------------------------
-- Bucket policies (sampling + lifecycle + access control hints)
-- Consulted by the MCP layer for policy-gated operations such
-- as content sampling.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS strataai.bucket_policies (
    tenant_id               text,
    bucket                  text,

    -- Content sampling policy (opt-in per bucket)
    allow_content_sampling  boolean,
    sample_max_bytes        int,        -- per-object sample cap override (0 = use global default)

    -- Lifecycle / retention policy
    default_retention_days  int,
    default_tier            text,       -- hot | warm | cold

    -- Owner / creation metadata
    created_ts              timestamp,
    owner_user_id           text,

    PRIMARY KEY ((tenant_id), bucket)
) WITH comment = 'Per-bucket policy configuration';
