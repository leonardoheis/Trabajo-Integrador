from classiflow.knowledge.domain.chat import RetrievedChunk
from classiflow.knowledge.domain.chunk import Chunk, Embedding
from classiflow.knowledge.utils.vectors import dot
from classiflow.knowledge.vectordb.vector_store import VectorStore


class InMemoryVectorStore(VectorStore):
    """Test double with the same semantics: cosine similarity over normalized vectors.

    Kept in its own module rather than beside ChromaVectorStore so the test container
    can wire it without importing chromadb.
    """

    def __init__(self) -> None:
        self._chunks: dict[str, Chunk] = {}
        self._embeddings: dict[str, Embedding] = {}

    def upsert(self, chunks: list[Chunk], embeddings: list[Embedding]) -> None:
        for chunk, embedding in zip(chunks, embeddings, strict=False):
            self._chunks[chunk.chunk_id] = chunk
            self._embeddings[chunk.chunk_id] = embedding

    def query(
        self,
        embedding: Embedding,
        top_k: int,
        filters: dict[str, str] | None = None,
    ) -> list[RetrievedChunk]:
        scored: list[RetrievedChunk] = []
        for chunk_id, chunk in self._chunks.items():
            metadata = chunk.to_store_metadata()
            if filters and any(metadata.get(key) != value for key, value in filters.items()):
                continue
            scored.append(
                RetrievedChunk(
                    chunk_id=chunk_id,
                    text=chunk.text,
                    score=dot(embedding, self._embeddings[chunk_id]),
                    metadata=metadata,
                )
            )
        scored.sort(key=lambda item: item.score, reverse=True)
        return scored[:top_k]

    def delete_by_job(self, job_id: str) -> None:
        for chunk_id in [cid for cid, c in self._chunks.items() if c.job_id == job_id]:
            del self._chunks[chunk_id]
            del self._embeddings[chunk_id]

    def count(self) -> int:
        return len(self._chunks)
