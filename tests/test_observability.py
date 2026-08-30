import os
from unittest.mock import MagicMock

import pytest
from weave.integrations.langchain import WeaveTracer

import classiflow.observability as observability_module
from classiflow.ingesta.llm_provider import MockLlm
from classiflow.observability import init_tracing


@pytest.fixture
def _enable_tracing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("classiflow.observability.Settings.WANDB_API_KEY", "fake-key")
    monkeypatch.setattr("classiflow.observability.Settings.WANDB_PROJECT", "test-project")
    monkeypatch.setattr("classiflow.observability.Settings.WEAVE_TRACE_LANGCHAIN", "true")
    monkeypatch.setattr("classiflow.observability.weave.init", MagicMock())
    monkeypatch.delenv("WEAVE_TRACE_LANGCHAIN", raising=False)


class TestInitTracing:
    def test_does_nothing_without_an_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("classiflow.observability.Settings.WANDB_API_KEY", "")
        weave_init = MagicMock()
        monkeypatch.setattr("classiflow.observability.weave.init", weave_init)

        init_tracing()

        weave_init.assert_not_called()

    @pytest.mark.usefixtures("_enable_tracing")
    def test_initializes_weave_and_enables_the_global_tracer(self) -> None:
        init_tracing()

        observability_module.weave.init.assert_called_once_with("test-project")
        # The global tracer is what covers chains and LangGraph nodes, not just LLMs.
        assert os.environ["WEAVE_TRACE_LANGCHAIN"] == "true"

    @pytest.mark.usefixtures("_enable_tracing")
    def test_patches_the_tracer_so_a_none_generation_info_does_not_lose_the_call(
        self,
    ) -> None:
        # Unpatched, weave's usage extraction raises on generation_info=None and
        # finish_call is never reached, leaving the trace unfinished.
        init_tracing()
        tracer = WeaveTracer()
        tracer.wc = MagicMock()
        tracer.wc.create_call.return_value = "call"

        MockLlm(response="hi").invoke("prompt", config={"callbacks": [tracer]})

        tracer.wc.finish_call.assert_called_once()

    @pytest.mark.usefixtures("_enable_tracing")
    def test_patching_the_tracer_twice_does_not_stack_wrappers(self) -> None:
        init_tracing()
        once = WeaveTracer.on_llm_end
        init_tracing()

        assert WeaveTracer.on_llm_end is once
