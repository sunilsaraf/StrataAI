"""
Hotness / Access Pattern Agent.

Consumes Get/List/Delete events and updates the hotness score in the AI
feature store.  Uses an exponential decay model:

    new_score = old_score * decay_factor + 1.0

so objects that receive many reads quickly accumulate a high score, and
inactive objects decay toward zero.
"""

from __future__ import annotations

import logging
from datetime import datetime, date, timezone
from typing import Any

import mcp_client
from config import AGENT_VERSION

logger = logging.getLogger(__name__)

_AGENT_NAME = f"hotness-agent@{AGENT_VERSION}"
_DECAY_FACTOR = 0.9   # applied per event
_HOT_THRESHOLD = 10.0


def _decayed_score(current: float | None, decay: float) -> float:
    return (current or 0.0) * decay + 1.0


def process(event: dict[str, Any]) -> bool:
    """
    Update hotness score for GET/LIST events.
    Returns True on success.
    """
    event_type = event.get("event_type", "")
    if event_type not in ("Get", "List"):
        return True  # nothing to do

    tenant_id = event.get("tenant_id", "")
    bucket = event.get("bucket", "")
    key = event.get("key", "")
    version = event.get("object_version") or ""

    logger.debug("[%s] Updating hotness for %s/%s/%s", _AGENT_NAME, tenant_id, bucket, key)

    # Fetch existing AI features
    existing = mcp_client.get_ai_object_features(tenant_id, bucket, key, version)
    current_score = (existing or {}).get("hotness_score", 0.0)

    new_score = _decayed_score(current_score, _DECAY_FACTOR)

    tier_reco = "hot" if new_score >= _HOT_THRESHOLD else None

    features: dict[str, Any] = {
        "hotness_score": round(new_score, 4),
        "last_accessed": datetime.now(timezone.utc).isoformat(),
    }
    if tier_reco:
        features["tier_reco"] = tier_reco
        features["reco_reason"] = f"hotness score {new_score:.1f} exceeds threshold {_HOT_THRESHOLD}"

    try:
        mcp_client.write_ai_object_features(tenant_id, bucket, key, features, version)
    except Exception as exc:
        logger.error("Failed to update hotness for %s/%s/%s: %s", tenant_id, bucket, key, exc)
        return False

    # Update prefix hotness rollup (best-effort)
    prefix = event.get("hints", {}).get("prefix") or (
        "/".join(key.split("/")[:-1]) + "/" if "/" in key else ""
    )
    today = date.today().isoformat()
    try:
        mcp_client.write_prefix_stats_daily(
            tenant_id, bucket, prefix, today,
            {"get_count": 1, "hotness_score": round(new_score, 4)},
        )
    except Exception as exc:
        logger.warning("Prefix hotness update failed for %s/%s/%s: %s", tenant_id, bucket, prefix, exc)
        # non-fatal

    return True
