from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from .product import Product
    from .user import User


class Order(Base):
    """Purchase order record."""

    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_orders_quantity_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    order_reference: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    sku: Mapped[str] = mapped_column(ForeignKey("products.sku"), nullable=False, index=True)
    quantity: Mapped[int] = mapped_column(nullable=False)
    supplier: Mapped[str] = mapped_column(String(255), nullable=False)
    requested_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)

    requested_by_user: Mapped["User"] = relationship(back_populates="orders", foreign_keys=[requested_by])
    product: Mapped["Product"] = relationship(back_populates="orders", foreign_keys=[sku])
