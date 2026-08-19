"""Ported from bert_tunning's src/smell_thresholds.py -- load + resolve only
(save_smell_thresholds is a training/calibration-time write path, not ported).
smell_thresholds.json is a second, deliberately decoupled threshold profile used only to
compute smell flags, never in_distribution/review_route directly."""

import logging
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from classiflow.classification.bert.ood_stats import OodThresholds

log = logging.getLogger(__name__)

_FILENAME = "smell_thresholds.json"
SmellSignalKey = Literal["mahalanobis_p", "cosine", "knn_distance", "tfidf_cosine", "svm_margin"]


class SmellThresholds(BaseModel):
    model_config = ConfigDict(frozen=True)

    thresholds: dict[SmellSignalKey, float] = {}
    mahalanobis_status: Literal["not_calibrated", "calibrated", "refused_degenerate"] = (
        "not_calibrated"
    )


def load_smell_thresholds(model_path: str) -> SmellThresholds:
    path = Path(model_path) / _FILENAME
    if not path.exists():
        log.info(
            "No smell_thresholds.json found at %s — smell thresholds fall back to this "
            "model's decision thresholds",
            path,
        )
        return SmellThresholds()
    return SmellThresholds.model_validate_json(path.read_text())


def resolve_smell_thresholds(
    smell_thresholds: SmellThresholds, decision_thresholds: OodThresholds
) -> OodThresholds:
    # Per-key fallback to the DECISION thresholds (not ClassificationConfig.ood_* directly)
    # when a key is missing -- an empty dict (no smell_thresholds.json, or a key never
    # customized) falls back to every decision-threshold value, so a model with no
    # smell_thresholds.json produces identical smells to the plain decision breakdown.
    thresholds = smell_thresholds.thresholds
    return OodThresholds(
        mahalanobis_p=thresholds.get("mahalanobis_p", decision_thresholds.mahalanobis_p),
        cosine_z=thresholds.get("cosine", decision_thresholds.cosine_z),
        knn_distance=thresholds.get("knn_distance", decision_thresholds.knn_distance),
        tfidf_cosine_z=thresholds.get("tfidf_cosine", decision_thresholds.tfidf_cosine_z),
    )
