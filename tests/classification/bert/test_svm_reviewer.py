from pathlib import Path

import numpy as np
from sklearn.svm import SVC

from classiflow.classification.bert.svm_reviewer import (
    SvmClassScore,
    load_svm_classifiers,
    svm_scores,
    svm_top_label,
)

_EXPECTED_SCORE_A = 0.9
_EXPECTED_SCORE_B_NEGATIVE = -0.2
_EXPECTED_SCORE_A_NEGATIVE = -0.9
_EXPECTED_SCORE_B = 0.2


def _fitted_svc(positive_center: float) -> SVC:
    x = np.array([
        [positive_center],
        [positive_center + 0.1],
        [-positive_center],
        [-positive_center - 0.1],
    ])
    y = np.array([1, 1, 0, 0])
    svc = SVC(kernel="linear")
    svc.fit(x, y)
    return svc


class TestLoadSvmClassifiers:
    def test_returns_none_when_file_missing(self, tmp_path: Path) -> None:
        assert load_svm_classifiers(tmp_path / "no_such_file.joblib") is None


class TestSvmScores:
    def test_returns_one_score_per_classifier(self) -> None:
        classifiers = {"class_a": _fitted_svc(5.0), "class_b": _fitted_svc(1.0)}
        scores = svm_scores(np.array([5.0]), classifiers)
        assert {s.class_name for s in scores} == {"class_a", "class_b"}
        assert all(isinstance(s.margin, float) for s in scores)


class TestSvmTopLabel:
    def test_returns_highest_scoring_class(self) -> None:
        assert (
            svm_top_label([
                SvmClassScore("class_a", _EXPECTED_SCORE_A),
                SvmClassScore("class_b", _EXPECTED_SCORE_B_NEGATIVE),
            ])
            == "class_a"
        )
        assert (
            svm_top_label([
                SvmClassScore("class_a", _EXPECTED_SCORE_A_NEGATIVE),
                SvmClassScore("class_b", _EXPECTED_SCORE_B),
            ])
            == "class_b"
        )
