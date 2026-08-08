from dataclasses import dataclass


@dataclass(frozen=True)
class JobContext:
    job_id: str
    filename: str
