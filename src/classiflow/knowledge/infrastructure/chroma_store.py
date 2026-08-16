from pathlib import Path
from typing import TYPE_CHECKING, cast

import chromadb
from chromadb.api.models.Collection import Collection
from chromadb.api.types import Where

from classiflow.knowledge.domain.chat import RetrievedChunk
from classiflow.knowledge.domain.chunk import Chunk, StoreMetadata
from classiflow.knowledge.exceptions import VectorStoreError
from classiflow.knowledge.repositories.vector_store import Embedding
from classiflow.settings import Settings

if TYPE_CHECKING:
    from collections.abc import Sequence


def _build_where(filters: dict[str, str] | None) -> Where | None:
    # Chroma takes a bare {key: value} for one condition but requires an explicit
    # $and for several.
    if not filters:
        return None
    if len(filters) == 1:
        return cast("Where", dict(filters.items()))
    return cast("Where", {"$and": [{key: value} for key, value in filters.items()]})


class ChromaVectorStore:
    """Persistent Chroma collection holding one entry per chunk.

    Embeddings are always supplied by the caller -- Chroma's own embedding function
    is never used, so the embedder port stays the single place that decides which
    model produces vectors.
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
                where=_build_where(filters),
            )
        except Exception as exc:
            raise VectorStoreError(operation="query", cause=str(exc)) from exc
        return _to_retrieved_chunks(result)

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


def _first_row(result: object, key: str) -> list[object]:
    # Chroma returns each field as a list-of-lists, one inner list per query
    # embedding; we always send exactly one.
    if not isinstance(result, dict):
        return []
    rows = result.get(key)
    if not isinstance(rows, list) or not rows:
        return []
    first = rows[0]
    return list(first) if isinstance(first, list) else []


def _to_retrieved_chunks(result: object) -> list[RetrievedChunk]:
    ids = _first_row(result, "ids")
    documents = _first_row(result, "documents")
    metadatas = _first_row(result, "metadatas")
    distances = _first_row(result, "distances")

    chunks: list[RetrievedChunk] = []
    for index, chunk_id in enumerate(ids):
        document = documents[index] if index < len(documents) else ""
        metadata = metadatas[index] if index < len(metadatas) else {}
        distance = distances[index] if index < len(distances) else 1.0
        chunks.append(
            RetrievedChunk(
                chunk_id=str(chunk_id),
                text=str(document) if document is not None else "",
                # The collection uses cosine *distance*; callers want similarity.
                score=1.0 - float(distance) if isinstance(distance, (int, float)) else 0.0,
                metadata=_coerce_metadata(metadata),
            )
        )
    return chunks


def _coerce_metadata(metadata: object) -> StoreMetadata:
    if not isinstance(metadata, dict):
        return {}
    coerced: StoreMetadata = {}
    for key, value in metadata.items():
        if isinstance(value, (str, int, float, bool)):
            coerced[str(key)] = value
        elif value is not None:
            coerced[str(key)] = str(value)
    return coerced


class InMemoryVectorStore:
    """Test double with the same semantics: cosine similarity over normalized vectors."""

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
                    score=_dot(embedding, self._embeddings[chunk_id]),
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


def _dot(left: Embedding, right: Embedding) -> float:
    return float(sum(a * b for a, b in zip(left, right, strict=False)))
