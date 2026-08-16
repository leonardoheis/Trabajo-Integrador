import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_PROJECT_ROOT = Path(__file__).parents[2]
_DEFAULT_MODEL = str(
    _PROJECT_ROOT / "src" / "classiflow" / "ingesta" / "models" / "Phi-4-mini-instruct-Q4_K_M.gguf"
)


# One read-only accessor per setting is this module's established pattern; the
# count grows with configuration, not with behaviour.
class _Settings(BaseSettings):  # noqa: PLR0904
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
    OCR_LANG: str = os.getenv("OCR_LANG", "es")
    OCR_RENDER_DPI: int = int(os.getenv("OCR_RENDER_DPI", "200"))
    SLM_TEMPERATURE: float = float(os.getenv("SLM_TEMPERATURE", "0.8"))
    SLM_TOP_P: float = float(os.getenv("SLM_TOP_P", "0.95"))
    SLM_SEED: int = int(os.getenv("SLM_SEED", "42"))

    # Knowledge base / chat (stage 5)
    CHROMA_PATH: str = os.getenv("CHROMA_PATH", str(_PROJECT_ROOT / "data" / "chroma"))
    CHROMA_COLLECTION: str = os.getenv("CHROMA_COLLECTION", "classiflow_docs")
    # Multilingual on purpose: the corpus is Spanish. Node 4's duplicate control keeps
    # all-MiniLM-L6-v2 -- swapping it there would invalidate the cosine threshold
    # calibrated in config/duplicate_control.yaml.
    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "paraphrase-multilingual-MiniLM-L12-v2")
    CHUNK_SIZE: int = int(os.getenv("CHUNK_SIZE", "1000"))
    CHUNK_OVERLAP: int = int(os.getenv("CHUNK_OVERLAP", "150"))
    RETRIEVAL_TOP_K: int = int(os.getenv("RETRIEVAL_TOP_K", "5"))
    SCRAPPER_DIR: str = os.getenv("SCRAPPER_DIR", str(_PROJECT_ROOT / "scrapper"))

    CHAT_LLM_PROVIDER: str = os.getenv("CHAT_LLM_PROVIDER", "llama")
    CHAT_MAX_TOKENS: int = int(os.getenv("CHAT_MAX_TOKENS", "2048"))
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    ANTHROPIC_MODEL: str = os.getenv("ANTHROPIC_MODEL", "claude-opus-5")
    CHAT_MODEL_PATH: str = _DEFAULT_MODEL
    # Retrieval passages plus the question do not fit in the 2048 the validation nodes
    # use, so the chat model gets its own context size.
    CHAT_MODEL_N_CTX: int = int(os.getenv("CHAT_MODEL_N_CTX", "8192"))

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
    def ocr_lang(self) -> str:
        return self.OCR_LANG

    @property
    def ocr_render_dpi(self) -> int:
        return self.OCR_RENDER_DPI

    @property
    def slm_temperature(self) -> float:
        return self.SLM_TEMPERATURE

    @property
    def slm_top_p(self) -> float:
        return self.SLM_TOP_P

    @property
    def slm_seed(self) -> int:
        return self.SLM_SEED

    @property
    def chroma_path(self) -> str:
        return self.CHROMA_PATH

    @property
    def chroma_collection(self) -> str:
        return self.CHROMA_COLLECTION

    @property
    def embedding_model(self) -> str:
        return self.EMBEDDING_MODEL

    @property
    def chunk_size(self) -> int:
        return self.CHUNK_SIZE

    @property
    def chunk_overlap(self) -> int:
        return self.CHUNK_OVERLAP

    @property
    def retrieval_top_k(self) -> int:
        return self.RETRIEVAL_TOP_K

    @property
    def scrapper_dir(self) -> str:
        return self.SCRAPPER_DIR

    @property
    def chat_llm_provider(self) -> str:
        return self.CHAT_LLM_PROVIDER

    @property
    def chat_max_tokens(self) -> int:
        return self.CHAT_MAX_TOKENS

    @property
    def anthropic_api_key(self) -> str:
        return self.ANTHROPIC_API_KEY

    @property
    def anthropic_model(self) -> str:
        return self.ANTHROPIC_MODEL

    @property
    def chat_model_path(self) -> str:
        return self.CHAT_MODEL_PATH

    @property
    def chat_model_n_ctx(self) -> int:
        return self.CHAT_MODEL_N_CTX


Settings = _Settings()
