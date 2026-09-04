# GPU Residency Module

**Date:** 2026-09-04
**Source:** `docs/architecture-reviews/2026-09-04-model-lifecycle.html` (Candidates 1 and 2)

## Context

Five model caches are unloaded by five separate functions, imported individually by five
call sites across four modules. Every caller must know which models exist, which are safe
to evict, and what guard to check first — knowledge that has no single home.

That shape has produced three live defects:

1. **Four of five unloaders have no busy guard.** Only `unload_chat_llm()` checks whether
   its model is in use; `unload_slm`, `unload_bert`, `unload_kb_embedder` and
   `unload_duplicate_control_embedder` evict unconditionally.
2. **A TOCTOU race in the one guard that exists.** `unload_chat_llm()` calls
   `is_chat_llm_busy()`, which takes and releases the lock, and only then runs
   `evict_lru_cache()` — unlocked. A generation can begin in that window.
   `unload_chat_llm` never holds `_generation_lock`.
3. **Four call sites, four different guard policies.** `pipeline_warmup` suppresses the
   chat unload when the pipeline is busy; `auth_logout` uses the same predicate to gate a
   *different* set of models; `_release_gpu_models` checks nothing and runs
   5×(`gc.collect()` + `empty_cache()`) synchronously on the event loop, twice per job;
   `llm_judge.py:88` unloads mid-node with no guard.

Two near-identical in-flight counters compound this: `_ActiveGenerations`
(`knowledge/llm/llama.py`) and `_JobsInFlight` (`services/pipeline/service.py`) implement
the same "mutable box around a count" pattern with cross-referencing docstrings, but have
diverged — the first has a lock and underflow detection, the second has neither.

## Goals

1. One module owns GPU residency: which models exist, which are safe to evict, and when.
2. Every eviction is guarded, with no unguarded back doors.
3. Model lifecycle becomes testable without CUDA or `lru_cache` manipulation.
4. One in-flight counter implementation, used by both the generation and job counters.

## Non-goals

- Changing which models load, their paths, or their parameters.
- Changing VRAM policy — when chat evicts pipeline models and vice versa stays as it is.
- Introducing model loading into this module. It manages *residency*, not construction.
- Making eviction wait for a busy model. Blocked evictions skip and log, as today.

## Requirements

### R1. Intent-based interface

`GpuResidency` exposes exactly four verbs. Callers state what they intend to run; the
module decides what to evict.

| Verb | Meaning | Replaces |
|---|---|---|
| `reserve_for_chat()` | Chat model resident, pipeline models evicted | `chat_warmup` |
| `reserve_for_pipeline()` | Pipeline models may load, chat model evicted | `pipeline_warmup`, `_release_gpu_models` |
| `reserve_for_judge()` | Small pipeline models evicted to make room for the judge's larger GGUF | `llm_judge.py:88` |
| `release_all()` | Evict everything safe to evict | `auth_logout` |

Which five models exist, which are pipeline-owned, and which are currently busy are
implementation details. No caller imports an individual `unload_*` function.

`reserve_for_judge()` is deliberately a named verb rather than a generic
`reserve_for(model)`: it makes the one intra-pipeline swap explicit and auditable, and
keeps the module the only place any eviction happens.

### R2. Every eviction is guarded

- No model is evicted while in use. The guard is enforced inside the module, not by
  convention at call sites.
- The chat model's guard must hold `_generation_lock` across the check *and* the
  eviction, closing the TOCTOU window.
- A blocked eviction skips and logs; it never waits, never raises, and never leaves the
  caller unable to proceed.

### R3. Eviction never blocks the event loop

`gc.collect()` and `torch.cuda.empty_cache()` are blocking. Every call path runs them off
the event loop. Today `auth_logout` wraps them in `asyncio.to_thread` and
`_release_gpu_models` does not; the module makes that decision once.

### R4. One in-flight counter

A single `InFlightCounter` module with a context-manager interface, used for both:

- chat generations (currently `_ActiveGenerations`)
- pipeline jobs (currently `_JobsInFlight`)

Thread-safety and underflow detection become properties of the type. The existing public
`generation_in_flight()` already has the right shape and should be preserved as a thin
alias or migrated wholesale.

Underflow logs an error rather than silently clamping — it indicates a lifecycle defect
and must stay visible.

### R5. Testable through its interface

- An in-memory adapter satisfies the residency interface for tests, recording
  reserve/release calls.
- Tests assert on residency behaviour without monkeypatching `Llama`, without calling
  `get_chat_llm.cache_clear()`, and without importing private module globals.
- The existing hand-written `cache_clear()` try/finally brackets in
  `tests/knowledge/test_llama.py` (repeated three times, no fixture) are removed or
  replaced by a fixture.

### R6. Preserve current VRAM policy exactly

This is a restructuring, not a behaviour change. After the refactor:

- Opening Chat evicts SLM and BETO, then loads the chat model.
- Opening Processing/Classification evicts the chat model.
- A pipeline job evicts all five at start and at finish.
- Logout evicts the chat model always, and the four pipeline models when idle.
- The judge evicts the SLM before loading its own model.

Any deviation is a bug, not an improvement, and must be called out rather than absorbed.

## Acceptance criteria

- No module outside `GpuResidency` imports `unload_slm`, `unload_bert`,
  `unload_chat_llm`, `unload_kb_embedder` or `unload_duplicate_control_embedder`.
- Evicting the chat model while a generation is in flight is impossible, including under
  the interleaving that defeats the current check-then-evict sequence.
- `_ActiveGenerations` and `_JobsInFlight` no longer exist as separate implementations.
- Both counters detect underflow and log it.
- A test suite for residency runs without CUDA and without loading any model.
- Ruff, strict mypy, backend tests and the frontend build pass.

## Required regression tests

1. Reserving for chat while a pipeline job is running does not evict pipeline models.
2. Reserving for pipeline while a chat generation is in flight does not evict the chat
   model.
3. A concurrent begin-generation racing an evict cannot produce an eviction — the lock
   covers check and evict together.
4. `release_all()` during an active generation evicts the pipeline models but not the
   chat model.
5. The counter releases exactly once on each of: normal completion, provider failure,
   consumer abandonment.
6. Counter underflow is logged and clamped to zero rather than going negative.
7. Every verb runs its blocking work off the event loop.

## Validation commands

```bash
uv run poe lint
uv run poe typecheck
uv run poe test
cd src/classiflow/frontend
npm run build
npm run test -- --run
```

## Notes

- **Not in scope, but adjacent:** `docs/architecture-reviews/2026-09-04-model-lifecycle.html`
  also raises the three-layer `aclosing` chain (Candidate 3) and call-time `Settings`
  reads (Candidate 4). Neither is addressed here. Candidate 3's cheap half — an
  end-to-end invariant test for stream abandonment — is worth doing next.
- **Two `get_sentence_model` functions exist** in different modules
  (`ingesta/nodes/node4_duplicate_control.py` and `knowledge/embeddings/embedder.py`),
  loading different models with different arities. The residency module must not conflate
  them.
- **"GPU residency" is a new domain term.** The project has no `CONTEXT.md`; if one is
  created, this belongs in it.
