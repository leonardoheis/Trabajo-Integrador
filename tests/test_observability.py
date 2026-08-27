import os
from unittest.mock import MagicMock

import pytest

from classiflow.ingesta.llm_provider import MockLlm
from classiflow.observability import PatchedWeaveTracer, init_tracing, tracing_callbacks


class TestTracingCallbacks:
    def test_returns_empty_list_when_no_api_key_is_configured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("classiflow.observability.Settings.WANDB_API_KEY", "")
        assert tracing_callbacks() == []

    def test_returns_a_tracer_when_a_key_is_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("classiflow.observability.Settings.WANDB_API_KEY", "fake-key")
        tracer_cls = MagicMock()
        monkeypatch.setattr("classiflow.observability.PatchedWeaveTracer", tracer_cls)

        assert tracing_callbacks() == [tracer_cls.return_value]


class TestInitTracing:
    def test_does_nothing_without_an_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("classiflow.observability.Settings.WANDB_API_KEY", "")
        weave_init = MagicMock()
        monkeypatch.setattr("classiflow.observability.weave.init", weave_init)

        init_tracing()

        weave_init.assert_not_called()

    def test_initializes_weave_and_opts_out_of_the_global_tracer(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("classiflow.observability.Settings.WANDB_API_KEY", "fake-key")
        monkeypatch.setattr("classiflow.observability.Settings.WANDB_PROJECT", "test-project")
        monkeypatch.setattr("classiflow.observability.Settings.WEAVE_TRACE_LANGCHAIN", "false")
        weave_init = MagicMock()
        monkeypatch.setattr("classiflow.observability.weave.init", weave_init)
        monkeypatch.delenv("WEAVE_TRACE_LANGCHAIN", raising=False)

        init_tracing()

        weave_init.assert_called_once_with("test-project")
        # weave registers its own unpatched global tracer unless this is already set.
        assert os.environ["WEAVE_TRACE_LANGCHAIN"] == "false"


class TestPatchedWeaveTracer:
    def test_finishes_the_call_despite_a_none_generation_info(self) -> None:
        # Unpatched, weave's usage extraction raises on generation_info=None and
        # finish_call is never reached, leaving the trace unfinished.
        tracer = PatchedWeaveTracer()
        tracer.wc = MagicMock()
        tracer.wc.create_call.return_value = "call"

        MockLlm(response="hi").invoke("prompt", config={"callbacks": [tracer]})

        tracer.wc.finish_call.assert_called_once()
