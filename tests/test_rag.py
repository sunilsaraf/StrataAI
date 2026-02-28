"""Tests for the RAG layer: vector store and retriever."""

from __future__ import annotations

from strataai.rag.retriever import (
    CATEGORY_OBJECT_CLASSIFICATION,
    CATEGORY_POLICY_KNOWLEDGE,
    CATEGORY_USAGE_PATTERN,
    RagRetriever,
)
from strataai.rag.store import Document, InMemoryVectorStore

# ---------------------------------------------------------------------------
# Document
# ---------------------------------------------------------------------------


class TestDocument:
    def test_defaults(self) -> None:
        doc = Document(text="hello world")
        assert doc.doc_id == ""
        assert doc.category == ""
        assert doc.metadata == {}


# ---------------------------------------------------------------------------
# InMemoryVectorStore
# ---------------------------------------------------------------------------


class TestInMemoryVectorStore:
    def setup_method(self) -> None:
        self.store = InMemoryVectorStore()

    def test_empty_store_returns_empty(self) -> None:
        results = self.store.search("anything", top_k=5)
        assert results == []

    def test_add_and_search(self) -> None:
        self.store.add(Document(text="hot data access NVMe flash", doc_id="d1"))
        self.store.add(Document(text="cold tape archive backup", doc_id="d2"))
        results = self.store.search("NVMe flash storage", top_k=1)
        assert len(results) == 1
        assert results[0].doc_id == "d1"

    def test_category_filter(self) -> None:
        self.store.add(Document(text="access pattern frequent", category=CATEGORY_USAGE_PATTERN))
        self.store.add(
            Document(text="access pattern classification", category=CATEGORY_OBJECT_CLASSIFICATION)
        )
        results = self.store.search("access pattern", top_k=5, category=CATEGORY_USAGE_PATTERN)
        assert all(d.category == CATEGORY_USAGE_PATTERN for d in results)

    def test_top_k_limits_results(self) -> None:
        for i in range(10):
            self.store.add(Document(text=f"file object bucket storage {i}", doc_id=f"d{i}"))
        results = self.store.search("file object", top_k=3)
        assert len(results) <= 3

    def test_delete_removes_document(self) -> None:
        self.store.add(Document(text="remove me", doc_id="remove"))
        self.store.add(Document(text="keep me here", doc_id="keep"))
        self.store.delete("remove")
        results = self.store.search("remove me", top_k=10)
        assert all(d.doc_id != "remove" for d in results)

    def test_len(self) -> None:
        assert len(self.store) == 0
        self.store.add(Document(text="a"))
        self.store.add(Document(text="b"))
        assert len(self.store) == 2

    def test_empty_query_returns_results(self) -> None:
        self.store.add(Document(text="some text"))
        # Empty query vector → all cosine scores are 0 → returns in insert order
        results = self.store.search("", top_k=5)
        assert len(results) == 1

    def test_cosine_similarity_ordering(self) -> None:
        """Most relevant document should rank first."""
        self.store.add(Document(text="lustre hot NVMe tiering", doc_id="relevant"))
        self.store.add(Document(text="cold tape archive", doc_id="irrelevant"))
        results = self.store.search("lustre hot NVMe", top_k=2)
        assert results[0].doc_id == "relevant"


# ---------------------------------------------------------------------------
# RagRetriever
# ---------------------------------------------------------------------------


class TestRagRetriever:
    def setup_method(self) -> None:
        self.store = InMemoryVectorStore()
        self.retriever = RagRetriever(store=self.store, top_k=2)

    def _seed_store(self) -> None:
        self.retriever.index_many([
            Document(
                text="project alpha accesses output.h5 frequently every hour",
                doc_id="up1",
                category=CATEGORY_USAGE_PATTERN,
            ),
            Document(
                text="simulation results accessed daily batch workflow",
                doc_id="up2",
                category=CATEGORY_USAGE_PATTERN,
            ),
            Document(
                text="HDF5 scientific dataset large file 10GB",
                doc_id="oc1",
                category=CATEGORY_OBJECT_CLASSIFICATION,
            ),
            Document(
                text="small text log files compressed gzip",
                doc_id="oc2",
                category=CATEGORY_OBJECT_CLASSIFICATION,
            ),
            Document(
                text="s3:GetObject allowed for project team members",
                doc_id="pk1",
                category=CATEGORY_POLICY_KNOWLEDGE,
            ),
            Document(
                text="s3:DeleteObject denied for read-only users",
                doc_id="pk2",
                category=CATEGORY_POLICY_KNOWLEDGE,
            ),
        ])

    def test_retrieve_returns_all_categories(self) -> None:
        self._seed_store()
        ctx = self.retriever.retrieve("output.h5 access policy")
        assert isinstance(ctx.usage_patterns, list)
        assert isinstance(ctx.similar_objects, list)
        assert isinstance(ctx.policy_knowledge, list)

    def test_retrieve_usage_patterns(self) -> None:
        self._seed_store()
        docs = self.retriever.retrieve_usage_patterns("frequent access simulation")
        assert all(d.category == CATEGORY_USAGE_PATTERN for d in docs)
        assert len(docs) <= 2

    def test_retrieve_similar_objects(self) -> None:
        self._seed_store()
        docs = self.retriever.retrieve_similar_objects("large HDF5 dataset")
        assert all(d.category == CATEGORY_OBJECT_CLASSIFICATION for d in docs)

    def test_retrieve_policy_knowledge(self) -> None:
        self._seed_store()
        docs = self.retriever.retrieve_policy_knowledge("s3:GetObject permissions")
        assert all(d.category == CATEGORY_POLICY_KNOWLEDGE for d in docs)

    def test_all_documents(self) -> None:
        self._seed_store()
        ctx = self.retriever.retrieve("simulation output access policy")
        total = len(ctx.all_documents())
        assert total == (
            len(ctx.usage_patterns) + len(ctx.similar_objects) + len(ctx.policy_knowledge)
        )

    def test_index_document(self) -> None:
        doc = Document(text="single doc", doc_id="s1", category=CATEGORY_USAGE_PATTERN)
        self.retriever.index_document(doc)
        results = self.retriever.retrieve_usage_patterns("single doc")
        assert any(d.doc_id == "s1" for d in results)

    def test_empty_store_retrieve_returns_empty_lists(self) -> None:
        ctx = self.retriever.retrieve("anything")
        assert ctx.all_documents() == []
