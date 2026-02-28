"""
Thin HTTP client for calling MCP Server tools.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from config import MCP_SERVER_URL, AGENT_VERSION

logger = logging.getLogger(__name__)

_HEADERS = {
    "Content-Type": "application/json",
    "x-caller-id": f"agent-worker@{AGENT_VERSION}",
}


def _post(path: str, payload: dict[str, Any]) -> dict[str, Any] | list | None:
    url = f"{MCP_SERVER_URL}{path}"
    try:
        resp = httpx.post(url, json=payload, headers=_HEADERS, timeout=10.0)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return None
        logger.warning("MCP call failed [%s %s]: %s", path, payload, exc)
        raise
    except Exception as exc:
        logger.warning("MCP call error [%s]: %s", path, exc)
        raise


def get_object_metadata(tenant_id: str, bucket: str, object_key: str,
                        object_version: str | None = None) -> dict[str, Any] | None:
    payload: dict[str, Any] = {
        "tenant_id": tenant_id, "bucket": bucket, "object_key": object_key
    }
    if object_version:
        payload["object_version"] = object_version
    return _post("/tools/get_object_metadata", payload)  # type: ignore[return-value]


def lustre_stat(lustre_path: str) -> dict[str, Any] | None:
    return _post("/tools/lustre_stat", {"lustre_path": lustre_path})  # type: ignore[return-value]


def lustre_layout(lustre_path: str) -> dict[str, Any] | None:
    return _post("/tools/lustre_layout", {"lustre_path": lustre_path})  # type: ignore[return-value]


def write_ai_object_features(tenant_id: str, bucket: str, object_key: str,
                              features: dict[str, Any],
                              object_version: str = "") -> dict[str, str] | None:
    return _post("/tools/write_ai_object_features", {  # type: ignore[return-value]
        "tenant_id": tenant_id,
        "bucket": bucket,
        "object_key": object_key,
        "object_version": object_version,
        "features": features,
    })


def get_ai_object_features(tenant_id: str, bucket: str, object_key: str,
                            object_version: str = "") -> dict[str, Any] | None:
    return _post("/tools/get_ai_object_features", {  # type: ignore[return-value]
        "tenant_id": tenant_id, "bucket": bucket,
        "object_key": object_key, "object_version": object_version,
    })
