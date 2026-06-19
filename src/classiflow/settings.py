import warnings

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEV_SECRET = "dev-secret-change-in-prod"  # noqa: S105


class _Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    DATABASE_URL: str = "sqlite+aiosqlite:///./classiflow.db"

    JWT_SECRET_KEY: str = _DEV_SECRET
    JWT_EXPIRE_MINUTES: int = 60

    @model_validator(mode="after")
    def _warn_default_secret(self) -> "_Settings":
        if self.JWT_SECRET_KEY == _DEV_SECRET:
            warnings.warn(
                "JWT_SECRET_KEY is set to the insecure development default. "
                "Set JWT_SECRET_KEY in your .env file before deploying.",
                stacklevel=2,
            )
        return self


settings = _Settings()
