"""Repository-backed policy document ingestion for grounded policy Q&A."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select

from app.models.document import Document
from app.models.document_chunk import DocumentChunk

_DEFAULT_POLICY_DIR = Path(__file__).resolve().parent / "documents"


def chunk_policy_text(text: str, *, chunk_size: int = 450, overlap: int = 80) -> list[str]:
    """Split policy content into readable chunks while preserving section headings."""
    raw = text.strip()
    if not raw:
        return []

    paragraphs = [part.strip() for part in re.split(r"\n\s*\n+", raw) if part.strip()]
    if len(paragraphs) == 1 and len(raw) <= chunk_size:
        return [raw]

    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if not current:
            current = paragraph
            continue
        if len(current) + len(paragraph) + 2 <= chunk_size:
            current = f"{current}\n\n{paragraph}"
            continue
        chunks.append(current.strip())
        if overlap <= 0:
            current = paragraph
        else:
            current = paragraph[-overlap:] if len(paragraph) > overlap else paragraph
    if current:
        chunks.append(current.strip())

    if not chunks:
        chunks = [raw]
    return [chunk for chunk in chunks if chunk]


async def ingest_repository_policy_documents(
    session: Any,
    uploader_user_id: int,
    documents_dir: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Load the repository policy documents into the database with chunk metadata."""
    base_dir = Path(documents_dir) if documents_dir is not None else _DEFAULT_POLICY_DIR
    if not base_dir.exists():
        return []

    ingested: list[dict[str, Any]] = []
    for document_path in sorted(base_dir.glob("*.md")):
        content = document_path.read_text(encoding="utf-8")
        title = _derive_title(content, document_path.stem)
        identifier = f"policy-{document_path.stem.lower().replace(' ', '-').replace('_', '-')}"

        existing = await session.scalar(select(Document).where(Document.document_identifier == identifier))
        if existing is None:
            document = Document(
                title=title,
                filename=document_path.name,
                document_identifier=identifier,
                version="1.0",
                source="repository-policy-library",
                uploaded_by=uploader_user_id,
                index_status="indexed",
                content=content,
            )
            session.add(document)
            await session.flush()
            db_document = document
        else:
            existing.title = title
            existing.filename = document_path.name
            existing.version = "1.0"
            existing.source = "repository-policy-library"
            existing.content = content
            existing.index_status = "indexed"
            db_document = existing
            await session.execute(delete(DocumentChunk).where(DocumentChunk.document_id == db_document.id))

        chunks = chunk_policy_text(content)
        for position, chunk_text in enumerate(chunks, start=1):
            session.add(
                DocumentChunk(
                    document_id=db_document.id,
                    chunk_text=chunk_text,
                    embedding_reference=f"{identifier}-chunk-{position}",
                    position=position,
                )
            )

        ingested.append(
            {
                "document_id": db_document.id,
                "document_identifier": identifier,
                "title": title,
                "filename": document_path.name,
                "chunks": len(chunks),
            }
        )

    await session.commit()
    return ingested


def _derive_title(content: str, fallback_name: str) -> str:
    heading = None
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            heading = stripped.lstrip("#").strip()
            if heading:
                break
    return heading or fallback_name.replace("_", " ").title()
