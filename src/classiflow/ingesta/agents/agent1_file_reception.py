import hashlib
import time

from pydantic import ConfigDict

from classiflow.ingesta.agents.base import BaseAgent
from classiflow.ingesta.config import get_allowed_formats
from classiflow.ingesta.domain.results import FileReceptionResult
from classiflow.ingesta.mime import MimeDetector, detect_mime
from classiflow.shared.audit.service import AuditService
from classiflow.shared.database.repositories.audit import AuditDetail
from classiflow.shared.domain.job import AgentEvent, JobStatus
from classiflow.shared.events.broadcaster import EventBroadcaster


class FileReceptionAgent(BaseAgent):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    @property
    def name(self) -> str:
        return "agent1_file_reception"

    audit: AuditService
    broadcaster: EventBroadcaster
    mime_detector: MimeDetector = detect_mime
    max_file_size_bytes: int = get_allowed_formats().max_file_size_bytes

    async def run(
        self,
        job_id: str,
        filename: str,
        file_bytes: bytes | None,
    ) -> FileReceptionResult:
        start = time.monotonic()

        await self.broadcaster.emit(
            AgentEvent(job_id=job_id, agent=self.name, status=JobStatus.STARTED)
        )

        result = self._receive(file_bytes)
        duration_ms = int((time.monotonic() - start) * 1000)

        status = JobStatus.PASSED if result.passed else JobStatus.FAILED
        await self.broadcaster.emit(AgentEvent(job_id=job_id, agent=self.name, status=status))

        await self.audit.record(
            job_id,
            self.name,
            status.value,
            duration_ms=duration_ms,
            detail=AuditDetail.model_validate({
                "filename": filename,
                "sha256": result.sha256,
                "detected_mime": result.detected_mime,
                "file_size_bytes": result.file_size_bytes,
                "passed": result.passed,
                "rejection_reason": result.rejection_reason,
            }),
        )

        return result

    def _receive(self, file_bytes: bytes | None) -> FileReceptionResult:
        if file_bytes is None:
            return FileReceptionResult(passed=False, rejection_reason="No file provided")

        size = len(file_bytes)

        if size == 0:
            return FileReceptionResult(passed=False, rejection_reason="File is empty")

        if size > self.max_file_size_bytes:
            limit_mb = self.max_file_size_bytes // (1024 * 1024)
            return FileReceptionResult(
                passed=False,
                file_size_bytes=size,
                rejection_reason=f"File exceeds maximum allowed size of {limit_mb} MB",
            )

        sha256 = hashlib.sha256(file_bytes).hexdigest()
        detected_mime = self.mime_detector(file_bytes)

        return FileReceptionResult(
            passed=True,
            sha256=sha256,
            detected_mime=detected_mime,
            file_size_bytes=size,
        )
