from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from .thread import Thread
    from .user import User


class AuditLog(Base):
    """Administrative audit log of tool activity."""

    __tablename__ = "audit_logs"
    __table_args__ = (
        CheckConstraint("outcome IN ('executed', 'rejected', 'denied')", name="ck_audit_logs_outcome"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    tool: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    arguments: Mapped[dict] = mapped_column(JSONB, nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    thread_id: Mapped[str] = mapped_column(ForeignKey("threads.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="audit_logs", foreign_keys=[user_id])
    thread: Mapped["Thread"] = relationship(back_populates="audit_logs", foreign_keys=[thread_id])
