import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_PROJECT_ROOT = Path(__file__).parents[2]
_MODELS_DIR = _PROJECT_ROOT / "models"
# Swapped from Phi-4-mini-instruct (3.8B) to Meta-Llama-3.1-8B-Instruct after real
# corpus testing found Phi-4-mini fabricating evidence that isn't in the source text
# at all (e.g. claiming a document "contains the phrase 'Compendio de Boletines'" and
# cites a number range, when neither appears anywhere in the actual excerpt) --
# confirmed via direct greedy-decoding (temperature=0) tests that this is a genuine
# hallucination/grounding failure, not prompt wording or sampling noise, and that
# Llama 3.1 8B does not reproduce it on the same real documents. Used for every
# node2/node3/enrichment/classification SLM call (all share this one path, and thus
# get_llm_langchain's cache), not just the primary classifier -- an earlier attempt to
# swap the classifier alone while leaving node2/node3/enrichment on Phi-4-mini meant
# two different GGUF models could be VRAM-resident at once, on top of the LLM Judge's
# own model, overflowing an 8GB card. A single shared model file avoids that: every
# stage either shares the exact same cached instance or (via
# FormatValidationNode/ContentValidationNode/EntityExtractorNode/PrimaryClassifierNode
# each dropping their own chain reference right after their one use per job) leaves
# nothing but get_llm_langchain's cache holding it, so LlmJudgeNode's unload_slm()
# call actually frees that VRAM before Gemma loads.
_DEFAULT_MODEL = str(_MODELS_DIR / "Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf")
_JUDGE_MODEL = str(_MODELS_DIR / "gemma-4-E4B-it-Q4_K_M.gguf")


class _Settings(BaseSettings):
    API_PORT: int = 8000
    HOST: list[str] = ["127.0.0.1", "localhost"]  # nosec

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
    CLASSIFICATION_MODEL_PATH: str = _DEFAULT_MODEL
    CLASSIFICATION_CONFIG_PATH: str = str(_PROJECT_ROOT / "config" / "classification.yaml")
    JUDGE_MODEL_PATH: str = _JUDGE_MODEL
    # 1, not 2: unload_slm() clears the shared get_llm_langchain cache when a job
    # finishes, so with parallel jobs the survivor reloads its ~4.9GB GGUF while the
    # old one is still resident -- two copies exceed an 8GB card and the load fails.
    # Raise only with VRAM headroom for one model per concurrent job.
    MAX_CONCURRENT_JOBS: int = int(os.getenv("MAX_CONCURRENT_JOBS", "1"))
    SLM_TEMPERATURE: float = float(os.getenv("SLM_TEMPERATURE", "0.1"))
    SLM_TOP_P: float = float(os.getenv("SLM_TOP_P", "0.95"))
    SLM_SEED: int = int(os.getenv("SLM_SEED", "42"))
    # LangChain's LlamaCpp wrapper defaults max_tokens to 256 when unset -- too small
    # for a structured JSON response with a "reasoning" field (e.g. the primary
    # classifier's 10-way label + confidence + reasoning), which silently truncates
    # mid-object and fails JSON parsing. Every get_llm_langchain() caller shares this
    # one setting; MockLlm-based tests never exercise the real default, which is why
    # this went unnoticed until a real model run.
    SLM_MAX_TOKENS: int = int(os.getenv("SLM_MAX_TOKENS", "512"))
    # Every quantized GGUF model here (Phi-4-mini, Gemma 4, ...) is trained for a far
    # larger context than this (n_ctx_train reported as 131072 for Phi-4-mini) -- 2048
    # was an arbitrary small cap this codebase set, not a model limit. Too small a
    # value here means llama.cpp silently clamps the completion budget once the
    # prompt (e.g. the primary classifier's ~1300-token category-definitions block +
    # document excerpt) fills the window, and the model can start hallucinating
    # off-prompt content once genuinely context-starved rather than erroring loudly.
    # 4096 gives real headroom while staying well inside an 8GB-VRAM budget's
    # KV-cache cost (roughly linear in n_ctx).
    SLM_N_CTX: int = int(os.getenv("SLM_N_CTX", "4096"))

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

    CHAT_MAX_TOKENS: int = int(os.getenv("CHAT_MAX_TOKENS", "2048"))
    CHAT_MODEL_PATH: str = _DEFAULT_MODEL
    # Retrieval passages plus the question do not fit in the 2048 the validation nodes
    # use, so the chat model gets its own context size.
    CHAT_MODEL_N_CTX: int = int(os.getenv("CHAT_MODEL_N_CTX", "8192"))

    GOOGLE_CLIENT_ID: str = os.getenv("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
    # Points at the frontend's OAuth popup route, not this backend's own /auth/callback
    # -- Google must redirect somewhere that can run JS to relay the token back to the
    # opener window via postMessage. The popup route itself calls the unchanged
    # /auth/callback JSON endpoint via fetch(); this only changes where Google's
    # redirect lands, not what /auth/callback returns.
    GOOGLE_REDIRECT_URI: str = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:5173/oauth-popup")

    # No os.getenv() wrapper on these three: pydantic-settings already fills every
    # field from the process environment first and .env second, so wrapping the default
    # would only re-read the environment and shadow what .env provides.
    #
    # Empty by default -- tracing stays off, so a clone with no .env (including every
    # test run) never calls weave.init() or reaches the network.
    WANDB_API_KEY: str = ""
    WANDB_PROJECT: str = "classiflow"
    # Consumed by weave, not by this app: weave.init() reads it from os.environ to
    # decide whether to register its global LangChain tracer. That tracer is what traces
    # the whole pipeline (chains and LangGraph nodes, not just direct LLM calls), so it
    # stays ON -- init_tracing() patches the tracer class first to fix weave's crash on
    # llama.cpp's None metadata. Set "false" only to disable LangChain tracing entirely.
    WEAVE_TRACE_LANGCHAIN: str = "true"

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
    def max_concurrent_jobs(self) -> int:
        return self.MAX_CONCURRENT_JOBS

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
    def slm_max_tokens(self) -> int:
        return self.SLM_MAX_TOKENS

    @property
    def slm_n_ctx(self) -> int:
        return self.SLM_N_CTX

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
    def chat_max_tokens(self) -> int:
        return self.CHAT_MAX_TOKENS

    @property
    def chat_model_path(self) -> str:
        return self.CHAT_MODEL_PATH

    @property
    def chat_model_n_ctx(self) -> int:
        return self.CHAT_MODEL_N_CTX

    @property
    def wandb_api_key(self) -> str:
        return self.WANDB_API_KEY

    @property
    def wandb_project(self) -> str:
        return self.WANDB_PROJECT

    @property
    def tracing_enabled(self) -> bool:
        # A configured key is the single switch: without one there is nothing to
        # authenticate against, so tracing stays off rather than failing at runtime.
        return bool(self.WANDB_API_KEY)


Settings = _Settings()

# Exposed for callers that need to resolve a project-root-relative path themselves
# (e.g. ClassificationConfig.bert_model_path, which the BERT spec's classification.yaml
# deliberately stores relative to the project root rather than baking an absolute path
# into a config file every clone would need to edit).
PROJECT_ROOT = _PROJECT_ROOT
