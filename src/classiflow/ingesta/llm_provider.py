from functools import lru_cache

from langchain_community.llms import LlamaCpp
from langchain_core.callbacks.manager import CallbackManagerForLLMRun
from langchain_core.language_models import BaseLLM
from langchain_core.outputs import Generation, LLMResult
from llama_cpp import Llama
from pydantic import Field

from classiflow.ingesta.exceptions import ModelLoadError, ModelNotFoundError
from classiflow.settings import Settings


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
    path = Settings.llm_model_path
    try:
        return Llama(model_path=path, n_ctx=2048, verbose=False)
    except FileNotFoundError as exc:
        raise ModelNotFoundError(path=path) from exc
    except Exception as exc:
        raise ModelLoadError(path=path, cause=str(exc)) from exc


@lru_cache(maxsize=1)
def get_llm_langchain() -> BaseLLM:
    path = Settings.llm_model_path
    try:
        return LlamaCpp(model_path=path, n_ctx=2048, verbose=False)  # type: ignore[no-any-return]
    except FileNotFoundError as exc:
        raise ModelNotFoundError(path=path) from exc
    except Exception as exc:
        raise ModelLoadError(path=path, cause=str(exc)) from exc
