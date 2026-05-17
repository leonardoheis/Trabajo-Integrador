from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
    )

    OUTPUT_BASE_DIR: Path = Path("./output")
    CONFIDENCE_THRESHOLD: float = 0.85
    LOG_LEVEL: str = "INFO"


settings = Settings()
