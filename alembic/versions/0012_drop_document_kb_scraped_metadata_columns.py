"""Drop scraped-catalogue-only columns from document_kb

subject/sanction_date/publication_date/bulletin_number/download_url only ever came
from the scrapper CSVs, which are no longer a dependency -- doc_type/number/year
(kept) now come from the document's own extracted entities instead.

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-30

"""

import sqlalchemy as sa

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("document_kb", "subject")
    op.drop_column("document_kb", "sanction_date")
    op.drop_column("document_kb", "publication_date")
    op.drop_column("document_kb", "bulletin_number")
    op.drop_column("document_kb", "download_url")


def downgrade() -> None:
    op.add_column("document_kb", sa.Column("download_url", sa.Text(), nullable=True))
    op.add_column(
        "document_kb", sa.Column("bulletin_number", sa.String(length=20), nullable=True)
    )
    op.add_column(
        "document_kb", sa.Column("publication_date", sa.String(length=20), nullable=True)
    )
    op.add_column("document_kb", sa.Column("sanction_date", sa.String(length=20), nullable=True))
    op.add_column("document_kb", sa.Column("subject", sa.Text(), nullable=True))
