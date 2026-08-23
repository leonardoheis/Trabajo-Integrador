from enum import Enum


class DocumentCategory(str, Enum):
    """Classiflow's 10 municipal document categories -- canonical label set, sourced
    from README.md's category table. BETO v2 (the Second Opinion Agent,
    classification/bert/) was only ever trained on 8 of these -- COMPENDIOS_DE_BOLETINES
    and CONVENIOS are LLM-only labels. See the BERT spec's Decision 5
    label-normalization map for the full BETO-to-Classiflow correspondence."""

    BOLETINES = "boletines"
    COMPENDIOS_DE_BOLETINES = "compendios_de_boletines"
    CONVENIOS = "convenios"
    DECLARACIONES_CONCEJO_MUNICIPAL = "declaraciones_concejo_municipal"
    DECRETO_ORDENANZAS = "decreto_ordenanzas"
    DECRETOS = "decretos"
    DECRETOS_CONCEJO_MUNICIPAL = "decretos_concejo_municipal"
    ORDENANZAS = "ordenanzas"
    RESOLUCIONES = "resoluciones"
    RESOLUCIONES_CONCEJO_MUNICIPAL = "resoluciones_concejo_municipal"
