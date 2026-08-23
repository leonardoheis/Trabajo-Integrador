import uvicorn

from classiflow.injections import configure_container
from classiflow.settings import Settings


def run_api() -> None:
    configure_container()
    uvicorn.run(
        "classiflow.api.app:create_app",
        factory=True,
        host=Settings.HOST,
        port=Settings.API_PORT,
        reload=True,
    )
