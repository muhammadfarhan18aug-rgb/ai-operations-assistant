from __future__ import annotations

from decimal import Decimal

from sqlalchemy import CheckConstraint, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if False:  # pragma: no cover
    from .order import Order


class Product(Base):
    """Inventory product record."""

    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("quantity_on_hand >= 0", name="ck_products_quantity_on_hand_non_negative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    quantity_on_hand: Mapped[int] = mapped_column(nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    supplier: Mapped[str] = mapped_column(String(255), nullable=False)

    orders: Mapped[list["Order"]] = relationship(
        back_populates="product",
        foreign_keys="Order.sku",
    )
