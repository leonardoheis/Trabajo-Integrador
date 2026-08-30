from unittest.mock import MagicMock

import pytest

from classiflow.knowledge.embeddings.embedder import get_sentence_model, unload_kb_embedder


class TestUnloadKbEmbedder:
    def test_forces_a_reload_on_the_next_call(self, monkeypatch: pytest.MonkeyPatch) -> None:
        EXPECTED_CALL_COUNT_AFTER_FIRST_CALL = 1
        EXPECTED_CALL_COUNT_AFTER_RELOAD = 2
        mock_transformer = MagicMock(side_effect=lambda *_args, **_kwargs: object())
        monkeypatch.setattr(
            "classiflow.knowledge.embeddings.embedder.SentenceTransformer",
            mock_transformer,
        )
        get_sentence_model.cache_clear()
        try:
            get_sentence_model("fake-model")
            assert mock_transformer.call_count == EXPECTED_CALL_COUNT_AFTER_FIRST_CALL

            unload_kb_embedder()
            get_sentence_model("fake-model")

            assert mock_transformer.call_count == EXPECTED_CALL_COUNT_AFTER_RELOAD
        finally:
            get_sentence_model.cache_clear()
