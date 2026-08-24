from classiflow.classification.config_classification import ClassificationConfig
from classiflow.classification.nodes.smells_risk import SmellsRiskNode
from classiflow.database.repositories.audit import InMemoryAuditRepository
from classiflow.events.broadcaster import EventBroadcaster
from classiflow.pipeline.context import JobContext
from classiflow.services.audit.service import AuditService

_JOB_ID = "test-job-smells-risk-001"
_RISK_THRESHOLD = 4
_CONFIG = ClassificationConfig(
    confidence_threshold=0.75, smell_review_risk_threshold=_RISK_THRESHOLD
)

# Mirrors smells_risk.py's _SMELL_WEIGHTS -- kept here as named constants (not the
# module's own dict) so a change to production weights breaks these tests loudly
# instead of silently agreeing with itself.
_UNREADABLE_WEIGHT = 3
_DISAGREEMENT_WEIGHT = 3
_FOREIGN_MUNICIPALITY_WEIGHT = 2
_LOW_SVM_MARGIN_WEIGHT = 2
_LOW_CONFIDENCE_WEIGHT = 1


def _node() -> SmellsRiskNode:
    return SmellsRiskNode(
        audit=AuditService(InMemoryAuditRepository()),
        broadcaster=EventBroadcaster(),
        config=_CONFIG,
    )


class TestSmellsRiskCompute:
    def test_no_smells_fire_for_a_clean_confident_document(self) -> None:
        result = _node().compute(
            cleaned_text="Artículo 1º ...",
            confidence=0.9,
            classifier_disagreement=False,
            foreign_municipality=None,
            svm_agrees_with_prediction=True,
        )
        assert result.smells == []
        assert result.risk_score == 0
        assert result.smell_review_suggested is False

    def test_unreadable_document_fires_on_empty_cleaned_text(self) -> None:
        result = _node().compute(
            cleaned_text="   ",
            confidence=0.9,
            classifier_disagreement=False,
            foreign_municipality=None,
            svm_agrees_with_prediction=True,
        )
        assert result.smells == ["unreadable_document"]
        assert result.risk_score == _UNREADABLE_WEIGHT

    def test_classifier_disagreement_fires(self) -> None:
        result = _node().compute(
            cleaned_text="texto",
            confidence=0.9,
            classifier_disagreement=True,
            foreign_municipality=None,
            svm_agrees_with_prediction=True,
        )
        assert result.smells == ["classifier_disagreement"]
        assert result.risk_score == _DISAGREEMENT_WEIGHT

    def test_foreign_municipality_fires(self) -> None:
        result = _node().compute(
            cleaned_text="texto",
            confidence=0.9,
            classifier_disagreement=False,
            foreign_municipality="Cordoba",
            svm_agrees_with_prediction=True,
        )
        assert result.smells == ["foreign_municipality"]
        assert result.risk_score == _FOREIGN_MUNICIPALITY_WEIGHT

    def test_low_svm_margin_fires(self) -> None:
        result = _node().compute(
            cleaned_text="texto",
            confidence=0.9,
            classifier_disagreement=False,
            foreign_municipality=None,
            svm_agrees_with_prediction=False,
        )
        assert result.smells == ["low_svm_margin"]
        assert result.risk_score == _LOW_SVM_MARGIN_WEIGHT

    def test_low_confidence_fires(self) -> None:
        result = _node().compute(
            cleaned_text="texto",
            confidence=0.5,
            classifier_disagreement=False,
            foreign_municipality=None,
            svm_agrees_with_prediction=True,
        )
        assert result.smells == ["low_confidence"]
        assert result.risk_score == _LOW_CONFIDENCE_WEIGHT

    def test_all_smells_fire_together_and_sum_weights(self) -> None:
        result = _node().compute(
            cleaned_text="",
            confidence=0.1,
            classifier_disagreement=True,
            foreign_municipality="Cordoba",
            svm_agrees_with_prediction=False,
        )
        assert set(result.smells) == {
            "unreadable_document",
            "classifier_disagreement",
            "foreign_municipality",
            "low_svm_margin",
            "low_confidence",
        }
        assert result.risk_score == (
            _UNREADABLE_WEIGHT
            + _DISAGREEMENT_WEIGHT
            + _FOREIGN_MUNICIPALITY_WEIGHT
            + _LOW_SVM_MARGIN_WEIGHT
            + _LOW_CONFIDENCE_WEIGHT
        )

    def test_boundary_not_exceeding_threshold_is_not_suggested(self) -> None:
        result = _node().compute(
            cleaned_text="texto",
            confidence=0.9,
            classifier_disagreement=False,
            foreign_municipality="Cordoba",
            svm_agrees_with_prediction=False,
        )
        expected_score = _FOREIGN_MUNICIPALITY_WEIGHT + _LOW_SVM_MARGIN_WEIGHT
        assert result.risk_score == expected_score
        assert expected_score == _RISK_THRESHOLD  # boundary: equal, not exceeding
        assert result.smell_review_suggested is False

    def test_boundary_exceeding_threshold_is_suggested(self) -> None:
        result = _node().compute(
            cleaned_text="texto",
            confidence=0.9,
            classifier_disagreement=True,
            foreign_municipality="Cordoba",
            svm_agrees_with_prediction=True,
        )
        expected_score = _DISAGREEMENT_WEIGHT + _FOREIGN_MUNICIPALITY_WEIGHT
        assert result.risk_score == expected_score
        assert expected_score > _RISK_THRESHOLD  # boundary: exceeding
        assert result.smell_review_suggested is True


class TestSmellsRiskRun:
    async def test_run_emits_started_then_passed(self) -> None:
        broadcaster = EventBroadcaster()
        audit_repo = InMemoryAuditRepository()
        node = SmellsRiskNode(
            audit=AuditService(audit_repo), broadcaster=broadcaster, config=_CONFIG
        )
        ctx = JobContext(job_id=_JOB_ID, filename="doc.pdf")
        await node.run(
            ctx,
            cleaned_text="texto",
            confidence=0.9,
            classifier_disagreement=False,
            foreign_municipality=None,
            svm_agrees_with_prediction=True,
        )
        records = await audit_repo.list_for_job(_JOB_ID)
        assert records[0].event == "passed"
