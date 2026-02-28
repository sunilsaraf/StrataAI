"""Tests for the AI Gateway."""

from __future__ import annotations

from strataai.gateway.gateway import AiGateway, GatewayRequest, GatewayResponse
from strataai.mcp.orchestrator import AgentOrchestrator, LlmBackend, StubLlmBackend
from strataai.mcp.tools import McpTools
from strataai.rag.retriever import CATEGORY_USAGE_PATTERN, RagRetriever
from strataai.rag.store import Document, InMemoryVectorStore
from strataai.storage.cassandra import BucketStats, InMemoryCassandraBackend, ObjectMetadata
from strataai.storage.iam import IamLayer, InMemoryIamBackend

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_gateway(llm: LlmBackend | None = None) -> tuple[AiGateway, InMemoryCassandraBackend]:
    cass = InMemoryCassandraBackend()
    iam = IamLayer(backend=InMemoryIamBackend())
    store = InMemoryVectorStore()
    retriever = RagRetriever(store=store, top_k=2)
    tools = McpTools(cassandra=cass, iam=iam)
    orchestrator = AgentOrchestrator(
        tools=tools, retriever=retriever, llm=llm or StubLlmBackend()
    )
    gateway = AiGateway(orchestrator=orchestrator)
    return gateway, cass


# ---------------------------------------------------------------------------
# GatewayRequest / GatewayResponse
# ---------------------------------------------------------------------------


class TestGatewayRequest:
    def test_frozen(self) -> None:
        req = GatewayRequest(user_id="alice", query="test")
        import pytest

        with pytest.raises(Exception):
            req.user_id = "bob"  # type: ignore[misc]


class TestGatewayResponse:
    def test_defaults(self) -> None:
        resp = GatewayResponse(user_id="alice", query="q", answer="a")
        assert resp.success
        assert resp.error == ""
        assert resp.tool_results_count == 0
        assert resp.retrieved_docs_count == 0


# ---------------------------------------------------------------------------
# AiGateway
# ---------------------------------------------------------------------------


class TestAiGateway:
    def test_process_basic_query(self) -> None:
        gateway, _ = _make_gateway()
        req = GatewayRequest(user_id="alice", query="what is my storage usage?")
        resp = gateway.process(req)
        assert resp.success
        assert resp.user_id == "alice"
        assert resp.query == "what is my storage usage?"
        assert resp.answer != ""

    def test_process_with_bucket_and_object(self) -> None:
        gateway, cass = _make_gateway()
        cass.put_object_metadata(ObjectMetadata(bucket="bkt", key="f.h5", size_bytes=4096))
        cass.update_bucket_stats(BucketStats(bucket="bkt", object_count=1, total_bytes=4096))
        req = GatewayRequest(
            user_id="bob", query="analyse f.h5", bucket="bkt", object_key="f.h5"
        )
        resp = gateway.process(req)
        assert resp.success
        # getObjectMetadata + getBucketStats + getUserPolicy = 3 tool calls
        assert resp.tool_results_count == 3

    def test_process_no_bucket_only_user_policy(self) -> None:
        gateway, _ = _make_gateway()
        req = GatewayRequest(user_id="carol", query="what can I do?")
        resp = gateway.process(req)
        assert resp.success
        assert resp.tool_results_count == 1  # only getUserPolicy

    def test_retrieved_docs_counted(self) -> None:
        cass = InMemoryCassandraBackend()
        iam = IamLayer(backend=InMemoryIamBackend())
        store = InMemoryVectorStore()
        store.add(Document(text="HPC batch job access pattern", category=CATEGORY_USAGE_PATTERN))
        store.add(Document(text="sequential read access NVMe", category=CATEGORY_USAGE_PATTERN))
        retriever = RagRetriever(store=store, top_k=2)
        tools = McpTools(cassandra=cass, iam=iam)
        orchestrator = AgentOrchestrator(
            tools=tools, retriever=retriever, llm=StubLlmBackend()
        )
        gateway = AiGateway(orchestrator=orchestrator)

        req = GatewayRequest(user_id="alice", query="HPC batch access NVMe")
        resp = gateway.process(req)
        assert resp.retrieved_docs_count >= 1

    def test_process_error_returns_failure_response(self) -> None:
        class BrokenOrchestrator:
            def orchestrate(self, request):  # noqa: ANN001
                raise RuntimeError("simulated failure")

        gateway = AiGateway(orchestrator=BrokenOrchestrator())  # type: ignore[arg-type]
        req = GatewayRequest(user_id="alice", query="fail me")
        resp = gateway.process(req)
        assert not resp.success
        assert "simulated failure" in resp.error
        assert resp.answer == ""

    def test_response_echoes_user_and_query(self) -> None:
        gateway, _ = _make_gateway()
        req = GatewayRequest(user_id="dave", query="my unique query string 12345")
        resp = gateway.process(req)
        assert resp.user_id == "dave"
        assert resp.query == "my unique query string 12345"

    def test_custom_llm_backend(self) -> None:
        class CapitalizeLlm:
            def reason(self, prompt: str) -> str:
                return prompt.upper()

        gateway, _ = _make_gateway(llm=CapitalizeLlm())
        req = GatewayRequest(user_id="alice", query="hello world")
        resp = gateway.process(req)
        assert resp.answer == resp.answer.upper()
