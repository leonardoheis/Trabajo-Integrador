"""Shared test doubles for pipeline wiring.

Node 5 sits on the coordinator's accept path, so every test that builds a full
coordinator needs one -- even the ones that only care about extraction or enrichment.
"""

from classiflow.database.repositories.document import InMemoryDocumentRepository
from classiflow.events.broadcaster import EventBroadcaster
from classiflow.ingesta.nodes import KnowledgeIndexingNode
from classiflow.knowledge.chunking.chunker import ChunkerService
from classiflow.knowledge.domain.chunk import Embedding
from classiflow.knowledge.domain.document import DocumentMetadata
from classiflow.knowledge.indexing.indexer import IndexerService
from classiflow.knowledge.vectordb.in_memory_store import InMemoryVectorStore
from classiflow.services.audit.service import AuditService


class StubKnowledgeEmbedder:
    """Fixed 2-d vectors -- coordinator tests exercise the path, not retrieval quality."""

    def embed_documents(self, texts: list[str]) -> list[Embedding]:
        return [[1.0, 0.0] for _ in texts]

    def embed_query(self, _text: str) -> Embedding:
        return [1.0, 0.0]


class StubKnowledgeMetadata:
    def resolve(self, filename: str) -> DocumentMetadata:
        return DocumentMetadata(filename=filename)


def make_indexing_node(audit: AuditService, broadcaster: EventBroadcaster) -> KnowledgeIndexingNode:
    """Build node 5 against fully in-memory knowledge infrastructure.

    Returns:
        A KnowledgeIndexingNode that indexes into a throwaway in-memory vector store.
    """
    return KnowledgeIndexingNode(
        audit=audit,
        broadcaster=broadcaster,
        indexer=IndexerService(
            chunker=ChunkerService(),
            embedder=StubKnowledgeEmbedder(),  # type: ignore[arg-type]
            vector_store=InMemoryVectorStore(),
            metadata_repo=StubKnowledgeMetadata(),  # type: ignore[arg-type]
        ),
        document_repo=InMemoryDocumentRepository(),
    )
