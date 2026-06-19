from pydantic_settings import BaseSettings, SettingsConfigDict


class _Settings(BaseSettings):
    API_PORT: int = 8000
    HOST: str = "0.0.0.0"  # nosec  # noqa: S104

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    DATABASE_URL: str
    JWT_SECRET_KEY: str
    JWT_EXPIRE_MINUTES: int


Settings = _Settings()
