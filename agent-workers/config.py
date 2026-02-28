"""
Agent Workers configuration.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# Kafka
KAFKA_BOOTSTRAP_SERVERS: str = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
KAFKA_TOPIC: str = os.getenv("KAFKA_TOPIC", "ai-control-events")
KAFKA_GROUP_ID: str = os.getenv("KAFKA_GROUP_ID", "ai-agent-workers")

# MCP Server
MCP_SERVER_URL: str = os.getenv("MCP_SERVER_URL", "http://mcp-server:8090")

# Agent identity (written to ai features as provenance)
AGENT_VERSION: str = os.getenv("AGENT_VERSION", "1.0.0")
