from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text, func
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
    document_identifier: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        unique=True,
        default=lambda: f"doc-{uuid.uuid4().hex[:12]}",
    )
    version: Mapped[str] = mapped_column(String(32), nullable=False, default="1.0")
    source: Mapped[str] = mapped_column(String(255), nullable=False, default="repository")
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    uploaded_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    index_status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)

    uploader: Mapped["User"] = relationship(back_populates="uploaded_documents", foreign_keys=[uploaded_by])
    chunks: Mapped[list["DocumentChunk"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        foreign_keys="DocumentChunk.document_id",
    )
