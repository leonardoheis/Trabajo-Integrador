"""Ported verbatim from bert_tunning's src/embeddings.py -- self-contained, no
bert_tunning-specific schema dependencies. Not currently called by any Classiflow node
(SecondOpinionNode does its own single-document tokenize+forward pass, matching
bert_tunning's own inference/classify.py -- these batched helpers exist for parity with
the source and for future bulk-calibration tooling, not a live call path today."""

from collections.abc import Iterator
from typing import NamedTuple

import numpy as np
import numpy.typing as npt
import torch
from transformers import BatchEncoding, PreTrainedTokenizerBase

_DEFAULT_BATCH_SIZE = 16


class LoadedModel(NamedTuple):
    model: torch.nn.Module
    tokenizer: PreTrainedTokenizerBase
    device: str


class DocumentEmbeddings(NamedTuple):
    """vectors: shape (num_texts, embedding_dim) -- one row per input text, same order."""

    vectors: npt.NDArray[np.float64]


class EmbeddingsWithPredictions(NamedTuple):
    """embeddings: shape (num_texts, embedding_dim). predicted_label_ids: one BETO
    class index per text, same order and length as embeddings."""

    embeddings: npt.NDArray[np.float64]
    predicted_label_ids: list[int]


def _batched_inputs(
    loaded: LoadedModel, texts: list[str], *, max_length: int, batch_size: int
) -> Iterator[BatchEncoding]:
    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        yield loaded.tokenizer(
            batch,
            truncation=True,
            padding="max_length",
            max_length=max_length,
            return_tensors="pt",
        ).to(loaded.device)


def _cls_embedding(hidden_state: torch.Tensor) -> npt.NDArray[np.float64]:
    return hidden_state[:, 0, :].cpu().numpy().astype(np.float64)


def extract_embeddings(
    loaded: LoadedModel,
    texts: list[str],
    *,
    max_length: int,
    batch_size: int = _DEFAULT_BATCH_SIZE,
) -> DocumentEmbeddings:
    loaded.model.eval()
    batches: list[npt.NDArray[np.float64]] = []
    with torch.no_grad():
        for inputs in _batched_inputs(loaded, texts, max_length=max_length, batch_size=batch_size):
            hidden = loaded.model.base_model(**inputs).last_hidden_state  # type: ignore[operator]
            batches.append(_cls_embedding(hidden))
    return DocumentEmbeddings(vectors=np.vstack(batches))


def extract_embeddings_and_predictions(
    loaded: LoadedModel,
    texts: list[str],
    *,
    max_length: int,
    batch_size: int = _DEFAULT_BATCH_SIZE,
) -> EmbeddingsWithPredictions:
    loaded.model.eval()
    embedding_batches: list[npt.NDArray[np.float64]] = []
    predicted_ids: list[int] = []
    with torch.no_grad():
        for inputs in _batched_inputs(loaded, texts, max_length=max_length, batch_size=batch_size):
            outputs = loaded.model(**inputs, output_hidden_states=True)
            embedding_batches.append(_cls_embedding(outputs.hidden_states[-1]))
            predicted_ids.extend(outputs.logits.argmax(dim=-1).cpu().tolist())
    return EmbeddingsWithPredictions(
        embeddings=np.vstack(embedding_batches), predicted_label_ids=predicted_ids
    )
