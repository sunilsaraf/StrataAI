"""AI Gateway – single front-door for user requests.

Routes incoming :class:`GatewayRequest` objects through the
:class:`~strataai.mcp.orchestrator.AgentOrchestrator` and returns a
structured :class:`GatewayResponse` to the caller.

The gateway is the topmost layer in the StrataAI architecture::

    ┌──────────────┐
    │     User     │
    └──────┬───────┘
           ↓
    ┌──────────────┐
    │  AI Gateway  │   ← this module
    └──────┬───────┘
           ↓
    ┌──────────────────────────┐
    │ Agent Orchestrator (MCP) │
    └─────────┬──────────┬─────┘
              ↓          ↓
        Tool Calls    RAG Retrieval
        (Cassandra/   (Vector DB)
         IAM Layer)
              ↓          ↓
           LLM reasoning over both
"""

from __future__ import annotations

from dataclasses import dataclass

from strataai.mcp.orchestrator import AgentOrchestrator, OrchestrationRequest


@dataclass(frozen=True)
class GatewayRequest:
    """A request arriving at the AI Gateway from a user.

    Attributes
    ----------
    user_id:
        Identity of the requesting user.
    query:
        Free-text question or intent (used for RAG retrieval and LLM reasoning).
    bucket:
        Optional bucket name to scope the request.
    object_key:
        Optional object key within *bucket*.
    """

    user_id: str
    query: str
    bucket: str = ""
    object_key: str = ""


@dataclass(frozen=True)
class GatewayResponse:
    """The AI Gateway's response to a :class:`GatewayRequest`.

    Attributes
    ----------
    user_id:
        Echo of the requesting user's ID.
    query:
        Echo of the original query.
    answer:
        The LLM's reasoning output.
    tool_results_count:
        Number of MCP tool calls that were executed.
    retrieved_docs_count:
        Total number of RAG documents that were retrieved.
    success:
        ``False`` when an unhandled error occurred.
    error:
        Human-readable error description when ``success`` is ``False``.
    """

    user_id: str
    query: str
    answer: str
    tool_results_count: int = 0
    retrieved_docs_count: int = 0
    success: bool = True
    error: str = ""


@dataclass
class AiGateway:
    """Routes user requests through the full StrataAI cognitive pipeline.

    Parameters
    ----------
    orchestrator:
        The :class:`~strataai.mcp.orchestrator.AgentOrchestrator` that
        performs tool calls, RAG retrieval and LLM reasoning.
    """

    orchestrator: AgentOrchestrator

    def process(self, request: GatewayRequest) -> GatewayResponse:
        """Process a user request end-to-end.

        Parameters
        ----------
        request:
            Incoming user request.

        Returns
        -------
        GatewayResponse
            The final response including the LLM answer and telemetry
            counts for tool calls and retrieved documents.
        """
        try:
            orch_req = OrchestrationRequest(
                user_id=request.user_id,
                bucket=request.bucket,
                object_key=request.object_key,
                query=request.query,
            )
            ctx = self.orchestrator.orchestrate(orch_req)
            retrieved_count = (
                len(ctx.retrieval_context.all_documents()) if ctx.retrieval_context else 0
            )
            return GatewayResponse(
                user_id=request.user_id,
                query=request.query,
                answer=ctx.llm_response,
                tool_results_count=len(ctx.tool_results),
                retrieved_docs_count=retrieved_count,
            )
        except Exception as exc:  # noqa: BLE001
            return GatewayResponse(
                user_id=request.user_id,
                query=request.query,
                answer="",
                success=False,
                error=str(exc),
            )
