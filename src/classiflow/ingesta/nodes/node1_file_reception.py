import hashlib

from classiflow.database.repositories.audit import AuditDetail
from classiflow.events.broadcaster import EventBroadcaster
from classiflow.ingesta.config import get_allowed_formats
from classiflow.ingesta.domain import FileReceptionResult, JobContext
from classiflow.ingesta.mime import MimeDetector, detect_mime
from classiflow.pipeline.base import BaseNode
from classiflow.services.audit.service import AuditService


class FileReceptionNode(BaseNode):
    @property
    def name(self) -> str:
        return "node1_file_reception"

    def __init__(
        self,
        audit: AuditService,
        broadcaster: EventBroadcaster,
        *,
        mime_detector: MimeDetector = detect_mime,
        max_file_size_bytes: int | None = None,
    ) -> None:
        super().__init__(audit, broadcaster)
        self.mime_detector = mime_detector
        self.max_file_size_bytes: int = (
            max_file_size_bytes
            if max_file_size_bytes is not None
            else get_allowed_formats().max_file_size_bytes
        )

    async def run(self, ctx: JobContext, file_bytes: bytes | None) -> FileReceptionResult:
        start = await self._emit_started(ctx)
        result = self._receive(file_bytes)
        await self._emit_and_audit(
            ctx,
            start,
            passed=result.passed,
            detail=AuditDetail.model_validate({
                "filename": ctx.filename,
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
