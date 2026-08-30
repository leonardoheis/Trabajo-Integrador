import asyncio

from classiflow.knowledge.chunking.chunker import ChunkerService
from classiflow.knowledge.domain.chunk import Chunk
from classiflow.knowledge.domain.document import DocumentMetadata
from classiflow.knowledge.embeddings.embedder import SentenceTransformerEmbedder
from classiflow.knowledge.vectordb.vector_store import VectorStore


class IndexResult:
    def __init__(self, metadata: DocumentMetadata, chunks: list[Chunk]) -> None:
        self.metadata = metadata
        self.chunks = chunks

    @property
    def chunk_count(self) -> int:
        return len(self.chunks)


def _resolve_metadata(filename: str, entities: dict[str, object]) -> DocumentMetadata:
    # doc_type/number/year come straight from Stage 2's entity extraction (already
    # run on every enriched document) rather than a separate scraped catalogue --
    # one less external data dependency, at the cost of the richer fields
    # (subject/dates/download_url) that only a scraped source ever had.
    doc_type = entities.get("doc_type_hint")
    number = entities.get("number")
    year = entities.get("year")
    return DocumentMetadata(
        filename=filename,
        doc_type=str(doc_type).capitalize() if doc_type else "",
        number=str(number) if number else "",
        year=str(year) if year else "",
    )


class IndexerService:
    """Turns one accepted document into persisted, queryable chunks."""

    def __init__(
        self,
        chunker: ChunkerService,
        embedder: SentenceTransformerEmbedder,
        vector_store: VectorStore,
    ) -> None:
        self._chunker = chunker
        self._embedder = embedder
        self._vector_store = vector_store

    async def index(
        self, job_id: str, filename: str, sha256: str, text: str, entities: dict[str, object]
    ) -> IndexResult:
        metadata = _resolve_metadata(filename, entities)
        if not text.strip():
            return IndexResult(metadata=metadata, chunks=[])

        chunks = self._chunker.split(text, job_id=job_id, sha256=sha256, metadata=metadata)
        if not chunks:
            return IndexResult(metadata=metadata, chunks=[])

        # Embedding and the Chroma write are both blocking and CPU-bound; keeping them
        # off the event loop matters because indexing runs inside a pipeline job while
        # other jobs and SSE streams are live.
        await asyncio.to_thread(self._embed_and_store, chunks)
        return IndexResult(metadata=metadata, chunks=chunks)

    def _embed_and_store(self, chunks: list[Chunk]) -> None:
        embeddings = self._embedder.embed_documents([chunk.text for chunk in chunks])
        self._vector_store.upsert(chunks, embeddings)
