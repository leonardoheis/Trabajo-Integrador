from collections.abc import AsyncIterator

import pytest

from classiflow.knowledge.chunker import ChunkerService
from classiflow.knowledge.domain.chat import ChatQuery
from classiflow.knowledge.domain.document import DocumentMetadata
from classiflow.knowledge.indexer import IndexerService
from classiflow.knowledge.infrastructure.chroma_store import InMemoryVectorStore
from classiflow.knowledge.rag import RagService
from classiflow.knowledge.repositories.embedder import Embedding

_TEXT = (
    "Artículo 1º — Apruébase el presupuesto municipal para el ejercicio fiscal."
    "\n\n"
    "Artículo 2º — La partida asignada asciende a un total en el Anexo I."
    "\n\n"
    "Artículo 3º — Comuníquese al Departamento Ejecutivo."
)


class _Embedder:
    """Keyword-indicator vectors: deterministic and dependency-free."""

    def embed_documents(self, texts: list[str]) -> list[Embedding]:
        return [self.embed_query(text) for text in texts]

    def embed_query(self, text: str) -> Embedding:
        lowered = text.lower()
        return [
            1.0 if "presupuesto" in lowered else 0.0,
            1.0 if "comuníquese" in lowered else 0.0,
        ]


class _MetadataRepo:
    def resolve(self, filename: str) -> DocumentMetadata:
        return DocumentMetadata(
            filename=filename,
            doc_type="Ordenanza",
            number="10902",
            year="2026",
            subject="Presupuesto municipal",
            download_url="https://example.test/ordenanza",
        )


class _ChatLlm:
    def __init__(self, tokens: list[str] | None = None) -> None:
        self.tokens = tokens or ["Según ", "la Ordenanza 10902/2026, ", "sí."]
        self.last_system = ""
        self.last_user = ""

    async def astream(self, system: str, user: str) -> AsyncIterator[str]:
        self.last_system = system
        self.last_user = user
        for token in self.tokens:
            yield token


@pytest.fixture
def store() -> InMemoryVectorStore:
    return InMemoryVectorStore()


@pytest.fixture
def indexer(store: InMemoryVectorStore) -> IndexerService:
    return IndexerService(
        chunker=ChunkerService(chunk_size=200, chunk_overlap=40),
        embedder=_Embedder(),
        vector_store=store,
        metadata_repo=_MetadataRepo(),
    )


class TestIndexerService:
    async def test_indexes_chunks_with_metadata(
        self, indexer: IndexerService, store: InMemoryVectorStore
    ) -> None:
        result = await indexer.index("job-1", "ordenanza_10902_2026.pdf", "sha-1", _TEXT)

        assert result.chunk_count > 0
        assert store.count() == result.chunk_count
        assert result.metadata.download_url == "https://example.test/ordenanza"

    async def test_reindexing_the_same_document_is_idempotent(
        self, indexer: IndexerService, store: InMemoryVectorStore
    ) -> None:
        first = await indexer.index("job-1", "ordenanza_10902_2026.pdf", "sha-1", _TEXT)
        await indexer.index("job-2", "ordenanza_10902_2026.pdf", "sha-1", _TEXT)

        # Chunk ids are derived from the sha256, so the second pass overwrites.
        assert store.count() == first.chunk_count

    async def test_empty_text_indexes_nothing_but_still_resolves_metadata(
        self, indexer: IndexerService, store: InMemoryVectorStore
    ) -> None:
        result = await indexer.index("job-1", "ordenanza_10902_2026.pdf", "sha-1", "   ")

        assert result.chunk_count == 0
        assert store.count() == 0
        assert result.metadata.doc_type == "Ordenanza"


class TestRagService:
    async def test_answer_returns_text_and_sources(
        self, indexer: IndexerService, store: InMemoryVectorStore
    ) -> None:
        await indexer.index("job-1", "ordenanza_10902_2026.pdf", "sha-1", _TEXT)
        rag = RagService(_Embedder(), store, _ChatLlm(), top_k=2)

        answer = await rag.answer(ChatQuery(question="¿Cuál es el presupuesto?"))

        assert answer.answer == "Según la Ordenanza 10902/2026, sí."
        assert answer.sources
        assert answer.sources[0].download_url == "https://example.test/ordenanza"
        assert answer.sources[0].doc_type == "Ordenanza"

    async def test_retrieval_is_capped_at_top_k(
        self, indexer: IndexerService, store: InMemoryVectorStore
    ) -> None:
        await indexer.index("job-1", "ordenanza_10902_2026.pdf", "sha-1", _TEXT)
        rag = RagService(_Embedder(), store, _ChatLlm(), top_k=1)

        answer = await rag.answer(ChatQuery(question="¿Cuál es el presupuesto?"))

        assert len(answer.sources) == 1

    async def test_prompt_carries_the_retrieved_passages(
        self, indexer: IndexerService, store: InMemoryVectorStore
    ) -> None:
        await indexer.index("job-1", "ordenanza_10902_2026.pdf", "sha-1", _TEXT)
        llm = _ChatLlm()
        rag = RagService(_Embedder(), store, llm, top_k=2)

        await rag.answer(ChatQuery(question="¿Cuál es el presupuesto?"))

        assert "Ordenanza 10902/2026" in llm.last_user
        assert "Pregunta: ¿Cuál es el presupuesto?" in llm.last_user
        assert "español" in llm.last_system

    async def test_empty_knowledge_base_still_answers_without_sources(
        self, store: InMemoryVectorStore
    ) -> None:
        llm = _ChatLlm(tokens=["No hay datos."])
        rag = RagService(_Embedder(), store, llm, top_k=3)

        answer = await rag.answer(ChatQuery(question="¿Algo?"))

        assert answer.sources == []
        assert "No se encontraron pasajes relevantes" in llm.last_user

    async def test_metadata_filters_narrow_retrieval(
        self, indexer: IndexerService, store: InMemoryVectorStore
    ) -> None:
        await indexer.index("job-1", "ordenanza_10902_2026.pdf", "sha-1", _TEXT)
        rag = RagService(_Embedder(), store, _ChatLlm(), top_k=5)

        matching = await rag.retrieve(
            ChatQuery(question="presupuesto", filters={"doc_type": "Ordenanza"})
        )
        other = await rag.retrieve(
            ChatQuery(question="presupuesto", filters={"doc_type": "Decreto"})
        )

        assert matching
        assert other == []

    async def test_astream_repeats_sources_on_every_token(
        self, indexer: IndexerService, store: InMemoryVectorStore
    ) -> None:
        await indexer.index("job-1", "ordenanza_10902_2026.pdf", "sha-1", _TEXT)
        rag = RagService(_Embedder(), store, _ChatLlm(), top_k=2)

        chunks = [
            (token, sources)
            async for token, sources in rag.astream(ChatQuery(question="¿Cuál es el presupuesto?"))
        ]

        assert "".join(token for token, _ in chunks) == "Según la Ordenanza 10902/2026, sí."
        assert all(sources for _, sources in chunks)
