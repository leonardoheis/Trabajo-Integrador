from fastapi import APIRouter

from classiflow.api.routes.auth import router as auth_router
from classiflow.api.routes.chat import router as chat_router
from classiflow.api.routes.health import router as health_router
from classiflow.api.routes.pipeline import router as pipeline_router

ROUTERS: list[APIRouter] = [health_router, auth_router, pipeline_router, chat_router]
