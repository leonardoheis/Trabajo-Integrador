"""Recover original_label for human-overridden records from the audit log

Revision ID: 0016
Revises: 0015
Create Date: 2026-09-05

"""

import json

import sqlalchemy as sa

from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None

# The primary classifier writes its prediction to the audit log before any human can
# change it, so this node's detail is the only surviving record of what the machine
# said for documents corrected before original_label existed.
_PRIMARY_CLASSIFIER_NODE = "classification_primary_classifier"


def upgrade() -> None:
    connection = op.get_bind()
    # Only overridden records: for the rest, label still holds the machine's prediction
    # and MetricsService reads it directly, so original_label is never consulted.
    rows = connection.execute(
        sa.text("""
            SELECT cr.id, cr.job_id, cr.original_label
            FROM classification_records cr
            WHERE cr.human_overridden = 1
        """)
    ).fetchall()

    for row in rows:
        prediction = _first_prediction(connection, row.job_id)
        if prediction is None or prediction == row.original_label:
            continue
        connection.execute(
            sa.text(
                "UPDATE classification_records SET original_label = :label WHERE id = :id"
            ),
            {"label": prediction, "id": row.id},
        )


def _first_prediction(connection: sa.Connection, job_id: str) -> str | None:
    """The label the primary classifier logged on its first pass over this job."""
    row = connection.execute(
        sa.text("""
            SELECT detail FROM audit_records
            WHERE job_id = :job_id AND node = :node
            ORDER BY timestamp
            LIMIT 1
        """),
        {"job_id": job_id, "node": _PRIMARY_CLASSIFIER_NODE},
    ).fetchone()
    if row is None or row.detail is None:
        return None
    label = json.loads(row.detail).get("label")
    return label if isinstance(label, str) else None


def downgrade() -> None:
    # Not reversed: rows written after this migration are indistinguishable from the ones
    # it recovered, so clearing original_label would destroy data the application wrote.
    pass
