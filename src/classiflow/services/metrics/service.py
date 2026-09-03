from collections import Counter, defaultdict

from classiflow.classification.domain.categories import DocumentCategory
from classiflow.classification.domain.review_route import ReviewRoute
from classiflow.database.models import ClassificationRecord
from classiflow.domain.repositories.classification_record import IClassificationRecordRepository
from classiflow.domain.repositories.job import IJobRepository
from classiflow.services.metrics.domain import AccuracyReport, CategoryMetrics, Miss


def _ground_truth(record: ClassificationRecord) -> str | None:
    """The known-correct label for a record, or None when it has no ground truth.

    Two independent sources, in priority order:

    1. `expected_label` -- the corpus filing convention (see classification/ground_truth.py).
    2. A human correction -- when a reviewer overrode the classification, THEIR label is
       the truth and `original_label` holds the machine's miss. Only trusted when
       `original_label` is actually populated: corrections made before that column
       existed set human_overridden without preserving what the model had said, and for
       those `label` is the human's answer with nothing to score it against.

    Returns:
        The ground-truth label, or None when the record carries none.
    """
    if record.expected_label is not None:
        return record.expected_label
    if record.human_overridden and record.original_label is not None:
        return record.label
    return None


def _prediction(record: ClassificationRecord) -> str | None:
    """What the machine predicted, which is not always `label`.

    After a human override `label` holds the reviewer's choice; the machine's own
    prediction moved to `original_label`.

    Returns:
        The machine's predicted label, or None if the record has none.
    """
    if record.human_overridden and record.original_label is not None:
        return record.original_label
    return record.label


def _safe_divide(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


class MetricsService:
    def __init__(
        self,
        classification_repo: IClassificationRecordRepository,
        job_repo: IJobRepository,
    ) -> None:
        self._classification_repo = classification_repo
        self._job_repo = job_repo

    async def accuracy_report(self) -> AccuracyReport:
        records = await self._classification_repo.list_all()
        jobs = await self._job_repo.list_all()
        filenames = {job.job_id: job.filename for job in jobs}

        classified_job_ids = {record.job_id for record in records}
        never_classified = Counter(
            job.status for job in jobs if job.job_id not in classified_job_ids
        )

        scored: list[tuple[ClassificationRecord, str, str]] = []
        for record in records:
            expected = _ground_truth(record)
            predicted = _prediction(record)
            if expected is None or predicted is None:
                continue
            scored.append((record, expected, predicted))

        support = Counter(expected for _, expected, _ in scored)
        predicted_counts = Counter(predicted for _, _, predicted in scored)
        hits = Counter(expected for _, expected, predicted in scored if expected == predicted)

        confusion: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for _, expected, predicted in scored:
            confusion[expected][predicted] += 1

        misses = [
            Miss(
                job_id=record.job_id,
                filename=filenames.get(record.job_id, ""),
                expected=expected,
                predicted=predicted,
                review_route=record.review_route,
                caught_by_safety_net=record.review_route == ReviewRoute.HUMAN_REVIEW,
            )
            for record, expected, predicted in scored
            if expected != predicted
        ]

        labelled = len(scored)
        correct = sum(hits.values())
        wrong_caught = sum(1 for miss in misses if miss.caught_by_safety_net)

        return AccuracyReport(
            total_jobs=len(jobs),
            never_classified=sum(never_classified.values()),
            never_classified_by_status=dict(never_classified),
            total_classified=len(records),
            labelled=labelled,
            correct=correct,
            wrong_caught=wrong_caught,
            wrong_uncaught=len(misses) - wrong_caught,
            strict_accuracy=_safe_divide(correct, labelled),
            safeguarded_accuracy=_safe_divide(correct + wrong_caught, labelled),
            per_category=[
                _category_metrics(category, support, predicted_counts, hits)
                for category in sorted(support)
            ],
            confusion={expected: dict(row) for expected, row in confusion.items()},
            misses=misses,
            # A category nothing was labelled with is unevaluated, which is not the same
            # as scoring 1.0 on it -- surfacing the gap keeps it from reading as coverage.
            unevaluated_categories=sorted(
                category.value for category in DocumentCategory if category.value not in support
            ),
        )


def _category_metrics(
    category: str,
    support: Counter[str],
    predicted_counts: Counter[str],
    hits: Counter[str],
) -> CategoryMetrics:
    correct = hits[category]
    precision = _safe_divide(correct, predicted_counts[category])
    recall = _safe_divide(correct, support[category])
    denominator = precision + recall
    return CategoryMetrics(
        category=category,
        support=support[category],
        predicted=predicted_counts[category],
        correct=correct,
        precision=precision,
        recall=recall,
        f1=(2 * precision * recall / denominator) if denominator else 0.0,
    )
