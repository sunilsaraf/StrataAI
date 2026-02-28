"""
Audit logger – append-only JSONL file per MCP tool invocation.
Every tool call is recorded with: who called it, what args, what result status.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any

from config import AUDIT_LOG_PATH

logger = logging.getLogger(__name__)


def _ensure_log_dir() -> None:
    os.makedirs(os.path.dirname(AUDIT_LOG_PATH), exist_ok=True)


def record(
    *,
    tool: str,
    caller: str,
    args: dict[str, Any],
    result_status: str,
    trace_id: str | None = None,
) -> str:
    """
    Write one audit record. Returns the generated trace_id.
    Failures are logged but never raised (audit must not break tool calls).
    """
    trace_id = trace_id or str(uuid.uuid4())
    entry = {
        "trace_id": trace_id,
        "ts": datetime.now(timezone.utc).isoformat(),
        "tool": tool,
        "caller": caller,
        "args": args,
        "result_status": result_status,
    }
    try:
        _ensure_log_dir()
        with open(AUDIT_LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    except Exception as exc:
        logger.warning("Audit write failed for trace_id=%s: %s", trace_id, exc)
    return trace_id
