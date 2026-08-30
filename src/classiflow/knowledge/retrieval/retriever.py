import asyncio

from classiflow.knowledge.domain.chat import ChatQuery, RetrievedChunk
from classiflow.knowledge.embeddings.embedder import SentenceTransformerEmbedder
from classiflow.knowledge.vectordb.vector_store import VectorStore
from classiflow.settings import Settings


class RetrieverService:
    """Similarity search over the indexed corpus.

    Split from the chat service so retrieval can be exercised (and reused) without a
    chat provider attached -- evaluating recall does not need an LLM.
    """

    def __init__(
        self,
        embedder: SentenceTransformerEmbedder,
        vector_store: VectorStore,
        top_k: int = 0,
    ) -> None:
        self._embedder = embedder
        self._vector_store = vector_store
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
