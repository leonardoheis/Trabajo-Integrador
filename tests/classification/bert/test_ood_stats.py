from pathlib import Path

import numpy as np
import pytest

from classiflow.classification.bert.ood_stats import (
    CalibratedThresholds,
    EmbeddingStats,
    OodArtifact,
    OodCalibrationStatus,
    OodThresholds,
    cosine_min_distance,
    cosine_z_score,
    empirical_survival_p_value,
    knn_mean_distance,
    load_stats,
    mahalanobis_chi2_p_value_from_distance,
    mahalanobis_min_distance,
    resolve_ood_calibration_status,
    resolve_ood_thresholds,
)
from classiflow.classification.config_classification import ClassificationConfig

_EXPECTED_MAHALANOBIS_DISTANCE = 0.5
_EXPECTED_MAHALANOBIS_P_THRESHOLD = 0.01
_EXPECTED_COSINE_THRESHOLD = 5.0
_EXPECTED_KNN_THRESHOLD = 3.0
_EXPECTED_TFIDF_THRESHOLD = 2.0
_EXPECTED_MAHALANOBIS_P_CALIBRATED = 0.005
_EXPECTED_FORMAT_VERSION = 2


def _stats() -> OodArtifact:
    # Two well-separated 2D classes; pca_mean=0/pca_components=identity makes _project()
    # a no-op, so assertions can reason about raw distances directly.
    centroids = np.array([[0.0, 0.0], [10.0, 10.0]])
    return OodArtifact(
        format_version=2,
        class_names=["class_a", "class_b"],
        embedding=EmbeddingStats(
            pca_mean=np.zeros(2),
            pca_components=np.eye(2),
            centroids=centroids,
            covariance_inv=np.eye(2),
            cosine_calibration_mean=0.5,
            cosine_calibration_std=0.1,
            knn_train_embeddings=np.array([[0.1, 0.1], [0.2, 0.2], [10.1, 10.1]]),
            knn_train_labels=[0, 0, 1],
        ),
    )


class TestMahalanobisMinDistance:
    def test_closer_to_class_a_centroid(self) -> None:
        distance = mahalanobis_min_distance(np.array([0.5, 0.5]), _stats())
        assert distance == pytest.approx(_EXPECTED_MAHALANOBIS_DISTANCE)  # 0.5^2 + 0.5^2


class TestCosineMinDistance:
    def test_returns_nonnegative_float(self) -> None:
        distance = cosine_min_distance(np.array([1.0, 1.0]), _stats())
        assert distance >= 0.0


class TestCosineZScore:
    def test_zscores_against_calibration_mean_and_std(self) -> None:
        stats = _stats()
        z = cosine_z_score(np.array([1.0, 1.0]), stats)
        raw = cosine_min_distance(np.array([1.0, 1.0]), stats)
        assert z == pytest.approx((raw - 0.5) / 0.1)


class TestKnnMeanDistance:
    def test_returns_mean_distance_to_predicted_class_neighbors(self) -> None:
        # Class 0 has exactly 2 training points ([0.1, 0.1], [0.2, 0.2]) and k=2 -- both
        # are the "k nearest", so the expected value is their mean distance, not just the
        # single closest point's distance.
        distance = knn_mean_distance(np.array([0.0, 0.0]), _stats(), predicted_label_id=0, k=2)
        expected = (float(np.hypot(0.1, 0.1)) + float(np.hypot(0.2, 0.2))) / 2
        assert distance == pytest.approx(expected)

    def test_returns_nan_for_class_with_no_training_points(self) -> None:
        distance = knn_mean_distance(np.array([0.0, 0.0]), _stats(), predicted_label_id=5, k=2)
        assert np.isnan(distance)


class TestMahalanobisChi2PValueFromDistance:
    def test_larger_distance_yields_smaller_p_value(self) -> None:
        stats = _stats()
        small_distance_p = mahalanobis_chi2_p_value_from_distance(0.1, stats)
        large_distance_p = mahalanobis_chi2_p_value_from_distance(50.0, stats)
        assert large_distance_p < small_distance_p


class TestEmpiricalSurvivalPValue:
    def test_rank_based_p_value(self) -> None:
        reference = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        p = empirical_survival_p_value(3.0, reference)
        assert p == pytest.approx((3 + 1) / (5 + 1))

    def test_raises_on_empty_reference(self) -> None:
        with pytest.raises(ValueError, match="reference array is empty"):
            empirical_survival_p_value(1.0, np.array([]))


class TestResolveOodThresholds:
    def test_falls_back_to_config_when_not_calibrated(self) -> None:
        stats = _stats()  # thresholds defaults to CalibratedThresholds() -- all None
        config = ClassificationConfig(
            ood_mahalanobis_p_threshold=_EXPECTED_MAHALANOBIS_P_THRESHOLD,
            ood_cosine_threshold=_EXPECTED_COSINE_THRESHOLD,
            ood_knn_distance_threshold=_EXPECTED_KNN_THRESHOLD,
            ood_tfidf_cosine_threshold=_EXPECTED_TFIDF_THRESHOLD,
        )
        resolved = resolve_ood_thresholds(stats, config)
        assert resolved == OodThresholds(
            mahalanobis_p=_EXPECTED_MAHALANOBIS_P_THRESHOLD,
            cosine_z=_EXPECTED_COSINE_THRESHOLD,
            knn_distance=_EXPECTED_KNN_THRESHOLD,
            tfidf_cosine_z=_EXPECTED_TFIDF_THRESHOLD,
        )

    def test_prefers_per_model_calibrated_threshold(self) -> None:
        stats = OodArtifact(
            format_version=2,
            class_names=["a"],
            embedding=_stats().embedding,
            thresholds=CalibratedThresholds(
                mahalanobis_p=_EXPECTED_MAHALANOBIS_P_CALIBRATED, mahalanobis_status="calibrated"
            ),
        )
        config = ClassificationConfig(ood_mahalanobis_p_threshold=_EXPECTED_MAHALANOBIS_P_THRESHOLD)
        resolved = resolve_ood_thresholds(stats, config)
        assert resolved.mahalanobis_p == _EXPECTED_MAHALANOBIS_P_CALIBRATED


class TestResolveOodCalibrationStatus:
    def test_uncalibrated_stats_report_not_calibrated(self) -> None:
        status = resolve_ood_calibration_status(_stats())
        assert status == OodCalibrationStatus(
            mahalanobis="not_calibrated",
            cosine="not_calibrated",
            knn_distance="not_calibrated",
            tfidf_cosine=None,
        )


class TestLoadStats:
    def test_round_trips_minimal_npz(self, tmp_path: Path) -> None:
        path = tmp_path / "ood_stats.npz"
        np.savez(
            str(path),
            format_version=2,
            class_names=np.array(["class_a", "class_b"]),
            pca_mean=np.zeros(2),
            pca_components=np.eye(2),
            centroids=np.array([[0.0, 0.0], [10.0, 10.0]]),
            covariance_inv=np.eye(2),
            cosine_calibration_mean=0.5,
            cosine_calibration_std=0.1,
            knn_train_embeddings=np.array([[0.1, 0.1], [10.1, 10.1]]),
            knn_train_labels=np.array([0, 1]),
            mahalanobis_p_threshold=np.nan,
            cosine_threshold=np.nan,
            knn_distance_threshold=np.nan,
            tfidf_threshold=np.nan,
            mahalanobis_threshold_status="not_calibrated",
            model_type="",
            model_hidden_size=-1,
        )

        stats = load_stats(path)

        assert stats.format_version == _EXPECTED_FORMAT_VERSION
        assert stats.class_names == ["class_a", "class_b"]
        assert stats.lexical.is_fitted() is False
        assert stats.thresholds.mahalanobis_p is None
        assert stats.metadata is None
