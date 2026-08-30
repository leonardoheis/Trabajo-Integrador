from http import HTTPStatus

from fastapi import Request
from fastapi.responses import JSONResponse

from classiflow.services.job.exceptions import JobNotFoundError, JobNotInReviewError


def handle_job_not_found_error(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, JobNotFoundError)
    return JSONResponse(status_code=HTTPStatus.NOT_FOUND, content={"detail": str(exc)})


def handle_job_not_in_review_error(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, JobNotInReviewError)
    return JSONResponse(status_code=HTTPStatus.CONFLICT, content={"detail": str(exc)})
