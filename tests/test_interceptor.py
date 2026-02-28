"""
Tests for AI Interceptor: signal extraction, event emission, prefix cache.
"""

import sys
import os
import json
import uuid
from unittest.mock import MagicMock, patch

# Ensure the correct service directory is first on the path.
# Remove stale entries from other services to avoid config name conflicts.
_INTERCEPTOR_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "ai-interceptor"))
for _name in ("config", "interceptor"):
    sys.modules.pop(_name, None)
if _INTERCEPTOR_DIR not in sys.path:
    sys.path.insert(0, _INTERCEPTOR_DIR)
else:
    sys.path.remove(_INTERCEPTOR_DIR)
    sys.path.insert(0, _INTERCEPTOR_DIR)

import interceptor


# ---------------------------------------------------------------------------
# extract_signals
# ---------------------------------------------------------------------------

def test_extract_signals_basic():
    req = {
        "event_type": "PutRequested",
        "tenant_id": "t1",
        "user_id": "u1",
        "bucket": "my-bucket",
        "key": "path/to/object.parquet",
        "size_bytes": 1024,
        "content_type": "application/octet-stream",
        "op_status": "REQUESTED",
    }
    evt = interceptor.extract_signals(req)

    assert evt["event_version"] == 1
    assert evt["tenant_id"] == "t1"
    assert evt["bucket"] == "my-bucket"
    assert evt["key"] == "path/to/object.parquet"
    assert evt["hints"]["prefix"] == "path/to/"
    assert evt["ts"]  # timestamp present


def test_extract_signals_generates_request_id():
    req = {"tenant_id": "t1", "bucket": "b", "key": "k"}
    evt = interceptor.extract_signals(req)
    # Should auto-generate a UUID
    assert len(evt["request_id"]) == 36  # UUID4 length


def test_extract_signals_preserves_request_id():
    rid = str(uuid.uuid4())
    req = {"tenant_id": "t1", "bucket": "b", "key": "k", "request_id": rid}
    evt = interceptor.extract_signals(req)
    assert evt["request_id"] == rid


def test_extract_signals_top_level_key():
    """Key with no path separator should yield empty prefix."""
    req = {"tenant_id": "t1", "bucket": "b", "key": "toplevel.json"}
    evt = interceptor.extract_signals(req)
    assert evt["hints"]["prefix"] == ""


def test_extract_signals_tags_present_flag():
    req = {"tenant_id": "t1", "bucket": "b", "key": "k", "tags": {"env": "prod"}}
    evt = interceptor.extract_signals(req)
    assert evt["hints"]["tags_present"] is True


# ---------------------------------------------------------------------------
# emit_event
# ---------------------------------------------------------------------------

def test_emit_event_success():
    mock_producer = MagicMock()
    mock_producer.send.return_value = None

    with patch.object(interceptor, "get_producer", return_value=mock_producer):
        result = interceptor.emit_event({"request_id": "abc", "event_type": "PutRequested"})

    assert result is True
    mock_producer.send.assert_called_once()


def test_emit_event_no_producer():
    with patch.object(interceptor, "get_producer", return_value=None):
        result = interceptor.emit_event({"event_type": "Get"})
    assert result is False


def test_emit_event_kafka_error():
    from kafka.errors import KafkaError
    mock_producer = MagicMock()
    mock_producer.send.side_effect = KafkaError("broker unavailable")

    with patch.object(interceptor, "get_producer", return_value=mock_producer):
        result = interceptor.emit_event({"event_type": "PutRequested"})

    assert result is False


# ---------------------------------------------------------------------------
# get_prefix_cache
# ---------------------------------------------------------------------------

def test_get_prefix_cache_hit():
    mock_redis = MagicMock()
    payload = json.dumps({"dominant_category": "dataset", "hotness_score": 5.2})
    mock_redis.get.return_value = payload

    with patch.object(interceptor, "get_redis", return_value=mock_redis):
        result = interceptor.get_prefix_cache("t1", "bucket", "prefix/")

    assert result == {"dominant_category": "dataset", "hotness_score": 5.2}


def test_get_prefix_cache_miss():
    mock_redis = MagicMock()
    mock_redis.get.return_value = None

    with patch.object(interceptor, "get_redis", return_value=mock_redis):
        result = interceptor.get_prefix_cache("t1", "bucket", "prefix/")

    assert result is None


def test_get_prefix_cache_no_redis():
    with patch.object(interceptor, "get_redis", return_value=None):
        result = interceptor.get_prefix_cache("t1", "bucket", "prefix/")
    assert result is None


def test_get_prefix_cache_redis_error():
    mock_redis = MagicMock()
    mock_redis.get.side_effect = Exception("connection reset")

    with patch.object(interceptor, "get_redis", return_value=mock_redis):
        result = interceptor.get_prefix_cache("t1", "bucket", "prefix/")

    assert result is None
