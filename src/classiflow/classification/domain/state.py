from typing import TypedDict

from classiflow.domain.base import BaseEntity


class _ClassificationStateRequired(TypedDict):
    job_id: str
    filename: str
    cleaned_text: str
    enriched_id: int


class ClassificationState(_ClassificationStateRequired, total=False):
    label: str
    confidence: float
    all_scores: dict[str, float]
    # "" = second_opinion_enabled and the node ran but had no opinion (e.g. an
    # unmappable BETO label, per the BERT spec's design). Key absent (total=False)
    # = second_opinion_enabled is False and the node never ran. Collapsing both into
    # `str | None` would make "never checked" and "checked, no opinion" indistinguishable
    # to a reader of the merged state (e.g. Routing's audit-log write).
    second_opinion_label: str
    second_opinion_confidence: float
    classifier_disagreement: bool
    # {} = the node ran but produced no OOD signal. Key absent = it never ran.
    ood_metrics: dict[str, object]
    svm_scores: dict[str, float]
    svm_agrees_with_prediction: bool
    # "" = foreign_municipality_enabled and the node confirmed the document is
    # domestic. Key absent = foreign_municipality_enabled is False, never checked.
    # A non-empty string is the detected foreign municipality's name.
    foreign_municipality: str
    smells: list[str]
    risk_score: int
    smell_review_suggested: bool
    review_route: str
    judged_by_llm: bool
    stored_path: str


class ClassificationUpdate(BaseEntity):
    """Typed construction for a classification coordinator node's partial
    ClassificationState update — mirrors enrichment/domain/state.py's EnrichmentUpdate.

    On every field, `None` means "this update didn't set this field" (dropped by the
    `{k: v for k, v in update if v is not None}` dump, so it never overwrites the
    merged state). For second_opinion_label/ood_metrics/foreign_municipality
    specifically: a node reporting "ran, found nothing" must pass "" / {} — never
    None — or the result becomes indistinguishable from "this node didn't run" once
    merged into ClassificationState.
    """

    label: str | None = None
    confidence: float | None = None
    all_scores: dict[str, float] | None = None
    second_opinion_label: str | None = None
    second_opinion_confidence: float | None = None
    classifier_disagreement: bool | None = None
    ood_metrics: dict[str, object] | None = None
    svm_scores: dict[str, float] | None = None
    svm_agrees_with_prediction: bool | None = None
    foreign_municipality: str | None = None
    smells: list[str] | None = None
    risk_score: int | None = None
    smell_review_suggested: bool | None = None
    review_route: str | None = None
    judged_by_llm: bool | None = None
    stored_path: str | None = None
