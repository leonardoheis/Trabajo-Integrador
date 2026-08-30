from http import HTTPStatus

from fastapi import Request
from fastapi.responses import JSONResponse

from classiflow.services.auth.exceptions import AuthError, NotAllowedError, OAuthError


def handle_auth_error(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AuthError)
    return JSONResponse(status_code=HTTPStatus.UNAUTHORIZED, content={"detail": str(exc)})


def handle_not_allowed_error(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, NotAllowedError)
    return JSONResponse(status_code=HTTPStatus.FORBIDDEN, content={"detail": str(exc)})


def handle_oauth_error(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, OAuthError)
    return JSONResponse(status_code=HTTPStatus.BAD_GATEWAY, content={"detail": str(exc)})
