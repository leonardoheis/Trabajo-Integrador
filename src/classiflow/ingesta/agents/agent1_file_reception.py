import hashlib
import time
from collections.abc import Callable

from classiflow.ingesta.domain.results import FileReceptionResult
from classiflow.shared.audit.service import AuditService
from classiflow.shared.database.repositories.audit import AuditDetail
from classiflow.shared.domain.job import AgentEvent, JobStatus
from classiflow.shared.events.broadcaster import EventBroadcaster

AGENT_NAME = "agent1_file_reception"
_MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB — matches config/allowed_formats.yaml

MimeDetector = Callable[[bytes], str]


class FileReceptionAgent:
    def __init__(
        self,
        audit: AuditService,
        broadcaster: EventBroadcaster,
        mime_detector: MimeDetector,
        max_file_size_bytes: int = _MAX_FILE_SIZE_BYTES,
    ) -> None:
        self._audit = audit
        self._broadcaster = broadcaster
        self._mime_detector = mime_detector
        self._max_size = max_file_size_bytes

    async def run(
        self,
        job_id: str,
        filename: str,
        file_bytes: bytes | None,
    ) -> FileReceptionResult:
        start = time.monotonic()

        await self._broadcaster.emit(
            AgentEvent(job_id=job_id, agent=AGENT_NAME, status=JobStatus.STARTED)
        )

        result = self._receive(file_bytes)
        duration_ms = int((time.monotonic() - start) * 1000)

        status = JobStatus.PASSED if result.passed else JobStatus.FAILED
        await self._broadcaster.emit(AgentEvent(job_id=job_id, agent=AGENT_NAME, status=status))

        await self._audit.record(
            job_id,
            AGENT_NAME,
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

        if size > self._max_size:
            limit_mb = self._max_size // (1024 * 1024)
            return FileReceptionResult(
                passed=False,
                file_size_bytes=size,
                rejection_reason=f"File exceeds maximum allowed size of {limit_mb} MB",
            )

        sha256 = hashlib.sha256(file_bytes).hexdigest()
        detected_mime = self._mime_detector(file_bytes)

        return FileReceptionResult(
            passed=True,
            sha256=sha256,
            detected_mime=detected_mime,
            file_size_bytes=size,
        )
