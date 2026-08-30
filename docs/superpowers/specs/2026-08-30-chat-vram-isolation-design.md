# Chat / Processing VRAM Isolation — Design Spec

## Status

Draft — pending user review.

## Context

The pipeline (node2/node3/enrichment/classification/LLM Judge) and the KB chat agent both run
local GGUF models via llama.cpp, but through two independent, unrelated caches:

- `ingesta/llm_provider.py`'s `get_llm_langchain()` — `@lru_cache(maxsize=4)`, cleared by
  `unload_slm()`. `PipelineService._run()` (`src/classiflow/services/pipeline/service.py:165-168`)
  calls `unload_slm()` **and** `unload_bert()` once, at the very end of a successful job.
- `knowledge/llm/llama.py`'s `get_chat_llm()` — `@lru_cache(maxsize=2)`, and until this spec, never
  cleared by anything. Once a chat message is sent, the chat model's GGUF handle (same
  `Meta-Llama-3.1-8B-Instruct` weights as the pipeline, by default, at a different `n_ctx`) stays
  resident in VRAM for the life of the process.

`settings.py` documents a hard VRAM budget (`MAX_CONCURRENT_JOBS = 1`, with an explicit comment
that two resident copies of the model overflow an 8GB card). That budget only accounts for
pipeline-vs-pipeline overlap. It does not account for chat, which sits outside it entirely. Two
concrete gaps fall out of this:

1. **No eviction at job start.** `_run()` only frees VRAM at the *end* of a job. If the chat model
   is already resident (because the user chatted first) and a processing job starts, the job's own
   SLM/BERT loads happen on top of it — the exact double-model condition `MAX_CONCURRENT_JOBS=1`
   was set up to avoid, triggered from the other direction.
2. **No `finally`.** The existing `unload_slm()`/`unload_bert()` calls sit at the bottom of `_run()`
   after every pipeline stage. If any node raises before reaching that line, cleanup never runs,
   and the loaded models stay resident until some *other* job happens to reach its own cleanup.

This spec closes both gaps and adds the missing eviction path for the chat model, plus a
pre-warming mechanism so paying that eviction back doesn't make every post-processing chat message
eat a multi-second cold load.

## Decisions

### 1. `unload_chat_llm()`

**File:** `src/classiflow/knowledge/llm/llama.py`

Added next to `get_chat_llm()`, same shape as `ingesta/llm_provider.py`'s `unload_slm()`:

```python
def unload_chat_llm() -> None:
    # Same reasoning as ingesta.llm_provider.unload_slm(): drop the lru_cache's reference
    # so gc can collect the Llama instance and its __del__ frees the GGUF's CUDA context.
    get_chat_llm.cache_clear()
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
```

Lives here rather than in `ingesta/llm_provider.py`: `knowledge/` already depends one-way on
`ingesta/` (for `n_gpu_layers`); putting a chat-specific unload function in `ingesta/` would need
`ingesta/llm_provider.py` to import from `knowledge/llm/llama.py`, reversing that dependency.
`PipelineService` already imports from `knowledge/` (`IndexerService`), so importing
`unload_chat_llm` from there is consistent with the existing direction.

### 2. `PipelineService._run()` evicts at start and in a `finally`

**File:** `src/classiflow/services/pipeline/service.py`

A private module helper replaces the two bare calls at the bottom of `_run()`:

```python
def _release_gpu_models() -> None:
    unload_slm()
    unload_bert()
    unload_chat_llm()
```

`_run()` calls it once immediately after acquiring `job_semaphore` (closing gap 1 — evicts
whatever chat left behind before this job loads its own models) and once more in a `finally`
wrapped around the whole job body (closing gap 2 — guaranteed even if a node raises):

```python
async def _run(self, job_id: str, filename: str, file_bytes: bytes) -> None:
    async with self._job_semaphore:
        _begin_job()
        try:
            _release_gpu_models()
            await self._job_repo.update_status(job_id, "processing")
            ...  # unchanged body
        finally:
            _release_gpu_models()
            _end_job()

        await self._broadcaster.emit(
            NodeEvent(job_id=job_id, node=_PIPELINE_NODE, status=JobStatus.DONE)
        )
```

The `DONE` broadcast stays outside the `try/finally`, unchanged from today: it only fires on the
success path, exactly as it does now. This spec only guarantees VRAM cleanup, not a change to
error-signaling behavior.

Calling `_release_gpu_models()` twice per job (start and end) is deliberately redundant on the
common case — the second job in a row has nothing left for the start-of-job call to evict. All
three underlying calls are cheap no-ops when their caches are already empty (`cache_clear()` on an
empty `lru_cache`, `gc.collect()`, a no-op `torch.cuda.empty_cache()`), so the redundancy costs
nothing measurable and buys the safety net for the crash case gap 2 was about.

### 3. Exposing "a job is running" without touching semaphore internals

**File:** `src/classiflow/services/pipeline/service.py`

`PipelineService` itself is **not** a Singleton — `injections/production.py`'s comment block
explains it's built fresh per request from `api/dependencies.py`'s `get_pipeline_service`, sharing
the container's `job_semaphore` Singleton via constructor injection. An instance attribute on
`PipelineService` would not be visible to a different request's freshly-built instance, and
`asyncio.Semaphore` has no public `.locked()` (unlike `asyncio.Lock`) to read externally.

Module-level state, mirroring `get_llm_langchain`'s own module-level `lru_cache`:

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
```

No lock needed: asyncio is single-threaded and every mutation happens on the event loop between
`await` points. `_begin_job()`/`_end_job()` bracket the same region as `_release_gpu_models()`
above (see Decision 2's snippet) — this is the counterpart to Decision 4's need for a busy check
that any other request can read without reaching into `job_semaphore`.

### 4. `POST /knowledge/chat/warmup`

**File:** `src/classiflow/api/routes/knowledge/endpoints.py`

```python
@router.post("/chat/warmup", status_code=HTTPStatus.NO_CONTENT)
async def chat_warmup() -> None:
    if is_pipeline_busy():
        return
    await asyncio.to_thread(get_chat_llm, Settings.chat_model_path, Settings.chat_model_n_ctx)
```

Same router, so it inherits the existing `dependencies=[Depends(get_current_user)]` auth gate — no
new auth wiring. Skips silently (no error, no queuing) when a pipeline job is in flight: warming
the chat model mid-job would recreate the exact double-model condition this spec exists to prevent,
and there is nothing useful to do about it beyond not making it worse — the next chat message just
cold-loads once the job's own `finally` has freed VRAM.

`asyncio.to_thread` matches the existing pattern in `LlamaCppChatLlm.astream()`/`_complete()`: the
`Llama(...)` constructor blocks the event loop for the whole load, same as inference does.

### 5. Frontend: fire warmup on Chat page mount

**File:** `src/classiflow/frontend/src/pages/ChatPage.tsx`, `src/classiflow/frontend/src/api/knowledge.ts`

```ts
export async function warmupChat(): Promise<void> {
  await apiFetch("/knowledge/chat/warmup", { method: "POST" });
}
```

```ts
useEffect(() => {
  warmupChat().catch(() => {});
}, []);
```

Fire-and-forget: no loading state tied to this call, no retry, errors swallowed. A failed or
skipped warmup just means the first message cold-loads instead of being pre-warmed — not a broken
page.

### 6. Frontend: cold-start loading indicator, timeout-based

**File:** `src/classiflow/frontend/src/pages/ChatPage.tsx`

The indicator does **not** track whether warmup itself completed — a skipped warmup (pipeline was
busy) looks identical, from the client's perspective, to a successful one, and either way the only
thing that actually matters to the user is "how long has this message been waiting with no
tokens yet." So: when sending a message, start a timer; if no `token` SSE event has arrived within
`~1500ms`, swap the placeholder from the existing generic `"…"` to a clearer
`"Cargando modelo, puede tardar unos segundos…"`; clear the timer the moment the first token
arrives (cold or not, the escalated text is replaced the instant real content starts streaming).

This covers all three cases uniformly: warmup succeeded and this message is fast anyway (timer
never fires), warmup was skipped because a job was running, and warmup hasn't finished yet because
the user typed fast — no explicit "is the model warm" state needs to be threaded from the backend.

## Non-Goals

- **No change to `MAX_CONCURRENT_JOBS` or `job_semaphore`'s concurrency control.** This spec adds a
  parallel, simpler busy-check for the warmup endpoint; it does not touch how pipeline jobs
  serialize against each other.
- **No queuing or blocking of a warmup request.** It is a pure skip, never a wait.
- **No token-level streaming change** to `LlamaCppChatLlm.astream()` — it still yields the whole
  completion as one chunk, same as today.
- **No "which documents are embedded" table marker, no dark-theme redesign.** Both were raised in
  the same conversation as this spec but are explicitly out of scope here — separate future spec.

## Testing

- **Backend:**
  - `unload_chat_llm()` clears `get_chat_llm`'s cache (mirrors the existing `unload_slm` test in
    `tests/ingesta/test_llm_provider.py`, if one exists, else a new equivalent in a
    `tests/knowledge/test_llama.py`).
  - `PipelineService._run()`: a case where a node raises mid-pipeline (patching the coordinator's
    `ainvoke`) still results in `unload_slm`/`unload_bert`/`unload_chat_llm` all being called
    (`finally` guarantee) — extends `tests/shared/test_pipeline_service_*.py`.
  - `is_pipeline_busy()` reflects `True` while `_run()`'s job body is executing and `False` before/
    after — a test that runs `_run()` concurrently with a busy-check assertion mid-flight.
  - `POST /knowledge/chat/warmup`: returns `204` and calls `get_chat_llm` when idle; returns `204`
    without calling `get_chat_llm` when `is_pipeline_busy()` is `True` (mocked) — extends
    `tests/api/routes/test_knowledge.py`.
- **Frontend:** a `ChatPage` test asserting `warmupChat` fires once on mount (mocking `apiFetch`),
  and a fake-timers test for the placeholder-text escalation after the timeout with no token event.
- Run `uv run poe check` per the project's standard gate — hand to the user rather than running
  directly, per this repo's execution-workflow rule.
