import pytest

from classiflow.database.models import ClassificationRecord, Job
from classiflow.database.repositories.classification_record import (
    InMemoryClassificationRecordRepository,
)
from classiflow.database.repositories.job import InMemoryJobRepository
from classiflow.services.metrics.service import MetricsService

_EXPECTED_LABELLED = 2
_EXPECTED_CLASSIFIED = 2
_EXPECTED_HALF = 0.5
_EXPECTED_DECRETOS_PRECISION = 2 / 3
_EXPECTED_FUNNEL_JOBS = 3


def _record(
    job_id: str,
    *,
    label: str,
    expected_label: str | None = None,
    review_route: str = "accept",
    machine_review_route: str | None = None,
    human_overridden: bool = False,
    original_label: str | None = None,
) -> ClassificationRecord:
    return ClassificationRecord(
        job_id=job_id,
        enriched_id=1,
        label=label,
        confidence=0.9,
        all_scores={},
        second_opinion_confidence=0.0,
        classifier_disagreement=False,
        svm_scores={},
        svm_agrees_with_prediction=True,
        review_route=review_route,
        machine_review_route=machine_review_route or review_route,
        smells=[],
        risk_score=0,
        smell_review_suggested=False,
        judged_by_llm=False,
        human_overridden=human_overridden,
        original_label=original_label,
        expected_label=expected_label,
    )


async def _service(*records: ClassificationRecord) -> MetricsService:
    classification_repo = InMemoryClassificationRecordRepository()
    job_repo = InMemoryJobRepository()
    for record in records:
        await classification_repo.save(record)
        await job_repo.create(
            Job(job_id=record.job_id, filename=f"{record.job_id}.pdf", status="classified")
        )
    return MetricsService(classification_repo, job_repo)


class TestGroundTruthSources:
    async def test_scores_records_labelled_from_the_corpus(self) -> None:
        service = await _service(
            _record("a", label="ordenanzas", expected_label="ordenanzas"),
            _record("b", label="decretos", expected_label="boletines"),
        )

        report = await service.accuracy_report()

        assert report.labelled == _EXPECTED_LABELLED
        assert report.correct == 1
        assert report.strict_accuracy == pytest.approx(_EXPECTED_HALF)

    async def test_a_human_correction_is_ground_truth(self) -> None:
        # The reviewer's label is the truth; original_label is what the model missed.
        service = await _service(
            _record(
                "a",
                label="convenios",
                human_overridden=True,
                original_label="ordenanzas",
                review_route="accept",
            )
        )

        report = await service.accuracy_report()

        assert report.labelled == 1
        assert report.correct == 0
        assert report.misses[0].expected == "convenios"
        assert report.misses[0].predicted == "ordenanzas"

    async def test_records_without_ground_truth_are_excluded(self) -> None:
        service = await _service(
            _record("a", label="ordenanzas", expected_label="ordenanzas"),
            _record("b", label="decretos"),  # no expected_label, never overridden
        )

        report = await service.accuracy_report()

        assert report.total_classified == _EXPECTED_CLASSIFIED
        assert report.labelled == 1

    async def test_override_without_a_preserved_prediction_is_excluded(self) -> None:
        # Corrections made before original_label existed have nothing to score against:
        # `label` is the human's answer and the machine's is gone.
        service = await _service(
            _record("a", label="convenios", human_overridden=True, original_label=None)
        )

        report = await service.accuracy_report()

        assert report.labelled == 0

    async def test_override_without_a_prediction_is_excluded_despite_expected_label(
        self,
    ) -> None:
        # expected_label must not rescue an unrecoverable prediction: `label` holds the
        # reviewer's answer, so scoring it against the filename measures a human, not the
        # classifier. Affects all 13 corrections made before original_label existed.
        service = await _service(
            _record(
                "a",
                label="convenios",
                expected_label="convenios",
                human_overridden=True,
                original_label=None,
            )
        )

        report = await service.accuracy_report()

        assert report.labelled == 0
        assert report.correct == 0

    async def test_human_correction_outranks_the_filename_label(self) -> None:
        # A reviewer adjudicated this document; the filename convention is a weak label
        # and must not override them.
        service = await _service(
            _record(
                "a",
                label="convenios",
                expected_label="ordenanzas",
                human_overridden=True,
                original_label="ordenanzas",
            )
        )

        report = await service.accuracy_report()

        assert report.labelled == 1
        assert report.correct == 0
        assert report.misses[0].expected == "convenios"
        assert report.misses[0].predicted == "ordenanzas"


class TestSafetyNet:
    async def test_a_miss_routed_to_review_counts_as_caught(self) -> None:
        service = await _service(
            _record("a", label="decretos", expected_label="convenios", review_route="human_review"),
            _record("b", label="decretos", expected_label="boletines", review_route="accept"),
        )

        report = await service.accuracy_report()

        assert report.wrong_caught == 1
        assert report.wrong_uncaught == 1
        # Neither is correct, but one never reached a filing cabinet unreviewed.
        assert report.strict_accuracy == pytest.approx(0.0)
        assert report.safeguarded_accuracy == pytest.approx(_EXPECTED_HALF)

    async def test_a_resolved_miss_still_counts_as_caught(self) -> None:
        # review_route is mutated to accept when the reviewer resolves the item, so the
        # safety net's original decision has to come from machine_review_route -- reading
        # the mutable field scores a caught miss as uncaught.
        service = await _service(
            _record(
                "a",
                label="convenios",
                review_route="accept",
                machine_review_route="human_review",
                human_overridden=True,
                original_label="ordenanzas",
            )
        )

        report = await service.accuracy_report()

        assert report.wrong_caught == 1
        assert report.wrong_uncaught == 0
        assert report.misses[0].caught_by_safety_net is True


class TestPerCategory:
    async def test_precision_and_recall_are_computed_per_category(self) -> None:
        # decretos: predicted 3x, correct 2x -> precision 2/3. Expected 2x, correct 2x
        # -> recall 1.0. boletines: expected 1x, never predicted -> recall 0.0.
        service = await _service(
            _record("a", label="decretos", expected_label="decretos"),
            _record("b", label="decretos", expected_label="decretos"),
            _record("c", label="decretos", expected_label="boletines"),
        )

        report = await service.accuracy_report()
        by_category = {metric.category: metric for metric in report.per_category}

        assert by_category["decretos"].precision == pytest.approx(_EXPECTED_DECRETOS_PRECISION)
        assert by_category["decretos"].recall == pytest.approx(1.0)
        assert by_category["boletines"].recall == pytest.approx(0.0)
        assert by_category["boletines"].support == 1

    async def test_zero_support_category_does_not_divide_by_zero(self) -> None:
        service = await _service(_record("a", label="decretos", expected_label="decretos"))

        report = await service.accuracy_report()

        # Every other category has no labelled examples at all.
        assert "compendios_de_boletines" in report.unevaluated_categories
        assert "decretos" not in report.unevaluated_categories

    async def test_a_label_outside_the_taxonomy_is_reported_not_hidden(self) -> None:
        # A stale or corrupt label still gets scored, but must not pass silently as if it
        # were a real category.
        service = await _service(
            _record("a", label="not_a_category", expected_label="not_a_category")
        )

        report = await service.accuracy_report()

        assert report.unknown_labels == ["not_a_category"]

    async def test_known_categories_are_not_reported_as_unknown(self) -> None:
        service = await _service(_record("a", label="decretos", expected_label="decretos"))

        report = await service.accuracy_report()

        assert report.unknown_labels == []

    async def test_f1_is_zero_when_precision_and_recall_are_both_zero(self) -> None:
        service = await _service(_record("a", label="decretos", expected_label="boletines"))

        report = await service.accuracy_report()
        by_category = {metric.category: metric for metric in report.per_category}

        assert by_category["boletines"].f1 == pytest.approx(0.0)


class TestConfusionMatrix:
    async def test_counts_expected_to_predicted_pairs(self) -> None:
        service = await _service(
            _record("a", label="decretos", expected_label="decretos"),
            _record("b", label="ordenanzas", expected_label="decretos"),
            _record("c", label="ordenanzas", expected_label="decretos"),
        )

        report = await service.accuracy_report()

        assert report.confusion["decretos"] == {"decretos": 1, "ordenanzas": 2}


class TestPipelineFunnel:
    async def test_counts_jobs_that_never_reached_the_classifier(self) -> None:
        # A duplicate rejected at node4 has a Job but no ClassificationRecord. It is not
        # a classification error, so it must not dilute the accuracy denominator -- but
        # it still has to be accounted for, or the drop from ingested to classified looks
        # like documents went missing.
        classification_repo = InMemoryClassificationRecordRepository()
        job_repo = InMemoryJobRepository()
        await classification_repo.save(_record("a", label="decretos", expected_label="decretos"))
        await job_repo.create(Job(job_id="a", filename="a.pdf", status="classified"))
        await job_repo.create(Job(job_id="dup", filename="dup.pdf", status="rejected"))
        await job_repo.create(Job(job_id="boom", filename="boom.pdf", status="failed"))

        report = await MetricsService(classification_repo, job_repo).accuracy_report()

        assert report.total_jobs == _EXPECTED_FUNNEL_JOBS
        assert report.never_classified == _EXPECTED_LABELLED
        assert report.never_classified_by_status == {"rejected": 1, "failed": 1}
        assert report.total_classified == 1
        # The rejected duplicate does not count against accuracy.
        assert report.strict_accuracy == pytest.approx(1.0)


class TestEmptyDatabase:
    async def test_reports_zeroes_rather_than_dividing_by_zero(self) -> None:
        service = await _service()

        report = await service.accuracy_report()

        assert report.labelled == 0
        assert report.strict_accuracy == pytest.approx(0.0)
        assert report.safeguarded_accuracy == pytest.approx(0.0)
        assert report.misses == []
