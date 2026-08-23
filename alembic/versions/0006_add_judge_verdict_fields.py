"""Add judge_final_label/judge_reasoning to classification_records

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-22

"""

import sqlalchemy as sa

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "classification_records", sa.Column("judge_final_label", sa.String(100), nullable=True)
    )
    op.add_column("classification_records", sa.Column("judge_reasoning", sa.Text, nullable=True))


def downgrade() -> None:
    op.drop_column("classification_records", "judge_reasoning")
    op.drop_column("classification_records", "judge_final_label")
