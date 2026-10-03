from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from .document import Document


class DocumentChunk(Base):
    """Chunk extracted from a document used for later indexing or retrieval."""

    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "position", name="uq_document_chunks_document_position"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    chunk_text: Mapped[str] = mapped_column(String, nullable=False)
    embedding_reference: Mapped[str] = mapped_column(String(255), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    document: Mapped["Document"] = relationship(back_populates="chunks", foreign_keys=[document_id])
