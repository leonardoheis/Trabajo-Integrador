import asyncio
import json
from collections.abc import AsyncGenerator
from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from classiflow.api.dependencies import (
    get_chat_service,
    get_classification_record_repo,
    get_current_user,
    get_document_kb_repo,
    get_enriched_record_repo,
    get_pipeline_service,
)
from classiflow.api.routes.knowledge.schemas import (
    ChatRequest,
    ChatResponse,
    DocumentKbResponse,
    DocumentKbSchema,
    SourceSchema,
    SynchronizeKbResponse,
)
from classiflow.classification.domain.review_route import ReviewRoute
from classiflow.classification.exceptions import (
    ClassificationNotAcceptedError,
    ClassificationRecordNotFoundError,
)
from classiflow.domain.repositories.classification_record import IClassificationRecordRepository
from classiflow.domain.repositories.document_kb import IDocumentKbRepository
from classiflow.domain.repositories.enriched_record import IEnrichedRecordRepository
from classiflow.knowledge.chat.service import ChatService
from classiflow.knowledge.domain.chat import ChatQuery, SourceRef
from classiflow.knowledge.llm.llama import get_chat_llm
from classiflow.services.pipeline.service import PipelineService, is_pipeline_busy
from classiflow.settings import Settings

router = APIRouter(
    prefix="/knowledge", tags=["knowledge"], dependencies=[Depends(get_current_user)]
)


def _to_query(body: ChatRequest) -> ChatQuery:
    return ChatQuery(question=body.question, filters=body.filters, top_k=body.top_k)


def _sse(event: str, payload: object) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _sources_payload(sources: list[SourceRef]) -> list[dict[str, object]]:
    return [SourceSchema.from_domain(s).model_dump(by_alias=True) for s in sources]


@router.post("/chat")
async def chat(
    body: ChatRequest,
    chat_service: Annotated[ChatService, Depends(get_chat_service)],
) -> ChatResponse:
    answer = await chat_service.answer(_to_query(body))
    return ChatResponse.from_domain(answer)


@router.post("/chat/stream")
async def chat_stream(
    body: ChatRequest,
    chat_service: Annotated[ChatService, Depends(get_chat_service)],
) -> StreamingResponse:
    async def _stream() -> AsyncGenerator[str, None]:
        sources: list[SourceRef] = []
        async for token, current_sources in chat_service.astream(_to_query(body)):
            sources = current_sources
            yield _sse("token", {"text": token})
        # Sources are emitted once at the end rather than per token: they are identical
        # on every yield, and repeating them would dominate the stream.
        yield _sse("sources", _sources_payload(sources))
        yield _sse("done", {})

    return StreamingResponse(_stream(), media_type="text/event-stream")


@router.post("/chat/warmup", status_code=HTTPStatus.NO_CONTENT)
async def chat_warmup() -> None:
    if is_pipeline_busy():
        return
    await asyncio.to_thread(get_chat_llm, Settings.chat_model_path, Settings.chat_model_n_ctx)


@router.post("/synchronize-kb", status_code=HTTPStatus.OK)
async def synchronize_kb(
    pipeline: Annotated[PipelineService, Depends(get_pipeline_service)],
) -> SynchronizeKbResponse:
    indexed_job_ids, skipped_count = await pipeline.synchronize_kb()
    return SynchronizeKbResponse(indexed_job_ids=indexed_job_ids, skipped_count=skipped_count)


@router.get("/documents/{job_id}")
async def document_kb(
    job_id: str,
    document_kb_repo: Annotated[IDocumentKbRepository, Depends(get_document_kb_repo)],
) -> DocumentKbResponse:
    doc = await document_kb_repo.find_by_job_id(job_id)
    return DocumentKbResponse(document_kb=DocumentKbSchema.from_model(doc) if doc else None)


@router.post("/documents/{job_id}/index")
async def index_document(
    job_id: str,
    classification_repo: Annotated[
        IClassificationRecordRepository, Depends(get_classification_record_repo)
    ],
    enriched_record_repo: Annotated[IEnrichedRecordRepository, Depends(get_enriched_record_repo)],
    document_kb_repo: Annotated[IDocumentKbRepository, Depends(get_document_kb_repo)],
    pipeline: Annotated[PipelineService, Depends(get_pipeline_service)],
) -> DocumentKbResponse:
    classification = await classification_repo.find_by_job_id(job_id)
    if classification is None:
        raise ClassificationRecordNotFoundError(job_id)
    if classification.review_route != ReviewRoute.ACCEPT:
        raise ClassificationNotAcceptedError(job_id, classification.review_route)

    record = await enriched_record_repo.find_by_job_id(job_id)
    if record is None:
        # Defensive only -- ClassificationRecord.enriched_id FK means this can't be
        # missing if the classification lookup above succeeded.
        raise ClassificationRecordNotFoundError(job_id)

    await pipeline.index_enriched_record(record, record.filename or "", record.sha256 or job_id)
    doc = await document_kb_repo.find_by_job_id(job_id)
    return DocumentKbResponse(document_kb=DocumentKbSchema.from_model(doc) if doc else None)
