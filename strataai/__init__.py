"""StrataAI – Cognitive Agentic Storage Control Plane.

Strata = storage layers: Lustre connection + tiering intelligence + AI.

Architecture::

    User → AiGateway → AgentOrchestrator (MCP)
                           ↓                ↓
                      McpTools          RagRetriever
                      (Cassandra/IAM)   (Vector DB)
                           ↓                ↓
                        LLM reasoning over both
"""

from strataai.control_plane.agent import StrataAgent
from strataai.gateway.gateway import AiGateway, GatewayRequest, GatewayResponse
from strataai.lustre.connector import LustreConnector
from strataai.mcp.orchestrator import AgentOrchestrator
from strataai.mcp.tools import McpTools
from strataai.rag.retriever import RagRetriever
from strataai.rag.store import InMemoryVectorStore
from strataai.storage.cassandra import InMemoryCassandraBackend
from strataai.storage.iam import IamLayer, InMemoryIamBackend
from strataai.tiering.engine import TieringEngine
from strataai.tiering.tiers import StorageTier

__all__ = [
    "LustreConnector",
    "StorageTier",
    "TieringEngine",
    "StrataAgent",
    "InMemoryCassandraBackend",
    "IamLayer",
    "InMemoryIamBackend",
    "InMemoryVectorStore",
    "RagRetriever",
    "McpTools",
    "AgentOrchestrator",
    "AiGateway",
    "GatewayRequest",
    "GatewayResponse",
]
__version__ = "0.1.0"

