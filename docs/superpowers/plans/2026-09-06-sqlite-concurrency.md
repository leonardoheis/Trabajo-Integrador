# SQLite concurrency — implementation plan

Design: `docs/superpowers/specs/2026-09-06-sqlite-concurrency-design.md`

All production changes land in `src/classiflow/database/base.py`. Branch:
`fix/sqlite-concurrency`, cut from `main`.

---

## Task 1: Failing test for concurrent writes

- [ ] **Step 1: Write the test**

New file `tests/shared/test_database_concurrency.py`. It must use a real file database —
`:memory:` has no file lock to contend over, so it cannot reproduce the bug.

```python
"""Concurrent-writer behaviour of the configured engine."""

import asyncio
import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import text

from classiflow.database.base import Base, _get_engine
from classiflow.database.models import Job
from classiflow.settings import Settings

pytestmark = pytest.mark.anyio


@pytest.fixture
def database_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    url = f"sqlite+aiosqlite:///{(tmp_path / 'concurrency.db').as_posix()}"
    monkeypatch.setattr(Settings, "DATABASE_URL", url)
    _get_engine.cache_clear()
    yield url
    _get_engine.cache_clear()
```

Two tests:

1. `test_concurrent_inserts_do_not_raise_database_is_locked` — hold an open write
   transaction on one connection, then issue an INSERT from a second, and assert it
   succeeds rather than raising `OperationalError`. Without the busy timeout the second
   writer raises immediately; with it, it waits for the first to commit.
2. `test_journal_mode_is_wal` — `SELECT * FROM pragma_journal_mode` returns `wal`.

- [ ] **Step 2: Run it, confirm both fail**

```bash
uv run pytest tests/shared/test_database_concurrency.py -v
```

Expected: test 1 raises `OperationalError: database is locked`, test 2 reports `delete`.
If test 1 passes before the fix, the concurrency it sets up is not real — fix the test
before touching production code.

---

## Task 2: Busy timeout

- [ ] **Step 1: Add the connect-arg**

In `src/classiflow/database/base.py`, replace `_get_engine`:

```python
_SQLITE_BUSY_TIMEOUT_SECONDS = 30


def _is_sqlite(url: str) -> bool:
    return url.startswith("sqlite")


@lru_cache(maxsize=1)
def _get_engine() -> AsyncEngine:
    url = Settings.DATABASE_URL
    # SQLite defaults busy_timeout to 0: a writer that finds the file locked raises
    # instead of waiting. Bulk ingest writes jobs while background jobs write steps.
    connect_args = {"timeout": _SQLITE_BUSY_TIMEOUT_SECONDS} if _is_sqlite(url) else {}
    return create_async_engine(url, echo=False, connect_args=connect_args)
```

- [ ] **Step 2: Test 1 passes, test 2 still fails**

---

## Task 3: WAL journal mode

- [ ] **Step 1: Add the connect listener**

WAL cannot be set through `connect_args`; it needs a pragma on each new connection.
Register it on the engine's sync counterpart:

```python
from sqlalchemy import event


def _enable_wal(dbapi_connection: object, _record: object) -> None:
    cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
    finally:
        cursor.close()
```

and inside `_get_engine`, after construction and only for SQLite:

```python
    engine = create_async_engine(url, echo=False, connect_args=connect_args)
    if _is_sqlite(url):
        # WAL lets the once-per-second job polling read while a write is in flight,
        # rather than each waiting out the other.
        event.listen(engine.sync_engine, "connect", _enable_wal)
    return engine
```

Mypy note: the DBAPI connection is untyped at this boundary. Per the project's no-`Any`
rule, type the parameter as `object` and keep the single `type: ignore[attr-defined]` on
the `.cursor()` call rather than widening the signature.

- [ ] **Step 2: Both tests pass**

```bash
uv run pytest tests/shared/test_database_concurrency.py -v
```

---

## Task 4: Confirm the non-SQLite path is untouched

- [ ] **Step 1: Add a test**

Point `Settings.DATABASE_URL` at `postgresql+asyncpg://user:pass@localhost/db`, call
`_get_engine()`, and assert no `connect` listener was registered and the engine carries
no `timeout` connect-arg. The engine is never connected, so no PostgreSQL server is
needed — construction alone is what is being checked.

- [ ] **Step 2: Run it**

---

## Task 5: Verify the fix against the real failure

- [ ] **Step 1: Full gate**

```bash
uv run poe check
```

- [ ] **Step 2: Manual reproduction**

Hand the command to the user — the project does not run the server from the agent:

Start the API, then bulk-ingest a directory of PDFs while the job list is polling.
Confirm no `database is locked` traceback appears, and that
`sqlite3 data/classiflow.db "PRAGMA journal_mode;"` reports `wal`.

- [ ] **Step 3: Confirm the sidecar files are ignored**

WAL creates `classiflow.db-wal` and `classiflow.db-shm`. Verify `git status` stays clean;
extend the gitignore if it does not.

---

## Not in this plan

Bulk ingest still takes one write lock per file, and content validation still reloads the
SLM per job after an eviction — both are real slowness, neither causes this crash. They
are separate work.
