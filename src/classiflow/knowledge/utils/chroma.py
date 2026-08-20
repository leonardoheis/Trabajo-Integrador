"""Adapters for Chroma's response and filter shapes.

Kept out of `vectordb/chroma_store.py` so the store itself reads as the four store
operations and nothing else. Nothing here touches a Chroma client -- these are pure
functions over the plain dicts Chroma hands back.
"""

from typing import cast

from chromadb.api.types import Where

from classiflow.knowledge.domain.chat import RetrievedChunk
from classiflow.knowledge.domain.chunk import StoreMetadata


def build_where(filters: dict[str, str] | None) -> Where | None:
    """Translate flat metadata filters into a Chroma `where` clause.

    Chroma takes a bare {key: value} for one condition but requires an explicit
    $and for several.

    Returns:
        The `where` clause, or None when there is nothing to filter on.
    """
    if not filters:
        return None
    if len(filters) == 1:
        return cast("Where", dict(filters.items()))
    return cast("Where", {"$and": [{key: value} for key, value in filters.items()]})


def first_row(result: object, key: str) -> list[object]:
    """Pull one field's row out of a Chroma query result.

    Chroma returns each field as a list-of-lists, one inner list per query
    embedding; we always send exactly one.

    Returns:
        The first inner list, or an empty list if the field is absent or malformed.
    """
    if not isinstance(result, dict):
        return []
    rows = result.get(key)
    if not isinstance(rows, list) or not rows:
        return []
    first = rows[0]
    return list(first) if isinstance(first, list) else []


def coerce_metadata(metadata: object) -> StoreMetadata:
    """Narrow an untyped Chroma metadata mapping to flat scalars.

    Returns:
        A StoreMetadata dict; non-scalar values are stringified, None values dropped.
    """
    if not isinstance(metadata, dict):
        return {}
    coerced: StoreMetadata = {}
    for key, value in metadata.items():
        if isinstance(value, (str, int, float, bool)):
            coerced[str(key)] = value
        elif value is not None:
            coerced[str(key)] = str(value)
    return coerced


def to_retrieved_chunks(result: object) -> list[RetrievedChunk]:
    """Convert a raw Chroma query result into domain objects.

    Returns:
        One RetrievedChunk per returned id, in Chroma's ranking order.
    """
    ids = first_row(result, "ids")
    documents = first_row(result, "documents")
    metadatas = first_row(result, "metadatas")
    distances = first_row(result, "distances")

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
                metadata=coerce_metadata(metadata),
            )
        )
    return chunks
