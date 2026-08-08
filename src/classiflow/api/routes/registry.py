from fastapi import APIRouter

from classiflow.api.routes.health import router as health_router

ROUTERS: list[APIRouter] = [health_router]
