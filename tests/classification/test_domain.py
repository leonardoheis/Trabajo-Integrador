import pytest

from classiflow.classification.domain.results import (
    JudgeOutput,
    PrimaryClassificationOutput,
    RoutingResult,
)
from classiflow.classification.domain.state import ClassificationUpdate
from classiflow.classification.exceptions import (
    ClassificationNotInReviewError,
    ClassificationRecordNotFoundError,
)


class TestResultDefaults:
    def test_primary_classification_output_defaults(self) -> None:
        result = PrimaryClassificationOutput(label="ordenanzas", confidence=0.9)
        assert result.all_scores == {}

    def test_judge_output_defaults(self) -> None:
        result = JudgeOutput(accept=True)
        assert not result.reasoning

    def test_routing_result_requires_stored_path(self) -> None:
        stored_path = "storage/documents/classified/ordenanzas/job-1_doc.pdf"
        result = RoutingResult(stored_path=stored_path)
        assert result.stored_path == stored_path


class TestClassificationUpdate:
    def test_dump_excludes_none_fields(self) -> None:
        update = ClassificationUpdate(label="ordenanzas", confidence=0.9)
        dumped = {k: v for k, v in update if v is not None}
        assert dumped == {"label": "ordenanzas", "confidence": 0.9}


class TestClassificationRecordNotFoundError:
    def test_message(self) -> None:
        exc = ClassificationRecordNotFoundError(job_id="job-1")
        assert str(exc) == "Classification record for job job-1 not found"

    def test_raises_with_context(self) -> None:
        with pytest.raises(ClassificationRecordNotFoundError, match="job-1"):
            raise ClassificationRecordNotFoundError(job_id="job-1")


class TestClassificationNotInReviewError:
    def test_message(self) -> None:
        exc = ClassificationNotInReviewError(job_id="job-1", review_route="accept")
        assert str(exc) == (
            "Classification for job job-1 is not awaiting human review (review_route=accept)"
        )
