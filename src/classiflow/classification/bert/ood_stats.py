"""Ported from bert_tunning's src/ood.py -- inference-time subset only. See this task's
description for what was deliberately left out (training/calibration functions)."""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, NamedTuple, Protocol, runtime_checkable

import numpy as np
import numpy.typing as npt
from numpy.lib.npyio import NpzFile
from scipy.stats import chi2
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_distances

from classiflow.classification.bert.text_cleaning import clean_text
from classiflow.classification.config_classification import ClassificationConfig
from classiflow.classification.exceptions import ClassificationArtifactError

log = logging.getLogger(__name__)

# sklearn.feature_extraction.text.TfidfVectorizer has no type stubs
# (ignore_missing_imports=true) -- a Protocol capturing only the method actually called
# here keeps Any from leaking into this module's checked signatures, same pattern as
# FittedClassifier in svm_reviewer.py. FittedVectorizer (not _-prefixed): ood_scorer.py
# also needs it for _tfidf_vectorizer's return type, so this is a real shared type now.


@runtime_checkable
class _SparseMatrix(Protocol):
    def toarray(self) -> npt.NDArray[np.float64]: ...


@runtime_checkable
class FittedVectorizer(Protocol):
    def transform(self, raw_documents: list[str]) -> _SparseMatrix: ...


@dataclass(frozen=True)
class EmbeddingStats:
    pca_mean: npt.NDArray[np.float64]
    pca_components: npt.NDArray[np.float64]
    centroids: npt.NDArray[np.float64]
    covariance_inv: npt.NDArray[np.float64]
    cosine_calibration_mean: float
    cosine_calibration_std: float
    knn_train_embeddings: npt.NDArray[np.float64]
    knn_train_labels: list[int]


@dataclass(frozen=True)
class LexicalStats:
    vocabulary_terms: list[str] = field(default_factory=list)
    idf: npt.NDArray[np.float64] = field(default_factory=lambda: np.zeros(0, dtype=np.float64))
    centroids: npt.NDArray[np.float64] = field(
        default_factory=lambda: np.zeros((0, 0), dtype=np.float64)
    )
    cosine_calibration_mean: float = 0.0
    cosine_calibration_std: float = 1.0

    def is_fitted(self) -> bool:
        return bool(self.vocabulary_terms)


@dataclass(frozen=True)
class CalibratedThresholds:
    mahalanobis_p: float | None = None
    cosine: float | None = None
    knn_distance: float | None = None
    tfidf_cosine: float | None = None
    mahalanobis_status: Literal["not_calibrated", "calibrated", "refused_degenerate"] = (
        "not_calibrated"
    )


@dataclass(frozen=True)
class ArtifactMetadata:
    model_type: str
    model_hidden_size: int


@dataclass(frozen=True)
class OodArtifact:
    format_version: int
    class_names: list[str]
    embedding: EmbeddingStats
    lexical: LexicalStats = field(default_factory=LexicalStats)
    thresholds: CalibratedThresholds = field(default_factory=CalibratedThresholds)
    metadata: ArtifactMetadata | None = None


def _project(embedding: npt.NDArray[np.float64], stats: OodArtifact) -> npt.NDArray[np.float64]:
    return (embedding - stats.embedding.pca_mean) @ stats.embedding.pca_components.T


def _cosine_min_distance_raw(
    point: npt.NDArray[np.float64], centroids: npt.NDArray[np.float64]
) -> float:
    return float(cosine_distances(point.reshape(1, -1), centroids).min())


def build_tfidf_vectorizer(stats: OodArtifact) -> FittedVectorizer | None:
    # Reconstructs a fixed-vocabulary vectorizer from the two arrays load_stats round-trips
    # through ood_stats.npz -- bit-identical .transform() output to the vectorizer
    # bert_tunning originally fit. None when this model's ood_stats.npz predates the
    # TF-IDF signal (vocabulary_terms empty).
    if not stats.lexical.is_fitted():
        return None
    vocabulary = {term: i for i, term in enumerate(stats.lexical.vocabulary_terms)}
    vectorizer: FittedVectorizer = TfidfVectorizer(vocabulary=vocabulary)
    vectorizer.idf_ = stats.lexical.idf  # type: ignore[attr-defined]
    return vectorizer


def tfidf_cosine_z_score(text: str, stats: OodArtifact, vectorizer: FittedVectorizer) -> float:
    point = vectorizer.transform([clean_text(text)]).toarray()[0]
    cosine_raw = _cosine_min_distance_raw(point, stats.lexical.centroids)
    lexical = stats.lexical
    return (cosine_raw - lexical.cosine_calibration_mean) / lexical.cosine_calibration_std


def mahalanobis_min_distance(embedding: npt.NDArray[np.float64], stats: OodArtifact) -> float:
    point = _project(embedding, stats)
    diffs = stats.embedding.centroids - point
    distances = np.einsum("kd,de,ke->k", diffs, stats.embedding.covariance_inv, diffs)
    return float(np.min(distances))


def cosine_min_distance(embedding: npt.NDArray[np.float64], stats: OodArtifact) -> float:
    point = _project(embedding, stats)
    return _cosine_min_distance_raw(point, stats.embedding.centroids)


def mahalanobis_chi2_p_value_from_distance(squared_distance: float, stats: OodArtifact) -> float:
    degrees_of_freedom = stats.embedding.centroids.shape[1]
    return float(chi2.sf(squared_distance, df=degrees_of_freedom))


def empirical_survival_p_value(distance: float, reference: npt.NDArray[np.float64]) -> float:
    # Standard permutation-test empirical p-value: fraction of `reference` values at least
    # as extreme as `distance`, +1/+1 corrected so the result is never exactly 0. Raises on
    # an empty reference rather than fail-open-returning 1.0 -- silently "maximally normal"
    # would be backwards for an anomaly-detection signal.
    if len(reference) == 0:
        msg = "empirical_survival_p_value: reference array is empty, cannot rank against it"
        raise ValueError(msg)
    exceed_count = int(np.sum(reference >= distance))
    return (exceed_count + 1) / (len(reference) + 1)


def compute_train_mahalanobis_distances(stats: OodArtifact) -> npt.NDArray[np.float64]:
    # Squared Mahalanobis distance from every training document to its OWN TRUE class
    # centroid (via knn_train_labels), not the nearest one -- the reference distribution
    # mahalanobis_empirical_p_value ranks a query point's nearest-centroid distance against.
    labels_arr = np.asarray(stats.embedding.knn_train_labels)
    distances = np.empty(len(stats.embedding.knn_train_embeddings), dtype=np.float64)
    for i, point in enumerate(stats.embedding.knn_train_embeddings):
        centroid = stats.embedding.centroids[labels_arr[i]]
        diff = centroid - point
        distances[i] = float(diff @ stats.embedding.covariance_inv @ diff)
    return distances


def mahalanobis_empirical_p_value(
    embedding: npt.NDArray[np.float64],
    stats: OodArtifact,
    train_distances: npt.NDArray[np.float64],
) -> float:
    distance = mahalanobis_min_distance(embedding, stats)
    return empirical_survival_p_value(distance, train_distances)


def cosine_z_score(embedding: npt.NDArray[np.float64], stats: OodArtifact) -> float:
    cosine_raw = cosine_min_distance(embedding, stats)
    mean, std = stats.embedding.cosine_calibration_mean, stats.embedding.cosine_calibration_std
    return (cosine_raw - mean) / std


# ponytail: bert_tunning's own fixed default (Settings.OOD_KNN_NEIGHBORS), never
# overridden by any committed model -- hardcoded here rather than plumbed through
# ClassificationConfig/classification.yaml, which the spec doesn't ask to add a key for.
# Add a config field if a future model ever needs a different value.
_KNN_NEIGHBORS = 10


def knn_mean_distance(
    embedding: npt.NDArray[np.float64],
    stats: OodArtifact,
    predicted_label_id: int,
    *,
    k: int = _KNN_NEIGHBORS,
) -> float:
    # Mean Euclidean distance, in PCA space, to the k nearest training documents that share
    # the predicted class. NaN if the predicted class has zero training points -- callers
    # must treat NaN as anomalous (fail-closed), since `nan > threshold` silently is False.
    point = _project(embedding, stats)
    labels_arr = np.array(stats.embedding.knn_train_labels)
    class_points = stats.embedding.knn_train_embeddings[labels_arr == predicted_label_id]
    if class_points.shape[0] == 0:
        log.warning(
            "knn_mean_distance: class %d has zero training points — returning NaN",
            predicted_label_id,
        )
        return float("nan")
    k_eff = min(k, class_points.shape[0])
    distances = np.linalg.norm(class_points - point, axis=1)
    nearest = np.partition(distances, k_eff - 1)[:k_eff]
    return float(nearest.mean())


class OodThresholds(NamedTuple):
    mahalanobis_p: float
    cosine_z: float
    knn_distance: float
    tfidf_cosine_z: float


def resolve_ood_thresholds(stats: OodArtifact, config: ClassificationConfig) -> OodThresholds:
    # Falls back to config.ood_* per-field, only for whichever threshold this model's own
    # ood_stats.npz hasn't calibrated (None) -- a fully-calibrated stats file never reads
    # config at all.
    return OodThresholds(
        mahalanobis_p=(
            stats.thresholds.mahalanobis_p
            if stats.thresholds.mahalanobis_p is not None
            else config.ood_mahalanobis_p_threshold
        ),
        cosine_z=(
            stats.thresholds.cosine
            if stats.thresholds.cosine is not None
            else config.ood_cosine_threshold
        ),
        knn_distance=(
            stats.thresholds.knn_distance
            if stats.thresholds.knn_distance is not None
            else config.ood_knn_distance_threshold
        ),
        tfidf_cosine_z=(
            stats.thresholds.tfidf_cosine
            if stats.thresholds.tfidf_cosine is not None
            else config.ood_tfidf_cosine_threshold
        ),
    )


class OodCalibrationStatus(NamedTuple):
    mahalanobis: Literal["calibrated", "not_calibrated", "refused_degenerate"]
    cosine: Literal["calibrated", "not_calibrated"]
    knn_distance: Literal["calibrated", "not_calibrated"]
    tfidf_cosine: Literal["calibrated", "not_calibrated"] | None


def resolve_ood_calibration_status(stats: OodArtifact) -> OodCalibrationStatus:
    thresholds = stats.thresholds
    return OodCalibrationStatus(
        mahalanobis=thresholds.mahalanobis_status,
        cosine="calibrated" if thresholds.cosine is not None else "not_calibrated",
        knn_distance="calibrated" if thresholds.knn_distance is not None else "not_calibrated",
        tfidf_cosine=(
            None
            if not stats.lexical.is_fitted()
            else ("calibrated" if thresholds.tfidf_cosine is not None else "not_calibrated")
        ),
    )


def _optional_threshold(data: npt.NDArray[np.float64]) -> float | None:
    value = float(data)
    return None if np.isnan(value) else value


def _optional_str(data: npt.NDArray[np.str_]) -> str | None:
    value = str(data)
    return value or None


# .npz has no native way to store None for an int field -- writers encode "not set"
# as this sentinel instead, since a real model_hidden_size is always positive.
_MISSING_INT_SENTINEL = -1


def _optional_int(data: npt.NDArray[np.int_]) -> int | None:
    value = int(data)
    return None if value == _MISSING_INT_SENTINEL else value


def _threshold_status(
    data: npt.NDArray[np.str_],
) -> Literal["not_calibrated", "calibrated", "refused_degenerate"]:
    value = str(data)
    if value in {"not_calibrated", "calibrated", "refused_degenerate"}:
        return value  # type: ignore[return-value]
    msg = f"ood_stats.npz has an unrecognized mahalanobis_threshold_status: {value!r}"
    raise ClassificationArtifactError(reason=msg)


def _load_embedding_stats(data: NpzFile) -> EmbeddingStats:
    return EmbeddingStats(
        pca_mean=data["pca_mean"],
        pca_components=data["pca_components"],
        centroids=data["centroids"],
        covariance_inv=data["covariance_inv"],
        cosine_calibration_mean=float(data["cosine_calibration_mean"]),
        cosine_calibration_std=float(data["cosine_calibration_std"]),
        knn_train_embeddings=data["knn_train_embeddings"],
        knn_train_labels=data["knn_train_labels"].tolist(),
    )


def _load_lexical_stats(data: NpzFile) -> LexicalStats:
    # "in data.files", not data.get() -- NpzFile has no .get(). Lets a pre-TF-IDF
    # ood_stats.npz (missing these keys entirely) still load with lexical scoring disabled.
    if "tfidf_vocabulary_terms" not in data.files:
        return LexicalStats()
    return LexicalStats(
        vocabulary_terms=data["tfidf_vocabulary_terms"].tolist(),
        idf=data["tfidf_idf"],
        centroids=data["tfidf_centroids"],
        cosine_calibration_mean=float(data["tfidf_cosine_calibration_mean"]),
        cosine_calibration_std=float(data["tfidf_cosine_calibration_std"]),
    )


def _load_thresholds(data: NpzFile) -> CalibratedThresholds:
    return CalibratedThresholds(
        mahalanobis_p=(
            _optional_threshold(data["mahalanobis_p_threshold"])
            if "mahalanobis_p_threshold" in data.files
            else None
        ),
        cosine=(
            _optional_threshold(data["cosine_threshold"])
            if "cosine_threshold" in data.files
            else None
        ),
        knn_distance=(
            _optional_threshold(data["knn_distance_threshold"])
            if "knn_distance_threshold" in data.files
            else None
        ),
        tfidf_cosine=(
            _optional_threshold(data["tfidf_threshold"])
            if "tfidf_threshold" in data.files
            else None
        ),
        mahalanobis_status=(
            _threshold_status(data["mahalanobis_threshold_status"])
            if "mahalanobis_threshold_status" in data.files
            else "not_calibrated"
        ),
    )


def _load_metadata(data: NpzFile) -> ArtifactMetadata | None:
    if "model_type" not in data.files or "model_hidden_size" not in data.files:
        return None
    model_type = _optional_str(data["model_type"])
    model_hidden_size = _optional_int(data["model_hidden_size"])
    if model_type is None or model_hidden_size is None:
        return None
    return ArtifactMetadata(model_type=model_type, model_hidden_size=model_hidden_size)


def load_stats(path: Path) -> OodArtifact:
    data = np.load(str(path), allow_pickle=False)
    format_version = int(data["format_version"]) if "format_version" in data.files else 1
    return OodArtifact(
        format_version=format_version,
        class_names=data["class_names"].tolist(),
        embedding=_load_embedding_stats(data),
        lexical=_load_lexical_stats(data),
        thresholds=_load_thresholds(data),
        metadata=_load_metadata(data),
    )
