"""Add raw_text to enriched_records

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-22

"""

import sqlalchemy as sa

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("enriched_records", sa.Column("raw_text", sa.Text, nullable=True))


def downgrade() -> None:
    op.drop_column("enriched_records", "raw_text")
