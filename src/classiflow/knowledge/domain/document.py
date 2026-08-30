from classiflow.domain.base import BaseEntity


def format_citation(doc_type: str, number: str, year: str, filename: str) -> str:
    """Format a municipal document citation, e.g. `Decreto 810/2026`.

    Falls back to filename when doc_type/number/year could not be resolved.

    Returns:
        Human-readable citation string.
    """
    if doc_type and number and year:
        return f"{doc_type} {number}/{year}"
    return filename


class DocumentMetadata(BaseEntity):
    """Municipal metadata for one document, resolved from its own extracted entities.

    doc_type/number/year are best-effort: an entity extraction that didn't find a
    clear hint still produces a valid instance carrying only its filename, so
    retrieval keeps working and the citation just falls back to the filename.
    """

    filename: str
    doc_type: str = ""
    number: str = ""
    year: str = ""

    @property
    def citation(self) -> str:
        """Human-readable identifier, e.g. `Decreto 810/2026`."""
        return format_citation(self.doc_type, self.number, self.year, self.filename)

    def for_storage(self) -> "DocumentMetadata":
        """Return a copy with empty strings converted to None for database storage.

        Empty string means 'not resolved'; None means 'should be NULL in DB'. This
        makes the distinction explicit rather than using ambiguous `or None` operators
        at call sites. Filename is never converted (required).

        Returns:
            A new DocumentMetadata with storage-safe values.
        """
        return self.model_copy(
            update={
                k: v or None
                for k, v in self.__dict__.items()
                if k != "filename" and isinstance(v, str)
            }
        )
