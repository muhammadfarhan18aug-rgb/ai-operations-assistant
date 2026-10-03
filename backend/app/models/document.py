from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from .document_chunk import DocumentChunk
    from .user import User


class Document(Base):
    """Uploaded source document."""

    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint(
            "index_status IN ('pending', 'indexed', 'failed', 'deleted')",
            name="ck_documents_index_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    uploaded_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    index_status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)

    uploader: Mapped["User"] = relationship(back_populates="uploaded_documents", foreign_keys=[uploaded_by])
    chunks: Mapped[list["DocumentChunk"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        foreign_keys="DocumentChunk.document_id",
    )
