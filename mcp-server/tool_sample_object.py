"""
MCP Tool: sample_object_bytes
Policy-gated content sampling for AI enrichment.
"""

from __future__ import annotations

import base64
import os
from typing import Any

import cassandra_client as db
from config import CASSANDRA_KEYSPACE_AUTH, SAMPLE_MAX_BYTES
from tool_lustre import _safe_path


def _is_sampling_allowed(tenant_id: str, bucket: str) -> bool:
    """
    Check bucket policy: sampling must be explicitly enabled.
    Returns True only when the bucket's allow_content_sampling flag is set.
    """
    cql = f"""
        SELECT allow_content_sampling
        FROM {CASSANDRA_KEYSPACE_AUTH}.bucket_policies
        WHERE tenant_id = %s AND bucket = %s
        LIMIT 1
    """
    rows = db.query(cql, (tenant_id, bucket))
    if not rows:
        return False
    return bool(rows[0].get("allow_content_sampling", False))


def run(
    tenant_id: str,
    bucket: str,
    object_key: str,
    lustre_path: str,
    max_bytes: int,
    offset: int = 0,
) -> dict[str, Any]:
    """
    Sample up to max_bytes from a Lustre object file.
    Enforces per-bucket policy gating and a hard cap of SAMPLE_MAX_BYTES.
    """
    if not _is_sampling_allowed(tenant_id, bucket):
        raise PermissionError(
            f"Content sampling not permitted for tenant={tenant_id!r} bucket={bucket!r}"
        )

    actual_max = min(max_bytes, SAMPLE_MAX_BYTES)
    path = _safe_path(lustre_path)

    with open(path, "rb") as fh:
        fh.seek(offset)
        data = fh.read(actual_max)

    content_hint = _infer_content_hint(data)
    return {
        "bytes_base64": base64.b64encode(data).decode("ascii"),
        "actual_bytes": len(data),
        "content_hint": content_hint,
    }


def _infer_content_hint(data: bytes) -> str:
    """Cheap magic-byte based content hint (no LLM)."""
    if data[:4] == b"PAR1":
        return "parquet"
    if data[:2] in (b"\x1f\x8b", b"BZ", b"\xfd7zXZ"):
        return "compressed"
    if data[:4] == b"ORC\x01":
        return "orc"
    if data[:4] == b"\x50\x4b\x03\x04":
        return "zip"
    try:
        data[:256].decode("utf-8")
        return "text"
    except UnicodeDecodeError:
        return "binary"
