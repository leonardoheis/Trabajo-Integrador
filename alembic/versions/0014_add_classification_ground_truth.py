"""Add original_label and expected_label to classification_records

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-02

"""

import sqlalchemy as sa

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "classification_records", sa.Column("original_label", sa.String(length=100), nullable=True)
    )
    op.add_column(
        "classification_records", sa.Column("expected_label", sa.String(length=100), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("classification_records", "expected_label")
    op.drop_column("classification_records", "original_label")
