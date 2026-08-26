import json
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from classiflow.api.dependencies import get_chat_service, get_current_user, get_pipeline_service
from classiflow.api.routes.knowledge.schemas import (
    ChatRequest,
    ChatResponse,
    SourceSchema,
    SynchronizeKbResponse,
)
from classiflow.knowledge.chat.service import ChatService
from classiflow.knowledge.domain.chat import ChatQuery, SourceRef
from classiflow.services.pipeline.service import PipelineService

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


@router.post("/synchronize-kb", status_code=200)
async def synchronize_kb(
    pipeline: Annotated[PipelineService, Depends(get_pipeline_service)],
) -> SynchronizeKbResponse:
    indexed_job_ids, skipped_count = await pipeline.synchronize_kb()
    return SynchronizeKbResponse(indexed_job_ids=indexed_job_ids, skipped_count=skipped_count)
