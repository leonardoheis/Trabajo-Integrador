"""Ported from bert_tunning's src/inference/ood_scorer.py -- the four embedding/lexical
out-of-distribution signals (Mahalanobis, cosine, k-NN, TF-IDF), combined into one
per-document score() call."""

import logging
from functools import cached_property
from pathlib import Path
from typing import Literal, NamedTuple

import numpy as np
import numpy.typing as npt
from pydantic import Field

from classiflow.classification.bert.ood_stats import (
    FittedVectorizer,
    OodArtifact,
    OodCalibrationStatus,
    OodThresholds,
    build_tfidf_vectorizer,
    compute_train_mahalanobis_distances,
    cosine_z_score,
    empirical_survival_p_value,
    knn_mean_distance,
    load_stats,
    mahalanobis_chi2_p_value_from_distance,
    mahalanobis_min_distance,
    resolve_ood_calibration_status,
    resolve_ood_thresholds,
    tfidf_cosine_z_score,
)
from classiflow.classification.bert.smell_thresholds import (
    SmellThresholds,
    resolve_smell_thresholds,
)
from classiflow.classification.config_classification import ClassificationConfig
from classiflow.classification.exceptions import ClassificationArtifactError
from classiflow.domain.base import BaseEntity

log = logging.getLogger(__name__)


class OodMetrics(BaseEntity):
    mahalanobis_p_value: float
    mahalanobis_p_value_theoretical: float
    cosine_z: float
    knn_distance: float
    tfidf_cosine_z: float | None = None
    in_distribution: bool
    mahalanobis_calibration_status: Literal[
        "calibrated", "not_calibrated", "refused_degenerate"
    ] = "calibrated"
    cosine_calibration_status: Literal["calibrated", "not_calibrated"] = "calibrated"
    knn_distance_calibration_status: Literal["calibrated", "not_calibrated"] = "calibrated"
    tfidf_calibration_status: Literal["calibrated", "not_calibrated"] | None = None
    smells: list[str] = Field(default_factory=list)


class OodScores(NamedTuple):
    mahalanobis_p: float
    cosine_z: float
    knn_distance: float
    tfidf_cosine_z: float = float("nan")


_NO_SMELL_THRESHOLDS = SmellThresholds()
# ponytail: bert_tunning's own fixed default (Settings.OOD_ALLOW_UNCALIBRATED_FALLBACK) --
# both committed production models rely on this fallback today, and neither spec asks for
# it to be configurable. Promote to a ClassificationConfig field if a future model needs
# strict per-model calibration enforcement.
_ALLOW_UNCALIBRATED_FALLBACK = True


class OodSignalBreakdown(NamedTuple):
    mahalanobis: bool
    cosine: bool
    knn_distance: bool
    tfidf: bool


def _signal_breakdown(
    scores: OodScores, thresholds: OodThresholds, calibration_status: OodCalibrationStatus
) -> OodSignalBreakdown:
    maha_blocked = (
        not _ALLOW_UNCALIBRATED_FALLBACK and calibration_status.mahalanobis == "not_calibrated"
    )
    maha_anomalous = not maha_blocked and scores.mahalanobis_p < thresholds.mahalanobis_p
    cosine_blocked = (
        not _ALLOW_UNCALIBRATED_FALLBACK and calibration_status.cosine == "not_calibrated"
    )
    cosine_anomalous = not cosine_blocked and scores.cosine_z > thresholds.cosine_z
    knn_blocked = (
        not _ALLOW_UNCALIBRATED_FALLBACK and calibration_status.knn_distance == "not_calibrated"
    )
    # NaN means the predicted class had zero training points -- fail-closed (anomalous).
    knn_anomalous = not knn_blocked and (
        bool(np.isnan(scores.knn_distance)) or scores.knn_distance > thresholds.knn_distance
    )
    tfidf_blocked = (
        not _ALLOW_UNCALIBRATED_FALLBACK and calibration_status.tfidf_cosine == "not_calibrated"
    )
    # Opposite NaN polarity from knn_anomalous, deliberately -- NaN here means this
    # model's ood_stats.npz predates the TF-IDF signal entirely (fail-open), not that this
    # document's signal failed to compute.
    tfidf_anomalous = not tfidf_blocked and (
        not np.isnan(scores.tfidf_cosine_z) and scores.tfidf_cosine_z > thresholds.tfidf_cosine_z
    )
    return OodSignalBreakdown(maha_anomalous, cosine_anomalous, knn_anomalous, tfidf_anomalous)


_SMELL_NAMES = {
    "mahalanobis": "low_mahalanobis_p",
    "cosine": "high_cosine_z",
    "knn_distance": "high_knn_distance",
    "tfidf": "high_tfidf_z",
}


def _smells_from_breakdown(breakdown: OodSignalBreakdown) -> list[str]:
    return [name for field_name, name in _SMELL_NAMES.items() if getattr(breakdown, field_name)]


class OodScorer:
    """Owns everything derived from a loaded ood_stats.npz: validation against the model
    it's paired with, the uncalibrated-threshold warning, and per-document scoring. One
    instance per SecondOpinionNode's loaded model, built once via load()."""

    def __init__(self, stats: OodArtifact) -> None:
        self._stats = stats

    @staticmethod
    def load(model_path: str) -> "OodScorer | None":
        stats_path = Path(model_path) / "ood_stats.npz"
        if not stats_path.exists():
            log.info("No ood_stats.npz found at %s — OOD scoring disabled", stats_path)
            return None
        log.info("Loaded OOD stats from %s", stats_path)
        return OodScorer(load_stats(stats_path))

    def validate(self, id2label: dict[int, str], model_type: str, model_hidden_size: int) -> None:
        self._validate_class_mapping(id2label)
        self._validate_model_identity(model_type, model_hidden_size)

    def _validate_class_mapping(self, id2label: dict[int, str]) -> None:
        # ood_stats.npz's class_names must match this model's id2label by count AND
        # ordered index, since knn_mean_distance() indexes stats.knn_train_labels
        # directly by the model's own predicted label id.
        expected = [id2label[i] for i in range(len(id2label))]
        if self._stats.class_names != expected:
            msg = (
                f"ood_stats.npz class_names {self._stats.class_names} do not match "
                f"this model's id2label {expected} (order matters, not just the set)."
            )
            raise ClassificationArtifactError(reason=msg)

    def _validate_model_identity(self, model_type: str, model_hidden_size: int) -> None:
        metadata = self._stats.metadata
        if metadata is None:
            return
        mismatched = (
            metadata.model_type != model_type or metadata.model_hidden_size != model_hidden_size
        )
        if mismatched:
            msg = (
                f"ood_stats.npz was computed from model_type={metadata.model_type!r}, "
                f"hidden_size={metadata.model_hidden_size}, but the loaded model is "
                f"model_type={model_type!r}, hidden_size={model_hidden_size} -- this "
                "ood_stats.npz belongs to a different model architecture."
            )
            raise ClassificationArtifactError(reason=msg)

    def warn_if_uncalibrated(self) -> None:
        status = resolve_ood_calibration_status(self._stats)
        uncalibrated = [
            name
            for name, value in (
                ("mahalanobis_p_threshold", status.mahalanobis),
                ("cosine_threshold", status.cosine),
                ("knn_distance_threshold", status.knn_distance),
                ("tfidf_threshold", status.tfidf_cosine),
            )
            if value == "not_calibrated"
        ]
        if uncalibrated:
            log.warning(
                "ood_stats.npz has no per-model value for %s — falling back to "
                "ClassificationConfig.ood_* (calibrated for a specific model, not "
                "necessarily this one).",
                ", ".join(uncalibrated),
            )
        if status.mahalanobis == "refused_degenerate":
            log.info(
                "mahalanobis_p_threshold falls back to config.ood_mahalanobis_p_threshold "
                "because bert_tunning's degenerate-threshold guard correctly refused to "
                "persist a floor-adjacent value for this model — expected, no action needed."
            )

    @cached_property
    def _train_mahalanobis_distances(self) -> npt.NDArray[np.float64]:
        return compute_train_mahalanobis_distances(self._stats)

    @cached_property
    def _tfidf_vectorizer(self) -> FittedVectorizer | None:
        return build_tfidf_vectorizer(self._stats)

    def score(
        self,
        text: str,
        embedding: npt.NDArray[np.float64],
        pred_idx: int,
        config: ClassificationConfig,
        smell_thresholds: SmellThresholds = _NO_SMELL_THRESHOLDS,
    ) -> OodMetrics | None:
        train_distances = self._train_mahalanobis_distances
        if len(train_distances) == 0:
            log.warning(
                "ood_stats.npz has no k-NN training data (empty knn_train_embeddings) — "
                "OOD scoring disabled for this prediction"
            )
            return None
        tfidf_z = (
            tfidf_cosine_z_score(text, self._stats, self._tfidf_vectorizer)
            if self._tfidf_vectorizer is not None
            else float("nan")
        )
        squared_distance = mahalanobis_min_distance(embedding, self._stats)
        scores = OodScores(
            mahalanobis_p=empirical_survival_p_value(squared_distance, train_distances),
            cosine_z=cosine_z_score(embedding, self._stats),
            knn_distance=knn_mean_distance(embedding, self._stats, pred_idx),
            tfidf_cosine_z=tfidf_z,
        )
        maha_p_theoretical = mahalanobis_chi2_p_value_from_distance(squared_distance, self._stats)
        decision_thresholds = resolve_ood_thresholds(self._stats, config)
        calibration_status = resolve_ood_calibration_status(self._stats)

        breakdown = _signal_breakdown(scores, decision_thresholds, calibration_status)
        smell_signal_thresholds = resolve_smell_thresholds(smell_thresholds, decision_thresholds)
        smell_breakdown = _signal_breakdown(scores, smell_signal_thresholds, calibration_status)

        return OodMetrics(
            mahalanobis_p_value=round(scores.mahalanobis_p, 6),
            mahalanobis_p_value_theoretical=round(maha_p_theoretical, 6),
            cosine_z=round(scores.cosine_z, 4),
            knn_distance=round(scores.knn_distance, 4),
            tfidf_cosine_z=(
                None if np.isnan(scores.tfidf_cosine_z) else round(scores.tfidf_cosine_z, 4)
            ),
            in_distribution=not any(breakdown),
            mahalanobis_calibration_status=calibration_status.mahalanobis,
            cosine_calibration_status=calibration_status.cosine,
            knn_distance_calibration_status=calibration_status.knn_distance,
            tfidf_calibration_status=calibration_status.tfidf_cosine,
            smells=_smells_from_breakdown(smell_breakdown),
        )
