"""Tests for MCP tools and Agent Orchestrator."""

from __future__ import annotations

import pytest

from strataai.mcp.orchestrator import (
    AgentOrchestrator,
    OrchestrationRequest,
    StubLlmBackend,
)
from strataai.mcp.tools import McpToolResult, McpTools
from strataai.rag.retriever import CATEGORY_POLICY_KNOWLEDGE, CATEGORY_USAGE_PATTERN, RagRetriever
from strataai.rag.store import Document, InMemoryVectorStore
from strataai.storage.cassandra import BucketStats, InMemoryCassandraBackend, ObjectMetadata
from strataai.storage.iam import (
    IamLayer,
    InMemoryIamBackend,
    PolicyEffect,
    PolicyStatement,
    UserPolicy,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tools() -> tuple[McpTools, InMemoryCassandraBackend, InMemoryIamBackend]:
    cass = InMemoryCassandraBackend()
    iam_backend = InMemoryIamBackend()
    iam = IamLayer(backend=iam_backend)
    tools = McpTools(cassandra=cass, iam=iam)
    return tools, cass, iam_backend


def _make_retriever() -> RagRetriever:
    store = InMemoryVectorStore()
    return RagRetriever(store=store, top_k=2)


# ---------------------------------------------------------------------------
# McpTools
# ---------------------------------------------------------------------------


class TestMcpTools:
    def setup_method(self) -> None:
        self.tools, self.cass, self.iam_backend = _make_tools()

    def test_get_object_metadata_success(self) -> None:
        meta = ObjectMetadata(bucket="bkt", key="data/file.h5", size_bytes=8192, tier="warm")
        self.cass.put_object_metadata(meta)
        result = self.tools.getObjectMetadata("bkt", "data/file.h5")
        assert result.success
        assert result.tool == "getObjectMetadata"
        assert result.data == meta

    def test_get_object_metadata_not_found(self) -> None:
        result = self.tools.getObjectMetadata("no-bucket", "no-key")
        assert not result.success
        assert "not found" in result.error.lower()

    def test_get_bucket_stats_success(self) -> None:
        stats = BucketStats(bucket="proj", object_count=5, total_bytes=5000)
        self.cass.update_bucket_stats(stats)
        result = self.tools.getBucketStats("proj")
        assert result.success
        assert result.tool == "getBucketStats"
        assert result.data == stats

    def test_get_bucket_stats_not_found(self) -> None:
        result = self.tools.getBucketStats("ghost")
        assert not result.success
        assert "not found" in result.error.lower()

    def test_get_user_policy_known_user(self) -> None:
        stmt = PolicyStatement(
            effect=PolicyEffect.ALLOW,
            actions=("s3:GetObject",),
            resources=("*",),
        )
        policy = UserPolicy(user_id="alice", statements=(stmt,))
        self.iam_backend.put_user_policy(policy)
        result = self.tools.getUserPolicy("alice")
        assert result.success
        assert result.tool == "getUserPolicy"
        assert result.data.user_id == "alice"

    def test_get_user_policy_unknown_user_returns_empty(self) -> None:
        result = self.tools.getUserPolicy("unknown-user")
        assert result.success  # empty policy, not an error
        assert result.data.user_id == "unknown-user"
        assert len(result.data.statements) == 0

    def test_mcp_tool_result_is_frozen(self) -> None:
        r = McpToolResult(tool="test", success=True)
        with pytest.raises(Exception):
            r.success = False  # type: ignore[misc]


# ---------------------------------------------------------------------------
# AgentOrchestrator
# ---------------------------------------------------------------------------


class TestAgentOrchestrator:
    def setup_method(self) -> None:
        self.tools, self.cass, self.iam_backend = _make_tools()
        self.retriever = _make_retriever()
        self.llm = StubLlmBackend()
        self.orchestrator = AgentOrchestrator(
            tools=self.tools, retriever=self.retriever, llm=self.llm
        )

    def test_orchestrate_with_all_fields(self) -> None:
        # Seed data
        self.cass.put_object_metadata(
            ObjectMetadata(bucket="bkt", key="file.h5", size_bytes=1024)
        )
        self.cass.update_bucket_stats(BucketStats(bucket="bkt", object_count=1))
        request = OrchestrationRequest(
            user_id="alice",
            bucket="bkt",
            object_key="file.h5",
            query="should I promote file.h5 to hot tier?",
        )
        ctx = self.orchestrator.orchestrate(request)
        # Three tool calls: getObjectMetadata + getBucketStats + getUserPolicy
        assert len(ctx.tool_results) == 3
        assert ctx.llm_response.startswith("[stub-llm]")

    def test_orchestrate_no_bucket_skips_metadata_stats(self) -> None:
        request = OrchestrationRequest(user_id="bob", query="what is the policy?")
        ctx = self.orchestrator.orchestrate(request)
        # Only getUserPolicy should have been called
        tool_names = [r.tool for r in ctx.tool_results]
        assert "getObjectMetadata" not in tool_names
        assert "getBucketStats" not in tool_names
        assert "getUserPolicy" in tool_names

    def test_orchestrate_rag_retrieval_triggered(self) -> None:
        self.retriever.index_document(
            Document(
                text="HPC simulation files accessed hourly",
                doc_id="up1",
                category=CATEGORY_USAGE_PATTERN,
            )
        )
        request = OrchestrationRequest(user_id="alice", query="HPC simulation file access")
        ctx = self.orchestrator.orchestrate(request)
        assert ctx.retrieval_context is not None
        assert len(ctx.retrieval_context.usage_patterns) >= 1

    def test_orchestrate_no_query_skips_rag(self) -> None:
        request = OrchestrationRequest(user_id="alice")
        ctx = self.orchestrator.orchestrate(request)
        assert ctx.retrieval_context is None

    def test_to_prompt_includes_tool_results(self) -> None:
        self.cass.update_bucket_stats(BucketStats(bucket="bkt", object_count=2))
        request = OrchestrationRequest(user_id="alice", bucket="bkt", query="analyse bucket")
        ctx = self.orchestrator.orchestrate(request)
        prompt = ctx.to_prompt()
        assert "getBucketStats" in prompt

    def test_to_prompt_includes_rag_context(self) -> None:
        self.retriever.index_document(
            Document(
                text="s3:GetObject allowed for team",
                doc_id="pk1",
                category=CATEGORY_POLICY_KNOWLEDGE,
            )
        )
        request = OrchestrationRequest(user_id="alice", query="s3 access policy GetObject")
        ctx = self.orchestrator.orchestrate(request)
        prompt = ctx.to_prompt()
        assert "policy_knowledge" in prompt

    def test_stub_llm_returns_context_length(self) -> None:
        request = OrchestrationRequest(user_id="alice", query="any question")
        ctx = self.orchestrator.orchestrate(request)
        assert "chars of context" in ctx.llm_response
