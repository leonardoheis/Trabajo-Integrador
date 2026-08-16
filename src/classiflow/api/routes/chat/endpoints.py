import json
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from classiflow.api.dependencies import get_current_user, get_rag_service
from classiflow.api.routes.chat.schemas import ChatRequest, ChatResponse, SourceSchema
from classiflow.knowledge.domain.chat import ChatQuery, SourceRef
from classiflow.knowledge.rag import RagService

router = APIRouter(prefix="/chat", tags=["chat"], dependencies=[Depends(get_current_user)])


def _to_query(body: ChatRequest) -> ChatQuery:
    return ChatQuery(question=body.question, filters=body.filters, top_k=body.top_k)


def _sse(event: str, payload: object) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _sources_payload(sources: list[SourceRef]) -> list[dict[str, object]]:
    return [SourceSchema.from_domain(s).model_dump(by_alias=True) for s in sources]


@router.post("")
async def chat(
    body: ChatRequest,
    rag: Annotated[RagService, Depends(get_rag_service)],
) -> ChatResponse:
    answer = await rag.answer(_to_query(body))
    return ChatResponse.from_domain(answer)


@router.post("/stream")
async def chat_stream(
    body: ChatRequest,
    rag: Annotated[RagService, Depends(get_rag_service)],
) -> StreamingResponse:
    async def _stream() -> AsyncGenerator[str, None]:
        sources: list[SourceRef] = []
        async for token, current_sources in rag.astream(_to_query(body)):
            sources = current_sources
            yield _sse("token", {"text": token})
        # Sources are emitted once at the end rather than per token: they are identical
        # on every yield, and repeating them would dominate the stream.
        yield _sse("sources", _sources_payload(sources))
        yield _sse("done", {})

    return StreamingResponse(_stream(), media_type="text/event-stream")
