from loguru import logger
from sqlalchemy.exc import SQLAlchemyError

from classiflow.database.repositories.audit import AuditDetail, make_audit_record
from classiflow.services.audit.exceptions import MissingFieldError, PersistenceError
from classiflow.services.audit.repository import IAuditRepository


class AuditService:
    def __init__(self, repo: IAuditRepository) -> None:
        self._repo = repo

    async def record(
        self,
        job_id: str,
        node: str,
        event: str,
        *,
        duration_ms: int | None = None,
        detail: AuditDetail | None = None,
    ) -> None:
        if not job_id:
            raise MissingFieldError("job_id")
        if not node:
            raise MissingFieldError("node")
        if not event:
            raise MissingFieldError("event")

        audit_record = make_audit_record(
            job_id, node, event, duration_ms=duration_ms, detail=detail
        )
        try:
            await self._repo.save(audit_record)
        except SQLAlchemyError as exc:
            raise PersistenceError(job_id, node, event) from exc

        logger.info("audit | job={} node={} event={}", job_id, node, event)
