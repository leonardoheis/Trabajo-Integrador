import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_PROJECT_ROOT = Path(__file__).parents[2]
_DEFAULT_MODEL = str(
    _PROJECT_ROOT / "src" / "classiflow" / "ingesta" / "models" / "Phi-4-mini-instruct-Q4_K_M.gguf"
)


class _Settings(BaseSettings):
    API_PORT: int = 8000
    HOST: str = "0.0.0.0"  # nosec

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./data/classiflow.db")
    JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "your_secret_key")
    JWT_EXPIRE_MINUTES: int = int(os.getenv("JWT_EXPIRE_MINUTES", "30"))
    NODE2_MODEL_PATH: str = _DEFAULT_MODEL
    NODE3_MODEL_PATH: str = _DEFAULT_MODEL

    GOOGLE_CLIENT_ID: str = os.getenv("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
    GOOGLE_REDIRECT_URI: str = os.getenv(
        "GOOGLE_REDIRECT_URI", "http://localhost:8000/auth/callback"
    )

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
    def node2_model_path(self) -> str:
        return self.NODE2_MODEL_PATH

    @property
    def node3_model_path(self) -> str:
        return self.NODE3_MODEL_PATH


Settings = _Settings()
