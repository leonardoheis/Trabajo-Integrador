"""Add filename and sha256 to enriched_records

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-23

"""

import sqlalchemy as sa

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("enriched_records", sa.Column("filename", sa.String(length=255), nullable=True))
    op.add_column("enriched_records", sa.Column("sha256", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("enriched_records", "sha256")
    op.drop_column("enriched_records", "filename")
