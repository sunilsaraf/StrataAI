"""
MCP Server – FastAPI entry point.

Exposes strict-schema tool endpoints for AI agents.
All calls are audited; agents NEVER receive raw Cassandra credentials.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel, Field

import audit
import tool_get_object_metadata
import tool_lustre
import tool_sample_object
import tool_ai_features
from config import SERVICE_HOST, SERVICE_PORT

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="MCP Server", version="1.0.0")

_SYSTEM_CALLER = "system"


def _caller(x_caller_id: str | None) -> str:
    return x_caller_id or _SYSTEM_CALLER


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "mcp-server"}


# ---------------------------------------------------------------------------
# Tool: get_object_metadata
# ---------------------------------------------------------------------------

class GetObjectMetadataRequest(BaseModel):
    tenant_id: str
    bucket: str
    object_key: str
    object_version: Optional[str] = None


@app.post("/tools/get_object_metadata")
async def get_object_metadata(
    req: GetObjectMetadataRequest,
    x_caller_id: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    caller = _caller(x_caller_id)
    trace_id = audit.record(
        tool="get_object_metadata",
        caller=caller,
        args=req.model_dump(),
        result_status="pending",
    )
    try:
        result = tool_get_object_metadata.run(
            req.tenant_id, req.bucket, req.object_key, req.object_version
        )
        audit.record(tool="get_object_metadata", caller=caller, args=req.model_dump(),
                     result_status="ok", trace_id=trace_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Object metadata not found")
        return result
    except HTTPException:
        raise
    except Exception as exc:
        audit.record(tool="get_object_metadata", caller=caller, args=req.model_dump(),
                     result_status="error", trace_id=trace_id)
        logger.exception("get_object_metadata failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Tool: lustre_stat
# ---------------------------------------------------------------------------

class LustreStatRequest(BaseModel):
    lustre_path: str


@app.post("/tools/lustre_stat")
async def lustre_stat(
    req: LustreStatRequest,
    x_caller_id: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    caller = _caller(x_caller_id)
    trace_id = audit.record(tool="lustre_stat", caller=caller, args=req.model_dump(),
                            result_status="pending")
    try:
        result = tool_lustre.lustre_stat(req.lustre_path)
        audit.record(tool="lustre_stat", caller=caller, args=req.model_dump(),
                     result_status="ok", trace_id=trace_id)
        return result
    except ValueError as exc:
        audit.record(tool="lustre_stat", caller=caller, args=req.model_dump(),
                     result_status="denied", trace_id=trace_id)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        audit.record(tool="lustre_stat", caller=caller, args=req.model_dump(),
                     result_status="error", trace_id=trace_id)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Tool: lustre_layout
# ---------------------------------------------------------------------------

@app.post("/tools/lustre_layout")
async def lustre_layout(
    req: LustreStatRequest,
    x_caller_id: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    caller = _caller(x_caller_id)
    trace_id = audit.record(tool="lustre_layout", caller=caller, args=req.model_dump(),
                            result_status="pending")
    try:
        result = tool_lustre.lustre_layout(req.lustre_path)
        audit.record(tool="lustre_layout", caller=caller, args=req.model_dump(),
                     result_status="ok", trace_id=trace_id)
        return result
    except ValueError as exc:
        audit.record(tool="lustre_layout", caller=caller, args=req.model_dump(),
                     result_status="denied", trace_id=trace_id)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        audit.record(tool="lustre_layout", caller=caller, args=req.model_dump(),
                     result_status="error", trace_id=trace_id)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Tool: sample_object_bytes (policy gated)
# ---------------------------------------------------------------------------

class SampleObjectRequest(BaseModel):
    tenant_id: str
    bucket: str
    object_key: str
    lustre_path: str
    max_bytes: int = Field(..., gt=0)
    offset: int = Field(default=0, ge=0)


@app.post("/tools/sample_object_bytes")
async def sample_object_bytes(
    req: SampleObjectRequest,
    x_caller_id: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    caller = _caller(x_caller_id)
    safe_args = {**req.model_dump(), "lustre_path": req.lustre_path[:200]}
    trace_id = audit.record(tool="sample_object_bytes", caller=caller, args=safe_args,
                            result_status="pending")
    try:
        result = tool_sample_object.run(
            req.tenant_id, req.bucket, req.object_key,
            req.lustre_path, req.max_bytes, req.offset
        )
        audit.record(tool="sample_object_bytes", caller=caller, args=safe_args,
                     result_status="ok", trace_id=trace_id)
        return result
    except PermissionError as exc:
        audit.record(tool="sample_object_bytes", caller=caller, args=safe_args,
                     result_status="denied", trace_id=trace_id)
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        audit.record(tool="sample_object_bytes", caller=caller, args=safe_args,
                     result_status="denied", trace_id=trace_id)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        audit.record(tool="sample_object_bytes", caller=caller, args=safe_args,
                     result_status="error", trace_id=trace_id)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Tool: write_ai_object_features
# ---------------------------------------------------------------------------

class WriteAIFeaturesRequest(BaseModel):
    tenant_id: str
    bucket: str
    object_key: str
    object_version: str = ""
    features: dict[str, Any]


@app.post("/tools/write_ai_object_features")
async def write_ai_object_features(
    req: WriteAIFeaturesRequest,
    x_caller_id: Optional[str] = Header(default=None),
) -> dict[str, str]:
    caller = _caller(x_caller_id)
    args = {k: v for k, v in req.model_dump().items() if k != "features"}
    trace_id = audit.record(tool="write_ai_object_features", caller=caller, args=args,
                            result_status="pending")
    try:
        result = tool_ai_features.write_ai_object_features(
            req.tenant_id, req.bucket, req.object_key,
            req.features, req.object_version, caller, trace_id
        )
        audit.record(tool="write_ai_object_features", caller=caller, args=args,
                     result_status="ok", trace_id=trace_id)
        return result
    except Exception as exc:
        audit.record(tool="write_ai_object_features", caller=caller, args=args,
                     result_status="error", trace_id=trace_id)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Tool: get_ai_object_features
# ---------------------------------------------------------------------------

class GetAIFeaturesRequest(BaseModel):
    tenant_id: str
    bucket: str
    object_key: str
    object_version: str = ""


@app.post("/tools/get_ai_object_features")
async def get_ai_object_features(
    req: GetAIFeaturesRequest,
    x_caller_id: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    caller = _caller(x_caller_id)
    trace_id = audit.record(tool="get_ai_object_features", caller=caller,
                            args=req.model_dump(), result_status="pending")
    try:
        result = tool_ai_features.get_ai_object_features(
            req.tenant_id, req.bucket, req.object_key, req.object_version
        )
        audit.record(tool="get_ai_object_features", caller=caller,
                     args=req.model_dump(), result_status="ok", trace_id=trace_id)
        if result is None:
            raise HTTPException(status_code=404, detail="AI features not found")
        return result
    except HTTPException:
        raise
    except Exception as exc:
        audit.record(tool="get_ai_object_features", caller=caller,
                     args=req.model_dump(), result_status="error", trace_id=trace_id)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Tool: get_prefix_stats_daily
# ---------------------------------------------------------------------------

class PrefixStatsRequest(BaseModel):
    tenant_id: str
    bucket: str
    prefix: str
    day: Optional[str] = None


@app.post("/tools/get_prefix_stats_daily")
async def get_prefix_stats_daily(
    req: PrefixStatsRequest,
    x_caller_id: Optional[str] = Header(default=None),
) -> list[dict[str, Any]]:
    caller = _caller(x_caller_id)
    trace_id = audit.record(tool="get_prefix_stats_daily", caller=caller,
                            args=req.model_dump(), result_status="pending")
    try:
        result = tool_ai_features.get_prefix_stats_daily(
            req.tenant_id, req.bucket, req.prefix, req.day
        )
        audit.record(tool="get_prefix_stats_daily", caller=caller,
                     args=req.model_dump(), result_status="ok", trace_id=trace_id)
        return result
    except Exception as exc:
        audit.record(tool="get_prefix_stats_daily", caller=caller,
                     args=req.model_dump(), result_status="error", trace_id=trace_id)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


if __name__ == "__main__":
    uvicorn.run("main:app", host=SERVICE_HOST, port=SERVICE_PORT, reload=False)
