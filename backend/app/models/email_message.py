from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from .user import User


class EmailMessage(Base):
    """Mocked outbound email message record."""

    __tablename__ = "email_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    recipient: Mapped[str] = mapped_column(String(255), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(String, nullable=False)
    sent_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)

    sender: Mapped["User"] = relationship(back_populates="sent_messages", foreign_keys=[sent_by])
