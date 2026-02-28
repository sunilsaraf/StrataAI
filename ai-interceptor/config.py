"""
AI Interceptor – synchronous observation layer.

Runs inline on every request (as ASGI middleware or standalone FastAPI service).
Responsibilities:
  - Extract cheap signals (tenant, bucket, key, size, content-type, …)
  - Emit a compact event to Kafka (non-blocking, best-effort)
  - Read cached prefix/bucket intelligence from Redis (hot read only)
  - Attach trace headers to downstream requests
  - NEVER call an LLM; NEVER block the CRUD path
"""

import os
from dotenv import load_dotenv

load_dotenv()

# Kafka
KAFKA_BOOTSTRAP_SERVERS: str = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
KAFKA_TOPIC: str = os.getenv("KAFKA_TOPIC", "ai-control-events")

# Redis (feature cache – optional; graceful degradation if unavailable)
REDIS_HOST: str = os.getenv("REDIS_HOST", "redis")
REDIS_PORT: int = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB: int = int(os.getenv("REDIS_DB", "0"))

# Service
SERVICE_HOST: str = os.getenv("SERVICE_HOST", "0.0.0.0")
SERVICE_PORT: int = int(os.getenv("SERVICE_PORT", "8080"))

# Max bytes Kafka will buffer locally before dropping (prevents OOM)
KAFKA_LOCAL_BUFFER_BYTES: int = int(os.getenv("KAFKA_LOCAL_BUFFER_BYTES", str(64 * 1024 * 1024)))
