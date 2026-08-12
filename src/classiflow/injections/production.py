from functools import cache

import easyocr
from dependency_injector import containers, providers

from classiflow.database.base import get_session
from classiflow.database.repositories.audit import SqlAuditRepository
from classiflow.database.repositories.document_steps import SqlDocumentStepsRepository
from classiflow.database.repositories.hash import SqlHashRepository
from classiflow.database.repositories.human_decision import SqlHumanDecisionRepository
from classiflow.database.repositories.job import SqlJobRepository
from classiflow.database.repositories.user import SqlUserRepository
from classiflow.events.broadcaster import EventBroadcaster
from classiflow.ingesta.coordinator import build_coordinator
from classiflow.ingesta.extract import TextExtractor
from classiflow.ingesta.extractors import MarkItDownExtractor, OCRExtractor
from classiflow.ingesta.nodes.node1_file_reception import FileReceptionNode
from classiflow.ingesta.nodes.node2_format_validation import FormatValidationNode
from classiflow.ingesta.nodes.node3_content_validation import ContentValidationNode
from classiflow.ingesta.nodes.node4_duplicate_control import DuplicateControlNode
from classiflow.services.audit.service import AuditService
from classiflow.services.auth.service import AuthService
from classiflow.services.pipeline.service import PipelineService
from classiflow.settings import Settings


class Container(containers.DeclarativeContainer):
    db_session = providers.Resource(get_session)

    hash_repo = providers.Factory(SqlHashRepository, session=db_session)
    audit_repo = providers.Factory(SqlAuditRepository, session=db_session)
    user_repo = providers.Factory(SqlUserRepository, session=db_session)
    document_steps_repo = providers.Factory(SqlDocumentStepsRepository, session=db_session)
    human_decision_repo = providers.Factory(SqlHumanDecisionRepository, session=db_session)
    job_repo = providers.Factory(SqlJobRepository, session=db_session)

    audit_service = providers.Factory(AuditService, repo=audit_repo)
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

    node1 = providers.Factory(FileReceptionNode, audit=audit_service, broadcaster=broadcaster)
    node2 = providers.Factory(FormatValidationNode, audit=audit_service, broadcaster=broadcaster)
    node3 = providers.Factory(ContentValidationNode, audit=audit_service, broadcaster=broadcaster)
    node4 = providers.Factory(
        DuplicateControlNode, audit=audit_service, broadcaster=broadcaster, hash_repo=hash_repo
    )
    coordinator = providers.Factory(
        build_coordinator,
        node1=node1,
        node2=node2,
        node3=node3,
        node4=node4,
        text_extractor=text_extractor,
    )
    pipeline_service = providers.Factory(
        PipelineService,
        job_repo=job_repo,
        document_steps_repo=document_steps_repo,
        broadcaster=broadcaster,
        coordinator=coordinator,
    )


@cache
def configure_container() -> Container:
    container = Container()
    container.wire(packages=["classiflow"])
    return container
