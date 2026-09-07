# Database dialect tuning — implementation plan

Design: `docs/superpowers/specs/2026-09-07-database-dialect-tuning-design.md`

New file: `src/classiflow/database/dialects.py`. Modified: `database/base.py`.
Nothing else in `src/` changes — that is the property the plan exists to preserve.

## Global constraints

- No `Any`, no `# noqa`, no `from __future__ import annotations`, no `Object` if it's possible.
- `get_session`'s signature and behaviour are untouched: four call sites depend on it.
- The existing SQLite behaviour must be byte-identical — same pragmas, same order.
- `tests/shared/test_database_concurrency.py` must pass unchanged throughout. It is the
  regression net for this whole refactor; if it needs editing, the refactor changed
  behaviour it should not have.
- Run `uv run poe check` after each task.
- Do not stage, commit, push, or open a PR without explicit authorization.

## Task 1: Characterization test for the current engine

The concurrency tests cover *behaviour* (WAL is on, writers do not raise). Nothing
asserts *construction* — which is what this refactor moves.

**Files:** modify `tests/shared/test_database_concurrency.py`

- [ ] Assert a SQLite URL produces an engine whose `connect_args` carries
  `timeout == Settings.SQLITE_BUSY_TIMEOUT_SECONDS`.
- [ ] Assert a `postgresql+asyncpg://` URL produces an engine with no `timeout`
  connect-arg. Construction alone — the engine is never connected, so no server is
  needed.
- [ ] Both pass against the current code, before any refactor.

```bash
uv run pytest tests/shared/test_database_concurrency.py -v
```

If either fails now, the assertion is wrong about today's behaviour — fix the test, not
the production code.

**Suggested commit boundary:** characterize engine construction before refactoring it.

## Task 2: The seam

**Files:** add `src/classiflow/database/dialects.py`, add `tests/shared/test_dialects.py`

- [ ] Define `DialectTuning` as a `@runtime_checkable` Protocol with `matches(url)`,
  `connect_args()`, and `on_connect(connection)`, matching the convention in
  `domain/repositories/` (Protocol, not ABC). Type `on_connect`'s parameter as
  SQLAlchemy's `DBAPIConnection`, never `object`: it declares `.cursor()`, which is what
  removes the `# type: ignore[attr-defined]` `base.py` used to need.
- [ ] Implement `SqliteTuning`, moving `_tune_sqlite_connection`'s body verbatim —
  `busy_timeout` before `journal_mode`, and keep the comment explaining why that order
  matters.
- [ ] Implement `DefaultTuning`: empty `connect_args`, no-op `on_connect`, `matches`
  returning `True`. It is the fallback, so it must be last in the registry.
- [ ] Define `_TUNINGS: tuple[DialectTuning, ...] = (SqliteTuning(), DefaultTuning())` and
  `resolve_tuning(url) -> DialectTuning` returning the first match.
- [ ] Tests: a SQLite URL resolves to `SqliteTuning`; a PostgreSQL URL resolves to
  `DefaultTuning`; `DefaultTuning.connect_args()` is empty; `SqliteTuning` claims
  `sqlite+aiosqlite://` and not `postgresql+asyncpg://`.

At this point nothing imports the new module. That is deliberate — it lands green and
reviewable on its own.

```bash
uv run pytest tests/shared/test_dialects.py -v
```

**Suggested commit boundary:** dialect tuning seam, not yet wired.

## Task 3: Wire `get_engine` to the seam

**Files:** modify `src/classiflow/database/base.py`

- [ ] Replace the two `_is_sqlite` branches with one `resolve_tuning(url)` call.
- [ ] Register the connect listener unconditionally — `DefaultTuning.on_connect` is a
  no-op, so a non-SQLite engine gets a listener that does nothing. **Verify this against
  Task 1's PostgreSQL test**: if registering an inert listener changes observable
  construction, guard it instead and say so in a comment.
- [ ] Delete `_is_sqlite` and `_tune_sqlite_connection` from `base.py`.
- [ ] Keep `get_engine`'s `lru_cache` and signature exactly as they are.

The listener signature stays `(DBAPIConnection, ConnectionPoolEntry)` — SQLAlchemy's
`connect` event passes both positionally, so the adapter that calls `tuning.on_connect`
must accept the record and ignore it.

```bash
uv run pytest tests/shared/ -v
```

Task 1's tests and the concurrency tests must both still pass, unedited.

**Suggested commit boundary:** route engine construction through dialect tuning.

## Task 4: Prove the seam is real

A seam with one implementation is hypothetical. This task demonstrates a second without
committing the project to PostgreSQL.

**Files:** modify `tests/shared/test_dialects.py`

- [ ] Write a stub tuning that records whether `on_connect` fired and returns a
  recognizable `connect_args`.
- [ ] Assert, with the registry monkeypatched to include it, that `get_engine` passes its
  `connect_args` to `create_async_engine` and calls its `on_connect` on a real
  connection. Use a `sqlite+aiosqlite:///:memory:` URL so the test needs no file and no
  server — the stub, not SQLite, is what is under test.
- [ ] Remember `get_engine.cache_clear()` in the fixture, both before and after: the
  `lru_cache` is process-wide and will leak an engine between tests otherwise.

This is the test that would have been impossible before the refactor, and it is the
argument for having done it.

**Suggested commit boundary:** prove a second dialect needs no change to `get_engine`.

## Task 5: Document how to add a dialect

**Files:** modify `CLAUDE.md`

- [ ] Add a short section under Conventions: to support a new database, implement
  `DialectTuning` and add it to `_TUNINGS` before `DefaultTuning`; do not edit
  `get_engine`.
- [ ] State the boundary explicitly — repositories, models and `get_session` are
  dialect-agnostic and must stay that way.

Keep it to a few lines. The spec holds the reasoning; CLAUDE.md holds the rule.

**Suggested commit boundary:** document the dialect extension point.

## Final verification

```bash
uv run poe check
```

- [ ] `tests/shared/test_database_concurrency.py` passes with no edits since Task 1.
- [ ] `grep -rn "sqlite\|PRAGMA" src/classiflow --include=*.py` returns hits only in
  `dialects.py` and `settings.py`.
- [ ] `git diff` touches only `database/base.py`, `database/dialects.py`, the two test
  files, and `CLAUDE.md`.
- [ ] The app still starts and reads the existing `data/classiflow.db` — hand the command
  to the user, per the project's execution-workflow rule.

## Not in this plan

No PostgreSQL support is added. Doing so means an `asyncpg` dependency, a migration run
against a real server, and a decision about JSON vs JSONB column types — none of which
this seam requires and all of which deserve their own spec.
