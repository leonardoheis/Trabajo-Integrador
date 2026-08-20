from classiflow.knowledge.indexing.indexer import IndexerService
from classiflow.knowledge.vectordb.in_memory_store import InMemoryVectorStore
from tests.knowledge.fakes import TEXT


class TestIndexerService:
    async def test_indexes_chunks_with_metadata(
        self, indexer: IndexerService, store: InMemoryVectorStore
    ) -> None:
        result = await indexer.index("job-1", "ordenanza_10902_2026.pdf", "sha-1", TEXT)

        assert result.chunk_count > 0
        assert store.count() == result.chunk_count
        assert result.metadata.download_url == "https://example.test/ordenanza"

    async def test_reindexing_the_same_document_is_idempotent(
        self, indexer: IndexerService, store: InMemoryVectorStore
    ) -> None:
        first = await indexer.index("job-1", "ordenanza_10902_2026.pdf", "sha-1", TEXT)
        await indexer.index("job-2", "ordenanza_10902_2026.pdf", "sha-1", TEXT)

        # Chunk ids are derived from the sha256, so the second pass overwrites.
        assert store.count() == first.chunk_count

    async def test_empty_text_indexes_nothing_but_still_resolves_metadata(
        self, indexer: IndexerService, store: InMemoryVectorStore
    ) -> None:
        result = await indexer.index("job-1", "ordenanza_10902_2026.pdf", "sha-1", "   ")

        assert result.chunk_count == 0
        assert store.count() == 0
        assert result.metadata.doc_type == "Ordenanza"
