import uvicorn

from classiflow.settings import Settings


def run_api() -> None:
    uvicorn.run(
        "classiflow.api.app:create_app",
        factory=True,
        host=Settings.HOST,
        port=Settings.API_PORT,
    )
