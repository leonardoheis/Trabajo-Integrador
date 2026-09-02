import os
import sys

import uvicorn

from classiflow.settings import Settings


def run_api() -> None:
    # W&B captures stdout/stderr in the main process. When multiprocessing spawns
    # this subprocess, the captured (invalid) handles are inherited. Restore real
    # file-descriptor-backed streams before uvicorn or any logger touches them.
    sys.stdout = os.fdopen(os.dup(1), "w", encoding="utf-8")
    sys.stderr = os.fdopen(os.dup(2), "w", encoding="utf-8")

    # create_app() (imported lazily by uvicorn via this factory string) calls
    # configure_container() itself -- see its own comment for why that has to live
    # there rather than here.
    uvicorn.run(
        "classiflow.api.app:create_app",
        factory=True,
        host=Settings.HOST[0],  # uvicorn binds one host per run
        port=Settings.API_PORT,
    )
