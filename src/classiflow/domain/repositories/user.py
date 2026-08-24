from typing import Protocol

from classiflow.database.models import AllowedUser
from classiflow.domain.repositories.job import UNSET, UnsetType


class IUserRepository(Protocol):
    async def find_by_email(self, email: str) -> AllowedUser | None: ...
    async def is_allowed(self, email: str) -> bool: ...
    async def list_all(self) -> list[AllowedUser]: ...
    async def create(self, user: AllowedUser) -> None: ...

    async def update(
        self,
        email: str,
        *,
        is_active: bool | UnsetType = UNSET,
        is_admin: bool | UnsetType = UNSET,
        is_blocked: bool | UnsetType = UNSET,
    ) -> None: ...

    async def delete(self, email: str) -> None: ...
