"""Rename agent column to node across audit_records, document_steps, jobs

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-05
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("audit_records") as batch_op:
        batch_op.alter_column("agent", new_column_name="node")

    with op.batch_alter_table("document_steps") as batch_op:
        batch_op.alter_column("agent", new_column_name="node")

    with op.batch_alter_table("jobs") as batch_op:
        batch_op.alter_column("failed_at_agent", new_column_name="failed_at_node")


def downgrade() -> None:
    with op.batch_alter_table("audit_records") as batch_op:
        batch_op.alter_column("node", new_column_name="agent")

    with op.batch_alter_table("document_steps") as batch_op:
        batch_op.alter_column("node", new_column_name="agent")

    with op.batch_alter_table("jobs") as batch_op:
        batch_op.alter_column("failed_at_node", new_column_name="failed_at_agent")
