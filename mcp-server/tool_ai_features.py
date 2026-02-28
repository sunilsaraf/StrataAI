"""
MCP Tools: AI feature store read/write + prefix stats.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import cassandra_client as db
from config import CASSANDRA_KEYSPACE_AI


def write_ai_object_features(
    tenant_id: str,
    bucket: str,
    object_key: str,
    features: dict[str, Any],
    object_version: str = "",
    caller: str = "unknown",
    trace_id: str | None = None,
) -> dict[str, str]:
    """Upsert AI-derived features for an object."""
    trace_id = trace_id or str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    cql = f"""
        UPDATE {CASSANDRA_KEYSPACE_AI}.ai_object_features
        SET
            last_updated = %s,
            category = %s,
            data_type = %s,
            semantic_tags = %s,
            entropy_est = %s,
            compressibility_est = %s,
            dedupe_ratio_est = %s,
            dedupe_confidence = %s,
            sensitivity_score = %s,
            sensitivity_codes = %s,
            hotness_score = %s,
            retention_days_reco = %s,
            tier_reco = %s,
            reco_reason = %s,
            producer_agent = %s,
            tool_trace_id = %s
        WHERE tenant_id = %s
          AND bucket = %s
          AND object_key = %s
          AND object_version = %s
    """
    db.execute(
        cql,
        (
            now,
            features.get("category"),
            features.get("data_type"),
            set(features.get("semantic_tags", [])) or None,
            features.get("entropy_est"),
            features.get("compressibility_est"),
            features.get("dedupe_ratio_est"),
            features.get("dedupe_confidence"),
            features.get("sensitivity_score"),
            set(features.get("sensitivity_codes", [])) or None,
            features.get("hotness_score"),
            features.get("retention_days_reco"),
            features.get("tier_reco"),
            features.get("reco_reason"),
            caller,
            trace_id,
            tenant_id,
            bucket,
            object_key,
            object_version,
        ),
    )
    return {
        "status": "ok",
        "last_updated": now.isoformat(),
        "tool_trace_id": trace_id,
    }


def get_ai_object_features(
    tenant_id: str,
    bucket: str,
    object_key: str,
    object_version: str = "",
) -> dict[str, Any] | None:
    """Read AI-derived features for an object."""
    cql = f"""
        SELECT *
        FROM {CASSANDRA_KEYSPACE_AI}.ai_object_features
        WHERE tenant_id = %s AND bucket = %s
          AND object_key = %s AND object_version = %s
        LIMIT 1
    """
    rows = db.query(cql, (tenant_id, bucket, object_key, object_version))
    return rows[0] if rows else None


def get_prefix_stats_daily(
    tenant_id: str,
    bucket: str,
    prefix: str,
    day: str | None = None,
) -> list[dict[str, Any]]:
    """Read daily rollup stats for a prefix."""
    if day:
        cql = f"""
            SELECT *
            FROM {CASSANDRA_KEYSPACE_AI}.ai_prefix_stats_daily
            WHERE tenant_id = %s AND bucket = %s AND prefix = %s AND day = %s
            LIMIT 1
        """
        rows = db.query(cql, (tenant_id, bucket, prefix, day))
    else:
        cql = f"""
            SELECT *
            FROM {CASSANDRA_KEYSPACE_AI}.ai_prefix_stats_daily
            WHERE tenant_id = %s AND bucket = %s AND prefix = %s
            LIMIT 30
        """
        rows = db.query(cql, (tenant_id, bucket, prefix))
    return rows
