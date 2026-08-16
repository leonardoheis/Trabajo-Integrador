from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from classiflow.database.models import Document


class SqlDocumentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, document: Document) -> None:
        existing = await self.find_by_sha256(document.sha256)
        if existing is not None:
            # sha256 is unique: re-indexing the same document updates the catalogue row
            # in place, mirroring the idempotent upsert into the vector store.
            existing.job_id = document.job_id
            existing.filename = document.filename
            existing.doc_type = document.doc_type
            existing.number = document.number
            existing.year = document.year
            existing.subject = document.subject
            existing.sanction_date = document.sanction_date
            existing.publication_date = document.publication_date
            existing.bulletin_number = document.bulletin_number
            existing.download_url = document.download_url
            existing.chunk_count = document.chunk_count
        else:
            self._session.add(document)
        await self._session.flush()

    async def find_by_sha256(self, sha256: str) -> Document | None:
        result = await self._session.execute(select(Document).where(Document.sha256 == sha256))
        return result.scalar_one_or_none()

    async def list_all(self) -> list[Document]:
        result = await self._session.execute(select(Document))
        return list(result.scalars().all())


class InMemoryDocumentRepository:
    def __init__(self) -> None:
        self._store: dict[str, Document] = {}

    async def save(self, document: Document) -> None:
        self._store[document.sha256] = document

    async def find_by_sha256(self, sha256: str) -> Document | None:
        return self._store.get(sha256)

    async def list_all(self) -> list[Document]:
        return list(self._store.values())
