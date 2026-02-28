-- ============================================================
-- StrataAI – AI Control Plane Cassandra Schema
-- Run with: cqlsh -f ai_control_keyspace.cql
-- ============================================================

CREATE KEYSPACE IF NOT EXISTS ai_control
    WITH replication = {'class': 'NetworkTopologyStrategy', 'DC1': '3'}
    AND durable_writes = true;

-- ------------------------------------------------------------
-- Per-object AI features
-- Keyed by (tenant_id, bucket) partition + (object_key, object_version) clustering
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ai_control.ai_object_features (
    tenant_id           text,
    bucket              text,
    object_key          text,
    object_version      text,           -- empty string when versioning disabled

    etag                text,
    last_updated        timestamp,
    first_seen          timestamp,
    size_bytes          bigint,
    content_type        text,

    -- Classification
    category            text,           -- logs | media | backup | dataset | source-code | unknown
    data_type           text,           -- parquet | json | csv | mp4 | zip | unknown
    semantic_tags       set<text>,      -- e.g. {"category:dataset", "project:analytics"}

    -- Storage intelligence
    entropy_est         double,
    compressibility_est double,
    dedupe_ratio_est    double,
    dedupe_confidence   double,

    -- Security/compliance signals (never raw secrets)
    sensitivity_score   double,
    sensitivity_codes   set<text>,      -- e.g. {"PII_NAME_HINT", "FINANCE_HINT"}

    -- Access intelligence
    hotness_score       double,
    last_accessed       timestamp,
    get_count_7d        bigint,

    -- Recommendations (non-authoritative)
    retention_days_reco int,
    tier_reco           text,           -- hot | warm | cold
    reco_reason         text,

    -- Provenance / audit
    producer_agent      text,           -- e.g. "metadata-profiler@1.0"
    producer_model      text,
    tool_trace_id       text,

    PRIMARY KEY ((tenant_id, bucket), object_key, object_version)
) WITH CLUSTERING ORDER BY (object_key ASC, object_version DESC)
  AND comment = 'AI-derived signals per object version';


-- ------------------------------------------------------------
-- Daily prefix/bucket rollups
-- Fast reads for inline interceptor + ops dashboards
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ai_control.ai_prefix_stats_daily (
    tenant_id               text,
    bucket                  text,
    prefix                  text,   -- e.g. "logs/2026/02/"
    day                     date,   -- YYYY-MM-DD

    object_count            bigint,
    total_bytes             bigint,

    avg_size_bytes          double,
    p50_size_bytes          bigint,
    p95_size_bytes          bigint,

    avg_dedupe_ratio_est    double,
    avg_compressibility_est double,
    dominant_category       text,
    dominant_data_type      text,

    get_count               bigint,
    put_count               bigint,
    hotness_score           double,

    last_updated            timestamp,

    PRIMARY KEY ((tenant_id, bucket, prefix), day)
) WITH CLUSTERING ORDER BY (day DESC)
  AND comment = 'Daily aggregate stats per tenant/bucket/prefix';


-- ------------------------------------------------------------
-- Chunk hash index for real deduplication (async CDC)
-- Optional – only needed for Level-1/Level-2 dedupe
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ai_control.ai_chunk_index (
    tenant_id   text,
    chunk_hash  text,       -- hex/base64 of strong hash (e.g. SHA-256)
    chunk_size  int,
    first_seen  timestamp,
    last_seen   timestamp,
    seen_count  counter,

    PRIMARY KEY ((tenant_id), chunk_hash)
) WITH comment = 'Content-defined chunk index for deduplication estimation';
