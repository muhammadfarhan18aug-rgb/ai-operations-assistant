"""Add durable approval workflow for dangerous write actions.

Revision ID: 20261005_human_approval_workflow
Revises: 20261004_policy_doc_meta
Create Date: 2026-10-03 16:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "20261005_human_approval_workflow"
down_revision = "20261004_policy_doc_meta"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "approval_requests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("thread_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tool_name", sa.String(length=128), nullable=False),
        sa.Column("action_args", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="PENDING"),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("decision_made_by", sa.Integer(), nullable=True),
        sa.Column("decision_made_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_reason", sa.String(length=255), nullable=True),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('PENDING', 'APPROVED', 'REJECTED', 'EXECUTED', 'FAILED', 'EXPIRED')",
            name="ck_approval_requests_status",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_approval_requests_user_id_users"),
        sa.ForeignKeyConstraint(["thread_id"], ["threads.id"], name="fk_approval_requests_thread_id_threads"),
        sa.ForeignKeyConstraint(["decision_made_by"], ["users.id"], name="fk_approval_requests_decision_made_by_users"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_approval_requests_user_id"), "approval_requests", ["user_id"], unique=False)
    op.create_index(op.f("ix_approval_requests_thread_id"), "approval_requests", ["thread_id"], unique=False)
    op.create_index(op.f("ix_approval_requests_tool_name"), "approval_requests", ["tool_name"], unique=False)
    op.create_index(op.f("ix_approval_requests_status"), "approval_requests", ["status"], unique=False)
    op.create_index(op.f("ix_approval_requests_idempotency_key"), "approval_requests", ["idempotency_key"], unique=True)
    op.create_index(op.f("ix_approval_requests_decision_made_by"), "approval_requests", ["decision_made_by"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_approval_requests_decision_made_by"), table_name="approval_requests")
    op.drop_index(op.f("ix_approval_requests_idempotency_key"), table_name="approval_requests")
    op.drop_index(op.f("ix_approval_requests_status"), table_name="approval_requests")
    op.drop_index(op.f("ix_approval_requests_tool_name"), table_name="approval_requests")
    op.drop_index(op.f("ix_approval_requests_thread_id"), table_name="approval_requests")
    op.drop_index(op.f("ix_approval_requests_user_id"), table_name="approval_requests")
    op.drop_table("approval_requests")
