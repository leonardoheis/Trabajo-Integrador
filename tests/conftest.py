import pytest

from classiflow.settings import Settings


@pytest.fixture
def _jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Settings, "JWT_SECRET_KEY", "test-secret-key-for-testing-only-32chars!")


def pytest_configure(config: pytest.Config) -> None:
    # Settings reads WANDB_API_KEY from the developer's real .env, so without this a
    # local key makes get_llm_langchain() call weave.init() for real -- logging into
    # the developer's W&B account and creating live traces from the test suite.
    # Done here rather than in an autouse fixture so no individual test has to
    # remember it and there is no per-test setup cost; a test that wants tracing on
    # patches WANDB_API_KEY itself (see tests/ingesta/test_llm_provider.py).
    del config
    Settings.WANDB_API_KEY = ""
