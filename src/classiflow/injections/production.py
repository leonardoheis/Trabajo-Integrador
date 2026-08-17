import asyncio
from functools import cache

import easyocr
from dependency_injector import containers, providers

from classiflow.database.base import get_session
from classiflow.database.repositories.user import SqlUserRepository
from classiflow.events.broadcaster import EventBroadcaster
from classiflow.ingesta.config_extraction import get_extraction_config
from classiflow.ingesta.extract import TextExtractor
from classiflow.ingesta.extractors import MarkItDownExtractor, OCRExtractor
from classiflow.ingesta.llm_provider import get_llm_langchain
from classiflow.ingesta.nodes.node3_content_validation import get_language_detector
from classiflow.ingesta.nodes.node4_duplicate_control import (
    EmbeddingStore,
    get_sentence_model,
    make_embed_fn,
)
from classiflow.ingesta.prompts import build_content_chain, build_format_chain
from classiflow.services.auth.service import AuthService
from classiflow.settings import Settings


def _extraction_concurrency_limit() -> int:
    return get_extraction_config().max_concurrent_extractions


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
    extraction_semaphore = providers.Singleton(
        asyncio.Semaphore, providers.Callable(_extraction_concurrency_limit)
    )

    language_detector = providers.Callable(get_language_detector)

    # Singleton (not Factory): makes the FAISS index actually persist across requests
    # -- previously each request built its own empty EmbeddingStore(), so semantic
    # near-duplicate detection was silently a no-op in production (only exact SHA-256
    # dedup, which is DB-backed, ever worked). This wiring fixes that as a side effect
    # of giving DuplicateControlNode a real, shared embedding_store.
    sentence_model = providers.Singleton(get_sentence_model)
    embed_fn = providers.Callable(make_embed_fn, sentence_model)
    embedding_store = providers.Singleton(EmbeddingStore, embed_fn=embed_fn)

    # Callable (not Singleton): each resolution just calls get_llm_langchain(path)
    # fresh, which is *itself* still the same @lru_cache(maxsize=4)-decorated module
    # function it always was -- PipelineService._run()'s unload_slm() call still
    # correctly releases GPU VRAM after every job via .cache_clear() on that same
    # underlying function. A Singleton here would need its own manual per-job
    # teardown hook (dependency_injector has none) and would double VRAM usage when
    # NODE2_MODEL_PATH == NODE3_MODEL_PATH (the default), since two Singletons
    # wouldn't share the cache the way two Callables calling the same lru_cache'd
    # function do.
    node2_llm = providers.Callable(get_llm_langchain, Settings.node2_model_path)
    node3_llm = providers.Callable(get_llm_langchain, Settings.node3_model_path)
    # Built here, not passed as a raw LLM into the node constructors -- FormatValidationNode/
    # ContentValidationNode already have a format_chain/content_chain override seam for
    # exactly this (a fully-built chain), so production just fills that existing seam
    # instead of adding a redundant llm constructor param to either node.
    node2_format_chain = providers.Callable(build_format_chain, node2_llm)
    node3_content_chain = providers.Callable(build_content_chain, node3_llm)


@cache
def configure_container() -> Container:
    container = Container()
    container.wire(packages=["classiflow"])
    return container
