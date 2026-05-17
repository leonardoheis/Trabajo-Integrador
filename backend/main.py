from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from api.routes import audit, jobs, upload

logging.basicConfig(
    level=settings.LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

_OUTPUT_FOLDERS = [
    "invoices",
    "contracts",
    "tax_returns",
    "reports",
    "review",
]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialize output directories on startup."""
    logger.info("Initializing output directories under '%s'.", settings.OUTPUT_BASE_DIR)
    settings.OUTPUT_BASE_DIR.mkdir(parents=True, exist_ok=True)
    for folder in _OUTPUT_FOLDERS:
        (settings.OUTPUT_BASE_DIR / folder).mkdir(parents=True, exist_ok=True)
    logger.info("Output directories ready.")
    yield
    logger.info("Application shutting down.")


app = FastAPI(
    title="Document Classification API",
    description=(
        "Classifies uploaded documents using Azure AI Document Intelligence "
        "and routes them to the appropriate output folder via a LangGraph orchestrator."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# CORS — allow Vite dev server
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
app.include_router(upload.router, prefix="/api/v1", tags=["upload"])
app.include_router(jobs.router, prefix="/api/v1", tags=["jobs"])
app.include_router(audit.router, prefix="/api/v1", tags=["audit"])


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
@app.get("/", tags=["health"])
async def root() -> dict:
    return {"status": "ok", "version": "1.0.0"}
