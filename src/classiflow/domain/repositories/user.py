from typing import Protocol

from classiflow.database.models import AllowedUser


class IUserRepository(Protocol):
    async def find_by_email(self, email: str) -> AllowedUser | None: ...
    async def is_allowed(self, email: str) -> bool: ...
