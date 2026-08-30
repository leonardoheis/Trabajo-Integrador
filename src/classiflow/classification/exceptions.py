from dataclasses import dataclass


class ClassificationError(Exception): ...


@dataclass
class ClassificationRecordNotFoundError(ClassificationError):
    job_id: str

    def __post_init__(self) -> None:
        super().__init__(str(self))

    def __str__(self) -> str:
        return f"Classification record for job {self.job_id} not found"


@dataclass
class ClassificationNotInReviewError(ClassificationError):
    job_id: str
    review_route: str

    def __post_init__(self) -> None:
        super().__init__(str(self))

    def __str__(self) -> str:
        return (
            f"Classification for job {self.job_id} is not awaiting human review "
            f"(review_route={self.review_route})"
        )


@dataclass
class ClassificationNotAcceptedError(ClassificationError):
    job_id: str
    review_route: str

    def __post_init__(self) -> None:
        super().__init__(str(self))

    def __str__(self) -> str:
        return (
            f"Classification for job {self.job_id} has not been accepted yet "
            f"(review_route={self.review_route})"
        )


@dataclass
class PrimaryClassificationFailedError(ClassificationError):
    reason: str

    def __post_init__(self) -> None:
        super().__init__(str(self))

    def __str__(self) -> str:
        return f"Primary classification failed: {self.reason}"


@dataclass
class ClassificationArtifactError(ClassificationError):
    reason: str

    def __post_init__(self) -> None:
        super().__init__(str(self))

    def __str__(self) -> str:
        return f"Classification artifact error: {self.reason}"


@dataclass
class LlmJudgeFailedError(ClassificationError):
    reason: str

    def __post_init__(self) -> None:
        super().__init__(str(self))

    def __str__(self) -> str:
        return f"LLM judge failed: {self.reason}"
