import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class _Settings(BaseSettings):
    API_PORT: int = 8000
    HOST: str = "0.0.0.0"  # nosec  # noqa: S104

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./test.db")
    JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "your_secret_key")
    JWT_EXPIRE_MINUTES: int = int(os.getenv("JWT_EXPIRE_MINUTES", "30"))
    AGENT2_MODEL_PATH: str = "src/classiflow/ingesta/models/Phi-4-mini-instruct-Q4_K_M.gguf"
    AGENT3_MODEL_PATH: str = "src/classiflow/ingesta/models/Phi-4-mini-instruct-Q4_K_M.gguf"

    @property
    def database_url(self) -> str:
        return self.DATABASE_URL

    @property
    def jwt_secret_key(self) -> str:
        return self.JWT_SECRET_KEY

    @property
    def jwt_expire_minutes(self) -> int:
        return self.JWT_EXPIRE_MINUTES

    @property
    def agent2_model_path(self) -> str:
        return self.AGENT2_MODEL_PATH

    @property
    def agent3_model_path(self) -> str:
        return self.AGENT3_MODEL_PATH


Settings = _Settings()
