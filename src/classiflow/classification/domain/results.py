from pydantic import Field

from classiflow.classification.bert.ood_scorer import OodMetrics
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


class SecondOpinionResult(BaseEntity):
    label: str
    confidence: float
    all_scores: dict[str, float] = Field(default_factory=dict)
    svm_scores: dict[str, float] = Field(default_factory=dict)
    svm_predicted_label: str = ""
    svm_agrees_with_prediction: bool = True
    ood_metrics: OodMetrics | None = None


class SmellsRiskResult(BaseEntity):
    smells: list[str] = Field(default_factory=list)
    risk_score: int = 0
    smell_review_suggested: bool = False
