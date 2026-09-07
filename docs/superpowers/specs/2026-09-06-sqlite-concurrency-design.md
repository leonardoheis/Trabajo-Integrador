# SQLite concurrency — design

## Problem

Bulk ingest crashes with `sqlite3.OperationalError: database is locked`:

```
File "src/classiflow/services/pipeline/service.py", line 128, in start
    await self._job_repo.create(
sqlalchemy.exc.OperationalError: (sqlite3.OperationalError) database is locked
[SQL: INSERT INTO jobs (job_id, status, filename, ...) VALUES (?, ?, ?, ...)]
```

The failure is not a deadlock and not a bug in the repository layer. It is the SQLite
default configuration meeting a workload the application always generates.

## Why it happens

`_get_engine()` (`src/classiflow/database/base.py:21`) builds the engine with no
`connect_args`:

```python
return create_async_engine(Settings.DATABASE_URL, echo=False)
```

Two SQLite defaults follow from that:

| Default | Value | Consequence |
|---|---|---|
| `busy_timeout` | `0` ms | A writer that finds the database locked raises immediately instead of waiting. |
| `journal_mode` | `delete` (rollback journal) | A write takes an exclusive lock over the whole file; concurrent readers block it and it blocks them. |

The workload that collides with those defaults:

- `POST /pipeline/ingest-bulk` loops over the uploaded files, calling `pipeline.start()`
  once per file (`src/classiflow/api/routes/pipeline/endpoints.py:75`). Each call flushes
  a `jobs` INSERT.
- Background pipeline jobs write `document_steps` and `audit` rows throughout their run.
- The frontend polls `GET /pipeline/jobs?status=running` roughly once per second — visible
  in the logs as a continuous stream of requests. Under a rollback journal these reads
  contend with the writes.

Any two of those overlapping is enough. With `busy_timeout=0` the loser does not retry.

## Decision

Two changes, both confined to `_get_engine()`.

### 1. `busy_timeout` (required)

Set aiosqlite's `timeout` so a blocked writer waits instead of raising. 30 seconds is
chosen to comfortably exceed the longest single write this application performs; the
value is a ceiling on waiting, not an expected latency — under normal load writers
acquire the lock in milliseconds.

This alone stops the crash.

### 2. WAL journal mode (recommended)

`PRAGMA journal_mode=WAL` lets readers proceed during a write. Given the once-per-second
job polling, this removes most of the contention rather than merely waiting it out.

WAL is a persistent property of the database file, not a per-connection setting, but the
pragma must still be issued on a connection. It is applied via a SQLAlchemy `connect`
event listener, since it cannot be expressed as a `connect_arg`.

Trade-offs accepted:

- WAL creates `-wal` and `-shm` sidecar files next to the database. Both are already
  covered by the `data/` gitignore entry.
- WAL requires the database to live on a filesystem supporting shared memory. Local
  development and the target deployment are both ordinary local disks, so this holds.
- `PRAGMA synchronous` is deliberately left at its default. Lowering it to `NORMAL` is a
  common WAL companion tweak, but it weakens durability on power loss and this system
  records an audit log that is meant to be authoritative.

### Applies only to SQLite

Both changes are gated on the URL scheme. `Settings.DATABASE_URL` is documented as
supporting `postgresql+asyncpg://` with no code changes (`tasks/plan.md:523`), and
passing a `timeout` connect-arg or a SQLite pragma to asyncpg would fail.

## Explicitly out of scope

- **Serializing writes behind an application-level lock.** SQLite's own locking is what
  `busy_timeout` makes usable; adding a second layer above it duplicates the mechanism.
- **Migrating to PostgreSQL.** The correct long-term answer for real concurrency, but a
  deployment decision, not a fix for this crash.
- **Batching the `ingest-bulk` inserts into one transaction.** It would reduce the number
  of write locks taken, but background jobs still write concurrently, so it does not
  remove the need for a busy timeout. Worth revisiting on its own merits.
- **Retry-on-locked in the repository layer.** `busy_timeout` is the same thing
  implemented inside SQLite, without partially-applied transactions.

## Acceptance

- Bulk-ingesting a directory of PDFs while background jobs run does not raise
  `database is locked`.
- `PRAGMA journal_mode` reports `wal` on the application database.
- A non-SQLite `DATABASE_URL` receives neither the timeout connect-arg nor the pragma.
- `uv run poe check` passes.
