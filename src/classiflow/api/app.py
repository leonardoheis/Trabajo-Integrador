from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .error_handlers import EXCEPTION_HANDLERS
from .routes import ROUTERS

_FRONTEND_DIST = Path(__file__).parents[1] / "frontend" / "dist"


def create_app() -> FastAPI:
    app = FastAPI(title="Classiflow")

    for router in ROUTERS:
        app.include_router(router)

    for exception, exception_handler in EXCEPTION_HANDLERS.items():
        app.add_exception_handler(exception, exception_handler)

    # Serves the built React SPA in production. Absent in dev (the frontend runs via
    # its own `npm run dev` + Vite's proxy instead) and absent until the frontend is
    # actually built for the first time -- both are normal, not errors, so this only
    # mounts when the directory is actually there.
    if _FRONTEND_DIST.is_dir():
        app.mount("/", StaticFiles(directory=_FRONTEND_DIST, html=True), name="frontend")

    return app
