from pathlib import Path
from typing import TYPE_CHECKING, cast

import chromadb
from chromadb.api.models.Collection import Collection

from classiflow.knowledge.domain.chat import RetrievedChunk
from classiflow.knowledge.domain.chunk import Chunk, Embedding
from classiflow.knowledge.utils.chroma import build_where, to_retrieved_chunks
from classiflow.knowledge.vectordb.exceptions import VectorStoreError
from classiflow.knowledge.vectordb.vector_store import VectorStore
from classiflow.settings import Settings

if TYPE_CHECKING:
    # Only ever named inside a cast(), so ruff's TC003 requires it here despite the
    # project's general no-TYPE_CHECKING rule. Carried over from the pre-split file.
    from collections.abc import Sequence

    from chromadb.api.types import Where


class ChromaVectorStore(VectorStore):
    """Persistent Chroma collection holding one entry per chunk.

    Embeddings are always supplied by the caller -- Chroma's own embedding function
    is never used, so the embedder stays the single place that decides which model
    produces vectors.
    """

    def __init__(self, path: str = "", collection_name: str = "") -> None:
        self._path = path or Settings.chroma_path
        self._collection_name = collection_name or Settings.chroma_collection
        self._collection: Collection | None = None

    def _get_collection(self) -> Collection:
        if self._collection is not None:
            return self._collection
        try:
            Path(self._path).mkdir(parents=True, exist_ok=True)
            client = chromadb.PersistentClient(path=self._path)
            self._collection = client.get_or_create_collection(
                name=self._collection_name,
                metadata={"hnsw:space": "cosine"},
            )
        except Exception as exc:
            raise VectorStoreError(operation="open", cause=str(exc)) from exc
        return self._collection

    def upsert(self, chunks: list[Chunk], embeddings: list[Embedding]) -> None:
        if not chunks:
            return
        collection = self._get_collection()
        try:
            collection.upsert(
                ids=[chunk.chunk_id for chunk in chunks],
                embeddings=cast("list[Sequence[float]]", embeddings),
                documents=[chunk.text for chunk in chunks],
                metadatas=[chunk.to_store_metadata() for chunk in chunks],
            )
        except Exception as exc:
            raise VectorStoreError(operation="upsert", cause=str(exc)) from exc

    def query(
        self,
        embedding: Embedding,
        top_k: int,
        filters: dict[str, str] | None = None,
    ) -> list[RetrievedChunk]:
        collection = self._get_collection()
        try:
            result = collection.query(
                query_embeddings=cast("list[Sequence[float]]", [embedding]),
                n_results=top_k,
                where=build_where(filters),
            )
        except Exception as exc:
            raise VectorStoreError(operation="query", cause=str(exc)) from exc
        return to_retrieved_chunks(result)

    def delete_by_job(self, job_id: str) -> None:
        collection = self._get_collection()
        try:
            collection.delete(where=cast("Where", {"job_id": job_id}))
        except Exception as exc:
            raise VectorStoreError(operation="delete", cause=str(exc)) from exc

    def count(self) -> int:
        collection = self._get_collection()
        try:
            return int(collection.count())
        except Exception as exc:
            raise VectorStoreError(operation="count", cause=str(exc)) from exc
