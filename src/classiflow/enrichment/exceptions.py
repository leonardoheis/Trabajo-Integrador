from dataclasses import dataclass


class EnrichmentError(Exception): ...


@dataclass
class EntityExtractionFailedError(EnrichmentError):
    reason: str

    def __post_init__(self) -> None:
        super().__init__(str(self))

    def __str__(self) -> str:
        return f"Entity extraction failed: {self.reason}"
