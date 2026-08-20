from functools import cache

import easyocr
from dependency_injector import containers, providers

from classiflow.database.base import get_session
from classiflow.database.repositories.user import SqlUserRepository
from classiflow.events.broadcaster import EventBroadcaster
from classiflow.ingesta.extract import TextExtractor
from classiflow.ingesta.extractors import MarkItDownExtractor, OCRExtractor
from classiflow.knowledge.chat.service import ChatService
from classiflow.knowledge.chunking.chunker import ChunkerService
from classiflow.knowledge.embeddings.embedder import SentenceTransformerEmbedder
from classiflow.knowledge.indexing.csv_metadata import CsvDocumentMetadataRepository
from classiflow.knowledge.llm.claude import ClaudeChatLlm
from classiflow.knowledge.llm.llama import LlamaCppChatLlm
from classiflow.knowledge.retrieval.retriever import RetrieverService
from classiflow.knowledge.vectordb.chroma_store import ChromaVectorStore
from classiflow.services.auth.service import AuthService
from classiflow.settings import Settings


class Container(containers.DeclarativeContainer):
    # Session-scoped repos/services (job_repo, document_steps_repo, human_decision_repo,
    # hash_repo, audit_repo, pipeline_service, coordinator, node1-4) are NOT declared
    # here -- this Resource is never torn down (no Closing[]/shutdown_resources() call
    # anywhere), so anything built from it shares one uncommitted, never-refreshed
    # session for the process's whole lifetime. Those pieces are built per-request from
    # a native FastAPI Depends(get_session) instead -- see api/dependencies.py's
    # get_job_repo/get_document_steps_repo/get_human_decision_repo/get_pipeline_service.
    # user_repo/auth_service stay here since they're read-only (no data-loss bug).
    db_session = providers.Resource(get_session)

    user_repo = providers.Factory(SqlUserRepository, session=db_session)
    auth_service = providers.Factory(AuthService, user_repo=user_repo)
    broadcaster = providers.Singleton(EventBroadcaster)

    # ThreadSafeSingleton (not Singleton): construction races are real — multiple
    # coordinator jobs' background tasks can hit OCR around the same time — and
    # reconstruction is expensive, so the shared reader needs a lock around its
    # first build. Replaces OCRExtractor's former hand-rolled double-checked lock.
    ocr_reader = providers.ThreadSafeSingleton(easyocr.Reader, [Settings.ocr_lang], gpu=True)
    markitdown_extractor = providers.Factory(MarkItDownExtractor)
    ocr_extractor = providers.Factory(OCRExtractor, reader=ocr_reader)
    extraction_chain = providers.List(markitdown_extractor, ocr_extractor)
    text_extractor = providers.Factory(TextExtractor, chain=extraction_chain)

    # Knowledge base (stage 5). All Singletons: the embedder holds a loaded
    # SentenceTransformer, the Chroma client owns an on-disk handle, and the CSV
    # repository caches parsed rows -- rebuilding any of them per request would be
    # wasteful. ThreadSafeSingleton for the embedder specifically, since concurrent
    # pipeline jobs can race on its first construction (same reasoning as ocr_reader).
    embedder = providers.ThreadSafeSingleton(SentenceTransformerEmbedder)
    vector_store = providers.Singleton(ChromaVectorStore)
    document_metadata_repo = providers.Singleton(CsvDocumentMetadataRepository)
    chunker = providers.Factory(ChunkerService)

    claude_chat_llm = providers.Singleton(ClaudeChatLlm)
    llama_chat_llm = providers.Singleton(LlamaCppChatLlm)
    chat_llm = providers.Selector(
        providers.Callable(lambda: Settings.chat_llm_provider),
        claude=claude_chat_llm,
        llama=llama_chat_llm,
    )

    retriever = providers.Factory(
        RetrieverService,
        embedder=embedder,
        vector_store=vector_store,
    )
    chat_service = providers.Factory(
        ChatService,
        retriever=retriever,
        chat_llm=chat_llm,
    )


@cache
def configure_container() -> Container:
    container = Container()
    container.wire(packages=["classiflow"])
    return container
