from typing import Annotated

from dependency_injector.wiring import Provide, inject
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from classiflow.domain.user import User
from classiflow.injections.production import Container
from classiflow.services.auth.service import AuthService

_bearer = HTTPBearer()


@inject
async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer)],
    auth_service: Annotated[AuthService, Depends(Provide[Container.auth_service])],
) -> User:
    return await auth_service.verify_token(credentials.credentials)


CurrentUser = Annotated[User, Depends(get_current_user)]
