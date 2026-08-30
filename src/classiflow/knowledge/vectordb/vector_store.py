from abc import ABC, abstractmethod

from classiflow.knowledge.domain.chat import RetrievedChunk
from classiflow.knowledge.domain.chunk import Chunk, Embedding


class VectorStore(ABC):
    """One entry per chunk, queried by embedding similarity.

    Deliberately free of any storage-library import: `retrieval/` and `indexing/`
    depend on this module, and pulling chromadb in here would put it on the import
    path of every consumer, including the test container.
    """

    @abstractmethod
    def upsert(self, chunks: list[Chunk], embeddings: list[Embedding]) -> None:
        """Insert or replace the given chunks, keyed by `chunk_id`."""

    @abstractmethod
    def query(
        self,
        embedding: Embedding,
        top_k: int,
        filters: dict[str, str] | None = None,
    ) -> list[RetrievedChunk]:
        """Return the `top_k` most similar chunks, optionally narrowed by metadata.

        Returns:
            Matching chunks ordered by descending similarity.
        """

    @abstractmethod
    def delete_by_job(self, job_id: str) -> None:
        """Remove every chunk produced by one pipeline job."""

    @abstractmethod
    def count(self) -> int:
        """Return the number of stored chunks.

        Returns:
            Total chunk count in the collection.
        """
