import logging
import os
from functools import cache
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from loguru import logger
from typing_extensions import override

from classiflow.injections import configure_container
from classiflow.observability import init_tracing

from .error_handlers import EXCEPTION_HANDLERS
from .routes import ROUTERS

_FRONTEND_DIST = Path(__file__).parents[1] / "frontend" / "dist"
_LOG_FILE = Path(__file__).parents[3] / "classiflow.log"


@cache
def _add_log_file_sink() -> None:
    # @cache-d for the same reason as configure_container(): create_app() itself isn't
    # cached and tests call it multiple times per process (once per module-scoped
    # `client` fixture) -- this guards against stacking duplicate sinks, which would
    # write every log line N times over.
    #
    # Loguru's default sink (id 0) captured sys.stderr at import time, which under
    # `poe serve` is W&B's console-capture wrapper around a handle inherited from the
    # parent process -- writing to it raises OSError [WinError 1] in this subprocess.
    # Swap it for a fresh fd-backed stream; errors="replace" also stops loguru's own
    # error interceptor from dying on cp1252-unencodable characters.
    logger.remove()
    stderr = os.fdopen(os.dup(2), "w", encoding="utf-8", errors="replace", buffering=1)
    logger.add(stderr, level="INFO")
    # mode="w": overwrite on every process start, so the file always reflects only the
    # current run -- makes it easy to grep a stuck job's timeline without scrolling
    # back through the terminal (or a previous run's output).
    logger.add(_LOG_FILE, mode="w", level="INFO", encoding="utf-8")
    # Bridge stdlib logging → loguru for the classiflow package. Attaching to the
    # named "classiflow" logger (not root) means uvicorn's own logging setup can't
    # clobber our handler — uvicorn only touches the root logger and its own named
    # loggers ("uvicorn", "uvicorn.access", "uvicorn.error").
    cf_log = logging.getLogger("classiflow")
    cf_log.handlers = [_LoguruHandler()]
    cf_log.setLevel(logging.INFO)
    cf_log.propagate = False  # don't double-emit via root


class _LoguruHandler(logging.Handler):
    @override
    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = str(record.levelno)
        logger.opt(depth=6, exception=record.exc_info).log(level, record.getMessage())


def create_app() -> FastAPI:
    # @cache-d, so this is a no-op after the first call in a process -- but it must run
    # here, not just once from a CLI entry point, since uvicorn's --factory + --reload
    # spawns a fresh worker subprocess that re-imports and re-calls create_app() without
    # ever running whatever wired the container in the parent process. Without this,
    # every @inject/Provide[Container.x] marker resolves to the raw Provide sentinel
    # instead of the real dependency (e.g. "'Provide' object has no attribute ...").
    configure_container()
    _add_log_file_sink()

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
