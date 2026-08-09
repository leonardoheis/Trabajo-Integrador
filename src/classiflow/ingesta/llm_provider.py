from functools import lru_cache

from langchain_community.llms import LlamaCpp
from langchain_core.callbacks.manager import CallbackManagerForLLMRun
from langchain_core.language_models import BaseLLM
from langchain_core.outputs import Generation, LLMResult
from llama_cpp import Llama
from pydantic import Field

from classiflow.ingesta.exceptions import ModelLoadError, ModelNotFoundError


class MockLlm(BaseLLM):
    response: str = Field(default='{"decision": "accept", "confidence": 0.95}')

    def _generate(  # type: ignore[override]  # BaseLLM declares **kwargs: Any; omitting it here is intentional
        self,
        prompts: list[str],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
    ) -> LLMResult:
        text = self.response
        if stop:
            for token in stop:
                if token in text:
                    text = text[: text.index(token)]
        if run_manager:
            run_manager.on_llm_new_token(text)
        return LLMResult(generations=[[Generation(text=text)] for _ in prompts])

    @property
    def _llm_type(self) -> str:
        return "mock"


@lru_cache(maxsize=4)
def get_llm(model_path: str) -> Llama:
    try:
        return Llama(model_path=model_path, n_ctx=2048, verbose=False)
    except FileNotFoundError as exc:
        raise ModelNotFoundError(path=model_path) from exc
    except Exception as exc:
        raise ModelLoadError(path=model_path, cause=str(exc)) from exc


@lru_cache(maxsize=4)
def get_llm_langchain(model_path: str) -> BaseLLM:
    try:
        return LlamaCpp(model_path=model_path, n_ctx=2048, verbose=False)  # type: ignore[no-any-return]
    except FileNotFoundError as exc:
        raise ModelNotFoundError(path=model_path) from exc
    except Exception as exc:
        raise ModelLoadError(path=model_path, cause=str(exc)) from exc
