"""Agent Orchestrator (MCP) – combines tool calls with RAG retrieval.

Implements the full pipeline described in the architecture diagram::

    User → AI Gateway → Agent Orchestrator (MCP)
                            ↓                ↓
                       Tool Calls       RAG Retrieval
                       (Cassandra/IAM)  (Vector DB)
                            ↓                ↓
                         LLM reasoning over both

The :class:`AgentOrchestrator` performs three steps:

1. **MCP tool calls** – :func:`getObjectMetadata`, :func:`getBucketStats`,
   :func:`getUserPolicy` via :class:`~strataai.mcp.tools.McpTools`.
2. **RAG retrieval** – historical usage patterns, similar object
   classifications and policy knowledge via
   :class:`~strataai.rag.retriever.RagRetriever`.
3. **LLM reasoning** – passes the combined context to an
   :class:`LlmBackend` for final reasoning.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from strataai.mcp.tools import McpToolResult, McpTools
from strataai.rag.retriever import RagRetriever, RetrievalContext


@dataclass
class OrchestrationRequest:
    """Describes what the orchestrator should look up.

    Attributes
    ----------
    user_id:
        The requesting user (used for :func:`getUserPolicy` and IAM checks).
    bucket:
        Target bucket name (used for :func:`getBucketStats`).
    object_key:
        Object key within *bucket* (used for :func:`getObjectMetadata`).
    query:
        Free-text query for RAG retrieval and LLM reasoning.
    """

    user_id: str
    bucket: str = ""
    object_key: str = ""
    query: str = ""


@dataclass
class OrchestrationContext:
    """All information gathered for a single orchestration cycle.

    Holds the MCP tool results, RAG-retrieved documents, and the final
    LLM response.  Exposes :meth:`to_prompt` to build the LLM input.
    """

    request: OrchestrationRequest
    tool_results: list[McpToolResult] = field(default_factory=list)
    retrieval_context: RetrievalContext | None = None
    llm_response: str = ""

    def to_prompt(self) -> str:
        """Format all gathered context as a single LLM prompt string."""
        parts: list[str] = []
        if self.request.query:
            parts.append(f"Query: {self.request.query}\n")

        parts.append("=== Tool Call Results ===")
        for result in self.tool_results:
            if result.success:
                parts.append(f"[{result.tool}] {result.data}")
            else:
                parts.append(f"[{result.tool}] ERROR: {result.error}")

        if self.retrieval_context:
            parts.append("\n=== Retrieved Context ===")
            for doc in self.retrieval_context.usage_patterns:
                parts.append(f"[usage_pattern] {doc.text}")
            for doc in self.retrieval_context.similar_objects:
                parts.append(f"[object_classification] {doc.text}")
            for doc in self.retrieval_context.policy_knowledge:
                parts.append(f"[policy_knowledge] {doc.text}")

        return "\n".join(parts)


@runtime_checkable
class LlmBackend(Protocol):
    """Protocol for LLM inference backends.

    Production implementations would call an OpenAI-compatible API or a
    local model.  :class:`StubLlmBackend` is used in tests.
    """

    def reason(self, prompt: str) -> str: ...


class StubLlmBackend:
    """Stub LLM backend that summarises its prompt length (for tests)."""

    def reason(self, prompt: str) -> str:
        return f"[stub-llm] Received {len(prompt)} chars of context."


@dataclass
class AgentOrchestrator:
    """MCP Agent Orchestrator.

    Calls MCP tools, runs RAG retrieval and passes the combined context
    to an LLM backend for final reasoning.

    Parameters
    ----------
    tools:
        :class:`~strataai.mcp.tools.McpTools` instance.
    retriever:
        :class:`~strataai.rag.retriever.RagRetriever` instance.
    llm:
        LLM backend.  Defaults to :class:`StubLlmBackend`.
    """

    tools: McpTools
    retriever: RagRetriever
    llm: LlmBackend = field(default_factory=StubLlmBackend)

    def orchestrate(self, request: OrchestrationRequest) -> OrchestrationContext:
        """Execute one full tool-call → RAG → LLM reasoning cycle.

        Parameters
        ----------
        request:
            Describes what to look up and reason about.

        Returns
        -------
        OrchestrationContext
            All gathered tool results, retrieved documents, and the LLM
            response.
        """
        ctx = OrchestrationContext(request=request)

        # Step 1 – MCP tool calls
        if request.bucket and request.object_key:
            ctx.tool_results.append(
                self.tools.getObjectMetadata(request.bucket, request.object_key)
            )
        if request.bucket:
            ctx.tool_results.append(self.tools.getBucketStats(request.bucket))
        if request.user_id:
            ctx.tool_results.append(self.tools.getUserPolicy(request.user_id))

        # Step 2 – RAG retrieval
        if request.query:
            ctx.retrieval_context = self.retriever.retrieve(request.query)

        # Step 3 – LLM reasoning over both
        prompt = ctx.to_prompt()
        ctx.llm_response = self.llm.reason(prompt)

        return ctx
