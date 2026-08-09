"""Initial schema — six tables

Revision ID: 0001
Revises:
Create Date: 2026-06-18
"""
import sqlalchemy as sa

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "allowed_users",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("email", sa.String(255), unique=True, nullable=False),
        sa.Column("is_active", sa.Boolean, server_default=sa.true(), nullable=False),
        sa.Column("is_blocked", sa.Boolean, server_default=sa.false(), nullable=False),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_allowed_users_email", "allowed_users", ["email"])

    op.create_table(
        "audit_records",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("job_id", sa.String(36), nullable=False),
        sa.Column("agent", sa.String(100), nullable=False),
        sa.Column("event", sa.String(50), nullable=False),
        sa.Column("timestamp", sa.DateTime, server_default=sa.func.now(), nullable=False),
        sa.Column("duration_ms", sa.Integer, nullable=True),
        sa.Column("detail", sa.JSON, nullable=True),
    )
    op.create_index("ix_audit_records_job_id", "audit_records", ["job_id"])

    op.create_table(
        "hash_records",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("sha256", sa.String(64), unique=True, nullable=False),
        sa.Column("job_id", sa.String(36), nullable=False),
        sa.Column("ingested_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_hash_records_sha256", "hash_records", ["sha256"])

    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("job_id", sa.String(36), unique=True, nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="started"),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
        # onupdate is handled at the ORM layer; raw SQL UPDATEs must include updated_at=func.now() explicitly.
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
        sa.Column("failed_at_agent", sa.String(100), nullable=True),
        sa.Column("rejection_reason", sa.Text, nullable=True),
        sa.Column("review_action_needed", sa.String(100), nullable=True),
    )
    op.create_index("ix_jobs_job_id", "jobs", ["job_id"])

    op.create_table(
        "document_steps",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "job_id",
            sa.String(36),
            sa.ForeignKey("jobs.job_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("step_order", sa.Integer, nullable=False),
        sa.Column("agent", sa.String(100), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("passed", sa.Boolean, nullable=False),
        sa.Column("rejection_reason", sa.Text, nullable=True),
        sa.Column("duration_ms", sa.Integer, nullable=True),
        sa.Column("detail", sa.JSON, nullable=True),
        sa.Column("timestamp", sa.DateTime, server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_document_steps_job_id", "document_steps", ["job_id"])

    op.create_table(
        "human_decisions",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "job_id",
            sa.String(36),
            sa.ForeignKey("jobs.job_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("decided_by", sa.String(255), nullable=False),
        sa.Column("decision", sa.String(20), nullable=False),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("decided_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_human_decisions_job_id", "human_decisions", ["job_id"])


def downgrade() -> None:
    op.drop_table("human_decisions")
    op.drop_table("document_steps")
    op.drop_table("hash_records")
    op.drop_table("audit_records")
    op.drop_table("jobs")
    op.drop_table("allowed_users")
