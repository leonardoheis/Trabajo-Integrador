from typing import Protocol

from classiflow.shared.database.models import DocumentStep


class IDocumentStepsRepository(Protocol):
    async def save_step(self, step: DocumentStep) -> None: ...
    async def steps_for_job(self, job_id: str) -> list[DocumentStep]: ...
