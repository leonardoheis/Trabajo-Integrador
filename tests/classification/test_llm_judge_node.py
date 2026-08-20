import pytest

from classiflow.classification.exceptions import LlmJudgeFailedError
from classiflow.classification.nodes.llm_judge import LlmJudgeNode
from classiflow.classification.prompts.llm_judge import JudgeInput, build_judge_chain
from classiflow.database.repositories.audit import InMemoryAuditRepository
from classiflow.events.broadcaster import EventBroadcaster
from classiflow.ingesta.llm_provider import MockLlm
from classiflow.pipeline.context import JobContext
from classiflow.services.audit.service import AuditService

_JOB_ID = "test-job-llm-judge-001"
_VALID_RESPONSE = '{"accept": false, "reasoning": "second opinion strongly disagrees"}'
_JUDGE_INPUT = JudgeInput(
    cleaned_text="Artículo 1º — texto completo sin truncar ...",
    primary_label="ordenanzas",
    primary_confidence=0.6,
)


class TestLlmJudgeJudge:
    def test_judge_returns_output_on_valid_response(self) -> None:
        node = LlmJudgeNode(
            audit=AuditService(InMemoryAuditRepository()),
            broadcaster=EventBroadcaster(),
            judge_chain=build_judge_chain(MockLlm(response=_VALID_RESPONSE)),
        )
        result = node.judge(_JUDGE_INPUT)
        assert result.accept is False

    def test_judge_raises_domain_error_on_malformed_response(self) -> None:
        node = LlmJudgeNode(
            audit=AuditService(InMemoryAuditRepository()),
            broadcaster=EventBroadcaster(),
            judge_chain=build_judge_chain(MockLlm(response="not json")),
        )
        with pytest.raises(LlmJudgeFailedError, match="No valid JSON object"):
            node.judge(_JUDGE_INPUT)


class TestLlmJudgeRun:
    async def test_run_emits_started_then_passed(self) -> None:
        broadcaster = EventBroadcaster()
        audit_repo = InMemoryAuditRepository()
        node = LlmJudgeNode(
            audit=AuditService(audit_repo),
            broadcaster=broadcaster,
            judge_chain=build_judge_chain(MockLlm(response=_VALID_RESPONSE)),
        )
        ctx = JobContext(job_id=_JOB_ID, filename="doc.pdf")
        result = await node.run(ctx, _JUDGE_INPUT)
        assert result.accept is False
        records = await audit_repo.list_for_job(_JOB_ID)
        assert records[0].event == "passed"

    async def test_run_emits_failed_and_reraises_on_error(self) -> None:
        broadcaster = EventBroadcaster()
        audit_repo = InMemoryAuditRepository()
        node = LlmJudgeNode(
            audit=AuditService(audit_repo),
            broadcaster=broadcaster,
            judge_chain=build_judge_chain(MockLlm(response="not json")),
        )
        ctx = JobContext(job_id=_JOB_ID, filename="doc.pdf")
        with pytest.raises(LlmJudgeFailedError):
            await node.run(ctx, _JUDGE_INPUT)
        records = await audit_repo.list_for_job(_JOB_ID)
        assert records[0].event == "failed"
