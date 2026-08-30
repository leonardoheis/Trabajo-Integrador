from unittest.mock import MagicMock

import pytest

from classiflow.knowledge.llm.llama import get_chat_llm, unload_chat_llm


class TestUnloadChatLlm:
    def test_forces_a_reload_on_the_next_call(self, monkeypatch: pytest.MonkeyPatch) -> None:
        EXPECTED_CALL_COUNT_AFTER_FIRST_CALL = 1
        EXPECTED_CALL_COUNT_AFTER_RELOAD = 2
        mock_llama = MagicMock(side_effect=lambda **_kwargs: object())
        monkeypatch.setattr("classiflow.knowledge.llm.llama.Llama", mock_llama)
        get_chat_llm.cache_clear()
        try:
            get_chat_llm("fake/model.gguf", 8192)
            assert mock_llama.call_count == EXPECTED_CALL_COUNT_AFTER_FIRST_CALL

            unload_chat_llm()
            get_chat_llm("fake/model.gguf", 8192)

            assert mock_llama.call_count == EXPECTED_CALL_COUNT_AFTER_RELOAD
        finally:
            get_chat_llm.cache_clear()
