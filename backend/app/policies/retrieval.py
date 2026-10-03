"""Grounded policy retrieval for knowledge questions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select

from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.policies.vector_store import LocalPolicyVectorStore


@dataclass
class PolicyRetrievalResult:
    """Structured result from retrieving policy context."""

    question: str
    retrieved_policy_chunks: list[str] = field(default_factory=list)
    citation_metadata: list[dict[str, Any]] = field(default_factory=list)
    grounded_answer: str = ""
    retrieval_status: str = "success"


async def retrieve_policy_context(
    session: Any,
    question: str,
    *,
    limit: int = 3,
    threshold: float = 0.15,
) -> PolicyRetrievalResult:
    """Retrieve relevant policy chunks and return grounded citation metadata."""
    if not question or not question.strip():
        return PolicyRetrievalResult(
            question=question,
            grounded_answer="No question was provided for grounded policy retrieval.",
            retrieval_status="no_question",
        )

    documents = (
        await session.execute(
            select(Document).where(Document.index_status == "indexed").order_by(Document.uploaded_at.desc())
        )
    ).scalars().all()

    if not documents:
        return PolicyRetrievalResult(
            question=question,
            grounded_answer="No relevant policy found in the local policy repository.",
            retrieval_status="no_relevant_policy_found",
        )

    vector_store = LocalPolicyVectorStore()
    for document in documents:
        chunk_rows = (
            await session.execute(
                select(DocumentChunk)
                .where(DocumentChunk.document_id == document.id)
                .order_by(DocumentChunk.position.asc())
            )
        ).scalars().all()
        for chunk in chunk_rows:
            section = _extract_section(chunk.chunk_text)
            vector_store.add_chunk(
                chunk_id=chunk.id,
                document_id=document.id,
                document_title=document.title,
                document_identifier=document.document_identifier,
                version=document.version,
                source=document.source,
                filename=document.filename,
                section=section,
                chunk_text=chunk.chunk_text,
            )

    matches = vector_store.search(question, limit=limit, threshold=threshold)
    if not matches:
        return PolicyRetrievalResult(
            question=question,
            grounded_answer="No relevant policy found in the local policy repository for this question.",
            retrieval_status="no_relevant_policy_found",
        )

    citation_metadata = [
        {
            "document_id": match.document_id,
            "document_title": match.document_title,
            "document_identifier": match.document_identifier,
            "filename": match.filename,
            "source": match.source,
            "version": match.version,
            "section": match.section,
            "chunk_position": match.chunk_id,
            "score": round(match.score, 4),
        }
        for match in matches
    ]
    retrieved_policy_chunks = [match.chunk_text for match in matches]
    summary_lines = [
        f"{match.document_title} ({match.section or 'document body'}): {match.chunk_text}"
        for match in matches
    ]
    grounded_answer = "Grounded answer based on the retrieved policy documents:\n\n" + "\n\n".join(summary_lines)

    return PolicyRetrievalResult(
        question=question,
        retrieved_policy_chunks=retrieved_policy_chunks,
        citation_metadata=citation_metadata,
        grounded_answer=grounded_answer,
        retrieval_status="success",
    )


def _extract_section(chunk_text: str) -> str | None:
    for line in chunk_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            cleaned = stripped.lstrip("#").strip()
            return cleaned or None
    return None
