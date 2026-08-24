from pathlib import Path
from unittest.mock import MagicMock, patch

import joblib
import numpy as np
import pytest
import torch
from sklearn.svm import SVC

from classiflow.classification.bert.classifier import BertClassifier
from classiflow.classification.config_classification import ClassificationConfig
from classiflow.classification.exceptions import ClassificationArtifactError

_EXPECTED_TOKENIZER_MAX_LENGTH = 512
_EXPECTED_HIDDEN_SIZE = 4
_EXPECTED_MAX_POSITION_EMBEDDINGS = 512


def _mock_tokenizer() -> MagicMock:
    tokenizer = MagicMock()
    tokenizer.model_max_length = _EXPECTED_TOKENIZER_MAX_LENGTH
    tokenizer.return_value.to.return_value = {
        "input_ids": torch.zeros(1, 8, dtype=torch.long),
        "attention_mask": torch.ones(1, 8, dtype=torch.long),
    }
    return tokenizer


def _mock_model() -> MagicMock:
    model = MagicMock()
    model.config.id2label = {0: "decreto", 1: "ordenanza"}
    model.config.model_type = "bert"
    model.config.hidden_size = _EXPECTED_HIDDEN_SIZE
    model.config.max_position_embeddings = _EXPECTED_MAX_POSITION_EMBEDDINGS
    model.return_value.logits = torch.tensor([[0.5, 2.0]])
    model.return_value.hidden_states = [torch.zeros(1, 8, 4)]
    return model


class TestBertClassifierPredict:
    def test_predict_returns_top_label_and_confidence(self, tmp_path: Path) -> None:
        with patch("torch.cuda.is_available", return_value=False):
            classifier = BertClassifier(
                str(tmp_path),
                ClassificationConfig(),
                tokenizer=_mock_tokenizer(),
                model=_mock_model(),
            )
        result = classifier.predict("Ordenanza de prueba")
        assert result.label == "ordenanza"
        assert result.all_scores.keys() == {"decreto", "ordenanza"}
        assert result.svm_scores == {}
        assert result.svm_agrees_with_prediction is True
        assert result.ood_metrics is None  # no ood_stats.npz present in tmp_path

    def test_disables_ood_and_svm_when_artifacts_absent(self, tmp_path: Path) -> None:
        with patch("torch.cuda.is_available", return_value=False):
            classifier = BertClassifier(
                str(tmp_path),
                ClassificationConfig(),
                tokenizer=_mock_tokenizer(),
                model=_mock_model(),
            )
        assert classifier.ood_scorer is None
        assert classifier.svm_classifiers is None


class TestBertClassifierSvmClassMappingValidation:
    def test_raises_when_svm_classes_do_not_match_model(self, tmp_path: Path) -> None:
        svc = SVC(kernel="linear")
        svc.fit(np.array([[0.0], [1.0]]), np.array([0, 1]))
        joblib.dump({"wrong_class": svc}, tmp_path / "svm_classifiers.joblib")

        with (
            patch("torch.cuda.is_available", return_value=False),
            pytest.raises(ClassificationArtifactError, match="do not match"),
        ):
            BertClassifier(
                str(tmp_path),
                ClassificationConfig(),
                tokenizer=_mock_tokenizer(),
                model=_mock_model(),
            )
