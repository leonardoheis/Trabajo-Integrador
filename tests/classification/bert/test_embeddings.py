from unittest.mock import MagicMock

import torch

from classiflow.classification.bert.embeddings import (
    LoadedModel,
    extract_embeddings,
    extract_embeddings_and_predictions,
)

_EXPECTED_ROWS = 2
_EXPECTED_DIM = 4


def _mock_loaded_model() -> LoadedModel:
    tokenizer = MagicMock()
    tokenizer.return_value.to.return_value = {
        "input_ids": torch.zeros(2, 8, dtype=torch.long),
        "attention_mask": torch.ones(2, 8, dtype=torch.long),
    }
    model = MagicMock()
    model.return_value.hidden_states = [torch.zeros(2, 8, 4)]
    model.return_value.logits = torch.tensor([[2.0, 0.5], [0.1, 3.0]])
    model.base_model.return_value.last_hidden_state = torch.zeros(2, 8, 4)
    return LoadedModel(model=model, tokenizer=tokenizer, device="cpu")


class TestExtractEmbeddings:
    def test_returns_one_embedding_per_input_text(self) -> None:
        loaded = _mock_loaded_model()
        result = extract_embeddings(loaded, ["doc one", "doc two"], max_length=8, batch_size=16)
        assert result.vectors.shape == (_EXPECTED_ROWS, _EXPECTED_DIM)


class TestExtractEmbeddingsAndPredictions:
    def test_returns_one_embedding_and_prediction_per_input_text(self) -> None:
        loaded = _mock_loaded_model()
        result = extract_embeddings_and_predictions(
            loaded, ["doc one", "doc two"], max_length=8, batch_size=16
        )
        assert result.embeddings.shape == (_EXPECTED_ROWS, _EXPECTED_DIM)
        assert result.predicted_label_ids == [0, 1]
