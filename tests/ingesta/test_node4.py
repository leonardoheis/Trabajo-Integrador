import asyncio
from unittest.mock import MagicMock

import numpy as np
import numpy.typing as npt
import pytest

from classiflow.database.repositories.audit import InMemoryAuditRepository
from classiflow.database.repositories.hash import InMemoryHashRepository
from classiflow.domain.job import JobStatus
from classiflow.events.broadcaster import EventBroadcaster
from classiflow.ingesta.domain import JobContext
from classiflow.ingesta.nodes import DuplicateControlNode
from classiflow.ingesta.nodes.node4_duplicate_control import (
    EmbeddingStore,
    get_sentence_model,
    unload_duplicate_control_embedder,
)
from classiflow.services.audit.service import AuditService

_DIM = 4
_JOB_ID = "test-job-004"
_FILENAME = "test.pdf"
_SHA256 = "a" * 64
_TEXT_A = "Municipal ordinance about urban planning."
_TEXT_B = "Another ordinance about city planning."
_STARTED_PLUS_OUTCOME = 2
_COSINE_THRESHOLD = 0.85

_CTX = JobContext(job_id=_JOB_ID, filename=_FILENAME)


def _stub_embed_fixed(_text: str) -> npt.NDArray[np.float32]:
    return np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)


def _stub_embed_orthogonal(_text: str) -> npt.NDArray[np.float32]:
    return np.array([0.0, 1.0, 0.0, 0.0], dtype=np.float32)


@pytest.fixture
def hash_repo() -> InMemoryHashRepository:
    return InMemoryHashRepository()


@pytest.fixture
def audit_repo() -> InMemoryAuditRepository:
    return InMemoryAuditRepository()


@pytest.fixture
def audit(audit_repo: InMemoryAuditRepository) -> AuditService:
    return AuditService(audit_repo)


@pytest.fixture
def broadcaster() -> EventBroadcaster:
    return EventBroadcaster()


@pytest.fixture
def store() -> EmbeddingStore:
    return EmbeddingStore(dim=_DIM, embed_fn=_stub_embed_fixed)


@pytest.fixture
def node(
    hash_repo: InMemoryHashRepository,
    audit: AuditService,
    broadcaster: EventBroadcaster,
    store: EmbeddingStore,
) -> DuplicateControlNode:
    return DuplicateControlNode(
        hash_repo=hash_repo,
        audit=audit,
        broadcaster=broadcaster,
        embedding_store=store,
    )


class TestDuplicateControlNode:
    async def test_exact_duplicate_fails(
        self,
        node: DuplicateControlNode,
        hash_repo: InMemoryHashRepository,
        audit_repo: InMemoryAuditRepository,
    ) -> None:
        await hash_repo.save(_SHA256, "previous-job")

        result = await node.run(_CTX, _SHA256, _TEXT_A)

        assert not result.passed
        assert result.is_duplicate
        assert result.duplicate_type == "exact"
        assert result.similarity_score >= 1.0
        records = await audit_repo.list_for_job(_JOB_ID)
        assert records[0].event == JobStatus.FAILED.value

    async def test_semantic_duplicate_fails(
        self,
        node: DuplicateControlNode,
        store: EmbeddingStore,
        audit_repo: InMemoryAuditRepository,
    ) -> None:
        store.add(_TEXT_A)  # pre-populate: [1,0,0,0]

        result = await node.run(_CTX, _SHA256, _TEXT_B)

        assert not result.passed
        assert result.is_duplicate
        assert result.duplicate_type == "semantic"
        assert result.similarity_score >= _COSINE_THRESHOLD
        records = await audit_repo.list_for_job(_JOB_ID)
        assert records[0].event == JobStatus.FAILED.value

    async def test_new_document_passes(
        self,
        node: DuplicateControlNode,
        hash_repo: InMemoryHashRepository,
        audit_repo: InMemoryAuditRepository,
    ) -> None:
        result = await node.run(_CTX, _SHA256, _TEXT_A)

        assert result.passed
        assert not result.is_duplicate
        assert await hash_repo.exists(_SHA256)
        records = await audit_repo.list_for_job(_JOB_ID)
        assert records[0].event == JobStatus.PASSED.value

    async def test_dissimilar_document_passes(
        self,
        audit: AuditService,
        broadcaster: EventBroadcaster,
        hash_repo: InMemoryHashRepository,
    ) -> None:
        store_a = EmbeddingStore(dim=_DIM, embed_fn=_stub_embed_fixed)
        store_b = EmbeddingStore(dim=_DIM, embed_fn=_stub_embed_orthogonal)

        DuplicateControlNode(
            hash_repo=hash_repo,
            audit=audit,
            broadcaster=broadcaster,
            embedding_store=store_a,
        )
        store_a.add(_TEXT_A)

        node_b = DuplicateControlNode(
            hash_repo=hash_repo,
            audit=audit,
            broadcaster=broadcaster,
            embedding_store=store_b,
        )
        result = await node_b.run(_CTX, _SHA256, _TEXT_B)

        assert result.passed
        assert not result.is_duplicate

    async def test_emits_started_then_passed(
        self,
        node: DuplicateControlNode,
        broadcaster: EventBroadcaster,
    ) -> None:
        events: list[object] = []

        async def collect() -> None:
            events.extend([event async for event in broadcaster.subscribe(_JOB_ID)])

        collect_task = asyncio.create_task(collect())
        await asyncio.sleep(0)
        await node.run(_CTX, _SHA256, _TEXT_A)
        await broadcaster.close(_JOB_ID)
        await collect_task

        assert len(events) == _STARTED_PLUS_OUTCOME
        assert events[0].status == JobStatus.STARTED  # type: ignore[union-attr]
        assert events[0].node == "node4_duplicate_control"  # type: ignore[union-attr]
        assert events[1].status == JobStatus.PASSED  # type: ignore[union-attr]

    async def test_emits_started_then_failed_on_duplicate(
        self,
        node: DuplicateControlNode,
        broadcaster: EventBroadcaster,
        hash_repo: InMemoryHashRepository,
    ) -> None:
        await hash_repo.save(_SHA256, "previous-job")

        events: list[object] = []

        async def collect() -> None:
            events.extend([event async for event in broadcaster.subscribe(_JOB_ID)])

        collect_task = asyncio.create_task(collect())
        await asyncio.sleep(0)
        await node.run(_CTX, _SHA256, _TEXT_A)
        await broadcaster.close(_JOB_ID)
        await collect_task

        assert len(events) == _STARTED_PLUS_OUTCOME
        assert events[1].status == JobStatus.FAILED  # type: ignore[union-attr]

    async def test_audit_records_duration(
        self,
        node: DuplicateControlNode,
        audit_repo: InMemoryAuditRepository,
    ) -> None:
        await node.run(_CTX, _SHA256, _TEXT_A)

        records = await audit_repo.list_for_job(_JOB_ID)
        assert records[0].duration_ms is not None
        assert records[0].duration_ms >= 0


class TestUnloadDuplicateControlEmbedder:
    def test_forces_a_reload_on_the_next_call(self, monkeypatch: pytest.MonkeyPatch) -> None:
        EXPECTED_CALL_COUNT_AFTER_FIRST_CALL = 1
        EXPECTED_CALL_COUNT_AFTER_RELOAD = 2
        mock_transformer = MagicMock(side_effect=lambda *_args, **_kwargs: object())
        monkeypatch.setattr(
            "classiflow.ingesta.nodes.node4_duplicate_control.SentenceTransformer",
            mock_transformer,
        )
        get_sentence_model.cache_clear()
        try:
            get_sentence_model()
            assert mock_transformer.call_count == EXPECTED_CALL_COUNT_AFTER_FIRST_CALL

            unload_duplicate_control_embedder()
            get_sentence_model()

            assert mock_transformer.call_count == EXPECTED_CALL_COUNT_AFTER_RELOAD
        finally:
            get_sentence_model.cache_clear()
