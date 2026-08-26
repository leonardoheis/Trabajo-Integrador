"""Rename documents to document_kb and link it to enriched_records

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-23

"""

import sqlalchemy as sa

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.rename_table("documents", "document_kb")

    op.drop_index("ix_documents_job_id", table_name="document_kb")
    op.drop_index("ix_documents_sha256", table_name="document_kb")
    op.drop_index("ix_documents_doc_type", table_name="document_kb")
    op.drop_index("ix_documents_year", table_name="document_kb")
    op.create_index("ix_document_kb_job_id", "document_kb", ["job_id"])
    op.create_index("ix_document_kb_sha256", "document_kb", ["sha256"])
    op.create_index("ix_document_kb_doc_type", "document_kb", ["doc_type"])
    op.create_index("ix_document_kb_year", "document_kb", ["year"])

    # Nullable: existing catalogue rows predate this relationship and cannot be
    # backfilled with a real enriched_records match by a migration.
    with op.batch_alter_table("document_kb") as batch_op:
        batch_op.add_column(sa.Column("enriched_record_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_document_kb_enriched_record_id_enriched_records",
            "enriched_records",
            ["enriched_record_id"],
            ["id"],
            ondelete="CASCADE",
        )


def downgrade() -> None:
    with op.batch_alter_table("document_kb") as batch_op:
        batch_op.drop_constraint(
            "fk_document_kb_enriched_record_id_enriched_records", type_="foreignkey"
        )
        batch_op.drop_column("enriched_record_id")

    op.drop_index("ix_document_kb_year", table_name="document_kb")
    op.drop_index("ix_document_kb_doc_type", table_name="document_kb")
    op.drop_index("ix_document_kb_sha256", table_name="document_kb")
    op.drop_index("ix_document_kb_job_id", table_name="document_kb")
    op.create_index("ix_documents_job_id", "document_kb", ["job_id"])
    op.create_index("ix_documents_sha256", "document_kb", ["sha256"])
    op.create_index("ix_documents_doc_type", "document_kb", ["doc_type"])
    op.create_index("ix_documents_year", "document_kb", ["year"])

    op.rename_table("document_kb", "documents")
