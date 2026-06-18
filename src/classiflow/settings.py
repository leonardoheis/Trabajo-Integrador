from pydantic_settings import BaseSettings, SettingsConfigDict


class _Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    DATABASE_URL: str = "sqlite+aiosqlite:///./classiflow.db"

    JWT_SECRET_KEY: str = "dev-secret-change-in-prod"  # noqa: S105
    JWT_EXPIRE_MINUTES: int = 60


settings = _Settings()
