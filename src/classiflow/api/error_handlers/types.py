from collections.abc import Callable

from fastapi import Request, Response

from classiflow.api.error_handlers.llm import (
    handle_llm_provider_error,
    handle_model_load_error,
    handle_model_not_found,
)
from classiflow.ingesta.exceptions import LlmProviderError, ModelLoadError, ModelNotFoundError

ExceptionHandler = Callable[[Request, Exception], Response]

EXCEPTION_HANDLERS: dict[type[Exception], ExceptionHandler] = {
    ModelNotFoundError: handle_model_not_found,
    ModelLoadError: handle_model_load_error,
    LlmProviderError: handle_llm_provider_error,
}
