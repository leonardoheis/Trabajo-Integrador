from dataclasses import dataclass


class PipelineError(Exception):
    """Base exception for all pipeline/job-related errors."""


@dataclass
class JobNotFoundError(PipelineError):
    job_id: str

    def __post_init__(self) -> None:
        super().__init__(str(self))

    def __str__(self) -> str:
        return f"Job {self.job_id} not found"


@dataclass
class JobNotInReviewError(PipelineError):
    job_id: str
    status: str

    def __post_init__(self) -> None:
        super().__init__(str(self))

    def __str__(self) -> str:
        return f"Job {self.job_id} is not in review (status={self.status})"
