from loguru import logger
from sqlalchemy.exc import SQLAlchemyError

from classiflow.shared.audit.exceptions import MissingFieldError, PersistenceError
from classiflow.shared.database.repositories.audit import (
    AuditDetail,
    IAuditRepository,
    make_audit_record,
)


class AuditService:
    def __init__(self, repo: IAuditRepository) -> None:
        self._repo = repo

    async def record(
        self,
        job_id: str,
        agent: str,
        event: str,
        *,
        duration_ms: int | None = None,
        detail: AuditDetail | None = None,
    ) -> None:
        if not job_id:
            raise MissingFieldError("job_id")  # noqa: EM101
        if not agent:
            raise MissingFieldError("agent")  # noqa: EM101
        if not event:
            raise MissingFieldError("event")  # noqa: EM101

        audit_record = make_audit_record(
            job_id, agent, event, duration_ms=duration_ms, detail=detail
        )
        try:
            await self._repo.save(audit_record)
        except SQLAlchemyError as exc:
            raise PersistenceError(job_id, agent, event) from exc

        logger.info("audit | job={} agent={} event={}", job_id, agent, event)
