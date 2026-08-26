from datetime import datetime

from classiflow.api.schemas import BaseSchema
from classiflow.database.models import AllowedUser


class UserSchema(BaseSchema):
    email: str
    is_active: bool
    is_admin: bool
    is_blocked: bool
    created_at: datetime

    @classmethod
    def from_model(cls, user: AllowedUser) -> "UserSchema":
        return cls(
            email=user.email,
            is_active=user.is_active,
            is_admin=user.is_admin,
            is_blocked=user.is_blocked,
            created_at=user.created_at,
        )


class CreateUserRequest(BaseSchema):
    email: str
    is_admin: bool = False


class UpdateUserRequest(BaseSchema):
    is_active: bool | None = None
    is_admin: bool | None = None
    is_blocked: bool | None = None
