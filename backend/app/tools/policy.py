"""Policy lookup tool backed by the existing database documents, not vector search."""

from __future__ import annotations

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.tools.authorization import ToolAuthorizationError, authorize_tool
from app.tools.context import ToolContext


class PolicyLookupInput(BaseModel):
    """Validated policy lookup request."""

    title: str | None = Field(default=None, min_length=1, max_length=255)
    document_id: int | None = None


async def lookup_policy(
    session: AsyncSession,
    context: ToolContext,
    title: str | PolicyLookupInput | None = None,
    document_id: int | None = None,
    **_ignored: object,
) -> list[dict[str, object]]:
    """Return document-based policy records only after DB-backed policy capability checks."""
    data: PolicyLookupInput
    if isinstance(title, PolicyLookupInput):
        data = title
    else:
        if title is None and document_id is None:
            raise ToolAuthorizationError("Policy lookup must include a title or document_id.")
        data = PolicyLookupInput(title=title, document_id=document_id)

    await authorize_tool(session, context, "policy:read")

    stmt = select(Document).order_by(Document.uploaded_at.desc())
    if data.document_id is not None:
        stmt = stmt.where(Document.id == data.document_id)
    elif data.title is not None:
        stmt = stmt.where(Document.title.ilike(f"%{data.title.strip()}%"))

    result = await session.execute(stmt)
    documents = result.scalars().all()

    rows: list[dict[str, object]] = []
    for document in documents:
        chunk_result = await session.execute(
            select(DocumentChunk.chunk_text)
            .where(DocumentChunk.document_id == document.id)
            .order_by(DocumentChunk.position.asc())
        )
        chunk_texts = [chunk for chunk in chunk_result.scalars().all() if chunk]
        rows.append(
            {
                "document_id": document.id,
                "title": document.title,
                "filename": document.filename,
                "index_status": document.index_status,
                "chunks": chunk_texts,
            }
        )
    return rows
