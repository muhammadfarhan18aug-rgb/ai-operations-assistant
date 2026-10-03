from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.database import Base

if TYPE_CHECKING:
    from .user import User


VALID_CAPABILITIES = {
    "policy:read",
    "inventory:read",
    "order:create",
    "email:send",
}


class UserCapability(Base):
    """Permission granted to a user for a specific capability."""

    __tablename__ = "user_capabilities"
    __table_args__ = (
        UniqueConstraint("user_id", "capability", name="uq_user_capabilities_user_capability"),
        Index("ix_user_capabilities_user_id", "user_id"),
        Index("ix_user_capabilities_capability", "capability"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    capability: Mapped[str] = mapped_column(String(64), nullable=False)
    granted_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    user: Mapped["User"] = relationship(
        back_populates="capabilities",
        foreign_keys=[user_id],
    )
    granted_by_user: Mapped["User"] = relationship(
        back_populates="granted_capabilities",
        foreign_keys=[granted_by],
    )

    @validates("capability")
    def validate_capability(self, _key: str, value: str) -> str:
        if value not in VALID_CAPABILITIES:
            raise ValueError(f"Unsupported capability: {value}")
        return value
