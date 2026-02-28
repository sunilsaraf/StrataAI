"""Vector store for RAG (Retrieval-Augmented Generation) retrieval.

Provides a pluggable :class:`VectorStore` protocol and a fully
dependency-free :class:`InMemoryVectorStore` that uses TF-normalised
bag-of-words cosine similarity – no external ML library is required.

Documents are optionally tagged with a *category* so that callers can
restrict retrieval to a specific knowledge domain (usage patterns,
object classifications, policy knowledge, …).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class Document:
    """A text document stored in the vector store.

    Attributes
    ----------
    text:
        Plain-text content of the document.
    doc_id:
        Optional unique identifier for the document.
    category:
        Knowledge-domain tag used to filter retrieval results.
        Conventional values: ``"usage_pattern"``,
        ``"object_classification"``, ``"policy_knowledge"``.
    metadata:
        Arbitrary string key/value pairs (e.g. bucket name, timestamp).
    """

    text: str
    doc_id: str = ""
    category: str = ""
    metadata: dict[str, str] = field(default_factory=dict)


@runtime_checkable
class VectorStore(Protocol):
    """Protocol for vector store backends."""

    def add(self, doc: Document) -> None: ...
    def search(self, query: str, top_k: int = 5, category: str = "") -> list[Document]: ...
    def delete(self, doc_id: str) -> None: ...


class InMemoryVectorStore:
    """Bag-of-words cosine similarity vector store.

    Embeds documents and queries as TF-normalised word-frequency vectors
    and ranks candidates by cosine similarity.  No external dependencies
    are required.

    Parameters
    ----------
    None – the store starts empty and documents are added via :meth:`add`.
    """

    def __init__(self) -> None:
        self._store: list[tuple[dict[str, float], Document]] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add(self, doc: Document) -> None:
        """Index *doc* in the store."""
        vec = self._embed(doc.text)
        self._store.append((vec, doc))

    def search(self, query: str, top_k: int = 5, category: str = "") -> list[Document]:
        """Return the *top_k* most similar documents to *query*.

        Parameters
        ----------
        query:
            Free-text query string.
        top_k:
            Maximum number of results to return.
        category:
            When non-empty, only documents with a matching
            :attr:`Document.category` are considered.
        """
        query_vec = self._embed(query)
        scored: list[tuple[float, Document]] = []
        for vec, doc in self._store:
            if category and doc.category != category:
                continue
            score = self._cosine(query_vec, vec)
            scored.append((score, doc))
        scored.sort(key=lambda x: -x[0])
        return [doc for _, doc in scored[:top_k]]

    def delete(self, doc_id: str) -> None:
        """Remove all documents with *doc_id* from the store."""
        self._store = [(v, d) for v, d in self._store if d.doc_id != doc_id]

    def __len__(self) -> int:
        return len(self._store)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        return text.lower().split()

    def _embed(self, text: str) -> dict[str, float]:
        """Return a TF-normalised word-frequency vector for *text*."""
        tokens = self._tokenize(text)
        freq: dict[str, float] = {}
        for t in tokens:
            freq[t] = freq.get(t, 0.0) + 1.0
        norm = math.sqrt(sum(v * v for v in freq.values()))
        if norm > 0:
            return {k: v / norm for k, v in freq.items()}
        return freq

    @staticmethod
    def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
        """Dot product of two unit vectors = cosine similarity."""
        return sum(a.get(k, 0.0) * v for k, v in b.items())
