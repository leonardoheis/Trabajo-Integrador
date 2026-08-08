from typing import Annotated

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse

from classiflow.domain.repositories.user import IUserRepository
from classiflow.domain.user import AuthToken
from classiflow.injections.production import Container
from classiflow.services.auth.oauth import exchange_code, get_authorization_url

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/login")
async def auth_login() -> RedirectResponse:
    return RedirectResponse(url=get_authorization_url(), status_code=302)


@router.get("/callback")
@inject
async def auth_callback(
    code: str,
    user_repo: Annotated[IUserRepository, Depends(Provide[Container.user_repo])],
) -> AuthToken:
    return await exchange_code(code, user_repo)
