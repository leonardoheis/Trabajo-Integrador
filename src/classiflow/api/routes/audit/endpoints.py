from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from classiflow.api.dependencies import get_audit_repo, get_current_user, require_admin
from classiflow.api.routes.audit.schemas import AuditPage, AuditRecordSchema
from classiflow.services.audit.repository import IAuditRepository

router = APIRouter(
    prefix="/audit",
    tags=["audit"],
    dependencies=[Depends(get_current_user), Depends(require_admin)],
)


@router.get("")
async def list_audit_records(
    audit_repo: Annotated[IAuditRepository, Depends(get_audit_repo)],
    job_id: Annotated[str | None, Query(alias="jobId")] = None,
    node: str | None = None,
    event: str | None = None,
    date_from: Annotated[datetime | None, Query(alias="dateFrom")] = None,
    date_to: Annotated[datetime | None, Query(alias="dateTo")] = None,
    page: int = 1,
    page_size: Annotated[int, Query(alias="pageSize")] = 50,
) -> AuditPage:
    records, total = await audit_repo.list_filtered(
        job_id, node, event, date_from, date_to, page, page_size
    )
    return AuditPage(
        items=[AuditRecordSchema.from_model(r) for r in records],
        total=total,
        page=page,
        page_size=page_size,
    )
