from loguru import logger

from classiflow.database.models import Document
from classiflow.database.repositories.audit import AuditDetail
from classiflow.domain.repositories.document import IDocumentRepository
from classiflow.events.broadcaster import EventBroadcaster
from classiflow.ingesta.domain.context import JobContext
from classiflow.ingesta.domain.results import KnowledgeIndexingResult
from classiflow.ingesta.nodes.base import BaseNode
from classiflow.knowledge.exceptions import KnowledgeError
from classiflow.knowledge.indexer import IndexerService
from classiflow.services.audit.service import AuditService


class KnowledgeIndexingNode(BaseNode):
    """Indexes an accepted document into the knowledge base.

    Runs after node 4 on the accept path only. Indexing is deliberately non-fatal: a
    document that already passed every validation gate stays accepted even if the
    vector store is unavailable, and the failure is recorded in the audit log so it
    can be re-indexed later from the `documents` catalogue.
    """

    @property
    def name(self) -> str:
        return "node5_knowledge_indexing"

    def __init__(
        self,
        audit: AuditService,
        broadcaster: EventBroadcaster,
        indexer: IndexerService,
        document_repo: IDocumentRepository,
    ) -> None:
        super().__init__(audit, broadcaster)
        self.indexer = indexer
        self.document_repo = document_repo

    async def run(self, ctx: JobContext, sha256: str, text: str) -> KnowledgeIndexingResult:
        start = await self._emit_started(ctx)
        result = await self._index(ctx, sha256, text)
        await self._emit_and_audit(
            ctx,
            start,
            passed=result.passed,
            detail=AuditDetail.model_validate({
                "filename": ctx.filename,
                "sha256": sha256,
                "indexed": result.indexed,
                "chunk_count": result.chunk_count,
                "doc_type": result.doc_type,
                "number": result.number,
                "year": result.year,
                "download_url": result.download_url,
                "passed": result.passed,
                "rejection_reason": result.rejection_reason,
            }),
        )
        return result

    async def _index(self, ctx: JobContext, sha256: str, text: str) -> KnowledgeIndexingResult:
        try:
            indexed = await self.indexer.index(ctx.job_id, ctx.filename, sha256, text)
        except KnowledgeError as exc:
            logger.warning("Knowledge indexing failed for job {}: {}", ctx.job_id, exc)
            return KnowledgeIndexingResult(passed=True, indexed=False, rejection_reason=str(exc))

        metadata = indexed.metadata
        if indexed.chunk_count:
            await self.document_repo.save(
                Document(
                    job_id=ctx.job_id,
                    sha256=sha256,
                    filename=ctx.filename,
                    doc_type=metadata.doc_type or None,
                    number=metadata.number or None,
                    year=metadata.year or None,
                    subject=metadata.subject or None,
                    sanction_date=metadata.sanction_date or None,
                    publication_date=metadata.publication_date or None,
                    bulletin_number=metadata.bulletin_number or None,
                    download_url=metadata.download_url or None,
                    chunk_count=indexed.chunk_count,
                )
            )

        return KnowledgeIndexingResult(
            passed=True,
            indexed=indexed.chunk_count > 0,
            chunk_count=indexed.chunk_count,
            doc_type=metadata.doc_type,
            number=metadata.number,
            year=metadata.year,
            subject=metadata.subject,
            download_url=metadata.download_url,
            rejection_reason="" if indexed.chunk_count else "No indexable text in document",
        )
