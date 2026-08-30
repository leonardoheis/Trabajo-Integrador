from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from classiflow.injections import configure_container
from classiflow.observability import init_tracing

from .error_handlers import EXCEPTION_HANDLERS
from .routes import ROUTERS

_FRONTEND_DIST = Path(__file__).parents[1] / "frontend" / "dist"


def create_app() -> FastAPI:
    # @cache-d, so this is a no-op after the first call in a process -- but it must run
    # here, not just once from a CLI entry point, since uvicorn's --factory + --reload
    # spawns a fresh worker subprocess that re-imports and re-calls create_app() without
    # ever running whatever wired the container in the parent process. Without this,
    # every @inject/Provide[Container.x] marker resolves to the raw Provide sentinel
    # instead of the real dependency (e.g. "'Provide' object has no attribute ...").
    configure_container()

    # Once per process, before any LLM is built -- weave decides whether to register its
    # own global LangChain tracer during init(), so this has to precede the first model
    # load rather than run lazily alongside it.
    init_tracing()

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
