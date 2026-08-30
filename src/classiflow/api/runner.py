import uvicorn

from classiflow.settings import Settings


def run_api() -> None:
    # create_app() (imported lazily by uvicorn via this factory string) calls
    # configure_container() itself -- see its own comment for why that has to live
    # there rather than here.
    uvicorn.run(
        "classiflow.api.app:create_app",
        factory=True,
        host=Settings.HOST[0],  # uvicorn binds one host per run
        port=Settings.API_PORT,
    )
