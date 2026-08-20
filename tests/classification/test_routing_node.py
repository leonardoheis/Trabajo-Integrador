from classiflow.classification.domain.results import RoutingInput
from classiflow.classification.nodes.routing import RoutingNode
from classiflow.database.repositories.audit import InMemoryAuditRepository
from classiflow.database.repositories.classification_record import (
    InMemoryClassificationRecordRepository,
)
from classiflow.events.broadcaster import EventBroadcaster
from classiflow.pipeline.context import JobContext
from classiflow.services.audit.service import AuditService

_JOB_ID = "test-job-routing-001"


class _FakeStorage:
    def __init__(self) -> None:
        self.moved: list[tuple[str, str, str]] = []

    async def save_staged(self, job_id: str, filename: str, file_bytes: bytes) -> str:
        raise NotImplementedError

    async def move_to_final(self, job_id: str, filename: str, subdirectory: str) -> str:
        self.moved.append((job_id, filename, subdirectory))
        return f"/storage/documents/{subdirectory}/{job_id}_{filename}"


def _routing_input(**overrides: object) -> RoutingInput:
    defaults: dict[str, object] = {
        "job_id": _JOB_ID,
        "filename": "doc.pdf",
        "enriched_id": 1,
        "label": "ordenanzas",
        "confidence": 0.9,
        "review_route": "accept",
    }
    defaults.update(overrides)
    return RoutingInput.model_validate(defaults)


class TestRoutingNodeRun:
    async def test_accept_moves_to_classified_subdirectory(self) -> None:
        storage = _FakeStorage()
        node = RoutingNode(
            audit=AuditService(InMemoryAuditRepository()),
            broadcaster=EventBroadcaster(),
            storage=storage,
            classification_repo=InMemoryClassificationRecordRepository(),
        )
        ctx = JobContext(job_id=_JOB_ID, filename="doc.pdf")
        result = await node.run(ctx, _routing_input(review_route="accept", label="ordenanzas"))
        assert storage.moved == [(_JOB_ID, "doc.pdf", "classified/ordenanzas")]
        assert "classified/ordenanzas" in result.stored_path

    async def test_human_review_moves_to_review_subdirectory(self) -> None:
        storage = _FakeStorage()
        node = RoutingNode(
            audit=AuditService(InMemoryAuditRepository()),
            broadcaster=EventBroadcaster(),
            storage=storage,
            classification_repo=InMemoryClassificationRecordRepository(),
        )
        ctx = JobContext(job_id=_JOB_ID, filename="doc.pdf")
        result = await node.run(ctx, _routing_input(review_route="human_review"))
        assert storage.moved == [(_JOB_ID, "doc.pdf", "review/human_review")]
        assert "review/human_review" in result.stored_path

    async def test_persists_classification_record(self) -> None:
        repo = InMemoryClassificationRecordRepository()
        node = RoutingNode(
            audit=AuditService(InMemoryAuditRepository()),
            broadcaster=EventBroadcaster(),
            storage=_FakeStorage(),
            classification_repo=repo,
        )
        ctx = JobContext(job_id=_JOB_ID, filename="doc.pdf")
        await node.run(
            ctx, _routing_input(label="ordenanzas", confidence=0.9, review_route="accept")
        )
        record = await repo.find_by_job_id(_JOB_ID)
        assert record is not None
        assert record.label == "ordenanzas"
        assert record.stored_path is not None

    async def test_second_call_updates_the_same_record_not_a_duplicate(self) -> None:
        repo = InMemoryClassificationRecordRepository()
        node = RoutingNode(
            audit=AuditService(InMemoryAuditRepository()),
            broadcaster=EventBroadcaster(),
            storage=_FakeStorage(),
            classification_repo=repo,
        )
        ctx = JobContext(job_id=_JOB_ID, filename="doc.pdf")
        await node.run(ctx, _routing_input(review_route="human_review"))
        await node.run(
            ctx, _routing_input(review_route="accept", label="ordenanzas", human_overridden=True)
        )
        record = await repo.find_by_job_id(_JOB_ID)
        assert record is not None
        assert record.review_route == "accept"
        assert record.human_overridden is True
