from fastapi import FastAPI

from classiflow.injections import configure_container

from .error_handlers import EXCEPTION_HANDLERS
from .routes import ROUTERS


def create_app() -> FastAPI:
    configure_container()
    app = FastAPI(title="Classiflow")

    for router in ROUTERS:
        app.include_router(router)

    for exception, exception_handler in EXCEPTION_HANDLERS.items():
        app.add_exception_handler(exception, exception_handler)

    return app
