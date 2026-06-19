from typing import Any

from loguru import logger

from classiflow.shared.database.repositories.audit import IAuditRepository, make_audit_record


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
        detail: dict[str, Any] | None = None,
    ) -> None:
        audit_record = make_audit_record(
            job_id, agent, event, duration_ms=duration_ms, detail=detail
        )
        await self._repo.save(audit_record)
        logger.info("audit | job={} agent={} event={}", job_id, agent, event)
