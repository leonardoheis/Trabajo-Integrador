"""Add machine_review_route and backfill accuracy history

Revision ID: 0015
Revises: 0014
Create Date: 2026-09-03

"""

import sqlalchemy as sa

from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None

# Duplicated from classification/ground_truth.py on purpose: a migration must keep
# producing the same result years from now, so it cannot import application code that
# will be refactored. Longest prefix first -- "decreto_cm_" and "decreto_ordenanza_" both
# start with "decreto_".
_PREFIX_TO_LABEL: tuple[tuple[str, str], ...] = (
    ("decreto_ordenanza_", "decreto_ordenanzas"),
    ("decreto_cm_", "decretos_concejo_municipal"),
    ("resolucion_cm_", "resoluciones_concejo_municipal"),
    ("declaracion_", "declaraciones_concejo_municipal"),
    ("ordenanza_", "ordenanzas"),
    ("resolucion_", "resoluciones"),
    ("convenio_", "convenios"),
    ("boletin_", "boletines"),
    ("decreto_", "decretos"),
)

_EXPLICIT_LABELS: dict[str, str] = {
    "a0470.pdf": "otro",
    "informe_agosto_2021.pdf": "otro",
    "dia_a_grupos_actualizados.xlsx": "otro",
    "v-reqcac_17-08-24.pdf": "otro",
}

_HUMAN_REVIEW = "human_review"


def _expected_label(filename: str) -> str | None:
    name = filename.lower()
    explicit = _EXPLICIT_LABELS.get(name)
    if explicit is not None:
        return explicit
    for prefix, label in _PREFIX_TO_LABEL:
        if name.startswith(prefix):
            return label
    return None


def upgrade() -> None:
    op.add_column(
        "classification_records",
        sa.Column("machine_review_route", sa.String(length=20), nullable=True),
    )

    connection = op.get_bind()
    rows = connection.execute(
        sa.text("""
            SELECT cr.id, cr.review_route, cr.human_overridden, cr.expected_label, j.filename
            FROM classification_records cr
            JOIN jobs j ON j.job_id = cr.job_id
            WHERE cr.machine_review_route IS NULL OR cr.expected_label IS NULL
        """)
    ).fetchall()

    for row in rows:
        # An override proves the record was escalated: the decision endpoint rejects
        # anything not currently in human_review, so review_route was human_review at the
        # time even though it now reads accept.
        machine_route = _HUMAN_REVIEW if row.human_overridden else row.review_route
        updates: dict[str, object] = {"id": row.id, "machine_route": machine_route}
        assignments = "machine_review_route = :machine_route"

        if row.expected_label is None:
            label = _expected_label(row.filename)
            if label is not None:
                assignments += ", expected_label = :expected_label"
                updates["expected_label"] = label

        connection.execute(
            sa.text(f"UPDATE classification_records SET {assignments} WHERE id = :id"), updates
        )


def downgrade() -> None:
    # expected_label backfills are not reversed: rows written after this migration are
    # indistinguishable from the ones it filled, so clearing them would destroy data.
    op.drop_column("classification_records", "machine_review_route")
