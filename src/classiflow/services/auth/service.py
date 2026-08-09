from classiflow.domain.repositories.user import IUserRepository
from classiflow.domain.user import User
from classiflow.services.auth.exceptions import NotAllowedError
from classiflow.services.auth.jwt import decode_token


class AuthService:
    def __init__(self, user_repo: IUserRepository) -> None:
        self._user_repo = user_repo

    async def verify_token(self, token: str) -> User:
        payload = decode_token(token)
        if not await self._user_repo.is_allowed(payload.sub):
            raise NotAllowedError(email=payload.sub)
        return User(email=payload.sub)
