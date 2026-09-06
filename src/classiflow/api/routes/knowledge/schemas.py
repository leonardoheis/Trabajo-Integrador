from datetime import datetime

from pydantic import Field

from classiflow.api.schemas import BaseSchema
from classiflow.database.models import DocumentKb
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


class SynchronizeKbResponse(BaseSchema):
    indexed_job_ids: list[str]
    skipped_count: int


class DocumentKbSchema(BaseSchema):
    sha256: str
    filename: str
    doc_type: str | None
    number: str | None
    year: str | None
    subject: str | None
    sanction_date: str | None
    publication_date: str | None
    bulletin_number: str | None
    download_url: str | None
    chunk_count: int
    indexed_at: datetime

    @classmethod
    def from_model(cls, doc: DocumentKb) -> "DocumentKbSchema":
        return cls(
            sha256=doc.sha256,
            filename=doc.filename,
            doc_type=doc.doc_type,
            number=doc.number,
            year=doc.year,
            subject=doc.subject,
            sanction_date=doc.sanction_date,
            publication_date=doc.publication_date,
            bulletin_number=doc.bulletin_number,
            download_url=doc.download_url,
            chunk_count=doc.chunk_count,
            indexed_at=doc.indexed_at,
        )


class DocumentKbResponse(BaseSchema):
    document_kb: DocumentKbSchema | None
