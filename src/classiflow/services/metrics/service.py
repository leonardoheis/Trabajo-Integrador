from collections import Counter, defaultdict
from typing import NamedTuple

from classiflow.classification.domain.categories import DocumentCategory
from classiflow.classification.domain.review_route import ReviewRoute
from classiflow.database.models import ClassificationRecord
from classiflow.domain.repositories.classification_record import IClassificationRecordRepository
from classiflow.domain.repositories.job import IJobRepository
from classiflow.services.metrics.domain import AccuracyReport, CategoryMetrics, Miss

_KNOWN_CATEGORIES = {category.value for category in DocumentCategory}


class ScoredRecord(NamedTuple):
    """One record reduced to the pair accuracy is computed from."""

    record: ClassificationRecord
    truth: str
    prediction: str


def _score(record: ClassificationRecord) -> ScoredRecord | None:
    """Pair a record's ground truth with the machine prediction to judge it against.

    Returns:
        None when the record cannot be scored, which excludes it from every rate.
    """
    if record.human_overridden:
        # A reviewer's adjudication outranks the weak filename label. Without
        # original_label the machine's prediction is gone, leaving nothing to score.
        if record.original_label is None or record.label is None:
            return None
        return ScoredRecord(record, truth=record.label, prediction=record.original_label)
    if record.expected_label is not None and record.label is not None:
        return ScoredRecord(record, truth=record.expected_label, prediction=record.label)
    return None


def _was_escalated(record: ClassificationRecord) -> bool:
    """Whether the safety net caught this prediction when it was first made.

    Returns:
        False when unknown: `machine_review_route` is NULL for rows written before it
        existed, and counting those as caught would overstate the safeguard.
    """
    return record.machine_review_route == ReviewRoute.HUMAN_REVIEW


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

        scored = [scored for record in records if (scored := _score(record)) is not None]

        support = Counter(entry.truth for entry in scored)
        predicted_counts = Counter(entry.prediction for entry in scored)
        hits = Counter(entry.truth for entry in scored if entry.truth == entry.prediction)

        confusion: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for entry in scored:
            confusion[entry.truth][entry.prediction] += 1

        misses = [
            Miss(
                job_id=entry.record.job_id,
                filename=filenames.get(entry.record.job_id, ""),
                expected=entry.truth,
                predicted=entry.prediction,
                review_route=entry.record.review_route,
                caught_by_safety_net=_was_escalated(entry.record),
            )
            for entry in scored
            if entry.truth != entry.prediction
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
            unknown_labels=sorted(
                (set(support) | set(predicted_counts)) - _KNOWN_CATEGORIES,
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
