"""Ported from bert_tunning's src/svm_reviewer.py -- inference-time subset only
(load_svm_classifiers, svm_scores, svm_top_label). Training functions
(fit_svm_classifiers, save_svm_classifiers, evaluate_svm_classifiers,
fit_and_evaluate_svm_reviewer) are not ported -- see this task's description."""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

import joblib
import numpy as np
import numpy.typing as npt

# sklearn.svm.SVC has no type stubs (ignore_missing_imports=true) -- a Protocol capturing
# only the method actually called here keeps Any from leaking into this module's checked
# signatures, same pattern already used for easyocr.Reader in ingesta/extractors/ocr.py.
# FittedClassifier (not _-prefixed): classifier.py also needs it for BertClassifier's
# svm_classifiers attribute type, so this is a real shared type now.
_Point = npt.NDArray[np.float64]

# Every `dict[str, FittedClassifier]`/`class_name: str` in this module is keyed by
# BETO's own raw label vocabulary (self.model.config.id2label's values -- e.g.
# "decreto", "ordenanza", "otro"), NOT Classiflow's normalized DocumentCategory
# (plural snake_case, e.g. "decretos"). label_mapping.py's job is translating one into
# the other; nothing in this module ever sees a normalized label.


@runtime_checkable
class FittedClassifier(Protocol):
    def decision_function(self, x: _Point) -> npt.NDArray[np.float64]: ...


def load_svm_classifiers(path: Path) -> dict[str, FittedClassifier] | None:
    if not path.exists():
        return None
    classifiers: dict[str, FittedClassifier] = joblib.load(path)
    return classifiers


@dataclass(frozen=True)
class SvmClassScore:
    """One class's one-vs-rest SVM result for a single document embedding."""

    class_name: str  # BETO's raw label, e.g. "decreto" -- see module docstring above
    # Decision-function margin: positive means the embedding falls inside this class's
    # SVM boundary, negative means outside. Not a probability, not calibrated across
    # classes -- raw evidence for the caller (svm_top_label, or the Smells/Risk node's
    # low_svm_margin check) to weigh itself, not a ready-made confidence score.
    margin: float


def svm_scores(
    embedding: npt.NDArray[np.float64], classifiers: dict[str, FittedClassifier]
) -> list[SvmClassScore]:
    """Score one document's embedding against every class's one-vs-rest SVM.

    Returns:
        One SvmClassScore per class in `classifiers`, in no particular order.
    """
    point = embedding.reshape(1, -1)
    return [
        SvmClassScore(class_name=name, margin=float(svc.decision_function(point)[0]))
        for name, svc in classifiers.items()
    ]


def svm_top_label(scores: list[SvmClassScore]) -> str:
    return max(scores, key=lambda s: s.margin).class_name
