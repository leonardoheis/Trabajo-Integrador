from fastapi import Request
from fastapi.responses import JSONResponse

from classiflow.classification.exceptions import (
    ClassificationNotInReviewError,
    ClassificationRecordNotFoundError,
)


def handle_classification_record_not_found_error(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ClassificationRecordNotFoundError)
    return JSONResponse(status_code=404, content={"detail": str(exc)})


def handle_classification_not_in_review_error(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ClassificationNotInReviewError)
    return JSONResponse(status_code=409, content={"detail": str(exc)})
