from functools import lru_cache

from langchain_core.callbacks.manager import CallbackManagerForLLMRun
from langchain_core.language_models import BaseLLM
from langchain_core.outputs import Generation, LLMResult
from llama_cpp import Llama
from pydantic import Field

_INSTALL_MSG = (
    "llama-cpp-python is not installed. See INSTALL.md for build and GPU-flag instructions."
)


class MockLlm(BaseLLM):
    response: str = Field(default='{"decision": "accept", "confidence": 0.95}')

    def _generate(
        self,
        prompts: list[str],
        stop: list[str] | None = None,  # noqa: ARG002
        run_manager: CallbackManagerForLLMRun | None = None,  # noqa: ARG002
        **kwargs: object,  # noqa: ARG002
    ) -> LLMResult:
        return LLMResult(generations=[[Generation(text=self.response)] for _ in prompts])

    @property
    def _llm_type(self) -> str:
        return "mock"


@lru_cache(maxsize=1)
def get_llm() -> Llama:
    try:
        from classiflow.settings import Settings  # noqa: PLC0415

        return Llama(model_path=Settings.LLM_MODEL_PATH, n_ctx=2048, verbose=False)
    except Exception as exc:
        raise ImportError(_INSTALL_MSG) from exc


@lru_cache(maxsize=1)
def get_llm_langchain() -> BaseLLM:
    try:
        from langchain_community.llms import LlamaCpp  # noqa: PLC0415
    except ImportError as exc:
        raise ImportError(_INSTALL_MSG) from exc

    from classiflow.settings import Settings  # noqa: PLC0415

    try:
        return LlamaCpp(model_path=Settings.LLM_MODEL_PATH, n_ctx=2048, verbose=False)  # type: ignore[no-any-return]
    except Exception as exc:
        raise ImportError(_INSTALL_MSG) from exc
