"""Ported from bert_tunning's src/inference/classify.py -- BertClassifier.predict()
combines tokenization, the BETO forward pass, SVM reviewer scoring, and OOD scoring into
one call. Deliberately NOT ported: decide_review_route, ConfidenceTier, OodEvidence --
bert_tunning's own confidence-gate/routing logic. Classiflow's own Confidence Gate node
(classification/nodes/confidence_gate.py) and Smells/Risk node fully replace that."""

import logging
from pathlib import Path
from typing import Protocol

import numpy as np
import torch
from transformers import (
    AutoModelForSequenceClassification,
    AutoTokenizer,
    PreTrainedTokenizerBase,
)

from classiflow.classification.bert.ood_scorer import OodScorer
from classiflow.classification.bert.smell_thresholds import load_smell_thresholds
from classiflow.classification.bert.svm_reviewer import (
    FittedClassifier,
    load_svm_classifiers,
    svm_top_label,
)
from classiflow.classification.bert.svm_reviewer import svm_scores as compute_svm_scores
from classiflow.classification.bert.text_cleaning import clean_text
from classiflow.classification.config_classification import ClassificationConfig
from classiflow.classification.domain.results import SecondOpinionResult
from classiflow.classification.exceptions import ClassificationArtifactError

log = logging.getLogger(__name__)


class TransformerModelConfig(Protocol):
    """The subset of a loaded transformers model's .config this classifier reads."""

    id2label: dict[int, str]
    model_type: str
    hidden_size: int
    max_position_embeddings: int


class TransformerModelOutput(Protocol):
    """The subset of a forward-pass output this classifier reads."""

    logits: torch.Tensor
    hidden_states: tuple[torch.Tensor, ...]


class TransformerModel(Protocol):
    """The subset of a loaded transformers model this classifier depends on -- named
    explicitly instead of typed as Any."""

    config: TransformerModelConfig

    def eval(self) -> "TransformerModel": ...
    def to(self, device: str) -> "TransformerModel": ...
    def __call__(self, **kwargs: torch.Tensor | bool) -> TransformerModelOutput: ...


class BertClassifier:
    def __init__(
        self,
        model_path: str,
        config: ClassificationConfig,
        *,
        tokenizer: PreTrainedTokenizerBase | None = None,
        model: TransformerModel | None = None,
    ) -> None:
        log.info("Loading BETO classifier from %s", model_path)
        self.config = config
        self.tokenizer = tokenizer or AutoTokenizer.from_pretrained(model_path)
        self.model: TransformerModel = model or AutoModelForSequenceClassification.from_pretrained(
            model_path
        )
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model.eval()
        self.model.to(self.device)
        self.max_length = min(
            self.tokenizer.model_max_length, self.model.config.max_position_embeddings
        )
        self.ood_scorer = OodScorer.load(model_path)
        if self.ood_scorer is not None:
            self.ood_scorer.validate(
                self.model.config.id2label,
                self.model.config.model_type,
                self.model.config.hidden_size,
            )
            self.ood_scorer.warn_if_uncalibrated()
        self.svm_classifiers = self._load_svm_classifiers(model_path)
        self._validate_svm_classifiers_class_mapping()
        self._smell_thresholds = load_smell_thresholds(model_path)
        log.info("BETO classifier ready on %s (max_length=%d)", self.device, self.max_length)

    @staticmethod
    def _load_svm_classifiers(model_path: str) -> dict[str, FittedClassifier] | None:
        classifiers_path = Path(model_path) / "svm_classifiers.joblib"
        classifiers = load_svm_classifiers(classifiers_path)
        if classifiers is None:
            log.info(
                "No svm_classifiers.joblib found at %s — SVM reviewer disabled",
                classifiers_path,
            )
            return None
        log.info("Loaded SVM reviewer classifiers from %s", classifiers_path)
        return classifiers

    def _validate_svm_classifiers_class_mapping(self) -> None:
        # svm_classifiers.joblib is keyed by class NAME -- only the set needs to match,
        # not the order (unlike ood_stats.npz's class_names, indexed positionally).
        if self.svm_classifiers is None:
            return
        id2label: dict[int, str] = self.model.config.id2label
        expected = set(id2label.values())
        actual = set(self.svm_classifiers.keys())
        if actual != expected:
            msg = (
                f"svm_classifiers.joblib classes {sorted(actual)} do not match this "
                f"model's id2label classes {sorted(expected)} -- svm_scores would be "
                "computed for the wrong classes."
            )
            raise ClassificationArtifactError(reason=msg)

    def predict(self, text: str) -> SecondOpinionResult:
        inputs = self.tokenizer(
            clean_text(text),
            truncation=True,
            padding="max_length",
            max_length=self.max_length,
            return_tensors="pt",
        ).to(self.device)

        with torch.no_grad():
            outputs = self.model(**inputs, output_hidden_states=True)
            probs = torch.softmax(outputs.logits, dim=-1)[0].cpu().numpy()
            cls_embedding = outputs.hidden_states[-1][:, 0, :][0].cpu().numpy().astype(np.float64)

        id2label = self.model.config.id2label
        pred_idx = int(np.argmax(probs))
        confidence = float(probs[pred_idx])
        label = id2label[pred_idx]
        all_scores = {id2label[i]: round(float(p), 4) for i, p in enumerate(probs)}

        if self.svm_classifiers is None:
            svm_scores_dict: dict[str, float] = {}
            svm_predicted_label, svm_agrees_with_prediction = "", True
        else:
            svm_scores_result = compute_svm_scores(cls_embedding, self.svm_classifiers)
            svm_scores_dict = {s.class_name: s.margin for s in svm_scores_result}
            svm_predicted_label = svm_top_label(svm_scores_result)
            svm_agrees_with_prediction = svm_predicted_label == label

        ood_metrics = None
        if self.ood_scorer is not None:
            ood_metrics = self.ood_scorer.score(
                text, cls_embedding, pred_idx, self.config, self._smell_thresholds
            )

        return SecondOpinionResult(
            label=label,
            confidence=round(confidence, 4),
            all_scores=all_scores,
            svm_scores=svm_scores_dict,
            svm_predicted_label=svm_predicted_label,
            svm_agrees_with_prediction=svm_agrees_with_prediction,
            ood_metrics=ood_metrics,
        )
