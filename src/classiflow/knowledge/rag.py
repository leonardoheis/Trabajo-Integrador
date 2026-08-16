import asyncio
from collections.abc import AsyncIterator

from classiflow.knowledge.domain.chat import ChatAnswer, ChatQuery, RetrievedChunk, SourceRef
from classiflow.knowledge.prompts.chat import SYSTEM_PROMPT, build_user_prompt
from classiflow.knowledge.repositories.chat_llm import IChatLlm
from classiflow.knowledge.repositories.embedder import IEmbedder
from classiflow.knowledge.repositories.vector_store import IVectorStore
from classiflow.settings import Settings


class RagService:
    """Retrieval-augmented chat over the indexed corpus."""

    def __init__(
        self,
        embedder: IEmbedder,
        vector_store: IVectorStore,
        chat_llm: IChatLlm,
        top_k: int = 0,
    ) -> None:
        self._embedder = embedder
        self._vector_store = vector_store
        self._chat_llm = chat_llm
        self._top_k = top_k or Settings.retrieval_top_k

    async def retrieve(self, query: ChatQuery) -> list[RetrievedChunk]:
        top_k = query.top_k or self._top_k
        # Both the query embedding and the Chroma lookup are blocking calls.
        return await asyncio.to_thread(self._retrieve_sync, query.question, top_k, query.filters)

    def _retrieve_sync(
        self, question: str, top_k: int, filters: dict[str, str]
    ) -> list[RetrievedChunk]:
        embedding = self._embedder.embed_query(question)
        return self._vector_store.query(embedding, top_k, filters or None)

    async def answer(self, query: ChatQuery) -> ChatAnswer:
        chunks = await self.retrieve(query)
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
        chunks = await self.retrieve(query)
        sources = [chunk.to_source() for chunk in chunks]
        user_prompt = build_user_prompt(query.question, chunks)
        async for token in self._chat_llm.astream(SYSTEM_PROMPT, user_prompt):
            yield token, sources
