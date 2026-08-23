import pytest

from classiflow.classification.config_classification import ClassificationConfig
from classiflow.classification.exceptions import PrimaryClassificationFailedError
from classiflow.classification.nodes.primary_classifier import PrimaryClassifierNode
from classiflow.classification.prompts.primary_classification import build_classification_chain
from classiflow.database.repositories.audit import InMemoryAuditRepository
from classiflow.events.broadcaster import EventBroadcaster
from classiflow.ingesta.llm_provider import MockLlm
from classiflow.pipeline.context import JobContext
from classiflow.services.audit.service import AuditService

_JOB_ID = "test-job-classify-001"
_VALID_RESPONSE = '{"label": "decretos", "confidence": 0.8, "reasoning": "..."}'
_EXPECTED_CONFIDENCE = 0.8


def _node(response: str) -> PrimaryClassifierNode:
    return PrimaryClassifierNode(
        audit=AuditService(InMemoryAuditRepository()),
        broadcaster=EventBroadcaster(),
        classification_chain=build_classification_chain(MockLlm(response=response)),
    )


class TestPrimaryClassifierClassify:
    def test_classify_returns_result_on_valid_response(self) -> None:
        result = _node(_VALID_RESPONSE).classify("Decreto 42 ...")
        assert result.label == "decretos"
        assert result.confidence == _EXPECTED_CONFIDENCE

    def test_classify_raises_domain_error_on_malformed_response(self) -> None:
        with pytest.raises(PrimaryClassificationFailedError, match="No valid JSON object"):
            _node("not json").classify("Decreto 42 ...")


class TestPrimaryClassifierRun:
    async def test_run_emits_started_then_passed(self) -> None:
        broadcaster = EventBroadcaster()
        audit_repo = InMemoryAuditRepository()
        node = PrimaryClassifierNode(
            audit=AuditService(audit_repo),
            broadcaster=broadcaster,
            classification_chain=build_classification_chain(MockLlm(response=_VALID_RESPONSE)),
        )
        ctx = JobContext(job_id=_JOB_ID, filename="doc.pdf")
        result = await node.run(ctx, "Decreto 42 ...")
        assert result.label == "decretos"
        records = await audit_repo.list_for_job(_JOB_ID)
        assert records[0].event == "passed"

    async def test_run_emits_failed_and_reraises_on_error(self) -> None:
        broadcaster = EventBroadcaster()
        audit_repo = InMemoryAuditRepository()
        node = PrimaryClassifierNode(
            audit=AuditService(audit_repo),
            broadcaster=broadcaster,
            classification_chain=build_classification_chain(MockLlm(response="not json")),
        )
        ctx = JobContext(job_id=_JOB_ID, filename="doc.pdf")
        with pytest.raises(PrimaryClassificationFailedError):
            await node.run(ctx, "Decreto 42 ...")
        records = await audit_repo.list_for_job(_JOB_ID)
        assert records[0].event == "failed"

    async def test_run_truncates_to_max_input_tokens(self) -> None:
        broadcaster = EventBroadcaster()
        node = PrimaryClassifierNode(
            audit=AuditService(InMemoryAuditRepository()),
            broadcaster=broadcaster,
            classification_chain=build_classification_chain(MockLlm(response=_VALID_RESPONSE)),
            config=ClassificationConfig(max_input_tokens=5),
        )
        ctx = JobContext(job_id=_JOB_ID, filename="doc.pdf")
        result = await node.run(ctx, "Decreto 42, largo texto que supera el límite")
        assert result.label == "decretos"
