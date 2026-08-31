from collections.abc import AsyncIterator

from classiflow.database.repositories.conversation import InMemoryConversationRepository
from classiflow.knowledge.memory.service import RAW_WINDOW_SIZE, MemoryService

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

    async def test_summarizes_the_aging_out_turn_once_the_window_overflows(self) -> None:
        repo = InMemoryConversationRepository()
        llm = _StubChatLlm(response="new summary")
        service = MemoryService(repo=repo, chat_llm=llm)
        for i in range(RAW_WINDOW_SIZE):
            await service.record_turn(_USER, f"q{i}", f"a{i}")
        await service.record_turn(_USER, "q-overflow", "a-overflow")

        assert len(llm.calls) == 1
        _system, user_prompt = llm.calls[0]
        assert "q0" in user_prompt  # the oldest turn is the one that ages out
        assert await repo.get_summary(_USER) == "new summary"

    async def test_a_summarization_failure_does_not_lose_the_saved_turn(self) -> None:
        repo = InMemoryConversationRepository()
        service = MemoryService(repo=repo, chat_llm=_FailingChatLlm())
        for i in range(RAW_WINDOW_SIZE):
            await service.record_turn(_USER, f"q{i}", f"a{i}")
        await service.record_turn(_USER, "q-overflow", "a-overflow")

        turns = await repo.all_turns(_USER)
        assert len(turns) == RAW_WINDOW_SIZE + 1
        assert await repo.get_summary(_USER) is None


class TestMemoryServiceClear:
    async def test_clears_turns_and_summary(self) -> None:
        repo = InMemoryConversationRepository()
        service = MemoryService(repo=repo, chat_llm=_StubChatLlm())
        await service.record_turn(_USER, "q1", "a1")
        await service.clear(_USER)
        assert await repo.all_turns(_USER) == []
