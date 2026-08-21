from dataclasses import dataclass


class JobError(Exception): ...


@dataclass
class JobNotFoundError(JobError):
    job_id: str

    def __post_init__(self) -> None:
        super().__init__(str(self))

    def __str__(self) -> str:
        return f"Job {self.job_id} not found"


@dataclass
class JobNotInReviewError(JobError):
    job_id: str
    status: str

    def __post_init__(self) -> None:
        super().__init__(str(self))

    def __str__(self) -> str:
        return f"Job {self.job_id} is not in review (status={self.status})"
