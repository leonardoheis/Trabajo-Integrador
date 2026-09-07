# Database dialect tuning — implementation plan

Design: `docs/superpowers/specs/2026-09-07-database-dialect-tuning-design.md`

New package: `src/classiflow/database/dialects/`, one file per engine. Modified:
`database/base.py`. Nothing else in `src/` changes — that is the property the plan exists
to preserve.

```
database/dialects/
├── __init__.py    re-exports DialectTuning, resolve_tuning
├── protocol.py    DialectTuning
├── registry.py    _TUNINGS, resolve_tuning, DefaultTuning
└── sqlite.py      SqliteTuning
```

## Global constraints

- No `Any`, no `# noqa`, no `from __future__ import annotations`, no `Object` if it's possible.
- `get_session`'s signature and behaviour are untouched: four call sites depend on it.
- The existing SQLite behaviour must be byte-identical — same pragmas, same order.
- `tests/shared/test_database_concurrency.py` must pass unchanged throughout. It is the
  regression net for this whole refactor; if it needs editing, the refactor changed
  behaviour it should not have.
- Run `uv run poe check` after each task.
- Do not stage, commit, push, or open a PR without explicit authorization.

## Task 1: ~~Characterization test for the current engine~~ — dropped

The original task asked for two assertions about engine *construction*. Both were
unworkable, and probing the library before writing code is what surfaced it:

1. **`connect_args` is not publicly readable off an engine.** SQLAlchemy merges it into a
   closure cell (`pool._creator.__closure__[1].cell_contents`). A test reaching in there
   is coupled to private internals and breaks on a patch release.
2. **A `postgresql+asyncpg://` URL cannot be constructed here.** `create_async_engine`
   imports the driver eagerly and `asyncpg` is not a project dependency. The plan claimed
   "the engine is never connected, so no server is needed" — true of the server, false of
   the driver.

Adding `asyncpg` purely to assert a negative was rejected: this spec scopes PostgreSQL
out, and `DefaultTuning`'s unit test covers the same ground without a dependency.

The intent — pin what reaches the engine before moving it — is served better at the seam
itself, where `connect_args()` is a plain function call needing no engine, no driver and
no server. Those assertions live in Task 2.

`TestEngineConfiguration` in `tests/shared/test_database_concurrency.py` already pins the
end-to-end behaviour (WAL on, busy_timeout applied) and is the regression net for the
whole refactor. It must pass unedited throughout.

## Task 2: The seam

**Files:** add `src/classiflow/database/dialects/{__init__,protocol,registry,sqlite}.py`,
add `tests/shared/test_dialects.py`

- [x] `protocol.py`: define `DialectTuning` as a `@runtime_checkable` Protocol with
  `matches(url)`, `connect_args()`, and `on_connect(connection)`, matching the convention
  in `domain/repositories/` (Protocol, not ABC). `connect_args()` returns
  `dict[str, object]` — the values are forwarded straight to SQLAlchemy and differ per
  engine, so this is the one signature where `object` is the honest type rather than a
  shortcut.
  **Changed during implementation:** the plan said to type `on_connect`'s parameter as
  SQLAlchemy's `DBAPIConnection`. That type declares `cursor(*args: Any, **kwargs: Any)`,
  so anything satisfying it — a test double included — must admit `Any`, which the project
  forbids. `protocol.py` defines a narrower `TuningConnection` instead: a tuning only opens
  a cursor, runs statements and closes it. Still no `object`, still no `type: ignore`.
- [x] `sqlite.py`: implement `SqliteTuning`, moving `_tune_sqlite_connection`'s body
  verbatim — `busy_timeout` before `journal_mode`, keeping the comment that explains why
  the order matters. This file is the only place in `src/` that may mention SQLite.
- [x] `registry.py`: implement `DefaultTuning` (empty `connect_args`, no-op `on_connect`,
  `matches` returning `True`), then
  `TUNINGS: tuple[DialectTuning, ...] = (SqliteTuning(), DefaultTuning())` and
  `resolve_tuning(url) -> DialectTuning` returning the first match. `DefaultTuning` lives
  here rather than in its own file: it is the registry's terminator, not an engine.
  **Changed during implementation:** every tuning method is a `@staticmethod`. Neither
  class holds state, so ruff's PLR6301 was correct that `self` is unused; unused Protocol
  parameters take the `_url` / `_connection` underscore, matching `_record` in `base.py`.
  A per-file-ignore for PLR6301/ARG002 was added first and then reverted — widening the
  lint config to avoid restructuring is the thing the project's no-suppression rule
  exists to prevent.
- [x] `__init__.py`: re-export `DialectTuning`, `TUNINGS`, `resolve_tuning` and the two
  tuning classes with `__all__`, so callers import from `classiflow.database.dialects`.
  Re-exports only — the project's `__init__.py` rule (ruff RUF067) forbids executable
  statements, which is also why the registry is a tuple in `registry.py` and not built
  here.
  **Changed during implementation:** `_TUNINGS` became public `TUNINGS`. Ruff's PLC2701
  flagged the test importing a private name across modules, and it was right — the
  registry is part of the seam's contract, not an implementation detail.
- [x] Tests: a SQLite URL resolves to `SqliteTuning`; a PostgreSQL URL resolves to
  `DefaultTuning`; `DefaultTuning.connect_args()` is empty; `SqliteTuning` claims
  `sqlite+aiosqlite://` and not `postgresql+asyncpg://`; `DefaultTuning` is last in
  `TUNINGS` (it matches everything, so anything after it is unreachable).
- [x] Tests, absorbed from the dropped Task 1: `SqliteTuning.connect_args()` is exactly
  `{"timeout": Settings.SQLITE_BUSY_TIMEOUT_SECONDS}`, and `on_connect` issues
  `busy_timeout` before `journal_mode` against a recording stub cursor. These are the
  construction assertions the engine could not expose — here they need no engine, no
  driver and no server.

At this point nothing imports the new package. That is deliberate — it lands green and
reviewable on its own.

```bash
uv run pytest tests/shared/test_dialects.py -v
```

**Suggested commit boundary:** dialect tuning seam, not yet wired.

## Task 3: Wire `get_engine` to the seam

**Files:** modify `src/classiflow/database/base.py`

- [x] Replace the two `_is_sqlite` branches with one `resolve_tuning(url)` call.
- [x] Register the connect listener unconditionally — `DefaultTuning.on_connect` is a
  no-op, so a non-SQLite engine gets a listener that does nothing. Confirmed harmless by
  the full suite; no guard needed.
- [x] Delete `_is_sqlite` and `_tune_sqlite_connection` from `base.py`.
- [x] Keep `get_engine`'s `lru_cache` and signature exactly as they are.

The listener signature stays `(DBAPIConnection, ConnectionPoolEntry)` — SQLAlchemy's
`connect` event passes both positionally, so the adapter that calls `tuning.on_connect`
must accept the record and ignore it.

```bash
uv run pytest tests/shared/ -v
```

The concurrency tests must still pass, unedited. They did.

**Suggested commit boundary:** route engine construction through dialect tuning.

## Task 4: Prove the seam is real

A seam with one implementation is hypothetical. This task demonstrates a second without
committing the project to PostgreSQL.

**Files:** modify `tests/shared/test_dialects.py`

- [x] Write a stub tuning that records whether `on_connect` fired and returns a
  recognizable `connect_args`. It lives in the test file, not the package: it proves the
  Protocol is satisfiable from outside, which a sibling module would not.
- [x] Assert, with `registry.TUNINGS` monkeypatched to include it, that `get_engine`
  passes its `connect_args` to `create_async_engine` and calls its `on_connect` on a real
  connection. Use a `sqlite+aiosqlite:///:memory:` URL so the test needs no file and no
  server — the stub, not SQLite, is what is under test.
- [x] Assert the stub satisfies `isinstance(stub, DialectTuning)` — the payoff of
  `@runtime_checkable`, and a check that the Protocol has not drifted from what an
  implementer must provide.
- [x] Remember `get_engine.cache_clear()` in the fixture, both before and after: the
  `lru_cache` is process-wide and will leak an engine between tests otherwise.

This is the test that would have been impossible before the refactor, and it is the
argument for having done it.

**Suggested commit boundary:** prove a second dialect needs no change to `get_engine`.

## Task 5: Document how to add a dialect

**Files:** modify `CLAUDE.md`

- [x] Add a short section under Conventions naming the three steps to support a new
  database: add `dialects/<engine>.py` with a `DialectTuning` implementation, import it in
  `registry.py`, and add it to `TUNINGS` before `DefaultTuning` (which matches
  everything, so anything after it is dead). `get_engine` is not edited.
- [x] State the boundary explicitly — repositories, models and `get_session` are
  dialect-agnostic and must stay that way. Engine-construction knobs belong in a tuning;
  anything else does not.

Keep it to a few lines. The spec holds the reasoning; CLAUDE.md holds the rule.

**Suggested commit boundary:** document the dialect extension point.

## Final verification

```bash
uv run poe check
```

- [x] `uv run poe check` green: 643 passed, 95% coverage, all 12 pre-commit hooks pass.
- [x] `tests/shared/test_database_concurrency.py` passes with no edits.
- [x] `grep -rn "sqlite\|PRAGMA" src/classiflow --include=*.py` returns one hit outside
  `database/dialects/` — the default URL in `settings.py`. The specialization did not leak.
- [x] `git status --short` touches only `database/base.py`, the four files under
  `database/dialects/`, `tests/shared/test_dialects.py`, `CLAUDE.md`, and these documents.
- [x] Task 4's test verified by sabotage: removing the `event.listen` call in `base.py`
  makes it fail with `assert 0 == 1`; restoring it passes. A test that cannot fail proves
  nothing.
- [x] **For the user:** start the app and confirm it reads the existing
  `data/classiflow.db`, and that `sqlite3 data/classiflow.db "PRAGMA journal_mode;"` still
  reports `wal`. Per the project's execution-workflow rule, the agent does not run it.

## Not in this plan

No PostgreSQL support is added. Doing so means an `asyncpg` dependency, a migration run
against a real server, and a decision about JSON vs JSONB column types — none of which
this seam requires and all of which deserve their own spec.
