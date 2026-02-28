"""RAG (Retrieval-Augmented Generation) retriever.

Retrieves contextually relevant documents from a :class:`VectorStore` to
augment LLM prompts with:

* **Historical usage patterns** – how objects in a bucket have been
  accessed over time.
* **Similar object classifications** – objects with comparable size,
  type, or access frequency.
* **Policy knowledge** – documentation and examples of IAM rules.

Documents are partitioned into these three categories so that each
retrieval path can be fine-tuned independently.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from strataai.rag.store import Document, VectorStore

# Canonical category tags – used when indexing and searching documents.
CATEGORY_USAGE_PATTERN = "usage_pattern"
CATEGORY_OBJECT_CLASSIFICATION = "object_classification"
CATEGORY_POLICY_KNOWLEDGE = "policy_knowledge"


@dataclass
class RetrievalContext:
    """Bundle of documents retrieved by the RAG system for a single query.

    Attributes
    ----------
    query:
        The original free-text query that triggered retrieval.
    usage_patterns:
        Documents in the ``usage_pattern`` category.
    similar_objects:
        Documents in the ``object_classification`` category.
    policy_knowledge:
        Documents in the ``policy_knowledge`` category.
    """

    query: str
    usage_patterns: list[Document] = field(default_factory=list)
    similar_objects: list[Document] = field(default_factory=list)
    policy_knowledge: list[Document] = field(default_factory=list)

    def all_documents(self) -> list[Document]:
        """Return all retrieved documents across all categories."""
        return self.usage_patterns + self.similar_objects + self.policy_knowledge


@dataclass
class RagRetriever:
    """Retrieves documents from a :class:`~strataai.rag.store.VectorStore`.

    Parameters
    ----------
    store:
        Underlying vector store.
    top_k:
        Number of documents to retrieve *per category* on each query.
    """

    store: VectorStore
    top_k: int = 3

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def retrieve(self, query: str) -> RetrievalContext:
        """Run retrieval across all three RAG categories for *query*."""
        return RetrievalContext(
            query=query,
            usage_patterns=self.retrieve_usage_patterns(query),
            similar_objects=self.retrieve_similar_objects(query),
            policy_knowledge=self.retrieve_policy_knowledge(query),
        )

    def retrieve_usage_patterns(self, query: str) -> list[Document]:
        """Retrieve historical usage patterns relevant to *query*."""
        return self.store.search(query, top_k=self.top_k, category=CATEGORY_USAGE_PATTERN)

    def retrieve_similar_objects(self, query: str) -> list[Document]:
        """Retrieve similar object classifications relevant to *query*."""
        return self.store.search(
            query, top_k=self.top_k, category=CATEGORY_OBJECT_CLASSIFICATION
        )

    def retrieve_policy_knowledge(self, query: str) -> list[Document]:
        """Retrieve policy knowledge relevant to *query*."""
        return self.store.search(query, top_k=self.top_k, category=CATEGORY_POLICY_KNOWLEDGE)

    def index_document(self, doc: Document) -> None:
        """Add a single document to the underlying vector store."""
        self.store.add(doc)

    def index_many(self, docs: list[Document]) -> None:
        """Add multiple documents to the underlying vector store."""
        for doc in docs:
            self.store.add(doc)
