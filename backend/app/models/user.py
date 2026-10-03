from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.database import Base

if TYPE_CHECKING:
    from .audit_log import AuditLog
    from .document import Document
    from .email_message import EmailMessage
    from .order import Order
    from .thread import Thread
    from .user_capability import UserCapability


class User(Base):
    """Application user record."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    capabilities: Mapped[list["UserCapability"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        foreign_keys="UserCapability.user_id",
    )
    granted_capabilities: Mapped[list["UserCapability"]] = relationship(
        back_populates="granted_by_user",
        foreign_keys="UserCapability.granted_by",
    )
    orders: Mapped[list["Order"]] = relationship(
        back_populates="requested_by_user",
        foreign_keys="Order.requested_by",
    )
    sent_messages: Mapped[list["EmailMessage"]] = relationship(
        back_populates="sender",
        foreign_keys="EmailMessage.sent_by",
    )
    uploaded_documents: Mapped[list["Document"]] = relationship(
        back_populates="uploader",
        foreign_keys="Document.uploaded_by",
    )
    audit_logs: Mapped[list["AuditLog"]] = relationship(
        back_populates="user",
        foreign_keys="AuditLog.user_id",
    )
    threads: Mapped[list["Thread"]] = relationship(
        back_populates="owner",
        foreign_keys="Thread.owner_user_id",
    )

    @validates("email")
    def normalize_email(self, _key: str, value: str) -> str:
        return value.strip().lower()
