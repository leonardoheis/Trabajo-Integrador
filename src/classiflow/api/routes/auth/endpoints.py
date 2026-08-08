import secrets
from typing import Annotated

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from fastapi.responses import RedirectResponse

from classiflow.domain.repositories.user import IUserRepository
from classiflow.domain.user import AuthToken
from classiflow.injections.production import Container
from classiflow.services.auth.oauth import exchange_code, get_authorization_url

router = APIRouter(prefix="/auth", tags=["auth"])

_STATE_COOKIE = "oauth_state"


@router.get("/login")
async def auth_login() -> RedirectResponse:
    state = secrets.token_urlsafe(32)
    resp = RedirectResponse(url=get_authorization_url(state), status_code=302)
    resp.set_cookie(_STATE_COOKIE, state, httponly=True, samesite="lax", max_age=600)
    return resp


@router.get("/callback")
@inject
async def auth_callback(
    code: str,
    state: str,
    response: Response,
    user_repo: Annotated[IUserRepository, Depends(Provide[Container.user_repo])],
    oauth_state: Annotated[str | None, Cookie()] = None,
) -> AuthToken:
    if oauth_state is None or oauth_state != state:
        raise HTTPException(status_code=400, detail="Invalid or missing CSRF state")
    response.delete_cookie(_STATE_COOKIE)
    return await exchange_code(code, user_repo)
