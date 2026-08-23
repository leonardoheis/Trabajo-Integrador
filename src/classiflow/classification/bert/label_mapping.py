"""BETO-to-Classiflow label normalization -- see the BERT spec's Decision 5. BETO v2 was
trained on 8 of Classiflow's 10 categories (singular Spanish, not plural snake_case) plus
its own "otro" catch-all with no Classiflow equivalent.

REVIEW AT END OF STAGE 4: normalize_bert_label currently has exactly one real caller
(classifier_disagreement, below) -- it's kept as a separate public function only because
it's already exported in bert/__init__.py's __all__ and independently unit-tested, not
because a second consumer exists yet. Once Task 9's SecondOpinionNode is built and its
actual usage is visible, revisit whether normalize_bert_label should stay standalone or
get folded into classifier_disagreement. Per the BERT spec (Decision on
ClassificationRecord fields), second_opinion_label stores BETO's RAW label, not the
normalized one -- so SecondOpinionNode is not expected to call normalize_bert_label
directly either."""

_LABEL_NORMALIZE: dict[str, str | None] = {
    "boletines": "boletines",
    "declaracion_concejo_municipal": "declaraciones_concejo_municipal",
    "decreto": "decretos",
    "decreto_ordenanza": "decreto_ordenanzas",
    "decretos_concejo_municipal": "decretos_concejo_municipal",
    "ordenanza": "ordenanzas",
    "resolucion": "resoluciones",
    "resolucion_concejo_municipal": "resoluciones_concejo_municipal",
    "otro": None,  # BETO's catch-all -- no Classiflow category equivalent
}
_BETO_TRAINED_LABELS = frozenset(v for v in _LABEL_NORMALIZE.values() if v is not None)


def normalize_bert_label(bert_label: str) -> str | None:
    return _LABEL_NORMALIZE.get(bert_label)


def classifier_disagreement(primary_label: str, second_opinion_label: str) -> bool:
    """primary_label is already in Classiflow's own taxonomy (the primary LLM
    classifier's output); second_opinion_label is BETO's raw label (its own taxonomy).

    Returns:
        False (not forced disagreement) when either label falls outside the mappable
        set: primary_label is convenios/compendios_de_boletines (BETO was never
        trained on these), or BETO's own label is otro. Mirrors bert_tunning's own
        svm_agrees_with_prediction default-True-on-missing-signal pattern rather than
        forcing a disagreement neither classifier can meaningfully confirm or deny.
        Otherwise, True iff the normalized labels differ.
    """
    normalized = normalize_bert_label(second_opinion_label)
    if normalized is None or primary_label not in _BETO_TRAINED_LABELS:
        return False
    return normalized != primary_label
