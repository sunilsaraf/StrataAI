"""
Core AI Interceptor logic: signal extraction, event emission, cache reads.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from kafka import KafkaProducer
from kafka.errors import KafkaError
import redis

from config import (
    KAFKA_BOOTSTRAP_SERVERS,
    KAFKA_TOPIC,
    KAFKA_LOCAL_BUFFER_BYTES,
    REDIS_HOST,
    REDIS_PORT,
    REDIS_DB,
)

logger = logging.getLogger(__name__)


def _make_producer() -> KafkaProducer | None:
    """Return a KafkaProducer, or None if Kafka is unavailable."""
    try:
        return KafkaProducer(
            bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            compression_type="snappy",
            max_block_ms=200,       # never block longer than 200 ms
            buffer_memory=KAFKA_LOCAL_BUFFER_BYTES,
            retries=3,
        )
    except Exception as exc:
        logger.warning("Kafka unavailable – events will be dropped: %s", exc)
        return None


def _make_redis() -> redis.Redis | None:
    """Return a Redis client, or None if Redis is unavailable."""
    try:
        client = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            db=REDIS_DB,
            socket_connect_timeout=0.5,
            socket_timeout=0.3,
            decode_responses=True,
        )
        client.ping()
        return client
    except Exception as exc:
        logger.warning("Redis unavailable – prefix cache disabled: %s", exc)
        return None


# Module-level singletons (reconnected lazily on first use)
_producer: KafkaProducer | None = None
_redis: redis.Redis | None = None


def get_producer() -> KafkaProducer | None:
    global _producer
    if _producer is None:
        _producer = _make_producer()
    return _producer


def get_redis() -> redis.Redis | None:
    global _redis
    if _redis is None:
        _redis = _make_redis()
    return _redis


def extract_signals(request_data: dict[str, Any]) -> dict[str, Any]:
    """
    Extract cheap, deterministic signals from raw request data.
    Adds: prefix, request_id (if missing), timestamp.
    """
    key = request_data.get("key", "")
    prefix = "/".join(key.split("/")[:-1]) + "/" if "/" in key else ""

    return {
        "event_version": 1,
        "event_type": request_data.get("event_type", "PutRequested"),
        "ts": datetime.now(timezone.utc).isoformat(),
        "request_id": request_data.get("request_id") or str(uuid.uuid4()),
        "tenant_id": request_data.get("tenant_id", ""),
        "user_id": request_data.get("user_id", ""),
        "bucket": request_data.get("bucket", ""),
        "key": key,
        "object_version": request_data.get("object_version"),
        "etag": request_data.get("etag"),
        "size_bytes": request_data.get("size_bytes"),
        "content_type": request_data.get("content_type", "application/octet-stream"),
        "op_status": request_data.get("op_status", "REQUESTED"),
        "error_code": request_data.get("error_code"),
        "lustre_path": request_data.get("lustre_path"),
        "client": request_data.get("client", {}),
        "authz": request_data.get("authz", {}),
        "hints": {
            "prefix": prefix,
            "kms_encrypted": request_data.get("kms_encrypted", False),
            "tags_present": bool(request_data.get("tags")),
        },
    }


def emit_event(event: dict[str, Any]) -> bool:
    """
    Emit event to Kafka.  Returns True on success, False on failure.
    Failures are best-effort – they MUST NOT block the CRUD path.
    """
    producer = get_producer()
    if producer is None:
        logger.debug("Kafka producer unavailable; dropping event %s", event.get("request_id"))
        return False
    try:
        producer.send(KAFKA_TOPIC, value=event)
        return True
    except KafkaError as exc:
        logger.warning("Failed to emit event: %s", exc)
        return False


def get_prefix_cache(tenant_id: str, bucket: str, prefix: str) -> dict[str, Any] | None:
    """
    Fetch cached AI prefix intelligence from Redis.
    Returns None if unavailable or not found.
    """
    client = get_redis()
    if client is None:
        return None
    cache_key = f"prefix:{tenant_id}:{bucket}:{prefix}"
    try:
        raw = client.get(cache_key)
        return json.loads(raw) if raw else None
    except Exception as exc:
        logger.debug("Redis read failed for key %s: %s", cache_key, exc)
        return None
