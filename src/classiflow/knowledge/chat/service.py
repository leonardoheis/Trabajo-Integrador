import logging
from collections.abc import AsyncIterator

import weave

from classiflow.knowledge.domain.chat import ChatAnswer, ChatQuery, SourceRef
from classiflow.knowledge.llm.chat_llm import ChatLlm
from classiflow.knowledge.memory.domain import ConversationHistory
from classiflow.knowledge.prompts.chat import SYSTEM_PROMPT, build_user_prompt
from classiflow.knowledge.retrieval.retriever import RetrieverService

logger = logging.getLogger(__name__)


class ChatService:
    """Retrieval-augmented chat over the indexed corpus."""

    def __init__(self, retriever: RetrieverService, chat_llm: ChatLlm) -> None:
        self._retriever = retriever
        self._chat_llm = chat_llm

    @weave.op()
    async def answer(
        self, query: ChatQuery, history: ConversationHistory | None = None
    ) -> ChatAnswer:
        logger.info("chat.answer question=%r top_k=%s", query.question[:80], query.top_k)
        chunks = await self._retriever.retrieve(query)
        logger.debug("chat.answer retrieved %d chunks", len(chunks))
        user_prompt = build_user_prompt(query.question, chunks, history=history)
        parts = [token async for token in self._chat_llm.astream(SYSTEM_PROMPT, user_prompt)]
        answer = ChatAnswer(
            answer="".join(parts).strip(),
            sources=[chunk.to_source() for chunk in chunks],
        )
        logger.info("chat.answer done answer_len=%d", len(answer.answer))
        return answer

    @weave.op()
    async def astream(
        self, query: ChatQuery, history: ConversationHistory | None = None
    ) -> AsyncIterator[tuple[str, list[SourceRef]]]:
        # Yields (token, sources) pairs. Sources are resolved before generation starts
        # and repeated on every yield, so a consumer can render citations immediately
        # instead of waiting for the answer to finish.
        logger.info("chat.stream start question=%r top_k=%s", query.question[:80], query.top_k)
        chunks = await self._retriever.retrieve(query)
        logger.debug("chat.stream retrieved %d chunks", len(chunks))
        sources = [chunk.to_source() for chunk in chunks]
        user_prompt = build_user_prompt(query.question, chunks, history=history)
        token_count = 0
        async for token in self._chat_llm.astream(SYSTEM_PROMPT, user_prompt):
            token_count += 1
            yield token, sources
        logger.info("chat.stream done tokens=%d", token_count)
