from fastapi import Request
from fastapi.responses import JSONResponse

from classiflow.services.auth.exceptions import AuthError, NotAllowedError, OAuthError


def handle_auth_error(request: Request, exc: Exception) -> JSONResponse:  # noqa: ARG001
    assert isinstance(exc, AuthError)
    return JSONResponse(status_code=401, content={"detail": str(exc)})


def handle_not_allowed_error(request: Request, exc: Exception) -> JSONResponse:  # noqa: ARG001
    assert isinstance(exc, NotAllowedError)
    return JSONResponse(status_code=403, content={"detail": str(exc)})


def handle_oauth_error(request: Request, exc: Exception) -> JSONResponse:  # noqa: ARG001
    assert isinstance(exc, OAuthError)
    return JSONResponse(status_code=502, content={"detail": str(exc)})
