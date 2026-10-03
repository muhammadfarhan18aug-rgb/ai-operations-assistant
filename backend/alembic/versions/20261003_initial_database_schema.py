"""Initial database schema for AI Operations Assistant.

Revision ID: 20261003_initial_database_schema
Revises: 
Create Date: 2026-10-03 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "20261003_initial_database_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("is_admin", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)
    op.create_index(op.f("ix_users_id"), "users", ["id"], unique=False)

    op.create_table(
        "user_capabilities",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("capability", sa.String(length=64), nullable=False),
        sa.Column("granted_by", sa.Integer(), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_user_capabilities_user_id_users", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["granted_by"], ["users.id"], name="fk_user_capabilities_granted_by_users"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "capability", name="uq_user_capabilities_user_capability"),
    )
    op.create_index(op.f("ix_user_capabilities_capability"), "user_capabilities", ["capability"], unique=False)
    op.create_index(op.f("ix_user_capabilities_user_id"), "user_capabilities", ["user_id"], unique=False)
    op.create_index(op.f("ix_user_capabilities_granted_by"), "user_capabilities", ["granted_by"], unique=False)

    op.create_table(
        "products",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("sku", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("quantity_on_hand", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("supplier", sa.String(length=255), nullable=False),
        sa.CheckConstraint("quantity_on_hand >= 0", name="ck_products_quantity_on_hand_non_negative"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sku", name="uq_products_sku"),
    )
    op.create_index(op.f("ix_products_sku"), "products", ["sku"], unique=True)

    op.create_table(
        "orders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("order_reference", sa.String(length=128), nullable=False),
        sa.Column("sku", sa.String(length=128), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("supplier", sa.String(length=255), nullable=False),
        sa.Column("requested_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_orders_quantity_positive"),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"], name="fk_orders_requested_by_users"),
        sa.ForeignKeyConstraint(["sku"], ["products.sku"], name="fk_orders_sku_products"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("order_reference", name="uq_orders_order_reference"),
        sa.UniqueConstraint("idempotency_key", name="uq_orders_idempotency_key"),
    )
    op.create_index(op.f("ix_orders_order_reference"), "orders", ["order_reference"], unique=True)
    op.create_index(op.f("ix_orders_sku"), "orders", ["sku"], unique=False)
    op.create_index(op.f("ix_orders_requested_by"), "orders", ["requested_by"], unique=False)
    op.create_index(op.f("ix_orders_idempotency_key"), "orders", ["idempotency_key"], unique=True)

    op.create_table(
        "threads",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], name="fk_threads_owner_user_id_users"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_threads_owner_user_id"), "threads", ["owner_user_id"], unique=False)

    op.create_table(
        "email_messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("recipient", sa.String(length=255), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("body", sa.String(), nullable=False),
        sa.Column("sent_by", sa.Integer(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.ForeignKeyConstraint(["sent_by"], ["users.id"], name="fk_email_messages_sent_by_users"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_email_messages_idempotency_key"),
    )
    op.create_index(op.f("ix_email_messages_sent_by"), "email_messages", ["sent_by"], unique=False)
    op.create_index(op.f("ix_email_messages_idempotency_key"), "email_messages", ["idempotency_key"], unique=True)

    op.create_table(
        "documents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("uploaded_by", sa.Integer(), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("index_status", sa.String(length=20), nullable=False),
        sa.CheckConstraint("index_status IN ('pending', 'indexed', 'failed', 'deleted')", name="ck_documents_index_status"),
        sa.ForeignKeyConstraint(["uploaded_by"], ["users.id"], name="fk_documents_uploaded_by_users"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_documents_uploaded_by"), "documents", ["uploaded_by"], unique=False)
    op.create_index(op.f("ix_documents_index_status"), "documents", ["index_status"], unique=False)

    op.create_table(
        "document_chunks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("chunk_text", sa.String(), nullable=False),
        sa.Column("embedding_reference", sa.String(length=255), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], name="fk_document_chunks_document_id_documents", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", "position", name="uq_document_chunks_document_position"),
    )
    op.create_index(op.f("ix_document_chunks_document_id"), "document_chunks", ["document_id"], unique=False)

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("tool", sa.String(length=255), nullable=False),
        sa.Column("arguments", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("thread_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("outcome IN ('executed', 'rejected', 'denied')", name="ck_audit_logs_outcome"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_audit_logs_user_id_users"),
        sa.ForeignKeyConstraint(["thread_id"], ["threads.id"], name="fk_audit_logs_thread_id_threads"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_audit_logs_user_id"), "audit_logs", ["user_id"], unique=False)
    op.create_index(op.f("ix_audit_logs_tool"), "audit_logs", ["tool"], unique=False)
    op.create_index(op.f("ix_audit_logs_outcome"), "audit_logs", ["outcome"], unique=False)
    op.create_index(op.f("ix_audit_logs_thread_id"), "audit_logs", ["thread_id"], unique=False)
    op.create_index(op.f("ix_audit_logs_created_at"), "audit_logs", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_audit_logs_created_at"), table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_thread_id"), table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_outcome"), table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_tool"), table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_user_id"), table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_index(op.f("ix_document_chunks_document_id"), table_name="document_chunks")
    op.drop_table("document_chunks")
    op.drop_index(op.f("ix_documents_uploaded_by"), table_name="documents")
    op.drop_index(op.f("ix_documents_index_status"), table_name="documents")
    op.drop_table("documents")
    op.drop_index(op.f("ix_email_messages_idempotency_key"), table_name="email_messages")
    op.drop_index(op.f("ix_email_messages_sent_by"), table_name="email_messages")
    op.drop_table("email_messages")
    op.drop_index(op.f("ix_threads_owner_user_id"), table_name="threads")
    op.drop_table("threads")
    op.drop_index(op.f("ix_orders_idempotency_key"), table_name="orders")
    op.drop_index(op.f("ix_orders_requested_by"), table_name="orders")
    op.drop_index(op.f("ix_orders_sku"), table_name="orders")
    op.drop_index(op.f("ix_orders_order_reference"), table_name="orders")
    op.drop_table("orders")
    op.drop_index(op.f("ix_products_sku"), table_name="products")
    op.drop_table("products")
    op.drop_index(op.f("ix_user_capabilities_granted_by"), table_name="user_capabilities")
    op.drop_index(op.f("ix_user_capabilities_capability"), table_name="user_capabilities")
    op.drop_index(op.f("ix_user_capabilities_user_id"), table_name="user_capabilities")
    op.drop_table("user_capabilities")
    op.drop_index(op.f("ix_users_id"), table_name="users")
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")
