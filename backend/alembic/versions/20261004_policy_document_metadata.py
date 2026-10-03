"""Add policy document metadata fields for grounded retrieval.

Revision ID: 20261004_policy_doc_meta
Revises: 20261003_initial_database_schema
Create Date: 2026-10-03 15:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20261004_policy_doc_meta"
down_revision = "20261003_initial_database_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("documents") as batch_op:
        batch_op.add_column(sa.Column("document_identifier", sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column("version", sa.String(length=32), nullable=True, server_default="1.0"))
        batch_op.add_column(sa.Column("source", sa.String(length=255), nullable=True, server_default="repository"))
        batch_op.add_column(sa.Column("content", sa.Text(), nullable=True, server_default=""))

    op.execute(
        "UPDATE documents SET document_identifier = CONCAT('policy-', id), version = '1.0', source = 'repository', content = '' WHERE document_identifier IS NULL"
    )

    with op.batch_alter_table("documents") as batch_op:
        batch_op.alter_column("document_identifier", nullable=False)
        batch_op.alter_column("version", nullable=False)
        batch_op.alter_column("source", nullable=False)
        batch_op.alter_column("content", nullable=False)
        batch_op.create_unique_constraint("uq_documents_document_identifier", ["document_identifier"])


def downgrade() -> None:
    with op.batch_alter_table("documents") as batch_op:
        batch_op.drop_constraint("uq_documents_document_identifier", type_="unique")
        batch_op.drop_column("content")
        batch_op.drop_column("source")
        batch_op.drop_column("version")
        batch_op.drop_column("document_identifier")
