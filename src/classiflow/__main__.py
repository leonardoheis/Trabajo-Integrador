from multiprocessing import Process

from .api import run_api
from .frontend import run_frontend


def main() -> None:
    api_process = Process(target=run_api)
    frontend_process = Process(target=run_frontend)

    api_process.start()
    frontend_process.start()

    api_process.join()
    frontend_process.join()


if __name__ == "__main__":
    main()
