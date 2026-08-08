from dataclasses import dataclass


class AuditError(Exception):
    """Base exception for all audit-related errors."""


@dataclass
class MissingFieldError(AuditError):
    field: str

    def __post_init__(self) -> None:
        super().__init__(str(self))

    def __str__(self) -> str:
        return f"{self.field} is required"


@dataclass
class PersistenceError(AuditError):
    job_id: str
    node: str
    event: str

    def __post_init__(self) -> None:
        super().__init__(str(self))

    def __str__(self) -> str:
        return (
            f"Failed to persist audit record for"
            f" job={self.job_id} node={self.node} event={self.event}"
        )
