import shutil
import subprocess
from pathlib import Path

_FRONTEND_DIR = Path(__file__).parent
_NPM_NOT_FOUND = "npm not found on PATH"


def run_frontend() -> None:
    # shutil.which resolves the platform-specific executable (npm.cmd on Windows) to
    # an absolute path, so this can run without shell=True.
    npm = shutil.which("npm")
    if npm is None:
        raise FileNotFoundError(_NPM_NOT_FOUND)
    subprocess.run([npm, "run", "dev"], cwd=_FRONTEND_DIR, check=True)
