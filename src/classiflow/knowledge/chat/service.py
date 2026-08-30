from collections.abc import AsyncIterator

from classiflow.knowledge.domain.chat import ChatAnswer, ChatQuery, SourceRef
from classiflow.knowledge.llm.chat_llm import ChatLlm
from classiflow.knowledge.prompts.chat import SYSTEM_PROMPT, build_user_prompt
from classiflow.knowledge.retrieval.retriever import RetrieverService


class ChatService:
    """Retrieval-augmented chat over the indexed corpus."""

    def __init__(self, retriever: RetrieverService, chat_llm: ChatLlm) -> None:
        self._retriever = retriever
        self._chat_llm = chat_llm

    async def answer(self, query: ChatQuery) -> ChatAnswer:
        chunks = await self._retriever.retrieve(query)
        user_prompt = build_user_prompt(query.question, chunks)
        parts = [token async for token in self._chat_llm.astream(SYSTEM_PROMPT, user_prompt)]
        return ChatAnswer(
            answer="".join(parts).strip(),
            sources=[chunk.to_source() for chunk in chunks],
        )

    # Yields (token, sources) pairs. Sources are resolved before generation starts
    # and repeated on every yield, so a consumer can render citations immediately
    # instead of waiting for the answer to finish.
    async def astream(self, query: ChatQuery) -> AsyncIterator[tuple[str, list[SourceRef]]]:
        chunks = await self._retriever.retrieve(query)
        sources = [chunk.to_source() for chunk in chunks]
        user_prompt = build_user_prompt(query.question, chunks)
        async for token in self._chat_llm.astream(SYSTEM_PROMPT, user_prompt):
            yield token, sources
