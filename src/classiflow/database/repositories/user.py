from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from classiflow.database.models import AllowedUser
from classiflow.domain.repositories.job import UNSET, UnsetType


class SqlUserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_by_email(self, email: str) -> AllowedUser | None:
        result = await self._session.execute(select(AllowedUser).where(AllowedUser.email == email))
        return result.scalar_one_or_none()

    async def is_allowed(self, email: str) -> bool:
        user = await self.find_by_email(email)
        return user is not None and user.is_active and not user.is_blocked

    async def list_all(self) -> list[AllowedUser]:
        result = await self._session.execute(select(AllowedUser).order_by(AllowedUser.email))
        return list(result.scalars().all())

    async def create(self, user: AllowedUser) -> None:
        self._session.add(user)
        await self._session.flush()

    async def update(
        self,
        email: str,
        *,
        is_active: bool | UnsetType = UNSET,
        is_admin: bool | UnsetType = UNSET,
        is_blocked: bool | UnsetType = UNSET,
    ) -> None:
        user = await self.find_by_email(email)
        if user is not None:
            if not isinstance(is_active, UnsetType):
                user.is_active = is_active
            if not isinstance(is_admin, UnsetType):
                user.is_admin = is_admin
            if not isinstance(is_blocked, UnsetType):
                user.is_blocked = is_blocked
            await self._session.flush()

    async def delete(self, email: str) -> None:
        user = await self.find_by_email(email)
        if user is not None:
            await self._session.delete(user)
            await self._session.flush()


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

    async def list_all(self) -> list[AllowedUser]:
        return list(self._users.values())

    async def create(self, user: AllowedUser) -> None:
        self._users[user.email] = user

    async def update(
        self,
        email: str,
        *,
        is_active: bool | UnsetType = UNSET,
        is_admin: bool | UnsetType = UNSET,
        is_blocked: bool | UnsetType = UNSET,
    ) -> None:
        user = self._users.get(email)
        if user is not None:
            if not isinstance(is_active, UnsetType):
                user.is_active = is_active
            if not isinstance(is_admin, UnsetType):
                user.is_admin = is_admin
            if not isinstance(is_blocked, UnsetType):
                user.is_blocked = is_blocked

    async def delete(self, email: str) -> None:
        self._users.pop(email, None)
