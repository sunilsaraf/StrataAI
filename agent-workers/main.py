"""
Agent Workers – main Kafka consumer loop.

Dispatches events to the appropriate agent based on event_type.
Uses a consumer group so multiple replicas share the load.
"""

from __future__ import annotations

import json
import logging
import signal
import sys
from typing import Any

from kafka import KafkaConsumer
from kafka.errors import KafkaError

from config import KAFKA_BOOTSTRAP_SERVERS, KAFKA_TOPIC, KAFKA_GROUP_ID
from agents import metadata_profiler, hotness_agent

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)

_running = True


def _handle_shutdown(signum: int, frame: Any) -> None:
    global _running
    logger.info("Shutdown signal received; draining consumer…")
    _running = False


signal.signal(signal.SIGTERM, _handle_shutdown)
signal.signal(signal.SIGINT, _handle_shutdown)


def _make_consumer() -> KafkaConsumer:
    return KafkaConsumer(
        KAFKA_TOPIC,
        bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
        group_id=KAFKA_GROUP_ID,
        value_deserializer=lambda v: json.loads(v.decode("utf-8")),
        auto_offset_reset="earliest",
        enable_auto_commit=True,
        max_poll_interval_ms=300_000,
    )


def _dispatch(event: dict[str, Any]) -> None:
    event_type = event.get("event_type", "")
    try:
        if event_type == "PutCommitted":
            metadata_profiler.process(event)
        elif event_type in ("Get", "List"):
            hotness_agent.process(event)
        else:
            logger.debug("No agent registered for event_type=%s; skipping", event_type)
    except Exception as exc:
        logger.exception("Agent dispatch error for event_type=%s: %s", event_type, exc)


def run() -> None:
    logger.info("Starting agent worker; topic=%s group=%s", KAFKA_TOPIC, KAFKA_GROUP_ID)
    consumer = _make_consumer()
    try:
        while _running:
            records = consumer.poll(timeout_ms=1000)
            for _tp, messages in records.items():
                for msg in messages:
                    _dispatch(msg.value)
    except KafkaError as exc:
        logger.error("Kafka error: %s", exc)
        sys.exit(1)
    finally:
        consumer.close()
        logger.info("Consumer closed.")


if __name__ == "__main__":
    run()
