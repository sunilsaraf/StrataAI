"""
MCP Tool: get_object_metadata
Reads authoritative object metadata from Cassandra.
"""

from __future__ import annotations

from typing import Any

import cassandra_client as db
from config import CASSANDRA_KEYSPACE_AUTH


def run(
    tenant_id: str,
    bucket: str,
    object_key: str,
    object_version: str | None = None,
) -> dict[str, Any] | None:
    cql = f"""
        SELECT etag, size_bytes, content_type, created_ts,
               user_metadata, tags, storage_ref
        FROM {CASSANDRA_KEYSPACE_AUTH}.object_metadata
        WHERE tenant_id = %s AND bucket = %s AND object_key = %s
    """
    params: tuple[Any, ...] = (tenant_id, bucket, object_key)
    if object_version:
        cql += " AND object_version = %s"
        params = (tenant_id, bucket, object_key, object_version)
    cql += " LIMIT 1"

    rows = db.query(cql, params)
    return rows[0] if rows else None
