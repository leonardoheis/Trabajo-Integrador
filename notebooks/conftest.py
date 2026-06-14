import pytest


def pytest_sessionfinish(session: pytest.Session, exitstatus: int | pytest.ExitCode) -> None:
    """Treat 'no tests collected' as a pass for the notebooks suite.

    The only current notebook (colab_downloader.ipynb) requires Google Colab
    and is excluded from local runs. Exit code 5 = no items collected.
    """
    if exitstatus == pytest.ExitCode.NO_TESTS_COLLECTED:
        session.exitstatus = pytest.ExitCode.OK
