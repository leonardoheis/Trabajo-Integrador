import pytest

from classiflow.ingesta.llm_provider import MockLlm


@pytest.fixture
def mock_llm() -> MockLlm:
    return MockLlm()
