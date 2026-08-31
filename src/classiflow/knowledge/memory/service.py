import logging

from classiflow.database.models import ConversationTurn
from classiflow.domain.repositories.conversation import IConversationRepository
from classiflow.knowledge.llm.chat_llm import ChatLlm
from classiflow.knowledge.memory.domain import ConversationHistory
from classiflow.knowledge.prompts.memory import SUMMARY_SYSTEM_PROMPT, build_summary_prompt

RAW_WINDOW_SIZE = 6

logger = logging.getLogger(__name__)


class MemoryService:
    def __init__(self, repo: IConversationRepository, chat_llm: ChatLlm) -> None:
        self._repo = repo
        self._chat_llm = chat_llm

    async def load(self, user_email: str) -> ConversationHistory:
        summary = await self._repo.get_summary(user_email)
        recent = await self._repo.recent_turns(user_email, RAW_WINDOW_SIZE)
        return ConversationHistory(summary=summary, recent_turns=recent)

    async def record_turn(self, user_email: str, question: str, answer: str) -> None:
        await self._repo.save_turn(user_email, question, answer)
        count = await self._repo.turn_count(user_email)
        if count <= RAW_WINDOW_SIZE:
            return
        turns = await self._repo.all_turns(user_email)
        aging_out = turns[-(RAW_WINDOW_SIZE + 1)]
        try:
            new_summary = await self._summarize(user_email, aging_out)
        except Exception:
            # The raw turn is already saved -- a failed fold-in only delays the
            # summary update; it will retry the next time a turn ages out.
            logger.exception("Failed to fold conversation turn into summary")
            return
        await self._repo.save_summary(user_email, new_summary)

    async def _summarize(self, user_email: str, turn: ConversationTurn) -> str:
        old_summary = await self._repo.get_summary(user_email) or ""
        prompt = build_summary_prompt(old_summary, turn.question, turn.answer)
        parts = [tok async for tok in self._chat_llm.astream(SUMMARY_SYSTEM_PROMPT, prompt)]
        return "".join(parts).strip()

    async def clear(self, user_email: str) -> None:
        await self._repo.clear(user_email)
