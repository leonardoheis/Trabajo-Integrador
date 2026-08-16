from pydantic import Field

from classiflow.api.schemas import BaseSchema
from classiflow.knowledge.domain.chat import ChatAnswer, SourceRef


class ChatRequest(BaseSchema):
    question: str
    # Metadata narrowing, e.g. {"doc_type": "Decreto", "year": "2026"}.
    filters: dict[str, str] = Field(default_factory=dict)
    top_k: int | None = None


class SourceSchema(BaseSchema):
    chunk_id: str
    filename: str
    doc_type: str
    number: str
    year: str
    subject: str
    download_url: str
    excerpt: str
    score: float

    @classmethod
    def from_domain(cls, source: SourceRef) -> "SourceSchema":
        return cls(**source.model_dump())


class ChatResponse(BaseSchema):
    answer: str
    sources: list[SourceSchema]

    @classmethod
    def from_domain(cls, answer: ChatAnswer) -> "ChatResponse":
        return cls(
            answer=answer.answer,
            sources=[SourceSchema.from_domain(s) for s in answer.sources],
        )
