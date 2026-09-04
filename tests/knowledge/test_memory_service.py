from collections.abc import AsyncIterator

from classiflow.database.repositories.conversation import InMemoryConversationRepository
from classiflow.knowledge.memory.service import MemoryService
from classiflow.settings import Settings

RAW_WINDOW_SIZE = Settings.RAW_WINDOW_SIZE
SUMMARY_BATCH_SIZE = Settings.SUMMARY_BATCH_SIZE
_EXPECTED_FOLDS_AFTER_TWO_BATCHES = 2

_USER = "memory-user@classiflow.dev"


class _StubChatLlm:
    def __init__(self, response: str = "stubbed summary") -> None:
        self._response = response
        self.calls: list[tuple[str, str]] = []

    async def astream(self, system: str, user: str) -> AsyncIterator[str]:
        self.calls.append((system, user))
        yield self._response


_MODEL_UNAVAILABLE = "model unavailable"


class _FailingChatLlm:
    async def astream(self, _system: str, _user: str) -> AsyncIterator[str]:
        raise RuntimeError(_MODEL_UNAVAILABLE)
        yield ""  # pragma: no cover - unreachable, satisfies async generator shape


class TestMemoryServiceLoad:
    async def test_returns_empty_history_for_a_new_user(self) -> None:
        service = MemoryService(repo=InMemoryConversationRepository(), chat_llm=_StubChatLlm())
        history = await service.load(_USER)
        assert history.summary is None
        assert history.recent_turns == []

    async def test_returns_summary_and_recent_turns(self) -> None:
        repo = InMemoryConversationRepository()
        await repo.save_turn(_USER, "q1", "a1")
        await repo.save_summary(_USER, "prior summary")
        service = MemoryService(repo=repo, chat_llm=_StubChatLlm())
        history = await service.load(_USER)
        assert history.summary == "prior summary"
        assert len(history.recent_turns) == 1

    async def test_caps_recent_turns_at_the_raw_window_size(self) -> None:
        repo = InMemoryConversationRepository()
        for i in range(RAW_WINDOW_SIZE + 3):
            await repo.save_turn(_USER, f"q{i}", f"a{i}")
        service = MemoryService(repo=repo, chat_llm=_StubChatLlm())
        history = await service.load(_USER)
        assert len(history.recent_turns) == RAW_WINDOW_SIZE


class TestMemoryServiceRecordTurn:
    async def test_saves_the_turn(self) -> None:
        repo = InMemoryConversationRepository()
        service = MemoryService(repo=repo, chat_llm=_StubChatLlm())
        await service.record_turn(_USER, "q1", "a1")
        turns = await repo.all_turns(_USER)
        assert len(turns) == 1
        assert turns[0].question == "q1"

    async def test_does_not_summarize_while_under_the_window(self) -> None:
        repo = InMemoryConversationRepository()
        llm = _StubChatLlm()
        service = MemoryService(repo=repo, chat_llm=llm)
        for i in range(RAW_WINDOW_SIZE):
            await service.record_turn(_USER, f"q{i}", f"a{i}")
        assert llm.calls == []
        assert await repo.get_summary(_USER) is None

    async def test_does_not_summarize_until_a_full_batch_has_aged_out(self) -> None:
        # Folding on every aged-out turn costs a full 8B generation per question.
        repo = InMemoryConversationRepository()
        llm = _StubChatLlm()
        service = MemoryService(repo=repo, chat_llm=llm)

        for i in range(RAW_WINDOW_SIZE + SUMMARY_BATCH_SIZE - 1):
            await service.record_turn(_USER, f"q{i}", f"a{i}")

        assert llm.calls == []

    async def test_summarizes_the_whole_batch_in_one_call(self) -> None:
        repo = InMemoryConversationRepository()
        llm = _StubChatLlm(response="new summary")
        service = MemoryService(repo=repo, chat_llm=llm)

        for i in range(RAW_WINDOW_SIZE + SUMMARY_BATCH_SIZE):
            await service.record_turn(_USER, f"q{i}", f"a{i}")

        assert len(llm.calls) == 1
        _system, user_prompt = llm.calls[0]
        # Every turn in the batch reaches the prompt, oldest first.
        for i in range(SUMMARY_BATCH_SIZE):
            assert f"q{i}" in user_prompt
        assert await repo.get_summary(_USER) == "new summary"

    async def test_folds_a_second_batch_without_repeating_the_first(self) -> None:
        repo = InMemoryConversationRepository()
        llm = _StubChatLlm()
        service = MemoryService(repo=repo, chat_llm=llm)

        for i in range(RAW_WINDOW_SIZE + 2 * SUMMARY_BATCH_SIZE):
            await service.record_turn(_USER, f"q{i}", f"a{i}")

        assert len(llm.calls) == _EXPECTED_FOLDS_AFTER_TWO_BATCHES
        _system, second_prompt = llm.calls[1]
        assert f"q{SUMMARY_BATCH_SIZE}" in second_prompt
        assert "q0" not in second_prompt  # already folded in by the first batch

    async def test_a_summarization_failure_does_not_lose_the_saved_turns(self) -> None:
        repo = InMemoryConversationRepository()
        service = MemoryService(repo=repo, chat_llm=_FailingChatLlm())
        total = RAW_WINDOW_SIZE + SUMMARY_BATCH_SIZE

        for i in range(total):
            await service.record_turn(_USER, f"q{i}", f"a{i}")

        turns = await repo.all_turns(_USER)
        assert len(turns) == total
        assert await repo.get_summary(_USER) is None


class TestMemoryServiceClear:
    async def test_clears_turns_and_summary(self) -> None:
        repo = InMemoryConversationRepository()
        service = MemoryService(repo=repo, chat_llm=_StubChatLlm())
        await service.record_turn(_USER, "q1", "a1")
        await service.clear(_USER)
        assert await repo.all_turns(_USER) == []
