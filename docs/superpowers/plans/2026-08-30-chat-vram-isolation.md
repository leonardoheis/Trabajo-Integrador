# Chat / Processing VRAM Isolation Implementation Plan

**Status: not started.**

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the chat model and the pipeline's own SLM/BERT models from being resident in VRAM
at the same time. Today the chat model (`LlamaCppChatLlm`/`get_chat_llm`) loads on first message
and is never unloaded; the pipeline only frees its own models at the end of a *successful* job.
Moving between chat and processing in either order can leave two ~5GB GGUF copies resident on an
8GB card. This plan adds an explicit unload for the chat model, evicts every model at both the
start and the guaranteed end of a pipeline job, and adds a pre-warm + cold-start indicator on the
Chat page so the added eviction doesn't turn every post-processing chat message into a multi-second
wait with no explanation.

**Architecture:** Two small backend additions (`unload_chat_llm()` next to the existing
`get_chat_llm()`; a module-level `is_pipeline_busy()` in `services/pipeline/service.py`, mirroring
that module's existing module-level `lru_cache` state rather than adding new DI-wired classes) plus
one new endpoint and two frontend changes. No existing endpoint's behavior changes.

**Tech Stack:** FastAPI, asyncio, llama.cpp (`llama-cpp-python`) (backend); React 19, TypeScript
(frontend); pytest (backend tests), Vitest + Testing Library (frontend tests).

**Spec:** `docs/superpowers/specs/2026-08-30-chat-vram-isolation-design.md`

## Global Constraints

- No change to `MAX_CONCURRENT_JOBS`, `job_semaphore`, or how pipeline jobs serialize against each
  other.
- No queuing/blocking in the warmup endpoint — it skips silently, never waits.
- No change to `LlamaCppChatLlm.astream()`'s single-chunk streaming behavior.
- No new npm dependencies.
- Follow `CLAUDE.md`: full type annotations, no `Any`, no `from __future__ import annotations`, no
  `TYPE_CHECKING` unless a real circular import forces it.

---

### Task 1: `unload_chat_llm()`

**Files:**
- Modify: `src/classiflow/knowledge/llm/llama.py`
- Create: `tests/knowledge/test_llama.py`

**Interfaces:**
- Produces: `unload_chat_llm() -> None`, consumed by Task 2's `_release_gpu_models()`.

- [ ] **Step 1: Write the failing test**

```python
from unittest.mock import MagicMock

import pytest

from classiflow.knowledge.llm.llama import get_chat_llm, unload_chat_llm


class TestUnloadChatLlm:
    def test_forces_a_reload_on_the_next_call(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_llama = MagicMock(side_effect=lambda **_kwargs: object())
        monkeypatch.setattr("classiflow.knowledge.llm.llama.Llama", mock_llama)
        get_chat_llm.cache_clear()
        try:
            get_chat_llm("fake/model.gguf", 8192)
            assert mock_llama.call_count == 1

            unload_chat_llm()
            get_chat_llm("fake/model.gguf", 8192)

            assert mock_llama.call_count == 2
        finally:
            get_chat_llm.cache_clear()
```

- [ ] **Step 2: Run the test, confirm it fails** — `unload_chat_llm` doesn't exist yet
  (`ImportError`).

  `uv run pytest tests/knowledge/test_llama.py -v`

- [ ] **Step 3: Implement `unload_chat_llm()`**

In `src/classiflow/knowledge/llm/llama.py`, add the imports and function (same shape as
`ingesta/llm_provider.py`'s `unload_slm()`):

```python
import gc

import torch
```

```python
def unload_chat_llm() -> None:
    # Same reasoning as ingesta.llm_provider.unload_slm(): drop the lru_cache's reference
    # so gc can collect the Llama instance and its __del__ frees the GGUF's CUDA context.
    get_chat_llm.cache_clear()
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
```

- [ ] **Step 4: Run the test, confirm it passes**

  `uv run pytest tests/knowledge/test_llama.py -v`

---

### Task 2: Evict all GPU models at job start and in a guaranteed `finally`

**Files:**
- Modify: `src/classiflow/services/pipeline/service.py`
- Modify: `tests/shared/test_pipeline_service_classification.py`

**Interfaces:**
- Consumes: `unload_slm`, `unload_bert` (unchanged), `unload_chat_llm` (Task 1).
- Produces: `is_pipeline_busy() -> bool` (module-level, importable), consumed by Task 3's warmup
  endpoint.

- [ ] **Step 1: Write the failing tests**

Add to `tests/shared/test_pipeline_service_classification.py` (reuses `_build_service` and
`_MINIMAL_PDF` already defined in that file):

```python
from classiflow.services.pipeline.service import is_pipeline_busy


class TestPipelineServiceGpuMemory:
    async def test_gpu_models_are_released_even_when_a_node_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        under_test = _build_service(tmp_path)

        async def _boom(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("node exploded")

        monkeypatch.setattr(under_test.service._coordinator, "ainvoke", _boom)

        calls: list[str] = []
        monkeypatch.setattr(
            "classiflow.services.pipeline.service.unload_slm", lambda: calls.append("slm")
        )
        monkeypatch.setattr(
            "classiflow.services.pipeline.service.unload_bert", lambda: calls.append("bert")
        )
        monkeypatch.setattr(
            "classiflow.services.pipeline.service.unload_chat_llm", lambda: calls.append("chat")
        )

        background_tasks = BackgroundTasks()
        await under_test.service.start(background_tasks, "ordenanza.pdf", _MINIMAL_PDF)
        with pytest.raises(RuntimeError):
            for task in background_tasks.tasks:
                await task()

        # Called once at start (nothing to evict yet, still a real call) and once in `finally`.
        assert calls.count("slm") == 2
        assert calls.count("bert") == 2
        assert calls.count("chat") == 2

    async def test_is_pipeline_busy_is_true_only_while_a_job_runs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        under_test = _build_service(tmp_path)
        assert is_pipeline_busy() is False

        observed: list[bool] = []
        original_ainvoke = under_test.service._coordinator.ainvoke

        async def _spy_ainvoke(*args: object, **kwargs: object) -> object:
            observed.append(is_pipeline_busy())
            return await original_ainvoke(*args, **kwargs)

        monkeypatch.setattr(under_test.service._coordinator, "ainvoke", _spy_ainvoke)

        background_tasks = BackgroundTasks()
        await under_test.service.start(background_tasks, "ordenanza.pdf", _MINIMAL_PDF)
        for task in background_tasks.tasks:
            await task()

        assert observed == [True]
        assert is_pipeline_busy() is False
```

- [ ] **Step 2: Run the tests, confirm they fail**

  `uv run pytest tests/shared/test_pipeline_service_classification.py -k "GpuMemory" -v`

  Expect: `ImportError` for `is_pipeline_busy`, and the raise-mid-pipeline test failing because
  today's `unload_slm`/`unload_bert` calls only happen once, at the very end, and never run at all
  when `ainvoke` raises.

- [ ] **Step 3: Implement**

In `src/classiflow/services/pipeline/service.py`, add the import and module-level state near the
top:

```python
from classiflow.knowledge.llm.llama import unload_chat_llm
```

```python
_jobs_in_flight = 0


def _begin_job() -> None:
    global _jobs_in_flight
    _jobs_in_flight += 1


def _end_job() -> None:
    global _jobs_in_flight
    _jobs_in_flight -= 1


def is_pipeline_busy() -> bool:
    return _jobs_in_flight > 0


def _release_gpu_models() -> None:
    unload_slm()
    unload_bert()
    unload_chat_llm()
```

Rewrite `_run()`'s body to wrap everything after acquiring the semaphore in `_begin_job()` /
`try` / `finally` / `_end_job()`, calling `_release_gpu_models()` at the top of the `try` and again
in the `finally`, replacing the old bare `unload_slm()` / `unload_bert()` calls at the bottom:

```python
    async def _run(self, job_id: str, filename: str, file_bytes: bytes) -> None:
        async with self._job_semaphore:
            _begin_job()
            try:
                _release_gpu_models()
                await self._job_repo.update_status(job_id, "processing")
                # ... unchanged body down through the classification branch ...
            finally:
                _release_gpu_models()
                _end_job()

            await self._broadcaster.emit(
                NodeEvent(job_id=job_id, node=_PIPELINE_NODE, status=JobStatus.DONE)
            )
```

The `DONE` broadcast stays outside the `try/finally`, unchanged — it only fires on the success
path, exactly as today.

- [ ] **Step 4: Run the tests, confirm they pass**

  `uv run pytest tests/shared/test_pipeline_service_classification.py -k "GpuMemory" -v`

- [ ] **Step 5: Run the full pipeline-service test files to confirm no regression**

  `uv run pytest tests/shared/test_pipeline_service_classification.py tests/shared/test_pipeline_service_enrichment.py tests/shared/test_pipeline_service_kb_sync.py -v`

---

### Task 3: `POST /knowledge/chat/warmup`

**Files:**
- Modify: `src/classiflow/api/routes/knowledge/endpoints.py`
- Modify: `tests/api/routes/test_knowledge.py`

**Interfaces:**
- Consumes: `get_chat_llm` (`knowledge/llm/llama.py`), `is_pipeline_busy`
  (`services/pipeline/service.py`, Task 2), `Settings.chat_model_path`, `Settings.chat_model_n_ctx`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/api/routes/test_knowledge.py`:

```python
_NO_CONTENT = 204


class TestChatWarmupEndpoint:
    def test_requires_authentication(self, client: TestClient) -> None:
        response = client.post("/knowledge/chat/warmup")

        assert response.status_code == _UNAUTHORIZED

    def test_loads_the_chat_model_when_idle(
        self, client: TestClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[tuple[str, int]] = []
        monkeypatch.setattr(
            "classiflow.api.routes.knowledge.endpoints.get_chat_llm",
            lambda model_path, n_ctx: calls.append((model_path, n_ctx)),
        )

        response = client.post("/knowledge/chat/warmup", headers=auth_headers)

        assert response.status_code == _NO_CONTENT
        assert len(calls) == 1

    def test_skips_silently_when_a_job_is_running(
        self, client: TestClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[tuple[str, int]] = []
        monkeypatch.setattr(
            "classiflow.api.routes.knowledge.endpoints.get_chat_llm",
            lambda model_path, n_ctx: calls.append((model_path, n_ctx)),
        )
        monkeypatch.setattr(
            "classiflow.api.routes.knowledge.endpoints.is_pipeline_busy", lambda: True
        )

        response = client.post("/knowledge/chat/warmup", headers=auth_headers)

        assert response.status_code == _NO_CONTENT
        assert calls == []
```

- [ ] **Step 2: Run the tests, confirm they fail**

  `uv run pytest tests/api/routes/test_knowledge.py -k Warmup -v`

- [ ] **Step 3: Implement**

In `src/classiflow/api/routes/knowledge/endpoints.py`, add imports and the route:

```python
import asyncio

from classiflow.knowledge.llm.llama import get_chat_llm
from classiflow.services.pipeline.service import is_pipeline_busy
from classiflow.settings import Settings
```

```python
@router.post("/chat/warmup", status_code=HTTPStatus.NO_CONTENT)
async def chat_warmup() -> None:
    if is_pipeline_busy():
        return
    await asyncio.to_thread(get_chat_llm, Settings.chat_model_path, Settings.chat_model_n_ctx)
```

- [ ] **Step 4: Run the tests, confirm they pass**

  `uv run pytest tests/api/routes/test_knowledge.py -v`

---

### Task 4: Frontend — fire warmup on Chat page mount

**Files:**
- Modify: `src/classiflow/frontend/src/api/knowledge.ts`
- Modify: `src/classiflow/frontend/src/pages/ChatPage.tsx`
- Create/modify: `src/classiflow/frontend/src/pages/ChatPage.test.tsx`

**Interfaces:**
- Produces: `warmupChat(): Promise<void>` in `api/knowledge.ts`.

- [ ] **Step 1: Write the failing test**

```tsx
import { render, waitFor } from "@testing-library/react";
import { vi } from "vitest";
import ChatPage from "./ChatPage";
import * as knowledgeApi from "../api/knowledge";

test("fires a warmup request once on mount", async () => {
  const warmupSpy = vi.spyOn(knowledgeApi, "warmupChat").mockResolvedValue();

  render(<ChatPage />);

  await waitFor(() => expect(warmupSpy).toHaveBeenCalledTimes(1));
});
```

- [ ] **Step 2: Run the test, confirm it fails**

  `npm --prefix src/classiflow/frontend run test -- ChatPage`

- [ ] **Step 3: Implement**

In `src/classiflow/frontend/src/api/knowledge.ts`, add:

```ts
export async function warmupChat(): Promise<void> {
  await apiFetch("/knowledge/chat/warmup", { method: "POST" });
}
```

In `src/classiflow/frontend/src/pages/ChatPage.tsx`, add an effect on mount (fire-and-forget,
errors swallowed — a failed or skipped warmup just means the first message cold-loads):

```tsx
import { useEffect, useState } from "react";
import { warmupChat } from "../api/knowledge";
```

```tsx
useEffect(() => {
  warmupChat().catch(() => {});
}, []);
```

- [ ] **Step 4: Run the test, confirm it passes**

---

### Task 5: Frontend — cold-start loading indicator

**Files:**
- Modify: `src/classiflow/frontend/src/pages/ChatPage.tsx`
- Modify: `src/classiflow/frontend/src/pages/ChatPage.test.tsx`

**Interfaces:**
- No new exports — internal component state only.

- [ ] **Step 1: Write the failing test**

Using Vitest fake timers, assert the placeholder text escalates if no `token` event has arrived
within the timeout, and clears the instant the first token arrives:

```tsx
test("shows a loading-model message if no token arrives within the timeout", async () => {
  vi.useFakeTimers();
  // ... mock fetch to return a ReadableStream that never emits, send a message ...
  vi.advanceTimersByTime(1500);
  // assert the message list shows "Cargando modelo, puede tardar unos segundos…"
  vi.useRealTimers();
});
```

(Exact mock shape follows whatever `ChatPage.test.tsx` already uses for the streaming `fetch`
mock, if Task 11 of the frontend-knowledge-base plan added one — reuse that fixture rather than
inventing a second one.)

- [ ] **Step 2: Run the test, confirm it fails**

- [ ] **Step 3: Implement**

In `ChatPage.tsx`'s send handler, start a timeout when the request begins; on timeout (only if no
token has arrived yet), set a `coldStart` flag driving the placeholder text; clear the timeout (and
the flag) the moment the first `token` event is processed:

```tsx
const _COLD_START_MS = 1500;
```

```tsx
const [coldStart, setColdStart] = useState(false);
// ... in the send handler, before awaiting the stream:
const coldStartTimer = setTimeout(() => setColdStart(true), _COLD_START_MS);
// ... on the first token event:
clearTimeout(coldStartTimer);
setColdStart(false);
```

Update the placeholder render:

```tsx
{m.content || (isStreaming && i === messages.length - 1
  ? (coldStart ? "Cargando modelo, puede tardar unos segundos…" : "…")
  : "")}
```

- [ ] **Step 4: Run the test, confirm it passes**

---

### Task 6: Whole-app verification

- [ ] Run `uv run poe check` (lint + typecheck + backend tests) — hand to the user per this repo's
  execution-workflow rule.
- [ ] Run the frontend test suite (`npm --prefix src/classiflow/frontend run test`) — same rule.
- [ ] Manual walkthrough (hand to the user, both servers running via `uv run poe serve`):
  1. Open the Chat page, send a message, confirm it answers (chat model loads on demand, or is
     already warm from the mount-time warmup).
  2. Without closing the Chat tab, start a processing job (upload a document on the Processing
     page). Confirm the job completes normally.
  3. Return to the Chat page and send another message. Confirm it still answers correctly — this
     is the scenario the whole plan exists to make safe (chat after processing, no VRAM overlap).
  4. While a processing job is running, open the Chat page in a way that fires warmup (e.g. a
     fresh page load) — confirm no error, and that the next chat message after the job finishes
     still works (this exercises the "skip silently" path).
