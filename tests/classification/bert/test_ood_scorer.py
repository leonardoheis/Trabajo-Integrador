from pathlib import Path

import numpy as np
import pytest

from classiflow.classification.bert.ood_scorer import OodMetrics, OodScorer
from classiflow.classification.config_classification import ClassificationConfig
from classiflow.classification.exceptions import ClassificationArtifactError

_MAHALANOBIS_P_THRESHOLD = 0.001
_COSINE_THRESHOLD = 13.0
_KNN_THRESHOLD = 5.0
_NEAR_IMPOSSIBLE_MAHALANOBIS_P_THRESHOLD = 0.9
_MODEL_HIDDEN_SIZE = 4
_WRONG_MODEL_HIDDEN_SIZE = 999


def _write_minimal_stats(path: Path, *, with_thresholds: bool = False) -> None:
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
        knn_train_embeddings=np.array([[0.1, 0.1], [0.2, 0.2], [10.1, 10.1], [10.2, 10.2]]),
        knn_train_labels=np.array([0, 0, 1, 1]),
        mahalanobis_p_threshold=(0.01 if with_thresholds else np.nan),
        cosine_threshold=(5.0 if with_thresholds else np.nan),
        knn_distance_threshold=(3.0 if with_thresholds else np.nan),
        tfidf_threshold=np.nan,
        mahalanobis_threshold_status=("calibrated" if with_thresholds else "not_calibrated"),
        model_type="bert",
        model_hidden_size=_MODEL_HIDDEN_SIZE,
    )


class TestOodScorerLoad:
    def test_returns_none_when_no_stats_file(self, tmp_path: Path) -> None:
        assert OodScorer.load(str(tmp_path)) is None

    def test_loads_when_stats_file_present(self, tmp_path: Path) -> None:
        _write_minimal_stats(tmp_path / "ood_stats.npz")
        assert OodScorer.load(str(tmp_path)) is not None


class TestOodScorerValidate:
    def test_raises_on_class_name_mismatch(self, tmp_path: Path) -> None:
        _write_minimal_stats(tmp_path / "ood_stats.npz")
        scorer = OodScorer.load(str(tmp_path))
        assert scorer is not None
        with pytest.raises(ClassificationArtifactError, match="do not match"):
            scorer.validate({0: "class_a", 1: "wrong_name"}, "bert", _MODEL_HIDDEN_SIZE)

    def test_raises_on_model_identity_mismatch(self, tmp_path: Path) -> None:
        _write_minimal_stats(tmp_path / "ood_stats.npz")
        scorer = OodScorer.load(str(tmp_path))
        assert scorer is not None
        with pytest.raises(ClassificationArtifactError, match="different model architecture"):
            scorer.validate({0: "class_a", 1: "class_b"}, "bert", _WRONG_MODEL_HIDDEN_SIZE)

    def test_passes_for_matching_model(self, tmp_path: Path) -> None:
        _write_minimal_stats(tmp_path / "ood_stats.npz")
        scorer = OodScorer.load(str(tmp_path))
        assert scorer is not None
        scorer.validate({0: "class_a", 1: "class_b"}, "bert", _MODEL_HIDDEN_SIZE)  # must not raise


class TestOodScorerScore:
    def test_returns_metrics_for_in_distribution_point(self, tmp_path: Path) -> None:
        _write_minimal_stats(tmp_path / "ood_stats.npz")
        scorer = OodScorer.load(str(tmp_path))
        assert scorer is not None
        config = ClassificationConfig(
            ood_mahalanobis_p_threshold=_MAHALANOBIS_P_THRESHOLD,
            ood_cosine_threshold=_COSINE_THRESHOLD,
            ood_knn_distance_threshold=_KNN_THRESHOLD,
        )
        metrics = scorer.score("texto de prueba", np.array([0.15, 0.15]), pred_idx=0, config=config)
        assert metrics is not None
        assert isinstance(metrics, OodMetrics)
        assert metrics.in_distribution is True

    def test_flags_anomalous_point_via_mahalanobis(self, tmp_path: Path) -> None:
        _write_minimal_stats(tmp_path / "ood_stats.npz")
        scorer = OodScorer.load(str(tmp_path))
        assert scorer is not None
        config = ClassificationConfig(
            ood_mahalanobis_p_threshold=_NEAR_IMPOSSIBLE_MAHALANOBIS_P_THRESHOLD
        )
        metrics = scorer.score(
            "texto de prueba", np.array([500.0, 500.0]), pred_idx=0, config=config
        )
        assert metrics is not None
        assert metrics.in_distribution is False
        assert "low_mahalanobis_p" in metrics.smells
