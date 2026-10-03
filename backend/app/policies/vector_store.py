"""Local vector store abstraction for policy chunk retrieval."""

from __future__ import annotations

from dataclasses import dataclass, field
from math import sqrt
from typing import Any

from app.policies.embeddings import LocalHashEmbeddingService


@dataclass
class PolicyMatch:
    """One retrieved policy chunk with similarity information."""

    chunk_id: int
    document_id: int
    document_title: str
    document_identifier: str
    version: str
    source: str
    filename: str
    section: str | None
    chunk_text: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)


class LocalPolicyVectorStore:
    """Minimal local vector store used for grounded policy retrieval in development."""

    def __init__(self, embedding_service: LocalHashEmbeddingService | None = None) -> None:
        self.embedding_service = embedding_service or LocalHashEmbeddingService()
        self._chunks: list[dict[str, Any]] = []

    def add_chunk(
        self,
        *,
        chunk_id: int,
        document_id: int,
        document_title: str,
        document_identifier: str,
        version: str,
        source: str,
        filename: str,
        section: str | None,
        chunk_text: str,
    ) -> None:
        self._chunks.append(
            {
                "chunk_id": chunk_id,
                "document_id": document_id,
                "document_title": document_title,
                "document_identifier": document_identifier,
                "version": version,
                "source": source,
                "filename": filename,
                "section": section,
                "chunk_text": chunk_text,
                "vector": self.embedding_service.embed_text(chunk_text),
            }
        )

    def search(self, question: str, limit: int = 3, threshold: float = 0.15) -> list[PolicyMatch]:
        """Return policy chunks most similar to the question."""
        if not self._chunks:
            return []

        query_vector = self.embedding_service.embed_text(question)
        scored: list[PolicyMatch] = []
        for chunk in self._chunks:
            score = _cosine_similarity(query_vector, chunk["vector"])
            if score < threshold:
                continue
            scored.append(
                PolicyMatch(
                    chunk_id=chunk["chunk_id"],
                    document_id=chunk["document_id"],
                    document_title=chunk["document_title"],
                    document_identifier=chunk["document_identifier"],
                    version=chunk["version"],
                    source=chunk["source"],
                    filename=chunk["filename"],
                    section=chunk["section"],
                    chunk_text=chunk["chunk_text"],
                    score=score,
                    metadata={
                        "document_identifier": chunk["document_identifier"],
                        "version": chunk["version"],
                        "source": chunk["source"],
                        "filename": chunk["filename"],
                    },
                )
            )

        scored.sort(key=lambda item: item.score, reverse=True)
        return scored[:limit]


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0

    dot = sum(a * b for a, b in zip(left, right))
    left_norm = sqrt(sum(value * value for value in left))
    right_norm = sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)
