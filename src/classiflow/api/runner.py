import uvicorn

from classiflow.settings import Settings


def run_api() -> None:
    # create_app() (imported lazily by uvicorn via this factory string) calls
    # configure_container() itself -- see its own comment for why that has to live
    # there rather than here. reload=True re-imports on every change under the excluded
    # paths below; that works safely with the factory string precisely because
    # create_app() self-wires instead of relying on module-level state from run_api().
    uvicorn.run(
        "classiflow.api.app:create_app",
        factory=True,
        host=Settings.HOST[0],  # uvicorn binds one host per run
        port=Settings.API_PORT,
        reload=True,
        # Without these, editing any frontend file (or its huge node_modules tree)
        # would also trigger a backend reload -- neither affects the Python process.
        reload_excludes=["src/classiflow/frontend/*"],
    )
