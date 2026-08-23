from collections.abc import Callable

from fastapi import Request, Response

from classiflow.api.error_handlers.auth import (
    handle_auth_error,
    handle_not_allowed_error,
    handle_oauth_error,
)
from classiflow.api.error_handlers.classification import (
    handle_classification_not_in_review_error,
    handle_classification_record_not_found_error,
)
from classiflow.api.error_handlers.knowledge import (
    handle_chat_refusal,
    handle_knowledge_error,
)
from classiflow.api.error_handlers.llm import (
    handle_llm_provider_error,
    handle_model_load_error,
    handle_model_not_found,
)
from classiflow.api.error_handlers.pipeline import (
    handle_job_not_found_error,
    handle_job_not_in_review_error,
)
from classiflow.classification.exceptions import (
    ClassificationNotInReviewError,
    ClassificationRecordNotFoundError,
)
from classiflow.ingesta.exceptions import LlmProviderError, ModelLoadError, ModelNotFoundError
from classiflow.knowledge.exceptions import KnowledgeError
from classiflow.knowledge.llm.exceptions import ChatRefusalError
from classiflow.services.auth.exceptions import AuthError, NotAllowedError, OAuthError
from classiflow.services.job.exceptions import JobNotFoundError, JobNotInReviewError

ExceptionHandler = Callable[[Request, Exception], Response]

EXCEPTION_HANDLERS: dict[type[Exception], ExceptionHandler] = {
    NotAllowedError: handle_not_allowed_error,
    OAuthError: handle_oauth_error,
    AuthError: handle_auth_error,
    ModelNotFoundError: handle_model_not_found,
    ModelLoadError: handle_model_load_error,
    LlmProviderError: handle_llm_provider_error,
    JobNotFoundError: handle_job_not_found_error,
    JobNotInReviewError: handle_job_not_in_review_error,
    ChatRefusalError: handle_chat_refusal,
    KnowledgeError: handle_knowledge_error,
    ClassificationRecordNotFoundError: handle_classification_record_not_found_error,
    ClassificationNotInReviewError: handle_classification_not_in_review_error,
}
