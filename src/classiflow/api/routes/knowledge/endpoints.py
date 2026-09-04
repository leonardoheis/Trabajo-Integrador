import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncGenerator
from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends
from fastapi.responses import StreamingResponse

from classiflow.api.dependencies import (
    CurrentUser,
    get_chat_service,
    get_classification_record_repo,
    get_conversation_repo,
    get_current_user,
    get_document_kb_repo,
    get_enriched_record_repo,
    get_memory_service,
    get_pipeline_service,
)
from classiflow.api.routes.knowledge.schemas import (
    ChatRequest,
    ChatResponse,
    ConversationResponse,
    ConversationTurnSchema,
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
from classiflow.classification.nodes.second_opinion import unload_bert
from classiflow.domain.repositories.classification_record import IClassificationRecordRepository
from classiflow.domain.repositories.conversation import IConversationRepository
from classiflow.domain.repositories.document_kb import IDocumentKbRepository
from classiflow.domain.repositories.enriched_record import IEnrichedRecordRepository
from classiflow.ingesta.llm_provider import unload_slm
from classiflow.knowledge.chat.service import ChatService
from classiflow.knowledge.domain.chat import ChatQuery, SourceRef
from classiflow.knowledge.llm.llama import get_chat_llm
from classiflow.knowledge.memory.service import MemoryService
from classiflow.services.pipeline.service import PipelineService, is_pipeline_busy
from classiflow.settings import Settings

logger = logging.getLogger(__name__)

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
    current_user: CurrentUser,
    chat_service: Annotated[ChatService, Depends(get_chat_service)],
    memory_service: Annotated[MemoryService, Depends(get_memory_service)],
) -> ChatResponse:
    history = await memory_service.load(current_user.email)
    answer = await chat_service.answer(_to_query(body), history=history)
    await memory_service.record_turn(current_user.email, body.question, answer.answer)
    return ChatResponse.from_domain(answer)


@router.post("/chat/stream")
async def chat_stream(
    body: ChatRequest,
    current_user: CurrentUser,
    background_tasks: BackgroundTasks,
    chat_service: Annotated[ChatService, Depends(get_chat_service)],
    memory_service: Annotated[MemoryService, Depends(get_memory_service)],
) -> StreamingResponse:
    history = await memory_service.load(current_user.email)
    logger.info("chat_stream user=%s question=%r", current_user.email, body.question[:80])

    async def _stream() -> AsyncGenerator[str, None]:
        sources: list[SourceRef] = []
        answer_parts: list[str] = []
        try:
            # aclosing, not a bare `async for`: Starlette does not aclose() a body
            # iterator on disconnect, leaking the generator's in-flight counter.
            async with contextlib.aclosing(
                chat_service.astream(_to_query(body), history=history)
            ) as tokens:
                async for token, current_sources in tokens:
                    sources = current_sources
                    answer_parts.append(token)
                    yield _sse("token", {"text": token})
        except Exception:
            logger.exception("chat_stream generation error user=%s", current_user.email)
            yield _sse("error", {"message": "Generation failed"})
            return
        # Sources are emitted once at the end rather than per token: they are identical
        # on every yield, and repeating them would dominate the stream.
        yield _sse("sources", _sources_payload(sources))
        yield _sse("done", {})
        answer = "".join(answer_parts).strip()
        logger.info(
            "chat_stream done user=%s tokens=%d sources=%d",
            current_user.email,
            len(answer_parts),
            len(sources),
        )
        # record_turn runs after the stream closes so it never stalls token delivery.
        # A slow memory write (or a summarization LLM call) would otherwise block the
        # generator and prevent the SSE response from closing cleanly.
        background_tasks.add_task(
            memory_service.record_turn, current_user.email, body.question, answer
        )

    return StreamingResponse(_stream(), media_type="text/event-stream")


@router.post("/chat/warmup", status_code=HTTPStatus.NO_CONTENT)
async def chat_warmup() -> None:
    if is_pipeline_busy():
        return
    await asyncio.to_thread(unload_slm)
    await asyncio.to_thread(unload_bert)
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


@router.get("/conversation")
async def get_conversation(
    current_user: CurrentUser,
    conversation_repo: Annotated[IConversationRepository, Depends(get_conversation_repo)],
) -> ConversationResponse:
    turns = await conversation_repo.all_turns(current_user.email)
    summary = await conversation_repo.get_summary(current_user.email)
    return ConversationResponse(
        summary=summary,
        turns=[ConversationTurnSchema.from_model(t) for t in turns],
    )


@router.delete("/conversation", status_code=HTTPStatus.NO_CONTENT)
async def clear_conversation(
    current_user: CurrentUser,
    memory_service: Annotated[MemoryService, Depends(get_memory_service)],
) -> None:
    await memory_service.clear(current_user.email)
