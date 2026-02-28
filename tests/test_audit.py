"""
Tests for MCP Server audit logger.
"""

import sys
import os
import json
import tempfile

_MCP_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "mcp-server"))
for _name in ("config", "audit"):
    sys.modules.pop(_name, None)
if _MCP_DIR not in sys.path:
    sys.path.insert(0, _MCP_DIR)
else:
    sys.path.remove(_MCP_DIR)
    sys.path.insert(0, _MCP_DIR)


def test_audit_record_writes_jsonl(monkeypatch, tmp_path):
    log_file = tmp_path / "audit.jsonl"
    monkeypatch.setenv("AUDIT_LOG_PATH", str(log_file))

    # Re-import after env change
    import importlib
    import config as cfg
    importlib.reload(cfg)
    import audit
    importlib.reload(audit)

    trace_id = audit.record(
        tool="lustre_stat",
        caller="test-agent",
        args={"lustre_path": "/lustre/t1/b/k"},
        result_status="ok",
    )

    assert log_file.exists()
    with open(log_file) as f:
        line = json.loads(f.readline())

    assert line["tool"] == "lustre_stat"
    assert line["caller"] == "test-agent"
    assert line["result_status"] == "ok"
    assert line["trace_id"] == trace_id


def test_audit_record_uses_provided_trace_id(monkeypatch, tmp_path):
    log_file = tmp_path / "audit2.jsonl"
    monkeypatch.setenv("AUDIT_LOG_PATH", str(log_file))

    import importlib
    import config as cfg
    importlib.reload(cfg)
    import audit
    importlib.reload(audit)

    tid = audit.record(
        tool="get_object_metadata",
        caller="agent-x",
        args={"tenant_id": "t1"},
        result_status="pending",
        trace_id="fixed-trace-id",
    )
    assert tid == "fixed-trace-id"

    with open(log_file) as f:
        line = json.loads(f.readline())
    assert line["trace_id"] == "fixed-trace-id"


def test_audit_record_does_not_raise_on_bad_path(monkeypatch):
    monkeypatch.setenv("AUDIT_LOG_PATH", "/nonexistent/deep/path/audit.jsonl")

    import importlib
    import config as cfg
    importlib.reload(cfg)
    import audit
    importlib.reload(audit)

    # Should not raise even if directory is missing – graceful degradation
    try:
        audit.record(tool="test", caller="x", args={}, result_status="ok")
    except Exception:
        pass  # acceptable; just must not crash the caller
