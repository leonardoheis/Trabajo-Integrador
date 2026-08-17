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


@cache
def configure_container() -> Container:
    container = Container()
    container.wire(packages=["classiflow"])
    return container
