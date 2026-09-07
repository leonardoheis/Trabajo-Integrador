# GPU Residency Module — Implementation Plan

> **For implementers:** Work task-by-task and keep the checkboxes current. Write the
> regression test first for each behavioural change. Suggested commit boundaries are
> documented, but no commit, push, or PR is authorized by this plan.

**Goal:** Give GPU residency one owner with a four-verb interface, close the TOCTOU race,
guard every eviction, and unify the two in-flight counters — without changing VRAM policy.

**Architecture:** A `GpuResidency` module holds a registry of the five model caches, each
paired with the guard that says whether it is safe to evict. Callers state intent
(`reserve_for_chat`, `reserve_for_pipeline`, `reserve_for_judge`, `release_all`); the
module resolves that to a set of evictions, checks each guard while holding the relevant
lock, and runs the blocking eviction off the event loop. An `InFlightCounter` module backs
both the chat-generation and pipeline-job counters.

**Tech stack:** Python 3.10, FastAPI, dependency-injector, pytest.

**Spec:** `docs/superpowers/specs/2026-09-04-gpu-residency-module.md`
**Review:** `docs/architecture-reviews/2026-09-04-model-lifecycle.html`

## Global constraints

- VRAM policy must not change. Any behavioural difference is a bug (spec R6).
- Keep comments to one or two lines explaining an invariant or non-obvious reason.
- No `Any`, no `# noqa`, no `from __future__ import annotations`.
- Do not stage, commit, push, or create a PR without new explicit user authorization.
- Run `uv run poe check` after each task.

## Task 1: Extract `InFlightCounter`

**Files:**

- Add: `src/classiflow/model_lifecycle/counter.py`
- Add: `tests/model_lifecycle/test_counter.py`
- Modify: `src/classiflow/knowledge/llm/llama.py`
- Modify: `src/classiflow/services/pipeline/service.py`
- Modify: `tests/knowledge/test_llama.py`

- [x] Write failing tests: increment/decrement, `is_busy()`, context-manager release on
  normal exit and on exception, underflow logs an error and clamps to zero, concurrent
  increments from two threads land correctly.
- [x] Implement `InFlightCounter` with a `threading.Lock`, an `in_flight()` context
  manager, and `is_busy()`. Underflow logs `logger.error` — never silently clamps.
- [x] Replace `_ActiveGenerations` in `llama.py` with an instance. Keep the public
  `generation_in_flight()` name as a thin alias so existing imports keep working.
- [x] Replace `_JobsInFlight` in `services/pipeline/service.py` with an instance. Note
  this *adds* a lock and underflow detection the pipeline counter did not have — that is
  the point.
- [x] Keep `is_pipeline_busy()` and `is_chat_llm_busy()` as module-level functions; they
  are the guard predicates the residency module will call.

```bash
uv run pytest tests/model_lifecycle/test_counter.py tests/knowledge/test_llama.py -v
```

**Suggested commit boundary:** unify the in-flight counters.

## Task 2: Lock the residency contract with failing tests

**Files:**

- Add: `tests/model_lifecycle/test_gpu_residency.py`

Write these before any residency code exists. All should fail.

- [x] `reserve_for_chat()` while a pipeline job is in flight does not evict pipeline
  models.
- [x] `reserve_for_pipeline()` while a chat generation is in flight does not evict the
  chat model.
- [x] `release_all()` during an active generation evicts pipeline models but not chat.
- [x] `reserve_for_judge()` evicts the SLM and nothing else.
- [x] **The race:** a thread that begins a generation between the guard check and the
  eviction cannot cause the chat model to be evicted. Drive it with a fake evictor whose
  `cache_clear` blocks on an event, so the interleaving is deterministic rather than
  timing-dependent.
- [x] Every verb runs its blocking work off the event loop — assert via a fake evictor
  that records its thread ident.

```bash
uv run pytest tests/model_lifecycle/test_gpu_residency.py -v
```

**Suggested commit boundary:** tests describing the residency contract.

## Task 3: Build `GpuResidency`

**Files:**

- Add: `src/classiflow/model_lifecycle/residency.py`
- Add: `src/classiflow/model_lifecycle/__init__.py`
- Modify: `src/classiflow/model_cache.py` (may be absorbed — see below)

- [x] Define a `ManagedModel` record pairing a cache-clearing callable with an optional
  guard predicate and a human-readable name for logging.
- [x] Build the registry of five: chat LLM (guard: `is_chat_llm_busy`), SLM, BETO,
  KB embedder, duplicate-control embedder (no guards today — they are only ever evicted
  when the pipeline is idle, which the verbs enforce).
- [x] Implement the four verbs. Each resolves to a set of models, then evicts each one
  whose guard permits.
- [x] **Close the TOCTOU race:** for the chat model, hold `_generation_lock` across both
  the guard check and `evict_lru_cache`. This requires moving or exposing that lock —
  decide whether it lives in `llama.py` and is passed in, or moves into the counter.
- [x] Every verb is `async` and wraps eviction in `asyncio.to_thread`.
- [x] Log every outcome: evicted, skipped-busy, or not-loaded.
- [x] Decide `model_cache.py`'s fate: it is a 19-line shallow module whose only caller
  becomes this one. Either absorb `evict_lru_cache` into `residency.py` or keep it as the
  low-level primitive. Prefer absorbing unless a second caller exists.
  - Decision: **kept.** It still has five callers (the `unload_*` functions), plus its own
    test. `GpuResidency` calls those functions rather than `evict_lru_cache` directly, so
    absorbing it would mean inlining `gc.collect()`/`empty_cache()` into five places.
    Revisit after Task 5, when the `unload_*` surface is folded into the registry.

```bash
uv run pytest tests/model_lifecycle -v
```

**Suggested commit boundary:** add the GPU residency module.

## Task 4: Migrate call sites

**Files:**

- Modify: `src/classiflow/api/routes/auth/endpoints.py`
- Modify: `src/classiflow/api/routes/pipeline/endpoints.py`
- Modify: `src/classiflow/api/routes/knowledge/endpoints.py`
- Modify: `src/classiflow/services/pipeline/service.py`
- Modify: `src/classiflow/classification/nodes/llm_judge.py`
- Modify: `src/classiflow/injections/production.py`, `src/classiflow/api/dependencies.py`
- Modify: `tests/api/routes/test_auth_oauth.py`

Migrate one at a time, running the suite between each.

- [x] `auth_logout` → `release_all()`. Removes five imports and the hand-rolled loop.
- [x] `pipeline_warmup` → `reserve_for_pipeline()`.
- [x] `chat_warmup` → `reserve_for_chat()`. Note this verb only *evicts*; the eager
  `get_chat_llm(...)` load stays in the route, since residency does not construct models.
- [x] `_release_gpu_models` → `await reserve_for_pipeline()`. **This changes it from sync
  to async** — verify both call sites in `_run` still work, and that the `finally` at the
  end of the job awaits correctly.
  - Decision: **left unconditional.** The job owns these models and clears them for its
    own use; `reserve_for_pipeline()` evicts only the chat model, so routing through it
    would stop freeing the four the job actually needs. Preserves R6.
- [x] `llm_judge.py:88` → `reserve_for_judge()`. This node is sync and runs inside
  LangGraph; if awaiting is not possible there, note the constraint and either provide a
  sync variant or keep the direct call with a comment pointing at this decision.
  - Restructured: the eviction moved from the sync `_take_chain()` up into the async
    `run()`, guarded by `if self.judge_chain is None` so it still only fires on the
    fallback path. Two new tests pin that conditional.
- [x] Wire `GpuResidency` through the DI container so tests can substitute an in-memory
  adapter.
- [x] Update `test_auth_oauth.py`, which currently monkeypatches
  `classiflow.api.routes.auth.endpoints.unload_chat_llm` — that name will no longer exist.

```bash
uv run poe test
```

**Suggested commit boundary:** route every eviction through GpuResidency.

## Task 5: Remove the old surface

**Files:**

- Modify: the five modules defining `unload_*`
- Modify: `tests/knowledge/test_llama.py`

- [x] Make the five `unload_*` functions private (`_unload_*`) or fold them into the
  registry entirely. Nothing outside `model_lifecycle/` should import them.
  - Decision: **names kept public.** No `src/` module calls them any more -- every
    eviction routes through GpuResidency, which is the goal. They stay public because
    each is unit-tested by its own module's tests (`test_node4.py`, `test_embedder.py`,
    `test_llama.py`) as the documented way to clear that cache; renaming would force
    tests to import private names.
- [x] Grep to confirm: `grep -rn "unload_" --include=*.py src/ | grep -v model_lifecycle`
  should return only comments. Verified: only definitions and comments remain -- zero
  call sites.
- [x] Remove the three hand-written `get_chat_llm.cache_clear()` try/finally brackets in
  `tests/knowledge/test_llama.py`; replace with a fixture if the tests still need cache
  isolation. Replaced with an autouse `_isolated_chat_llm_cache` fixture on the class.
- [x] Confirm `tests/test_model_cache.py` still applies, or move it under
  `tests/model_lifecycle/`. Left in place: `model_cache.py` survives with five callers
  and is a different module from `model_lifecycle/`.

**Suggested commit boundary:** remove the scattered unload surface.

## Task 6: Verify VRAM policy is unchanged

Spec R6 says this is a restructuring. Prove it.

- [x] Start the app. Watch `nvidia-smi` while exercising each path:
  - Open Chat → chat model loads, pipeline models gone
  - Open Processing → chat model freed
  - Run a job → all five evicted at start and finish
  - Sign out → chat freed; pipeline models freed only when idle
  - Trigger a judge-tier classification → SLM freed before the judge model loads
- [x] Confirm the logs name each eviction and its outcome.
- [x] Start a chat, navigate away mid-answer, then sign out — the counter must release and
  the model must actually evict (the bug fixed earlier this session; this proves the
  refactor preserves it).

**Suggested commit boundary:** none — verification only.

## Final verification

- [x] `uv run poe check` — lint, typecheck, coverage, all pre-commit hooks.
- [x] `cd src/classiflow/frontend && npm run build && npm run test -- --run`.
- [x] Review `git diff origin/main...HEAD` for unrelated changes.
- [x] Confirm no `data/classiflow.db` or generated report churn in the diff.

## Recommended execution order

```text
Task 1 counters
  -> Task 2 residency contract tests
  -> Task 3 residency implementation
  -> Task 4 migrate call sites (one at a time)
  -> Task 5 remove old surface
  -> Task 6 manual VRAM verification
  -> final verification
```

Tasks 1 and 2 are independent and may be done in either order. Tasks 3-5 are strictly
sequential — each depends on the previous one landing.

## Open questions for the implementer

1. **Where does `_generation_lock` live after this?** Task 3 needs it held across
   check-and-evict. Options: keep it in `llama.py` and pass it to the registry entry, or
   move it into `InFlightCounter` so the counter owns both the count and the mutex.
2. **Can `llm_judge` await?** It runs inside a synchronous LangGraph node. If not, the
   module needs a documented sync entry point for that one case.
3. **Does `model_cache.py` survive?** It has one caller after this change. Absorbing it
   makes the residency module the single owner; keeping it preserves a testable primitive.
