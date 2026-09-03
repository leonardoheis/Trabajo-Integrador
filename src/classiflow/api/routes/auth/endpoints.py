import asyncio
import secrets
from http import HTTPStatus
from typing import Annotated

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from fastapi.responses import RedirectResponse

from classiflow.api.dependencies import CurrentUser
from classiflow.api.schemas import BaseSchema
from classiflow.classification.nodes.second_opinion import unload_bert
from classiflow.domain.repositories.user import IUserRepository
from classiflow.domain.user import AuthToken
from classiflow.ingesta.llm_provider import unload_slm
from classiflow.ingesta.nodes.node4_duplicate_control import unload_duplicate_control_embedder
from classiflow.injections.production import Container
from classiflow.knowledge.embeddings.embedder import unload_kb_embedder
from classiflow.knowledge.llm.llama import reset_active_generations, unload_chat_llm
from classiflow.services.auth.oauth import exchange_code, get_authorization_url
from classiflow.services.pipeline.service import is_pipeline_busy

router = APIRouter(prefix="/auth", tags=["auth"])

_STATE_COOKIE = "oauth_state"


class CurrentUserSchema(BaseSchema):
    email: str
    is_admin: bool
    picture: str | None = None


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


@router.get("/me")
async def auth_me(current_user: CurrentUser) -> CurrentUserSchema:
    return CurrentUserSchema(
        email=current_user.email,
        is_admin=current_user.is_admin,
        picture=current_user.picture,
    )


@router.post("/logout", status_code=HTTPStatus.NO_CONTENT)
async def auth_logout(_current_user: CurrentUser) -> None:
    # The JWT itself is stateless and cleared client-side; this only releases VRAM.
    # The chat GGUF is never used by the pipeline, so it always goes. The other four
    # (SLM, BETO, duplicate-control and KB embedders) belong to the pipeline graph --
    # unloading them out from under an in-flight job would fail it.
    # Signing out means no chat can be in flight; clears a counter leaked by any
    # abandoned SSE stream, which would otherwise block every unload.
    reset_active_generations()
    await asyncio.to_thread(unload_chat_llm)
    if is_pipeline_busy():
        return
    for unload in (
        unload_slm,
        unload_bert,
        unload_duplicate_control_embedder,
        unload_kb_embedder,
    ):
        await asyncio.to_thread(unload)
