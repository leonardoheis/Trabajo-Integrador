from classiflow.knowledge.chat.service import ChatService
from classiflow.knowledge.domain.chat import ChatQuery
from classiflow.knowledge.indexing.indexer import IndexerService
from classiflow.knowledge.retrieval.retriever import RetrieverService
from classiflow.knowledge.vectordb.in_memory_store import InMemoryVectorStore
from tests.knowledge.fakes import TEXT, FakeChatLlm, FakeEmbedder


def _retriever(store: InMemoryVectorStore, top_k: int) -> RetrieverService:
    return RetrieverService(FakeEmbedder(), store, top_k=top_k)  # type: ignore[arg-type]


def _chat(store: InMemoryVectorStore, llm: FakeChatLlm, top_k: int) -> ChatService:
    return ChatService(retriever=_retriever(store, top_k), chat_llm=llm)


class TestRetrieverService:
    async def test_metadata_filters_narrow_retrieval(
        self, indexer: IndexerService, store: InMemoryVectorStore
    ) -> None:
        await indexer.index("job-1", "ordenanza_10902_2026.pdf", "sha-1", TEXT)
        retriever = _retriever(store, top_k=5)

        matching = await retriever.retrieve(
            ChatQuery(question="presupuesto", filters={"doc_type": "Ordenanza"})
        )
        other = await retriever.retrieve(
            ChatQuery(question="presupuesto", filters={"doc_type": "Decreto"})
        )

        assert matching
        assert other == []

    async def test_retrieval_is_capped_at_top_k(
        self, indexer: IndexerService, store: InMemoryVectorStore
    ) -> None:
        await indexer.index("job-1", "ordenanza_10902_2026.pdf", "sha-1", TEXT)

        hits = await _retriever(store, top_k=1).retrieve(ChatQuery(question="presupuesto"))

        assert len(hits) == 1

    async def test_query_top_k_overrides_the_service_default(
        self, indexer: IndexerService, store: InMemoryVectorStore
    ) -> None:
        await indexer.index("job-1", "ordenanza_10902_2026.pdf", "sha-1", TEXT)
        retriever = _retriever(store, top_k=5)

        hits = await retriever.retrieve(ChatQuery(question="presupuesto", top_k=1))

        assert len(hits) == 1


class TestChatService:
    async def test_answer_returns_text_and_sources(
        self, indexer: IndexerService, store: InMemoryVectorStore
    ) -> None:
        await indexer.index("job-1", "ordenanza_10902_2026.pdf", "sha-1", TEXT)

        answer = await _chat(store, FakeChatLlm(), top_k=2).answer(
            ChatQuery(question="¿Cuál es el presupuesto?")
        )

        assert answer.answer == "Según la Ordenanza 10902/2026, sí."
        assert answer.sources
        assert answer.sources[0].download_url == "https://example.test/ordenanza"
        assert answer.sources[0].doc_type == "Ordenanza"

    async def test_answer_is_capped_at_top_k(
        self, indexer: IndexerService, store: InMemoryVectorStore
    ) -> None:
        await indexer.index("job-1", "ordenanza_10902_2026.pdf", "sha-1", TEXT)

        answer = await _chat(store, FakeChatLlm(), top_k=1).answer(
            ChatQuery(question="¿Cuál es el presupuesto?")
        )

        assert len(answer.sources) == 1

    async def test_prompt_carries_the_retrieved_passages(
        self, indexer: IndexerService, store: InMemoryVectorStore
    ) -> None:
        await indexer.index("job-1", "ordenanza_10902_2026.pdf", "sha-1", TEXT)
        llm = FakeChatLlm()

        await _chat(store, llm, top_k=2).answer(ChatQuery(question="¿Cuál es el presupuesto?"))

        assert "Ordenanza 10902/2026" in llm.last_user
        assert "Pregunta: ¿Cuál es el presupuesto?" in llm.last_user
        assert "español" in llm.last_system

    async def test_empty_knowledge_base_still_answers_without_sources(
        self, store: InMemoryVectorStore
    ) -> None:
        llm = FakeChatLlm(tokens=["No hay datos."])

        answer = await _chat(store, llm, top_k=3).answer(ChatQuery(question="¿Algo?"))

        assert answer.sources == []
        assert "No se encontraron pasajes relevantes" in llm.last_user

    async def test_astream_repeats_sources_on_every_token(
        self, indexer: IndexerService, store: InMemoryVectorStore
    ) -> None:
        await indexer.index("job-1", "ordenanza_10902_2026.pdf", "sha-1", TEXT)

        chunks = [
            (token, sources)
            async for token, sources in _chat(store, FakeChatLlm(), top_k=2).astream(
                ChatQuery(question="¿Cuál es el presupuesto?")
            )
        ]

        assert "".join(token for token, _ in chunks) == "Según la Ordenanza 10902/2026, sí."
        assert all(sources for _, sources in chunks)


class TestSplitPreservesComposition:
    """The retriever/chat split must not change what a caller observes.

    Guards the one behavioural seam in the capability reorganization: ChatService's
    sources have to stay exactly the retriever's hits, converted.
    """

    async def test_chat_sources_are_the_retrievers_hits(
        self, indexer: IndexerService, store: InMemoryVectorStore
    ) -> None:
        await indexer.index("job-1", "ordenanza_10902_2026.pdf", "sha-1", TEXT)
        query = ChatQuery(question="¿Cuál es el presupuesto?")

        hits = await _retriever(store, top_k=2).retrieve(query)
        answer = await _chat(store, FakeChatLlm(), top_k=2).answer(query)

        assert answer.sources == [hit.to_source() for hit in hits]

    async def test_answer_and_astream_agree(
        self, indexer: IndexerService, store: InMemoryVectorStore
    ) -> None:
        await indexer.index("job-1", "ordenanza_10902_2026.pdf", "sha-1", TEXT)
        query = ChatQuery(question="¿Cuál es el presupuesto?")

        answer = await _chat(store, FakeChatLlm(), top_k=2).answer(query)
        streamed = [
            (token, sources)
            async for token, sources in _chat(store, FakeChatLlm(), top_k=2).astream(query)
        ]

        assert "".join(token for token, _ in streamed) == answer.answer
        assert streamed[-1][1] == answer.sources
