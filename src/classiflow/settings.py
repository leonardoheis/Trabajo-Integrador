import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_PROJECT_ROOT = Path(__file__).parents[2]
_MODELS_DIR = _PROJECT_ROOT / "models"
_DEFAULT_MODEL = str(_MODELS_DIR / "Phi-4-mini-instruct-Q4_K_M.gguf")
# LLM Judge tier only runs on the minority of documents the primary classifier (Phi-4-mini,
# _DEFAULT_MODEL) couldn't confidently resolve -- a bigger model earns its extra cost there.
# Not yet present under models/ -- must be downloaded before Task 13 (LlmJudgeNode) can be
# exercised end-to-end; MockLlm-based unit tests don't need the real file.
_JUDGE_MODEL = str(_MODELS_DIR / "gemma-4-E4B-it-Q4_K_M.gguf")
# Primary classifier runs on every document (unlike the Judge above), so it stays in
# Phi-4-mini's footprint (~2.5GB Q4_K_M) rather than a larger model -- Llama 3.2 3B is
# the closest match (~2.0GB) and adds real model diversity from Node2/Node3/enrichment's
# shared Phi-4-mini, plus multilingual tuning relevant to Spanish municipal documents.
# Not yet present under models/ -- must be downloaded before Task 5 (PrimaryClassifierNode)
# can be exercised end-to-end; MockLlm-based unit tests don't need the real file.
_CLASSIFICATION_MODEL = str(_MODELS_DIR / "Llama-3.2-3B-Instruct-Q4_K_M.gguf")


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
    EMBEDDING_MODEL_PATH: str = str(_MODELS_DIR / "embeddings")
    OCR_LANG: str = os.getenv("OCR_LANG", "es")
    OCR_RENDER_DPI: int = int(os.getenv("OCR_RENDER_DPI", "200"))
    EXTRACTION_CONFIG_PATH: str = str(_PROJECT_ROOT / "config" / "extraction.yaml")
    ENRICHMENT_MODEL_PATH: str = _DEFAULT_MODEL
    ENRICHMENT_CONFIG_PATH: str = str(_PROJECT_ROOT / "config" / "enrichment.yaml")
    DOCUMENT_STORAGE_ROOT: str = str(_PROJECT_ROOT / "storage" / "documents")
    CLASSIFICATION_MODEL_PATH: str = _CLASSIFICATION_MODEL
    CLASSIFICATION_CONFIG_PATH: str = str(_PROJECT_ROOT / "config" / "classification.yaml")
    JUDGE_MODEL_PATH: str = _JUDGE_MODEL
    SLM_TEMPERATURE: float = float(os.getenv("SLM_TEMPERATURE", "0.8"))
    SLM_TOP_P: float = float(os.getenv("SLM_TOP_P", "0.95"))
    SLM_SEED: int = int(os.getenv("SLM_SEED", "42"))

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

    @property
    def embedding_model_path(self) -> str:
        return self.EMBEDDING_MODEL_PATH

    @property
    def ocr_lang(self) -> str:
        return self.OCR_LANG

    @property
    def ocr_render_dpi(self) -> int:
        return self.OCR_RENDER_DPI

    @property
    def extraction_config_path(self) -> str:
        return self.EXTRACTION_CONFIG_PATH

    @property
    def enrichment_model_path(self) -> str:
        return self.ENRICHMENT_MODEL_PATH

    @property
    def enrichment_config_path(self) -> str:
        return self.ENRICHMENT_CONFIG_PATH

    @property
    def document_storage_root(self) -> str:
        return self.DOCUMENT_STORAGE_ROOT

    @property
    def classification_model_path(self) -> str:
        return self.CLASSIFICATION_MODEL_PATH

    @property
    def classification_config_path(self) -> str:
        return self.CLASSIFICATION_CONFIG_PATH

    @property
    def judge_model_path(self) -> str:
        return self.JUDGE_MODEL_PATH

    @property
    def slm_temperature(self) -> float:
        return self.SLM_TEMPERATURE

    @property
    def slm_top_p(self) -> float:
        return self.SLM_TOP_P

    @property
    def slm_seed(self) -> int:
        return self.SLM_SEED


Settings = _Settings()
