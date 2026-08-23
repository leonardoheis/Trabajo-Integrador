from pydantic import Field

from classiflow.classification.bert.ood_scorer import OodMetrics
from classiflow.domain.base import BaseEntity


class PrimaryClassificationOutput(BaseEntity):
    label: str
    confidence: float
    all_scores: dict[str, float] = Field(default_factory=dict)


class JudgeOutput(BaseEntity):
    accept: bool
    final_label: str
    reasoning: str = ""


class RoutingInput(BaseEntity):
    job_id: str
    filename: str
    enriched_id: int
    label: str
    confidence: float
    all_scores: dict[str, float] = Field(default_factory=dict)
    second_opinion_label: str | None = None
    second_opinion_confidence: float = 0.0
    classifier_disagreement: bool = False
    ood_metrics: OodMetrics | None = None
    svm_scores: dict[str, float] = Field(default_factory=dict)
    svm_agrees_with_prediction: bool = True
    review_route: str
    smells: list[str] = Field(default_factory=list)
    risk_score: int = 0
    smell_review_suggested: bool = False
    foreign_municipality: str | None = None
    judged_by_llm: bool = False
    judge_final_label: str | None = None
    judge_reasoning: str | None = None
    human_overridden: bool = False


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
