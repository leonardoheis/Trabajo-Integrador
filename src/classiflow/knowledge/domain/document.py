from classiflow.domain.base import BaseEntity


def format_citation(doc_type: str, number: str, year: str, filename: str) -> str:
    """Format a municipal document citation, e.g. `Decreto 810/2026`.

    Falls back to filename when the document was not matched to a CSV row.

    Returns:
        Human-readable citation string.
    """
    if doc_type and number and year:
        return f"{doc_type} {number}/{year}"
    return filename


class DocumentMetadata(BaseEntity):
    """Municipal metadata for one document, resolved from the scrapper CSVs.

    Every field except `filename` is best-effort: a manually uploaded file that
    matches no CSV row still produces a valid instance carrying only its filename,
    so retrieval keeps working and the source simply has no download link.
    """

    filename: str
    doc_type: str = ""
    number: str = ""
    year: str = ""
    subject: str = ""
    sanction_date: str = ""
    publication_date: str = ""
    bulletin_number: str = ""
    download_url: str = ""
    source_csv: str = ""

    @property
    def citation(self) -> str:
        """Human-readable identifier, e.g. `Decreto 810/2026`."""
        return format_citation(self.doc_type, self.number, self.year, self.filename)

    def for_storage(self) -> "DocumentMetadata":
        """Return a copy with empty strings converted to None for database storage.

        Empty string means 'not in CSV'; None means 'should be NULL in DB'. This
        makes the distinction explicit rather than using ambiguous `or None` operators
        at call sites. Filename and source_csv are never converted (required/metadata).

        Returns:
            A new DocumentMetadata with storage-safe values.
        """
        return self.model_copy(
            update={
                k: v or None
                for k, v in self.__dict__.items()
                if k not in {"filename", "source_csv"} and isinstance(v, str)
            }
        )
