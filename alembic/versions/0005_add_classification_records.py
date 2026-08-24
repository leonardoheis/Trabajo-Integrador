"""Add classification_records table

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-18

"""

import sqlalchemy as sa

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "classification_records",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "job_id",
            sa.String(36),
            sa.ForeignKey("jobs.job_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "enriched_id",
            sa.Integer,
            sa.ForeignKey("enriched_records.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("label", sa.String(100), nullable=True),
        sa.Column("confidence", sa.Float, nullable=False, server_default="0.0"),
        sa.Column("all_scores", sa.JSON, nullable=False),
        sa.Column("second_opinion_label", sa.String(100), nullable=True),
        sa.Column("second_opinion_confidence", sa.Float, nullable=False, server_default="0.0"),
        sa.Column(
            "classifier_disagreement", sa.Boolean, nullable=False, server_default=sa.false()
        ),
        sa.Column("ood_metrics", sa.JSON, nullable=True),
        sa.Column("svm_scores", sa.JSON, nullable=False),
        sa.Column(
            "svm_agrees_with_prediction", sa.Boolean, nullable=False, server_default=sa.true()
        ),
        sa.Column("review_route", sa.String(20), nullable=False),
        sa.Column("smells", sa.JSON, nullable=False),
        sa.Column("risk_score", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "smell_review_suggested", sa.Boolean, nullable=False, server_default=sa.false()
        ),
        sa.Column("foreign_municipality", sa.String(255), nullable=True),
        sa.Column("judged_by_llm", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("stored_path", sa.String(500), nullable=True),
        sa.Column("human_overridden", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_classification_records_job_id", "classification_records", ["job_id"])


def downgrade() -> None:
    op.drop_table("classification_records")
