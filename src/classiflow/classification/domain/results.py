from pydantic import Field

from classiflow.domain.base import BaseEntity


class PrimaryClassificationOutput(BaseEntity):
    label: str
    confidence: float
    all_scores: dict[str, float] = Field(default_factory=dict)


class JudgeOutput(BaseEntity):
    accept: bool
    reasoning: str = ""


class RoutingResult(BaseEntity):
    stored_path: str
