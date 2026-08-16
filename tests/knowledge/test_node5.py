import asyncio

import pytest

from classiflow.database.repositories.audit import InMemoryAuditRepository
from classiflow.database.repositories.document import InMemoryDocumentRepository
from classiflow.domain.job import JobStatus
from classiflow.events.broadcaster import EventBroadcaster
from classiflow.ingesta.domain.context import JobContext
from classiflow.ingesta.nodes.node5_knowledge_indexing import KnowledgeIndexingNode
from classiflow.knowledge.chunker import ChunkerService
from classiflow.knowledge.domain.document import DocumentMetadata
from classiflow.knowledge.exceptions import VectorStoreError
from classiflow.knowledge.indexer import IndexerService
from classiflow.knowledge.infrastructure.chroma_store import InMemoryVectorStore
from classiflow.knowledge.repositories.embedder import Embedding
from classiflow.services.audit.service import AuditService

_JOB_ID = "test-job-005"
_FILENAME = "ordenanza_10902_2026.pdf"
_SHA256 = "b" * 64
_CTX = JobContext(job_id=_JOB_ID, filename=_FILENAME)
_TEXT = (
    "Artículo 1º — Apruébase el presupuesto municipal.\n\n"
    "Artículo 2º — Comuníquese al Departamento Ejecutivo."
)
_STARTED_PLUS_OUTCOME = 2


class _Embedder:
    def embed_documents(self, texts: list[str]) -> list[Embedding]:
        return [self.embed_query(text) for text in texts]

    def embed_query(self, _text: str) -> Embedding:
        return [1.0, 0.0]


class _MetadataRepo:
    def resolve(self, filename: str) -> DocumentMetadata:
        return DocumentMetadata(
            filename=filename,
            doc_type="Ordenanza",
            number="10902",
            year="2026",
            subject="Presupuesto municipal",
            download_url="https://example.test/ordenanza",
        )


class _BrokenVectorStore(InMemoryVectorStore):
    def upsert(self, _chunks: list[object], _embeddings: list[Embedding]) -> None:  # type: ignore[override]
        raise VectorStoreError(operation="upsert", cause="disk unavailable")


def _make_node(
    vector_store: InMemoryVectorStore,
    document_repo: InMemoryDocumentRepository,
    broadcaster: EventBroadcaster,
) -> KnowledgeIndexingNode:
    indexer = IndexerService(
        chunker=ChunkerService(chunk_size=200, chunk_overlap=40),
        embedder=_Embedder(),
        vector_store=vector_store,
        metadata_repo=_MetadataRepo(),
    )
    return KnowledgeIndexingNode(
        audit=AuditService(InMemoryAuditRepository()),
        broadcaster=broadcaster,
        indexer=indexer,
        document_repo=document_repo,
    )


@pytest.fixture
def broadcaster() -> EventBroadcaster:
    return EventBroadcaster()


@pytest.fixture
def document_repo() -> InMemoryDocumentRepository:
    return InMemoryDocumentRepository()


class TestKnowledgeIndexingNode:
    async def test_indexes_and_records_the_document(
        self, broadcaster: EventBroadcaster, document_repo: InMemoryDocumentRepository
    ) -> None:
        store = InMemoryVectorStore()
        node = _make_node(store, document_repo, broadcaster)

        result = await node.run(_CTX, _SHA256, _TEXT)

        assert result.passed
        assert result.indexed
        assert result.chunk_count == store.count()
        assert result.download_url == "https://example.test/ordenanza"

    async def test_persists_the_catalogue_row_with_its_link(
        self, broadcaster: EventBroadcaster, document_repo: InMemoryDocumentRepository
    ) -> None:
        node = _make_node(InMemoryVectorStore(), document_repo, broadcaster)

        await node.run(_CTX, _SHA256, _TEXT)
        saved = await document_repo.find_by_sha256(_SHA256)

        assert saved is not None
        assert saved.doc_type == "Ordenanza"
        assert saved.number == "10902"
        assert saved.download_url == "https://example.test/ordenanza"
        assert saved.chunk_count > 0

    async def test_indexing_failure_leaves_the_document_accepted(
        self, broadcaster: EventBroadcaster, document_repo: InMemoryDocumentRepository
    ) -> None:
        node = _make_node(_BrokenVectorStore(), document_repo, broadcaster)

        result = await node.run(_CTX, _SHA256, _TEXT)

        # The document already cleared every validation gate: a knowledge-base outage
        # must not retroactively reject it.
        assert result.passed
        assert not result.indexed
        assert "disk unavailable" in result.rejection_reason
        assert await document_repo.find_by_sha256(_SHA256) is None

    async def test_document_without_text_is_not_indexed(
        self, broadcaster: EventBroadcaster, document_repo: InMemoryDocumentRepository
    ) -> None:
        node = _make_node(InMemoryVectorStore(), document_repo, broadcaster)

        result = await node.run(_CTX, _SHA256, "   ")

        assert result.passed
        assert not result.indexed
        assert result.chunk_count == 0
        assert await document_repo.find_by_sha256(_SHA256) is None

    async def test_emits_started_then_passed(
        self, broadcaster: EventBroadcaster, document_repo: InMemoryDocumentRepository
    ) -> None:
        node = _make_node(InMemoryVectorStore(), document_repo, broadcaster)
        events: list[object] = []

        async def collect() -> None:
            events.extend([event async for event in broadcaster.subscribe(_JOB_ID)])

        collect_task = asyncio.create_task(collect())
        await asyncio.sleep(0)
        await node.run(_CTX, _SHA256, _TEXT)
        await broadcaster.close(_JOB_ID)
        await collect_task

        assert len(events) == _STARTED_PLUS_OUTCOME
        assert events[0].status == JobStatus.STARTED  # type: ignore[union-attr]
        assert events[0].node == "node5_knowledge_indexing"  # type: ignore[union-attr]
        assert events[1].status == JobStatus.PASSED  # type: ignore[union-attr]

    async def test_emits_passed_even_when_indexing_fails(
        self, broadcaster: EventBroadcaster, document_repo: InMemoryDocumentRepository
    ) -> None:
        node = _make_node(_BrokenVectorStore(), document_repo, broadcaster)
        events: list[object] = []

        async def collect() -> None:
            events.extend([event async for event in broadcaster.subscribe(_JOB_ID)])

        collect_task = asyncio.create_task(collect())
        await asyncio.sleep(0)
        await node.run(_CTX, _SHA256, _TEXT)
        await broadcaster.close(_JOB_ID)
        await collect_task

        assert events[1].status == JobStatus.PASSED  # type: ignore[union-attr]
