import json
from pathlib import Path

from classiflow.classification.bert.ood_stats import OodThresholds
from classiflow.classification.bert.smell_thresholds import (
    SmellThresholds,
    load_smell_thresholds,
    resolve_smell_thresholds,
)

_EXPECTED_SVM_MARGIN = 0.1
_EXPECTED_MAHALANOBIS_P = 0.01
_EXPECTED_COSINE_Z = 5.0
_EXPECTED_KNN_DISTANCE = 3.0
_EXPECTED_TFIDF_COSINE_Z = 2.0
_EXPECTED_CUSTOM_COSINE_Z = 1.0


class TestLoadSmellThresholds:
    def test_returns_empty_defaults_when_file_missing(self, tmp_path: Path) -> None:
        thresholds = load_smell_thresholds(str(tmp_path))
        assert thresholds.thresholds == {}
        assert thresholds.mahalanobis_status == "not_calibrated"

    def test_loads_real_file(self, tmp_path: Path) -> None:
        (tmp_path / "smell_thresholds.json").write_text(
            json.dumps({
                "thresholds": {"svm_margin": _EXPECTED_SVM_MARGIN},
                "mahalanobis_status": "calibrated",
            })
        )
        thresholds = load_smell_thresholds(str(tmp_path))
        assert thresholds.thresholds == {"svm_margin": _EXPECTED_SVM_MARGIN}
        assert thresholds.mahalanobis_status == "calibrated"


class TestResolveSmellThresholds:
    def test_empty_thresholds_falls_back_to_decision_thresholds(self) -> None:
        decision = OodThresholds(
            mahalanobis_p=_EXPECTED_MAHALANOBIS_P,
            cosine_z=_EXPECTED_COSINE_Z,
            knn_distance=_EXPECTED_KNN_DISTANCE,
            tfidf_cosine_z=_EXPECTED_TFIDF_COSINE_Z,
        )
        resolved = resolve_smell_thresholds(SmellThresholds(), decision)
        assert resolved == decision

    def test_customized_key_overrides_decision_threshold(self) -> None:
        decision = OodThresholds(
            mahalanobis_p=_EXPECTED_MAHALANOBIS_P,
            cosine_z=_EXPECTED_COSINE_Z,
            knn_distance=_EXPECTED_KNN_DISTANCE,
            tfidf_cosine_z=_EXPECTED_TFIDF_COSINE_Z,
        )
        smell = SmellThresholds(thresholds={"cosine": _EXPECTED_CUSTOM_COSINE_Z})
        resolved = resolve_smell_thresholds(smell, decision)
        assert resolved.cosine_z == _EXPECTED_CUSTOM_COSINE_Z
        assert resolved.mahalanobis_p == _EXPECTED_MAHALANOBIS_P
