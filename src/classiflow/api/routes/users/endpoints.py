from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from classiflow.api.dependencies import get_current_user, get_user_repo, require_admin
from classiflow.api.routes.users.schemas import CreateUserRequest, UpdateUserRequest, UserSchema
from classiflow.database.models import AllowedUser
from classiflow.domain.repositories import UNSET
from classiflow.domain.repositories.user import IUserRepository

router = APIRouter(
    prefix="/users",
    tags=["users"],
    dependencies=[Depends(get_current_user), Depends(require_admin)],
)


@router.get("")
async def list_users(
    user_repo: Annotated[IUserRepository, Depends(get_user_repo)],
) -> list[UserSchema]:
    users = await user_repo.list_all()
    return [UserSchema.from_model(u) for u in users]


@router.post("", status_code=HTTPStatus.CREATED)
async def create_user(
    body: CreateUserRequest,
    user_repo: Annotated[IUserRepository, Depends(get_user_repo)],
) -> UserSchema:
    user = AllowedUser(email=body.email, is_active=True, is_admin=body.is_admin, is_blocked=False)
    await user_repo.create(user)
    return UserSchema.from_model(user)


@router.patch("/{email}")
async def update_user(
    email: str,
    body: UpdateUserRequest,
    user_repo: Annotated[IUserRepository, Depends(get_user_repo)],
) -> UserSchema:
    if await user_repo.find_by_email(email) is None:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=f"No user {email}")

    await user_repo.update(
        email,
        is_active=body.is_active if body.is_active is not None else UNSET,
        is_admin=body.is_admin if body.is_admin is not None else UNSET,
        is_blocked=body.is_blocked if body.is_blocked is not None else UNSET,
    )
    updated = await user_repo.find_by_email(email)
    if updated is None:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=f"No user {email}")
    return UserSchema.from_model(updated)


@router.delete("/{email}", status_code=HTTPStatus.NO_CONTENT)
async def delete_user(
    email: str,
    user_repo: Annotated[IUserRepository, Depends(get_user_repo)],
) -> None:
    await user_repo.delete(email)
