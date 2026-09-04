from http import HTTPStatus

from fastapi import Request
from fastapi.responses import JSONResponse

from classiflow.classification.exceptions import (
    ClassificationNotAcceptedError,
    ClassificationNotDecidedError,
    ClassificationNotInReviewError,
    ClassificationRecordNotFoundError,
)


def handle_classification_record_not_found_error(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ClassificationRecordNotFoundError)
    return JSONResponse(status_code=HTTPStatus.NOT_FOUND, content={"detail": str(exc)})


def handle_classification_not_in_review_error(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ClassificationNotInReviewError)
    return JSONResponse(status_code=HTTPStatus.CONFLICT, content={"detail": str(exc)})


def handle_classification_not_accepted_error(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ClassificationNotAcceptedError)
    return JSONResponse(status_code=HTTPStatus.CONFLICT, content={"detail": str(exc)})


def handle_classification_not_decided_error(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ClassificationNotDecidedError)
    return JSONResponse(status_code=HTTPStatus.CONFLICT, content={"detail": str(exc)})
