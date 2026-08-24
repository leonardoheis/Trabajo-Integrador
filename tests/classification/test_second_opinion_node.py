from classiflow.classification.config_classification import ClassificationConfig
from classiflow.classification.domain.results import SecondOpinionResult
from classiflow.classification.nodes.second_opinion import SecondOpinionNode
from classiflow.database.repositories.audit import InMemoryAuditRepository
from classiflow.events.broadcaster import EventBroadcaster
from classiflow.pipeline.context import JobContext
from classiflow.services.audit.service import AuditService

_JOB_ID = "test-job-second-opinion-001"
_EXPECTED_CONFIDENCE = 0.8


class _FakeClassifier:
    def __init__(self, result: SecondOpinionResult) -> None:
        self._result = result

    def predict(self, _text: str) -> SecondOpinionResult:
        return self._result


class TestSecondOpinionNodeRun:
    async def test_returns_prediction_when_enabled(self) -> None:
        fake_result = SecondOpinionResult(label="ordenanza", confidence=_EXPECTED_CONFIDENCE)
        node = SecondOpinionNode(
            audit=AuditService(InMemoryAuditRepository()),
            broadcaster=EventBroadcaster(),
            classifier=_FakeClassifier(fake_result),
            config=ClassificationConfig(second_opinion_enabled=True),
        )
        ctx = JobContext(job_id=_JOB_ID, filename="doc.pdf")
        result = await node.run(ctx, "texto de prueba")
        assert result is not None
        assert result.label == "ordenanza"

    async def test_returns_none_when_disabled(self) -> None:
        node = SecondOpinionNode(
            audit=AuditService(InMemoryAuditRepository()),
            broadcaster=EventBroadcaster(),
            classifier=_FakeClassifier(SecondOpinionResult(label="x", confidence=0.5)),
            config=ClassificationConfig(second_opinion_enabled=False),
        )
        ctx = JobContext(job_id=_JOB_ID, filename="doc.pdf")
        result = await node.run(ctx, "texto de prueba")
        assert result is None

    async def test_emits_started_then_passed_when_enabled(self) -> None:
        broadcaster = EventBroadcaster()
        audit_repo = InMemoryAuditRepository()
        node = SecondOpinionNode(
            audit=AuditService(audit_repo),
            broadcaster=broadcaster,
            classifier=_FakeClassifier(
                SecondOpinionResult(label="ordenanza", confidence=_EXPECTED_CONFIDENCE)
            ),
            config=ClassificationConfig(second_opinion_enabled=True),
        )
        ctx = JobContext(job_id=_JOB_ID, filename="doc.pdf")
        await node.run(ctx, "texto de prueba")
        records = await audit_repo.list_for_job(_JOB_ID)
        assert records[0].event == "passed"
