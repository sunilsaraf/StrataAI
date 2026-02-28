# StrataAI
"Strata" → storage layers connection to lustre+ tiering intelligence with AI, it's a Cognitive Agentic Storage Control Plane.

## Architecture Overview

StrataAI separates responsibilities into two distinct planes:

### Deterministic Control Plane (authoritative)
- **Nginx** – edge reverse proxy
- **Python Management API** – user/bucket/object CRUD
- **Java IAM Service** – authoritative AuthN/AuthZ, policy evaluation
- **Cassandra** – authoritative object metadata

### AI Control Plane (enrichment + recommendations)
- **AI Interceptor** – synchronous, thin observation layer (<20 ms target); extracts cheap signals, emits Kafka events, reads Redis prefix cache. **Never calls an LLM inline.**
- **Kafka** (`ai-control-events`) – minimal event bus (one topic, 6–12 partitions, snappy compression)
- **MCP Server** – safe tool gateway for agents; strict schemas, per-call audit log, no raw DB credentials exposed to agents
- **Agent Workers** – async Kafka consumers; run enrichment pipelines seconds/minutes after the CRUD path
- **Cassandra AI Keyspace** (`ai_control`) – derived signals, not authoritative metadata
- **Redis** – prefix/bucket intelligence cache for fast inline reads

```
Client (S3/SDK) → Nginx → AI Interceptor (SYNC) → Python Mgmt API → Java IAM → Cassandra → Lustre
                                 ↓
                            Kafka (async)
                                 ↓
                         Agent Workers
                                 ↓
                          MCP Server (tools w/ audit)
                         /              \
                  Cassandra (auth)    Cassandra AI keyspace
```

## Directory Layout

```
.
├── ai-interceptor/         # Sync observation layer (FastAPI)
├── mcp-server/             # MCP tool gateway (FastAPI + audit)
├── agent-workers/          # Async Kafka consumers (agents)
│   └── agents/
│       ├── metadata_profiler.py   # Phase 1: classification from naming + Lustre layout
│       └── hotness_agent.py       # Phase 1: GET/LIST access pattern tracking
├── cassandra-schema/       # CQL schema for ai_control keyspace
│   ├── ai_control_keyspace.cql
│   └── init.sh
├── tests/                  # Unit tests (30 tests, no external deps required)
├── docker-compose.yml      # Full stack orchestration
└── README.md
```

## Request Flow (PutObject example)

1. **Client → Nginx** — edge routing
2. **AI Interceptor (SYNC, <20 ms)** — extracts tenant/bucket/key/size/content-type/timestamp; emits `PutRequested` event to Kafka; optionally reads Redis prefix cache; never blocks on LLM
3. **Deterministic pipeline** — Python API → Java IAM authorize → metadata write to Cassandra → data write to Lustre; emits `PutCommitted` event
4. **Agent Workers (ASYNC, seconds/minutes)** — consume `PutCommitted`; call MCP tools to fetch authoritative metadata + Lustre layout; classify, enrich, estimate compressibility/tiering; write results to AI feature store

## AI Feature Store Schema

Per-object derived signals keyed by `(tenant_id, bucket, object_key, object_version)`:

| Field | Description |
|-------|-------------|
| `category` | logs / media / backup / dataset / source-code / unknown |
| `data_type` | parquet / json / csv / mp4 / zip / unknown |
| `semantic_tags` | set of tag strings (e.g. `category:dataset`, `lustre_stripes:4`) |
| `entropy_est` | 0–8 entropy estimate |
| `compressibility_est` | 0–1 estimate |
| `dedupe_ratio_est` | 0–1 estimate with `dedupe_confidence` |
| `sensitivity_score` | 0–1 + `sensitivity_codes` (no raw secrets stored) |
| `hotness_score` | exponential-decay access score |
| `tier_reco` | hot / warm / cold recommendation |
| `retention_days_reco` | recommended retention in days |
| `producer_agent` | agent + version that produced this record |
| `tool_trace_id` | links to MCP audit log entry |

## MCP Server Tools

All tool calls are schema-validated and appended to an audit JSONL log:

| Tool | Description |
|------|-------------|
| `get_object_metadata` | Read authoritative metadata from Cassandra |
| `lustre_stat` | File stats (size, mtime, ctime, inode) from Lustre |
| `lustre_layout` | Stripe count/size/OSTs via `lfs getstripe` |
| `sample_object_bytes` | Policy-gated content sampling (max 64 KB, per-bucket opt-in) |
| `write_ai_object_features` | Write derived features to AI store |
| `get_ai_object_features` | Read derived features from AI store |
| `get_prefix_stats_daily` | Read daily rollup stats for a prefix |

## Agent Catalog

| Agent | Trigger | What it does |
|-------|---------|--------------|
| `metadata_profiler` | `PutCommitted` | Category/type classification from key naming + Lustre layout; tiering recommendation |
| `hotness_agent` | `Get`, `List` | Exponential-decay hotness score; promotes hot objects to `hot` tier recommendation |

## Running Locally

```bash
# Start full stack (requires Docker + Docker Compose v2)
docker compose up --build

# Run unit tests (no external dependencies required)
python -m pytest tests/ -v
```

## Kafka Event Schema

Topic: `ai-control-events` | Partitions: 6 | Retention: 3 days | Compression: snappy

```json
{
  "event_version": 1,
  "event_type": "PutRequested|PutCommitted|Get|Delete|List|BucketCreated|PolicyChanged",
  "ts": "2026-02-28T12:34:56.789Z",
  "request_id": "<uuid>",
  "tenant_id": "t1",
  "user_id": "u123",
  "bucket": "bkt-a",
  "key": "path/to/object.parquet",
  "object_version": "v1",
  "etag": "<etag>",
  "size_bytes": 1234567,
  "content_type": "application/octet-stream",
  "op_status": "REQUESTED|COMMITTED|FAILED",
  "lustre_path": "/lustre/t1/bkt-a/path/to/object.parquet",
  "client": {"ip": "1.2.3.4", "user_agent": "...", "app_id": "optional"},
  "authz": {"decision": "ALLOW|DENY", "policy_ref": "optional"},
  "hints": {"prefix": "path/to/", "kms_encrypted": false, "tags_present": true}
}
```

## Security Properties

- **No LLM on CRUD hot path** — interceptor emits events only; zero LLM calls inline
- **No raw Cassandra credentials for agents** — agents call MCP tools only, which enforce schema + audit
- **Content sampling is opt-in** — per-bucket `allow_content_sampling` policy, 64 KB cap, fully audited
- **Path traversal protection** — all Lustre paths are validated to stay within the mount point
- **Prompt injection safety** — MCP tools use strict Pydantic schemas; agents cannot issue arbitrary queries
- **Tenant isolation** — all partition keys include `tenant_id`; AI features are per-tenant
- **Circuit breaker** — if Kafka or Redis is unavailable, CRUD still works; enrichment skips gracefully
