from typing import Protocol, runtime_checkable

from classiflow.knowledge.domain.chat import RetrievedChunk
from classiflow.knowledge.domain.chunk import Chunk

Embedding = list[float]


@runtime_checkable
class IVectorStore(Protocol):
    def upsert(self, chunks: list[Chunk], embeddings: list[Embedding]) -> None: ...

    def query(
        self,
        embedding: Embedding,
        top_k: int,
        filters: dict[str, str] | None = None,
    ) -> list[RetrievedChunk]: ...

    def delete_by_job(self, job_id: str) -> None: ...

    def count(self) -> int: ...
