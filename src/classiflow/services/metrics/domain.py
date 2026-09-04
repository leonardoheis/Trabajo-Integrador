from pydantic import Field

from classiflow.domain.base import BaseEntity


class CategoryMetrics(BaseEntity):
    """Per-class scores for one category.

    `support` is how many documents genuinely belong to this category (the recall
    denominator); `predicted` is how many the model assigned to it (the precision
    denominator). Both can be zero -- a category with no examples in the corpus, or one
    the model never predicts -- so every rate here is 0.0 rather than undefined.
    """

    category: str
    support: int
    predicted: int
    correct: int
    precision: float
    recall: float
    f1: float


class Miss(BaseEntity):
    """One wrong prediction, and whether the safety net caught it."""

    job_id: str
    filename: str
    expected: str
    predicted: str
    review_route: str
    # True when the pipeline escalated instead of filing the wrong label unreviewed.
    caught_by_safety_net: bool


class AccuracyReport(BaseEntity):
    """Classification accuracy over every record that carries a ground-truth label.

    Two headline rates, deliberately kept apart:

    - `strict_accuracy` -- predicted == expected. What "accuracy" normally means.
    - `safeguarded_accuracy` -- correct, OR wrong but escalated to human_review before
      anything was filed. A claim about the safety net, not the classifier.

    Reporting only the second invites reading it as classifier accuracy, which it is not.
    """

    # Everything ever ingested, including documents that never reached the classifier.
    total_jobs: int
    # Stopped in Stage 1 -- duplicates, unsupported formats, failed extraction. Not
    # classification errors, so they are excluded from every rate below; surfaced so the
    # drop from total_jobs to total_classified is accounted for rather than unexplained.
    never_classified: int
    total_classified: int
    labelled: int
    correct: int
    # Wrong, but escalated to human_review -- a reviewer saw it before it was filed.
    wrong_caught: int
    # Wrong and filed anyway. The number that actually matters for trust.
    wrong_uncaught: int
    strict_accuracy: float
    safeguarded_accuracy: float
    per_category: list[CategoryMetrics] = Field(default_factory=list)
    # expected -> predicted -> count. Only rows with a ground-truth label appear.
    confusion: dict[str, dict[str, int]] = Field(default_factory=dict)
    misses: list[Miss] = Field(default_factory=list)
    # Categories in the taxonomy with zero labelled examples -- unevaluated, not perfect.
    unevaluated_categories: list[str] = Field(default_factory=list)
    # Labels found in the database that are not DocumentCategory members. Surfaced rather
    # than dropped: they are still scored, but they signal corrupt or stale data.
    unknown_labels: list[str] = Field(default_factory=list)
    # Job status -> count, for the documents that never reached the classifier (rejected
    # duplicates, failed extraction). Explains the gap between total_jobs and
    # total_classified without implying the classifier got anything wrong.
    never_classified_by_status: dict[str, int] = Field(default_factory=dict)
