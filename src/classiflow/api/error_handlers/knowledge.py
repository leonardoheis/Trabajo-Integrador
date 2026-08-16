from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from classiflow.knowledge.exceptions import ChatRefusalError, KnowledgeError

_SERVICE_UNAVAILABLE = 503
_UNPROCESSABLE = 422


class KnowledgeErrorBody(BaseModel):
    error: str
    detail: str


def handle_chat_refusal(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ChatRefusalError)
    body = KnowledgeErrorBody(error="ChatRefusalError", detail=str(exc))
    # The provider answered successfully and declined the content, so this is a
    # problem with the request, not with the service.
    return JSONResponse(status_code=_UNPROCESSABLE, content=body.model_dump())


def handle_knowledge_error(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, KnowledgeError)
    body = KnowledgeErrorBody(error=type(exc).__name__, detail=str(exc))
    return JSONResponse(status_code=_SERVICE_UNAVAILABLE, content=body.model_dump())
