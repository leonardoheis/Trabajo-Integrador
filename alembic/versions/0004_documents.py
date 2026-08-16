"""Add documents catalogue for the knowledge base

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-14
"""
import sqlalchemy as sa

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("doc_type", sa.String(length=100), nullable=True),
        sa.Column("number", sa.String(length=50), nullable=True),
        sa.Column("year", sa.String(length=10), nullable=True),
        sa.Column("subject", sa.Text(), nullable=True),
        sa.Column("sanction_date", sa.String(length=20), nullable=True),
        sa.Column("publication_date", sa.String(length=20), nullable=True),
        sa.Column("bulletin_number", sa.String(length=20), nullable=True),
        sa.Column("download_url", sa.Text(), nullable=True),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("indexed_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sha256"),
    )
    op.create_index("ix_documents_job_id", "documents", ["job_id"])
    op.create_index("ix_documents_sha256", "documents", ["sha256"])
    op.create_index("ix_documents_doc_type", "documents", ["doc_type"])
    op.create_index("ix_documents_year", "documents", ["year"])


def downgrade() -> None:
    op.drop_index("ix_documents_year", table_name="documents")
    op.drop_index("ix_documents_doc_type", table_name="documents")
    op.drop_index("ix_documents_sha256", table_name="documents")
    op.drop_index("ix_documents_job_id", table_name="documents")
    op.drop_table("documents")
