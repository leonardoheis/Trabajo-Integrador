from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    STARTED = "started"
    PASSED = "passed"
    FAILED = "failed"
    REJECTED = "rejected"
    REVIEW = "review"
    DONE = "done"


class AgentEvent(BaseModel):
    job_id: str
    agent: str
    status: JobStatus
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    detail: dict[str, Any] = Field(default_factory=dict)

    def to_sse(self) -> str:
        return f"event: agent_update\ndata: {self.model_dump_json()}\n\n"
