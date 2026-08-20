import pytest

from classiflow.knowledge.chunking.chunker import ChunkerService
from classiflow.knowledge.indexing.indexer import IndexerService
from classiflow.knowledge.vectordb.in_memory_store import InMemoryVectorStore
from tests.knowledge.fakes import FakeEmbedder, FakeMetadataRepo


@pytest.fixture
def store() -> InMemoryVectorStore:
    return InMemoryVectorStore()


@pytest.fixture
def indexer(store: InMemoryVectorStore) -> IndexerService:
    return IndexerService(
        chunker=ChunkerService(chunk_size=200, chunk_overlap=40),
        embedder=FakeEmbedder(),  # type: ignore[arg-type]
        vector_store=store,
        metadata_repo=FakeMetadataRepo(),  # type: ignore[arg-type]
    )
