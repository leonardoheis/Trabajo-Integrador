from http import HTTPStatus

from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from classiflow.knowledge.exceptions import KnowledgeError


class KnowledgeErrorBody(BaseModel):
    error: str
    detail: str


def handle_knowledge_error(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, KnowledgeError)
    body = KnowledgeErrorBody(error=type(exc).__name__, detail=str(exc))
    return JSONResponse(status_code=HTTPStatus.SERVICE_UNAVAILABLE, content=body.model_dump())
