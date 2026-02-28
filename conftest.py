"""
conftest.py – pytest configuration for StrataAI tests.

Each test module that imports from a specific service directory needs
sys.path set up correctly. We avoid conflicts by clearing stale module
caches when switching between service paths.
"""
import sys
import os

REPO_ROOT = os.path.dirname(__file__)

# Paths to each service
INTERCEPTOR_PATH = os.path.join(REPO_ROOT, "ai-interceptor")
MCP_SERVER_PATH = os.path.join(REPO_ROOT, "mcp-server")
AGENT_WORKERS_PATH = os.path.join(REPO_ROOT, "agent-workers")

# Modules that exist in multiple service directories (name conflicts)
_SHARED_NAMES = {"config"}
