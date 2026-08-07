from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from classiflow.shared.database.models import AllowedUser


class SqlUserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_by_email(self, email: str) -> AllowedUser | None:
        result = await self._session.execute(select(AllowedUser).where(AllowedUser.email == email))
        return result.scalar_one_or_none()

    async def is_allowed(self, email: str) -> bool:
        user = await self.find_by_email(email)
        return user is not None and user.is_active and not user.is_blocked


class InMemoryUserRepository:
    def __init__(self) -> None:
        self._users: dict[str, AllowedUser] = {}

    def seed(self, user: AllowedUser) -> None:
        self._users[user.email] = user

    async def find_by_email(self, email: str) -> AllowedUser | None:
        return self._users.get(email)

    async def is_allowed(self, email: str) -> bool:
        user = self._users.get(email)
        return user is not None and user.is_active and not user.is_blocked
