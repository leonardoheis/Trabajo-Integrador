import asyncio
from typing import TYPE_CHECKING, cast

from classiflow.database.models import EnrichedRecord
from classiflow.database.repositories.document_kb import InMemoryDocumentKbRepository
from classiflow.database.repositories.document_steps import InMemoryDocumentStepsRepository
from classiflow.database.repositories.enriched_record import InMemoryEnrichedRecordRepository
from classiflow.database.repositories.job import InMemoryJobRepository
from classiflow.events.broadcaster import EventBroadcaster
from classiflow.knowledge.chunking.chunker import ChunkerService
from classiflow.knowledge.domain.chunk import Embedding
from classiflow.knowledge.indexing.indexer import IndexerService
from classiflow.knowledge.vectordb.exceptions import VectorStoreError
from classiflow.knowledge.vectordb.in_memory_store import InMemoryVectorStore
from classiflow.services.pipeline.service import PipelineService
from tests.fakes import StubKnowledgeEmbedder, StubKnowledgeMetadata, make_indexer

if TYPE_CHECKING:
    from langgraph.graph.state import CompiledStateGraph

    from classiflow.storage.document_storage import IDocumentStorage

_TEXT = (
    "Artículo 1º — Apruébase el presupuesto municipal.\n\n"
    "Artículo 2º — Comuníquese al Departamento Ejecutivo."
)
_ROWS_1 = 1


class _BrokenVectorStore(InMemoryVectorStore):
    def upsert(self, _chunks: list[object], _embeddings: list[Embedding]) -> None:  # type: ignore[override]
        raise VectorStoreError(operation="upsert", cause="disk unavailable")


def _broken_indexer() -> IndexerService:
    return IndexerService(
        chunker=ChunkerService(),
        embedder=StubKnowledgeEmbedder(),  # type: ignore[arg-type]
        vector_store=_BrokenVectorStore(),
        metadata_repo=StubKnowledgeMetadata(),  # type: ignore[arg-type]
    )


def _enriched_record(job_id: str = "job-1", enriched_id: int = 1) -> EnrichedRecord:
    return EnrichedRecord(
        id=enriched_id,
        job_id=job_id,
        cleaned_text=_TEXT,
        entities={},
        metadata_={},
        filename="ordenanza.pdf",
        sha256="a" * 64,
    )


def _build_service(
    indexer: IndexerService,
) -> tuple[PipelineService, InMemoryDocumentKbRepository]:
    document_kb_repo = InMemoryDocumentKbRepository()
    service = PipelineService(
        job_repo=InMemoryJobRepository(),
        document_steps_repo=InMemoryDocumentStepsRepository(),
        enriched_record_repo=InMemoryEnrichedRecordRepository(),
        broadcaster=EventBroadcaster(),
        coordinator=cast("CompiledStateGraph", None),  # unused: these tests call methods directly
        enrichment_coordinator=cast("CompiledStateGraph", None),  # unused
        document_storage=cast("IDocumentStorage", None),  # unused
        classification_coordinator=cast("CompiledStateGraph", None),  # unused
        job_semaphore=asyncio.Semaphore(1),  # unused
        indexer=indexer,
        document_kb_repo=document_kb_repo,
    )
    return service, document_kb_repo


class TestIndexEnrichedRecord:
    async def test_indexes_and_persists_the_link(self) -> None:
        service, document_kb_repo = _build_service(make_indexer())
        record = _enriched_record()

        was_indexed = await service.index_enriched_record(record, record.filename, record.sha256)

        assert was_indexed
        saved = await document_kb_repo.find_by_sha256(record.sha256)
        assert saved is not None
        assert saved.enriched_record_id == record.id
        assert saved.job_id == record.job_id

    async def test_knowledge_error_is_swallowed(self) -> None:
        service, document_kb_repo = _build_service(_broken_indexer())
        record = _enriched_record()

        was_indexed = await service.index_enriched_record(record, record.filename, record.sha256)

        assert not was_indexed
        assert await document_kb_repo.find_by_sha256(record.sha256) is None

    async def test_no_indexable_text_is_skipped(self) -> None:
        service, document_kb_repo = _build_service(make_indexer())
        record = _enriched_record()
        record.cleaned_text = "   "

        was_indexed = await service.index_enriched_record(record, record.filename, record.sha256)

        assert not was_indexed
        assert await document_kb_repo.find_by_sha256(record.sha256) is None


class TestSynchronizeKb:
    async def test_indexes_every_pending_record(self) -> None:
        service, document_kb_repo = _build_service(make_indexer())
        first = _enriched_record(job_id="job-1", enriched_id=1)
        first.sha256 = "a" * 64
        second = _enriched_record(job_id="job-2", enriched_id=2)
        second.sha256 = "b" * 64
        await service._enriched_record_repo.save(first)  # noqa: SLF001  (test seam)
        await service._enriched_record_repo.save(second)  # noqa: SLF001  (test seam)

        indexed_job_ids, skipped = await service.synchronize_kb()

        assert sorted(indexed_job_ids) == ["job-1", "job-2"]
        assert skipped == 0
        assert await document_kb_repo.find_by_sha256("a" * 64) is not None
        assert await document_kb_repo.find_by_sha256("b" * 64) is not None

    async def test_reports_failed_records_as_skipped(self) -> None:
        service, _document_kb_repo = _build_service(_broken_indexer())
        record = _enriched_record()
        await service._enriched_record_repo.save(record)  # noqa: SLF001  (test seam)

        indexed_job_ids, skipped = await service.synchronize_kb()

        assert indexed_job_ids == []
        assert skipped == _ROWS_1
