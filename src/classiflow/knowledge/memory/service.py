import contextlib
import logging

from classiflow.database.models import ConversationTurn
from classiflow.domain.repositories.conversation import IConversationRepository
from classiflow.knowledge.llm.chat_llm import ChatLlm
from classiflow.knowledge.memory.domain import ConversationHistory
from classiflow.knowledge.prompts.memory import SUMMARY_SYSTEM_PROMPT, build_summary_prompt
from classiflow.settings import Settings

logger = logging.getLogger(__name__)


class MemoryService:
    def __init__(
        self,
        repo: IConversationRepository,
        chat_llm: ChatLlm,
        raw_window_size: int = 0,
        summary_batch_size: int = 0,
    ) -> None:
        self._repo = repo
        self._chat_llm = chat_llm
        self._raw_window_size = raw_window_size or Settings.RAW_WINDOW_SIZE
        self._summary_batch_size = summary_batch_size or Settings.SUMMARY_BATCH_SIZE

    async def load(self, user_email: str) -> ConversationHistory:
        summary = await self._repo.get_summary(user_email)
        recent = await self._repo.recent_turns(user_email, self._raw_window_size)
        return ConversationHistory(summary=summary, recent_turns=recent)

    async def record_turn(self, user_email: str, question: str, answer: str) -> None:
        await self._repo.save_turn(user_email, question, answer)
        count = await self._repo.turn_count(user_email)
        aged_out = count - self._raw_window_size
        if aged_out <= 0 or aged_out % self._summary_batch_size != 0:
            return
        turns = await self._repo.all_turns(user_email)
        batch = turns[aged_out - self._summary_batch_size : aged_out]
        try:
            new_summary = await self._summarize(user_email, batch)
        except Exception:
            # The raw turns are already saved -- a failed fold-in only delays the summary
            # update, and the next batch will carry these turns in with it.
            logger.exception("Failed to fold conversation turns into summary")
            return
        await self._repo.save_summary(user_email, new_summary)

    async def _summarize(self, user_email: str, turns: list[ConversationTurn]) -> str:
        old_summary = await self._repo.get_summary(user_email) or ""
        exchange = "\n\n".join(f"P: {turn.question}\nR: {turn.answer}" for turn in turns)
        prompt = build_summary_prompt(old_summary, exchange)
        async with contextlib.aclosing(
            self._chat_llm.astream(SUMMARY_SYSTEM_PROMPT, prompt)
        ) as tokens:
            parts = [token async for token in tokens]
        return "".join(parts).strip()

    async def clear(self, user_email: str) -> None:
        await self._repo.clear(user_email)
