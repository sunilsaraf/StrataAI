"""
MCP Server configuration.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# Cassandra
CASSANDRA_HOSTS: list[str] = os.getenv("CASSANDRA_HOSTS", "cassandra").split(",")
CASSANDRA_KEYSPACE_AUTH: str = os.getenv("CASSANDRA_KEYSPACE_AUTH", "strataai")
CASSANDRA_KEYSPACE_AI: str = os.getenv("CASSANDRA_KEYSPACE_AI", "ai_control")
CASSANDRA_PORT: int = int(os.getenv("CASSANDRA_PORT", "9042"))

# IAM service (Java)
IAM_SERVICE_URL: str = os.getenv("IAM_SERVICE_URL", "http://iam-service:8081")

# Lustre
LUSTRE_MOUNT: str = os.getenv("LUSTRE_MOUNT", "/lustre")
SAMPLE_MAX_BYTES: int = int(os.getenv("SAMPLE_MAX_BYTES", str(64 * 1024)))  # 64 KB cap

# Service
SERVICE_HOST: str = os.getenv("MCP_HOST", "0.0.0.0")
SERVICE_PORT: int = int(os.getenv("MCP_PORT", "8090"))

# Audit log file (append-only)
AUDIT_LOG_PATH: str = os.getenv("AUDIT_LOG_PATH", "/var/log/mcp/audit.jsonl")
