"""
Tests for Agent Workers: metadata_profiler and hotness_agent.
"""

import sys
import os
from unittest.mock import patch, MagicMock

_AGENT_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "agent-workers"))
for _name in ("config", "mcp_client"):
    sys.modules.pop(_name, None)
if _AGENT_DIR not in sys.path:
    sys.path.insert(0, _AGENT_DIR)
else:
    sys.path.remove(_AGENT_DIR)
    sys.path.insert(0, _AGENT_DIR)


def _raise(exc: Exception):
    """Helper: raise *exc* inside a lambda-compatible callable."""
    raise exc


# ---------------------------------------------------------------------------
# Metadata Profiler Agent
# ---------------------------------------------------------------------------

from agents import metadata_profiler


def test_metadata_profiler_guess_category_parquet():
    cat = metadata_profiler._guess_category("analytics/data/run.parquet", "application/octet-stream")
    assert cat == "dataset"


def test_metadata_profiler_guess_category_log():
    cat = metadata_profiler._guess_category("app/logs/2026-02.log", "text/plain")
    assert cat == "logs"


def test_metadata_profiler_guess_category_video():
    cat = metadata_profiler._guess_category("media/clip.mp4", "video/mp4")
    assert cat == "media"


def test_metadata_profiler_guess_category_unknown():
    cat = metadata_profiler._guess_category("data/blob.bin", "application/octet-stream")
    assert cat == "unknown"


def test_metadata_profiler_tiering_backup():
    tier, reason = metadata_profiler._tiering_recommendation(100, "backup")
    assert tier == "cold"


def test_metadata_profiler_tiering_large_object():
    size = 15 * 1024 * 1024 * 1024  # 15 GB
    tier, reason = metadata_profiler._tiering_recommendation(size, "dataset")
    assert tier == "warm"


def test_metadata_profiler_process_calls_mcp(monkeypatch):
    mock_meta = {"content_type": "application/json", "size_bytes": 1024}
    mock_layout = {"stripe_count": 4, "stripe_size": 1048576, "osts": ["0", "1"]}
    write_calls = []

    monkeypatch.setattr(
        "agents.metadata_profiler.mcp_client.get_object_metadata",
        lambda *a, **kw: mock_meta
    )
    monkeypatch.setattr(
        "agents.metadata_profiler.mcp_client.lustre_layout",
        lambda *a, **kw: mock_layout
    )
    monkeypatch.setattr(
        "agents.metadata_profiler.mcp_client.write_ai_object_features",
        lambda *a, **kw: write_calls.append(a) or {"status": "ok"}
    )

    event = {
        "event_type": "PutCommitted",
        "tenant_id": "t1",
        "bucket": "bkt",
        "key": "data/run.parquet",
        "object_version": "v1",
        "lustre_path": "/lustre/t1/bkt/data/run.parquet",
    }
    result = metadata_profiler.process(event)

    assert result is True
    assert len(write_calls) == 1
    features = write_calls[0][3]  # positional arg: features dict
    assert features["category"] == "dataset"
    assert "category:dataset" in features["semantic_tags"]


def test_metadata_profiler_process_handles_mcp_write_failure(monkeypatch):
    monkeypatch.setattr(
        "agents.metadata_profiler.mcp_client.get_object_metadata",
        lambda *a, **kw: None
    )
    monkeypatch.setattr(
        "agents.metadata_profiler.mcp_client.lustre_layout",
        lambda *a, **kw: {}
    )
    monkeypatch.setattr(
        "agents.metadata_profiler.mcp_client.write_ai_object_features",
        lambda *a, **kw: _raise(Exception("Cassandra down"))
    )

    event = {"event_type": "PutCommitted", "tenant_id": "t1",
             "bucket": "b", "key": "f.log", "object_version": ""}
    result = metadata_profiler.process(event)
    assert result is False


# ---------------------------------------------------------------------------
# Hotness Agent
# ---------------------------------------------------------------------------

from agents import hotness_agent


def test_metadata_profiler_updates_prefix_stats(monkeypatch):
    """Metadata profiler must call write_prefix_stats_daily after profiling."""
    monkeypatch.setattr(
        "agents.metadata_profiler.mcp_client.get_object_metadata",
        lambda *a, **kw: {"content_type": "application/octet-stream", "size_bytes": 2048}
    )
    monkeypatch.setattr(
        "agents.metadata_profiler.mcp_client.lustre_layout",
        lambda *a, **kw: {"stripe_count": 2, "stripe_size": 1048576, "osts": ["0"]}
    )
    monkeypatch.setattr(
        "agents.metadata_profiler.mcp_client.write_ai_object_features",
        lambda *a, **kw: {"status": "ok"}
    )

    prefix_calls = []
    monkeypatch.setattr(
        "agents.metadata_profiler.mcp_client.write_prefix_stats_daily",
        lambda *a, **kw: prefix_calls.append(a) or {"status": "ok"}
    )

    event = {
        "event_type": "PutCommitted",
        "tenant_id": "t1",
        "bucket": "bkt",
        "key": "logs/2026/run.log",
        "object_version": "",
        "lustre_path": "/lustre/t1/bkt/logs/2026/run.log",
    }
    result = metadata_profiler.process(event)

    assert result is True
    assert len(prefix_calls) == 1
    # positional args: (tenant_id, bucket, prefix, day, stats)
    _, _, prefix_arg, _, stats_arg = prefix_calls[0]
    assert prefix_arg == "logs/2026/"
    assert stats_arg["put_count"] == 1
    assert stats_arg["dominant_category"] == "logs"


def test_metadata_profiler_prefix_stats_failure_is_nonfatal(monkeypatch):
    """A failure in write_prefix_stats_daily must not cause process() to return False."""
    monkeypatch.setattr(
        "agents.metadata_profiler.mcp_client.get_object_metadata",
        lambda *a, **kw: None
    )
    monkeypatch.setattr(
        "agents.metadata_profiler.mcp_client.lustre_layout",
        lambda *a, **kw: {}
    )
    monkeypatch.setattr(
        "agents.metadata_profiler.mcp_client.write_ai_object_features",
        lambda *a, **kw: {"status": "ok"}
    )
    monkeypatch.setattr(
        "agents.metadata_profiler.mcp_client.write_prefix_stats_daily",
        lambda *a, **kw: _raise(Exception("Cassandra timeout"))
    )

    event = {"event_type": "PutCommitted", "tenant_id": "t1",
             "bucket": "b", "key": "path/file.parquet", "object_version": ""}
    result = metadata_profiler.process(event)
    # prefix stats failure is non-fatal; object features were written successfully
    assert result is True


# ---------------------------------------------------------------------------
# Hotness Agent – prefix stats
# ---------------------------------------------------------------------------

def test_hotness_agent_updates_prefix_stats(monkeypatch):
    """Hotness agent must call write_prefix_stats_daily after updating object hotness."""
    monkeypatch.setattr(
        "agents.hotness_agent.mcp_client.get_ai_object_features",
        lambda *a, **kw: {"hotness_score": 3.0}
    )
    monkeypatch.setattr(
        "agents.hotness_agent.mcp_client.write_ai_object_features",
        lambda *a, **kw: {"status": "ok"}
    )

    prefix_calls = []
    monkeypatch.setattr(
        "agents.hotness_agent.mcp_client.write_prefix_stats_daily",
        lambda *a, **kw: prefix_calls.append(a) or {"status": "ok"}
    )

    event = {
        "event_type": "Get",
        "tenant_id": "t2",
        "bucket": "data",
        "key": "reports/2026/q1.parquet",
        "object_version": "",
    }
    result = hotness_agent.process(event)

    assert result is True
    assert len(prefix_calls) == 1
    _, _, prefix_arg, _, stats_arg = prefix_calls[0]
    assert prefix_arg == "reports/2026/"
    assert stats_arg["get_count"] == 1
    assert "hotness_score" in stats_arg


def test_hotness_agent_prefix_stats_failure_is_nonfatal(monkeypatch):
    """A failure in write_prefix_stats_daily must not prevent the hotness update."""
    monkeypatch.setattr(
        "agents.hotness_agent.mcp_client.get_ai_object_features",
        lambda *a, **kw: None
    )
    monkeypatch.setattr(
        "agents.hotness_agent.mcp_client.write_ai_object_features",
        lambda *a, **kw: {"status": "ok"}
    )
    monkeypatch.setattr(
        "agents.hotness_agent.mcp_client.write_prefix_stats_daily",
        lambda *a, **kw: _raise(Exception("Redis down"))
    )

    event = {"event_type": "Get", "tenant_id": "t1", "bucket": "b",
             "key": "dir/obj.bin", "object_version": ""}
    result = hotness_agent.process(event)
    assert result is True
    score = hotness_agent._decayed_score(None, 0.9)
    assert score == 1.0


def test_hotness_agent_decayed_score_accumulates():
    score = 0.0
    for _ in range(10):
        score = hotness_agent._decayed_score(score, 0.9)
    # Should converge toward 10 (geometric series limit = 1/(1-0.9) = 10)
    assert 5.0 < score < 10.0


def test_hotness_agent_skips_non_get_events(monkeypatch):
    called = []
    monkeypatch.setattr(
        "agents.hotness_agent.mcp_client.get_ai_object_features",
        lambda *a, **kw: called.append(1) or None
    )
    result = hotness_agent.process({"event_type": "PutCommitted", "tenant_id": "t1",
                                     "bucket": "b", "key": "k"})
    assert result is True
    assert len(called) == 0  # not called for non-GET events


def test_hotness_agent_updates_score_on_get(monkeypatch):
    existing = {"hotness_score": 5.0}
    writes = []

    monkeypatch.setattr(
        "agents.hotness_agent.mcp_client.get_ai_object_features",
        lambda *a, **kw: existing
    )
    monkeypatch.setattr(
        "agents.hotness_agent.mcp_client.write_ai_object_features",
        lambda *a, **kw: writes.append(a) or {"status": "ok"}
    )

    event = {"event_type": "Get", "tenant_id": "t1", "bucket": "b",
             "key": "k", "object_version": ""}
    result = hotness_agent.process(event)

    assert result is True
    assert len(writes) == 1
    features = writes[0][3]
    assert features["hotness_score"] == round(5.0 * 0.9 + 1.0, 4)
