"""Add conversation_turns and conversation_summaries tables

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-31

"""

import sqlalchemy as sa

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversation_turns",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_email", sa.String(length=255), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_conversation_turns_user_email", "conversation_turns", ["user_email"])
    op.create_table(
        "conversation_summaries",
        sa.Column("user_email", sa.String(length=255), primary_key=True),
        sa.Column("summary_text", sa.Text(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("conversation_summaries")
    op.drop_index("ix_conversation_turns_user_email", table_name="conversation_turns")
    op.drop_table("conversation_turns")
