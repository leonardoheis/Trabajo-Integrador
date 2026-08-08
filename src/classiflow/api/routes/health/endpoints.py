from fastapi import APIRouter

from classiflow.api.schemas import BaseSchema

router = APIRouter(tags=["health"])


class HealthResponse(BaseSchema):
    message: str
    status: str


@router.get("/health")
async def health() -> HealthResponse:
    return HealthResponse(status="healthy", message="The API is running smoothly.")
