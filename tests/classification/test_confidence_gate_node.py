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
    def test_foreign_municipality_routes_to_llm_judge_regardless_of_confidence(self) -> None:
        # The judge always runs for a flagged document (coordinator._judge_review_route
        # forces the final HUMAN_REVIEW outcome regardless of its verdict).
        route = _node().decide(
            primary_label="decretos",
            confidence=0.99,
            foreign_municipality="Cordoba",
            classifier_disagreement=False,
            risk_score=0,
        )
        assert route == "llm_judge"

    def test_classifier_disagreement_routes_to_llm_judge_regardless_of_confidence(self) -> None:
        route = _node().decide(
            primary_label="decretos",
            confidence=0.99,
            foreign_municipality=None,
            classifier_disagreement=True,
            risk_score=0,
        )
        assert route == "llm_judge"

    def test_disagreement_and_foreign_municipality_both_route_to_llm_judge(self) -> None:
        route = _node().decide(
            primary_label="decretos",
            confidence=0.99,
            foreign_municipality="Cordoba",
            classifier_disagreement=True,
            risk_score=0,
        )
        assert route == "llm_judge"

    def test_high_risk_score_routes_to_llm_judge_regardless_of_confidence(self) -> None:
        route = _node().decide(
            primary_label="decretos",
            confidence=0.99,
            foreign_municipality=None,
            classifier_disagreement=False,
            risk_score=_CONFIG.smell_review_risk_threshold + 1,
        )
        assert route == "llm_judge"

    def test_risk_score_at_threshold_does_not_force_llm_judge(self) -> None:
        route = _node().decide(
            primary_label="decretos",
            confidence=0.9,
            foreign_municipality=None,
            classifier_disagreement=False,
            risk_score=_CONFIG.smell_review_risk_threshold,
        )
        assert route == "accept"

    def test_high_confidence_with_no_flags_accepts(self) -> None:
        route = _node().decide(
            primary_label="decretos",
            confidence=0.9,
            foreign_municipality=None,
            classifier_disagreement=False,
            risk_score=0,
        )
        assert route == "accept"

    def test_confidence_exactly_at_threshold_accepts(self) -> None:
        route = _node().decide(
            primary_label="decretos",
            confidence=0.75,
            foreign_municipality=None,
            classifier_disagreement=False,
            risk_score=0,
        )
        assert route == "accept"

    def test_low_confidence_with_no_flags_goes_to_llm_judge(self) -> None:
        route = _node().decide(
            primary_label="decretos",
            confidence=0.5,
            foreign_municipality=None,
            classifier_disagreement=False,
            risk_score=0,
        )
        assert route == "llm_judge"

    def test_primary_label_otro_routes_to_llm_judge_regardless_of_confidence(self) -> None:
        route = _node().decide(
            primary_label="otro",
            confidence=0.99,
            foreign_municipality=None,
            classifier_disagreement=False,
            risk_score=0,
        )
        assert route == "llm_judge"

    def test_foreign_municipality_and_otro_both_route_to_llm_judge(self) -> None:
        route = _node().decide(
            primary_label="otro",
            confidence=0.99,
            foreign_municipality="Cordoba",
            classifier_disagreement=False,
            risk_score=0,
        )
        assert route == "llm_judge"


class TestConfidenceGateForcesHumanReview:
    def test_true_for_each_flag_independently(self) -> None:
        node = _node()
        assert node.forces_human_review(
            primary_label="decretos",
            foreign_municipality=None,
            classifier_disagreement=True,
            risk_score=0,
        )
        assert node.forces_human_review(
            primary_label="decretos",
            foreign_municipality=None,
            classifier_disagreement=False,
            risk_score=_CONFIG.smell_review_risk_threshold + 1,
        )
        assert node.forces_human_review(
            primary_label="decretos",
            foreign_municipality="Cordoba",
            classifier_disagreement=False,
            risk_score=0,
        )
        assert node.forces_human_review(
            primary_label="otro",
            foreign_municipality=None,
            classifier_disagreement=False,
            risk_score=0,
        )

    def test_false_with_no_flags(self) -> None:
        assert not _node().forces_human_review(
            primary_label="decretos",
            foreign_municipality=None,
            classifier_disagreement=False,
            risk_score=0,
        )


class TestConfidenceGateRun:
    async def test_run_emits_started_then_passed(self) -> None:
        broadcaster = EventBroadcaster()
        audit_repo = InMemoryAuditRepository()
        node = ConfidenceGateNode(
            audit=AuditService(audit_repo), broadcaster=broadcaster, config=_CONFIG
        )
        ctx = JobContext(job_id=_JOB_ID, filename="doc.pdf")
        route = await node.run(
            ctx,
            primary_label="decretos",
            confidence=0.9,
            foreign_municipality=None,
            classifier_disagreement=False,
            risk_score=0,
        )
        assert route == "accept"
        records = await audit_repo.list_for_job(_JOB_ID)
        assert records[0].event == "passed"
