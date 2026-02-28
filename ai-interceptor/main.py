"""
AI Interceptor – FastAPI service entry point.

Can be deployed as:
  1. A standalone micro-service behind Nginx (forward proxy mode)
  2. Embedded as ASGI middleware inside the Python Management API

POST /intercept  – receives request context, emits AI observation event,
                   returns trace headers + optional prefix cache hint.
GET  /health     – liveness probe.
"""

from __future__ import annotations

import logging

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import Any, Optional

from config import SERVICE_HOST, SERVICE_PORT
from interceptor import extract_signals, emit_event, get_prefix_cache

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="AI Interceptor", version="1.0.0")


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class ClientInfo(BaseModel):
    ip: Optional[str] = None
    user_agent: Optional[str] = None
    app_id: Optional[str] = None


class AuthzInfo(BaseModel):
    decision: Optional[str] = None
    policy_ref: Optional[str] = None


class InterceptRequest(BaseModel):
    event_type: str = Field(..., description="e.g. PutRequested, PutCommitted, Get, Delete")
    tenant_id: str
    user_id: str
    bucket: str
    key: str
    object_version: Optional[str] = None
    etag: Optional[str] = None
    size_bytes: Optional[int] = None
    content_type: str = "application/octet-stream"
    op_status: str = "REQUESTED"
    error_code: Optional[str] = None
    lustre_path: Optional[str] = None
    request_id: Optional[str] = None
    kms_encrypted: bool = False
    tags: Optional[dict[str, str]] = None
    client: Optional[ClientInfo] = None
    authz: Optional[AuthzInfo] = None


class InterceptResponse(BaseModel):
    request_id: str
    event_emitted: bool
    prefix_cache_hit: bool
    prefix_intelligence: Optional[dict[str, Any]] = None
    trace_headers: dict[str, str]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "ai-interceptor"}


@app.post("/intercept", response_model=InterceptResponse)
async def intercept(req: InterceptRequest) -> InterceptResponse:
    """
    Synchronous observation endpoint (<20 ms target).
    Extracts cheap signals, emits Kafka event, reads Redis prefix cache.
    """
    raw = req.model_dump()
    if req.client:
        raw["client"] = req.client.model_dump()
    if req.authz:
        raw["authz"] = req.authz.model_dump()

    # 1. Extract signals
    event = extract_signals(raw)

    # 2. Emit event to Kafka (best-effort, non-blocking)
    emitted = emit_event(event)

    # 3. Read prefix intelligence from Redis cache
    prefix = event["hints"]["prefix"]
    cache = get_prefix_cache(req.tenant_id, req.bucket, prefix)

    # 4. Build trace headers for downstream
    trace_headers = {
        "x-ai-request-id": event["request_id"],
        "x-ai-prefix": prefix,
        "x-ai-tenant": req.tenant_id,
    }

    return InterceptResponse(
        request_id=event["request_id"],
        event_emitted=emitted,
        prefix_cache_hit=cache is not None,
        prefix_intelligence=cache,
        trace_headers=trace_headers,
    )


if __name__ == "__main__":
    uvicorn.run("main:app", host=SERVICE_HOST, port=SERVICE_PORT, reload=False)
