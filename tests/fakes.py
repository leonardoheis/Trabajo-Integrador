"""Shared test doubles for pipeline wiring.

PipelineService indexes into the knowledge base itself (after enrichment succeeds),
so every test that builds a full PipelineService needs an IndexerService -- even the
ones that only care about extraction or enrichment.
"""

from classiflow.knowledge.chunking.chunker import ChunkerService
from classiflow.knowledge.domain.chunk import Embedding
from classiflow.knowledge.indexing.indexer import IndexerService
from classiflow.knowledge.vectordb.in_memory_store import InMemoryVectorStore


class StubKnowledgeEmbedder:
    """Fixed 2-d vectors -- pipeline tests exercise the path, not retrieval quality."""

    def embed_documents(self, texts: list[str]) -> list[Embedding]:
        return [[1.0, 0.0] for _ in texts]

    def embed_query(self, _text: str) -> Embedding:
        return [1.0, 0.0]


def make_indexer() -> IndexerService:
    """Build an IndexerService against fully in-memory knowledge infrastructure.

    Returns:
        An IndexerService that indexes into a throwaway in-memory vector store.
    """
    return IndexerService(
        chunker=ChunkerService(),
        embedder=StubKnowledgeEmbedder(),  # type: ignore[arg-type]
        vector_store=InMemoryVectorStore(),
    )
