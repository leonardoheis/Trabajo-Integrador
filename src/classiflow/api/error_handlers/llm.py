from http import HTTPStatus

from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from classiflow.ingesta.exceptions import LlmProviderError, ModelLoadError, ModelNotFoundError


class LlmErrorBody(BaseModel):
    error: str
    detail: str


def handle_model_not_found(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ModelNotFoundError)
    body = LlmErrorBody(error="ModelNotFoundError", detail=str(exc))
    return JSONResponse(status_code=HTTPStatus.SERVICE_UNAVAILABLE, content=body.model_dump())


def handle_model_load_error(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ModelLoadError)
    body = LlmErrorBody(error="ModelLoadError", detail=str(exc))
    return JSONResponse(status_code=HTTPStatus.SERVICE_UNAVAILABLE, content=body.model_dump())


def handle_llm_provider_error(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, LlmProviderError)
    body = LlmErrorBody(error=type(exc).__name__, detail=str(exc))
    return JSONResponse(status_code=HTTPStatus.SERVICE_UNAVAILABLE, content=body.model_dump())
