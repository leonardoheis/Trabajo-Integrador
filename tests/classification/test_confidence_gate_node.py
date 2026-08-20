from classiflow.classification.config_classification import ClassificationConfig
from classiflow.classification.nodes.confidence_gate import ConfidenceGateNode
from classiflow.database.repositories.audit import InMemoryAuditRepository
from classiflow.events.broadcaster import EventBroadcaster
from classiflow.pipeline.context import JobContext
from classiflow.services.audit.service import AuditService

_JOB_ID = "test-job-confidence-gate-001"
_CONFIG = ClassificationConfig(confidence_threshold=0.75)


def _node() -> ConfidenceGateNode:
    return ConfidenceGateNode(
        audit=AuditService(InMemoryAuditRepository()),
        broadcaster=EventBroadcaster(),
        config=_CONFIG,
    )


class TestConfidenceGateDecide:
    def test_foreign_municipality_routes_to_human_review_regardless_of_confidence(self) -> None:
        route = _node().decide(
            confidence=0.99, foreign_municipality="Cordoba", classifier_disagreement=False
        )
        assert route == "human_review"

    def test_classifier_disagreement_routes_to_human_review_regardless_of_confidence(self) -> None:
        route = _node().decide(
            confidence=0.99, foreign_municipality=None, classifier_disagreement=True
        )
        assert route == "human_review"

    def test_high_confidence_with_no_flags_accepts(self) -> None:
        route = _node().decide(
            confidence=0.9, foreign_municipality=None, classifier_disagreement=False
        )
        assert route == "accept"

    def test_confidence_exactly_at_threshold_accepts(self) -> None:
        route = _node().decide(
            confidence=0.75, foreign_municipality=None, classifier_disagreement=False
        )
        assert route == "accept"

    def test_low_confidence_with_no_flags_goes_to_llm_judge(self) -> None:
        route = _node().decide(
            confidence=0.5, foreign_municipality=None, classifier_disagreement=False
        )
        assert route == "llm_judge"


class TestConfidenceGateRun:
    async def test_run_emits_started_then_passed(self) -> None:
        broadcaster = EventBroadcaster()
        audit_repo = InMemoryAuditRepository()
        node = ConfidenceGateNode(
            audit=AuditService(audit_repo), broadcaster=broadcaster, config=_CONFIG
        )
        ctx = JobContext(job_id=_JOB_ID, filename="doc.pdf")
        route = await node.run(
            ctx, confidence=0.9, foreign_municipality=None, classifier_disagreement=False
        )
        assert route == "accept"
        records = await audit_repo.list_for_job(_JOB_ID)
        assert records[0].event == "passed"
