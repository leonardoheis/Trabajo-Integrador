from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    STARTED = "started"
    PASSED = "passed"
    FAILED = "failed"
    REJECTED = "rejected"
    REVIEW = "review"
    DONE = "done"


class NodeEvent(BaseModel):
    job_id: str
    node: str
    status: JobStatus
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_sse(self) -> str:
        return f"event: node_update\ndata: {self.model_dump_json()}\n\n"
