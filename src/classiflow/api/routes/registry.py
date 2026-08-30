from fastapi import APIRouter

from classiflow.api.routes.audit import router as audit_router
from classiflow.api.routes.auth import router as auth_router
from classiflow.api.routes.classification import router as classification_router
from classiflow.api.routes.documents import router as documents_router
from classiflow.api.routes.health import router as health_router
from classiflow.api.routes.knowledge import router as knowledge_router
from classiflow.api.routes.pipeline import router as pipeline_router
from classiflow.api.routes.pipeline import sse_router as pipeline_sse_router
from classiflow.api.routes.users import router as users_router

ROUTERS: list[APIRouter] = [
    health_router,
    auth_router,
    pipeline_router,
    pipeline_sse_router,
    classification_router,
    knowledge_router,
    users_router,
    audit_router,
    documents_router,
]
