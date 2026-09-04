"""Corpus ground truth derived from a document's filename.

The municipal corpus names every file after the category it was filed under
(`ordenanza_9964_2019.pdf`, `decreto_cm_68770_2025.pdf`), so the filename itself is a
label -- the same convention the Stage 4 notebook's `_SAMPLE_FILES` dict encodes by hand.
Deriving it means the labelled set grows with the corpus instead of staying frozen at the
12 files someone typed out.

This is a *weak* label: it reflects how the source archive filed the document, not an
independent adjudication. It is good enough to compute per-category accuracy over hundreds
of documents, which hand-labelling never will be.
"""

from classiflow.classification.domain.categories import DocumentCategory

# Longest prefix first: "decreto_cm_" and "decreto_ordenanza_" must both be tested before
# the bare "decreto_" they start with, or every council decree scores as a plain decree.
_PREFIX_TO_CATEGORY: tuple[tuple[str, DocumentCategory], ...] = (
    ("decreto_ordenanza_", DocumentCategory.DECRETO_ORDENANZAS),
    ("decreto_cm_", DocumentCategory.DECRETOS_CONCEJO_MUNICIPAL),
    ("resolucion_cm_", DocumentCategory.RESOLUCIONES_CONCEJO_MUNICIPAL),
    ("declaracion_", DocumentCategory.DECLARACIONES_CONCEJO_MUNICIPAL),
    ("ordenanza_", DocumentCategory.ORDENANZAS),
    ("resolucion_", DocumentCategory.RESOLUCIONES),
    ("convenio_", DocumentCategory.CONVENIOS),
    ("boletin_", DocumentCategory.BOLETINES),
    ("decreto_", DocumentCategory.DECRETOS),
)

# Non-municipal documents follow no naming convention, so they are listed by name.
# OTRO is a real category the classifier predicts -- these are labelled examples.
_EXPLICIT_LABELS: dict[str, DocumentCategory] = {
    "a0470.pdf": DocumentCategory.OTRO,  # Banco Central "Comunicación A 470"
    "informe_agosto_2021.pdf": DocumentCategory.OTRO,
    "dia_a_grupos_actualizados.xlsx": DocumentCategory.OTRO,
    "v-reqcac_17-08-24.pdf": DocumentCategory.OTRO,
}


def expected_category(filename: str) -> DocumentCategory | None:
    """The category a filename claims, by the corpus filing convention.

    Returns:
        The matched category, or None when the convention says nothing about this name.
        None means "unlabelled", which keeps the document out of the accuracy
        denominator -- it is not a claim that the document is out of scope. Documents
        that genuinely aren't municipal acts belong to DocumentCategory.OTRO, which the
        classifier can and does predict, so they are labelled explicitly rather than
        left as None.
    """
    name = filename.lower()
    explicit = _EXPLICIT_LABELS.get(name)
    if explicit is not None:
        return explicit
    for prefix, category in _PREFIX_TO_CATEGORY:
        if name.startswith(prefix):
            return category
    return None


def expected_label(filename: str) -> str | None:
    """`expected_category` as the bare string the DB column and RoutingInput store.

    Returns:
        The category's string value, or None when the filename claims no category.
    """
    category = expected_category(filename)
    return category.value if category is not None else None
