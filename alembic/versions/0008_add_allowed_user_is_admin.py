"""Add is_admin to allowed_users

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-24

"""

import sqlalchemy as sa

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "allowed_users",
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("allowed_users", "is_admin")
