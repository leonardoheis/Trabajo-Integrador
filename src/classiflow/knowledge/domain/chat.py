from pydantic import Field

from classiflow.domain.base import BaseEntity
from classiflow.knowledge.domain.chunk import StoreMetadata

_EXCERPT_CHARS = 300


class ChatQuery(BaseEntity):
    question: str
    # Optional metadata narrowing, e.g. {"doc_type": "Decreto", "year": "2026"}.
    filters: dict[str, str] = Field(default_factory=dict)
    top_k: int | None = None


class RetrievedChunk(BaseEntity):
    chunk_id: str
    text: str
    score: float
    metadata: StoreMetadata

    def _meta_str(self, key: str) -> str:
        value = self.metadata.get(key, "")
        return value if isinstance(value, str) else str(value)

    def to_source(self) -> "SourceRef":
        return SourceRef(
            chunk_id=self.chunk_id,
            filename=self._meta_str("filename"),
            doc_type=self._meta_str("doc_type"),
            number=self._meta_str("number"),
            year=self._meta_str("year"),
            excerpt=self.text[:_EXCERPT_CHARS],
            score=self.score,
        )


class SourceRef(BaseEntity):
    chunk_id: str
    filename: str
    doc_type: str
    number: str
    year: str
    excerpt: str
    score: float


class ChatAnswer(BaseEntity):
    answer: str
    sources: list[SourceRef]
