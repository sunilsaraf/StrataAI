"""
Metadata Profiler Agent.

Consumes PutCommitted events, calls MCP tools to fetch authoritative metadata
and Lustre layout, then derives cheap classification signals and writes them
back to the AI feature store.

Runs fully ASYNC – never on the CRUD hot path.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

import mcp_client
from config import AGENT_VERSION

logger = logging.getLogger(__name__)

_AGENT_NAME = f"metadata-profiler@{AGENT_VERSION}"

# Heuristic category maps based on key suffix and mime
_EXT_CATEGORY: dict[str, str] = {
    ".parquet": "dataset", ".orc": "dataset", ".avro": "dataset",
    ".csv": "dataset", ".json": "dataset", ".jsonl": "dataset",
    ".log": "logs", ".gz": "logs",
    ".mp4": "media", ".mkv": "media", ".mov": "media",
    ".jpg": "media", ".jpeg": "media", ".png": "media",
    ".tar": "backup", ".zip": "backup", ".bz2": "backup",
    ".py": "source-code", ".java": "source-code", ".go": "source-code",
    ".c": "source-code", ".cpp": "source-code",
}

_MIME_CATEGORY: dict[str, str] = {
    "application/json": "dataset",
    "text/csv": "dataset",
    "text/plain": "logs",
    "video/mp4": "media",
    "image/jpeg": "media",
    "image/png": "media",
    "application/zip": "backup",
    "application/x-tar": "backup",
    "application/octet-stream": "unknown",
}


def _guess_category(object_key: str, content_type: str) -> str:
    lower = object_key.lower()
    for ext, cat in _EXT_CATEGORY.items():
        if lower.endswith(ext):
            return cat
    return _MIME_CATEGORY.get(content_type, "unknown")


def _guess_data_type(object_key: str, content_type: str) -> str:
    lower = object_key.lower()
    for ext in (".parquet", ".orc", ".avro", ".csv", ".json", ".jsonl",
                ".log", ".gz", ".mp4", ".tar", ".zip", ".py"):
        if lower.endswith(ext):
            return ext.lstrip(".")
    return content_type.split("/")[-1] if "/" in content_type else "unknown"


def _tiering_recommendation(size_bytes: int | None, category: str) -> tuple[str, str]:
    """Very simple rule-based tiering hint."""
    if category == "backup":
        return "cold", "backup data is rarely re-accessed"
    if size_bytes and size_bytes > 10 * 1024 * 1024 * 1024:  # >10 GB
        return "warm", "large object; candidate for warm tier"
    return "hot", "default hot tier"


def _compressibility_hint(content_type: str, category: str) -> float:
    """Heuristic compressibility estimate."""
    if category in ("logs", "dataset"):
        return 0.6
    if category == "source-code":
        return 0.7
    if category in ("backup",):
        return 0.4
    if "image" in content_type or "video" in content_type:
        return 0.05  # already compressed
    return 0.3


def process(event: dict[str, Any]) -> bool:
    """
    Process a single PutCommitted event.
    Returns True on success.
    """
    tenant_id = event.get("tenant_id", "")
    bucket = event.get("bucket", "")
    key = event.get("key", "")
    version = event.get("object_version") or ""
    request_id = event.get("request_id", "")

    logger.info("[%s] Profiling %s/%s/%s", _AGENT_NAME, tenant_id, bucket, key)

    # 1. Fetch authoritative metadata via MCP
    meta = mcp_client.get_object_metadata(tenant_id, bucket, key, version or None)

    content_type = (meta or {}).get("content_type") or event.get("content_type", "application/octet-stream")
    size_bytes = (meta or {}).get("size_bytes") or event.get("size_bytes")

    # 2. Fetch Lustre layout if path available
    lustre_path = event.get("lustre_path")
    layout: dict[str, Any] = {}
    if lustre_path:
        try:
            layout = mcp_client.lustre_layout(lustre_path) or {}
        except Exception as exc:
            logger.warning("lustre_layout failed for %s: %s", lustre_path, exc)

    # 3. Derive signals
    category = _guess_category(key, content_type)
    data_type = _guess_data_type(key, content_type)
    tier_reco, reco_reason = _tiering_recommendation(size_bytes, category)
    compressibility = _compressibility_hint(content_type, category)

    # Encode Lustre layout hints as semantic tags
    semantic_tags: list[str] = [f"category:{category}"]
    stripe_count = layout.get("stripe_count", 0)
    if stripe_count:
        semantic_tags.append(f"lustre_stripes:{stripe_count}")

    features: dict[str, Any] = {
        "category": category,
        "data_type": data_type,
        "semantic_tags": semantic_tags,
        "compressibility_est": compressibility,
        "tier_reco": tier_reco,
        "reco_reason": reco_reason,
    }

    # 4. Write features back via MCP
    try:
        mcp_client.write_ai_object_features(tenant_id, bucket, key, features, version)
    except Exception as exc:
        logger.error("Failed to write AI features for %s/%s/%s: %s", tenant_id, bucket, key, exc)
        return False

    # 5. Update daily prefix rollup (best-effort; profiler contributes PUT counts
    #    and category/compressibility aggregates).
    prefix = event.get("hints", {}).get("prefix") or (
        "/".join(key.split("/")[:-1]) + "/" if "/" in key else ""
    )
    today = date.today().isoformat()
    prefix_stats: dict[str, Any] = {
        "put_count": 1,
        "dominant_category": category,
        "dominant_data_type": data_type,
        "avg_compressibility_est": compressibility,
    }
    if size_bytes is not None:
        prefix_stats["total_bytes"] = size_bytes
    try:
        mcp_client.write_prefix_stats_daily(tenant_id, bucket, prefix, today, prefix_stats)
    except Exception as exc:
        logger.warning("Prefix stats update failed for %s/%s/%s: %s", tenant_id, bucket, prefix, exc)
        # non-fatal – object features already written

    logger.info("[%s] Done profiling %s/%s/%s → category=%s", _AGENT_NAME, tenant_id, bucket, key, category)
    return True
