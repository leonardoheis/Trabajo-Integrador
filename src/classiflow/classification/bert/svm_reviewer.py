"""Ported from bert_tunning's src/svm_reviewer.py -- inference-time subset only
(load_svm_classifiers, svm_scores, svm_top_label). Training functions
(fit_svm_classifiers, save_svm_classifiers, evaluate_svm_classifiers,
fit_and_evaluate_svm_reviewer) are not ported -- see this task's description."""

from pathlib import Path
from typing import Protocol, runtime_checkable

import joblib
import numpy as np
import numpy.typing as npt

# sklearn.svm.SVC has no type stubs (ignore_missing_imports=true) -- a Protocol capturing
# only the method actually called here keeps Any from leaking into this module's checked
# signatures, same pattern already used for easyocr.Reader in ingesta/extractors/ocr.py.
_Point = npt.NDArray[np.float64]


@runtime_checkable
class _FittedClassifier(Protocol):
    def decision_function(self, x: _Point) -> npt.NDArray[np.float64]: ...


def load_svm_classifiers(path: Path) -> dict[str, _FittedClassifier] | None:
    if not path.exists():
        return None
    classifiers: dict[str, _FittedClassifier] = joblib.load(path)
    return classifiers


def svm_scores(
    embedding: npt.NDArray[np.float64], classifiers: dict[str, _FittedClassifier]
) -> dict[str, float]:
    # Each class's one-vs-rest decision-function margin for this embedding -- positive
    # means inside that class's SVM boundary, negative means outside. Not a probability,
    # not calibrated -- raw evidence for the caller to weigh itself.
    point = embedding.reshape(1, -1)
    return {name: float(svc.decision_function(point)[0]) for name, svc in classifiers.items()}


def svm_top_label(scores: dict[str, float]) -> str:
    return max(scores, key=lambda name: scores[name])
