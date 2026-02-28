"""
MCP Tool: write_prefix_stats_daily
Upserts daily aggregate stats for a (tenant, bucket, prefix) rollup.

Called by agent workers after processing PutCommitted or Get/List events
so that operators and the AI interceptor's Redis cache can get fast
summary intelligence without querying every individual object.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import cassandra_client as db
from config import CASSANDRA_KEYSPACE_AI

# All writable columns for ai_prefix_stats_daily (excluding the primary key).
_ALLOWED_COLUMNS = {
    "object_count",
    "total_bytes",
    "avg_size_bytes",
    "avg_dedupe_ratio_est",
    "avg_compressibility_est",
    "dominant_category",
    "dominant_data_type",
    "get_count",
    "put_count",
    "hotness_score",
}


def run(
    tenant_id: str,
    bucket: str,
    prefix: str,
    day: str,
    stats: dict[str, Any],
) -> dict[str, str]:
    """
    Upsert one day's aggregate stats for a prefix.

    Only the fields present in *stats* (and recognised in _ALLOWED_COLUMNS)
    are written; all others are left unchanged.  This lets the Metadata
    Profiler update category/compression fields while the Hotness Agent
    independently updates get_count/hotness_score without overwriting each
    other's data.

    *day* must be a date string in YYYY-MM-DD format.
    """
    # Build a dynamic SET clause containing only the fields supplied by the caller.
    fields = {k: v for k, v in stats.items() if k in _ALLOWED_COLUMNS and v is not None}
    if not fields:
        # Nothing to write; return early rather than issuing a no-op UPDATE.
        return {"status": "ok", "last_updated": datetime.now(timezone.utc).isoformat()}

    now = datetime.now(timezone.utc)
    set_clauses = ", ".join(f"{col} = %s" for col in fields)
    values = list(fields.values())

    cql = f"""
        UPDATE {CASSANDRA_KEYSPACE_AI}.ai_prefix_stats_daily
        SET {set_clauses}, last_updated = %s
        WHERE tenant_id = %s
          AND bucket    = %s
          AND prefix    = %s
          AND day       = %s
    """
    db.execute(cql, (*values, now, tenant_id, bucket, prefix, day))
    return {"status": "ok", "last_updated": now.isoformat()}
