from fastapi import Request
from fastapi.responses import JSONResponse

from classiflow.services.job.exceptions import JobNotFoundError, JobNotInReviewError


def handle_job_not_found_error(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, JobNotFoundError)
    return JSONResponse(status_code=404, content={"detail": str(exc)})


def handle_job_not_in_review_error(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, JobNotInReviewError)
    return JSONResponse(status_code=409, content={"detail": str(exc)})
