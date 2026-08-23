"""Add enriched_records table

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-17

"""

import sqlalchemy as sa

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "enriched_records",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "job_id",
            sa.String(36),
            sa.ForeignKey("jobs.job_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("cleaned_text", sa.Text, nullable=False),
        sa.Column("entities", sa.JSON, nullable=False),
        sa.Column("metadata", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_enriched_records_job_id", "enriched_records", ["job_id"])


def downgrade() -> None:
    op.drop_table("enriched_records")
