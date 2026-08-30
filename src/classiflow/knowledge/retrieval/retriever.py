import asyncio
import re

from classiflow.knowledge.domain.chat import ChatQuery, RetrievedChunk
from classiflow.knowledge.embeddings.embedder import SentenceTransformerEmbedder
from classiflow.knowledge.vectordb.vector_store import VectorStore
from classiflow.settings import Settings

# Dense vector search is weak at exact identifier lookup: a bare filename embeds
# poorly against its own content. When the question names a file explicitly (e.g.
# "resumen de boletin_2056_2026.pdf"), filtering on the stored "filename" metadata
# (Chunk.to_store_metadata()) finds it directly instead of hoping cosine similarity
# happens to favor it. Deliberately filename-only, not doc_type/number matching --
# doc_type is LLM-extracted and inconsistent in real data (seen: "Ordenanza, decreto,
# resolucion", mojibake like "Resoluci�n"), so an exact-match filter on it would fail
# silently for a real fraction of documents rather than degrade gracefully.
_FILENAME_PATTERN = re.compile(r"[\w][\w\-]*\.pdf", re.IGNORECASE)


def detect_filename(question: str) -> str | None:
    match = _FILENAME_PATTERN.search(question)
    return match.group(0) if match else None


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
        filters = dict(query.filters)
        filename = detect_filename(query.question)
        if filename and "filename" not in filters:
            filters["filename"] = filename
        # Both the query embedding and the Chroma lookup are blocking calls.
        return await asyncio.to_thread(self._retrieve_sync, query.question, top_k, filters)

    def _retrieve_sync(
        self, question: str, top_k: int, filters: dict[str, str]
    ) -> list[RetrievedChunk]:
        embedding = self._embedder.embed_query(question)
        return self._vector_store.query(embedding, top_k, filters or None)
