# Database dialect tuning — design

## Problem

`database/base.py` builds the engine and applies SQLite-specific tuning inline:

```python
connect_args = {"timeout": Settings.SQLITE_BUSY_TIMEOUT_SECONDS} if _is_sqlite(url) else {}
engine = create_async_engine(url, echo=False, connect_args=connect_args)
if _is_sqlite(url):
    event.listen(engine.sync_engine, "connect", _tune_sqlite_connection)
```

Adding a second engine means editing `get_engine` — a function every caller in the
process depends on — and the two `_is_sqlite` branches become a growing conditional.

**What is already fine and must stay fine.** Repositories take `AsyncSession` and know
nothing about the dialect. `get_session` is the only entry point outside this module
(four call sites: `api/dependencies.py`, `injections/production.py`, `scripts/accuracy.py`,
and the tests). No `PRAGMA`, no raw `text()` SQL, and no dialect-specific column types
exist anywhere else in `src/`. Switching to PostgreSQL today is already an env-var change.

**So this is not about decoupling callers — they are decoupled.** It is about
Open/Closed at the one place that is closed today: adding a dialect should add a file,
not edit a shared function.

## Scope

**In:** a seam for per-dialect engine tuning, and moving the SQLite behaviour behind it
unchanged.

**Out:** changing `get_session`, repositories, models, or migrations. No new dialect is
implemented — PostgreSQL appears only as a test double proving the seam works. No
dialect-specific column types or query builders; SQLAlchemy already abstracts those.

## Design

A `database/dialects/` package, one file per engine:

```
database/
├── base.py            engine construction, session factory, get_session
└── dialects/
    ├── __init__.py    re-exports DialectTuning, resolve_tuning
    ├── protocol.py    DialectTuning
    ├── registry.py    _TUNINGS, resolve_tuning, DefaultTuning
    ├── sqlite.py      SqliteTuning
    └── postgres.py    (a future engine lands here — not in this spec)
```

The tree is the documentation: which engines are specialized is visible from the file
list, and adding one means adding a file rather than growing a module. This mirrors how
`enrichment/nodes/` and `classification/nodes/` are already organized — one file per node
rather than one module holding all of them, which CLAUDE.md records as a deliberate
choice for this project's size.

The package holds a Protocol and a registry.

```python
@runtime_checkable
class DialectTuning(Protocol):
    """Per-dialect engine configuration, applied at construction time."""

    def matches(self, url: str) -> bool: ...
    def connect_args(self) -> dict[str, object]: ...
    def on_connect(self, connection: DBAPIConnection) -> None: ...
```

Three methods, chosen because they are the three things SQLAlchemy lets a dialect
influence: which URLs it claims, what goes into `create_async_engine(connect_args=...)`,
and what runs on each new pooled connection.

`SqliteTuning` implements it with today's exact behaviour. `get_engine` becomes:

```python
@lru_cache(maxsize=1)
def get_engine() -> AsyncEngine:
    url = Settings.DATABASE_URL
    tuning = resolve_tuning(url)
    engine = create_async_engine(url, echo=False, connect_args=tuning.connect_args())
    event.listen(engine.sync_engine, "connect", _apply(tuning))
    return engine
```

`resolve_tuning` walks `registry.py`'s tuple and returns the first match, falling back to
`DefaultTuning` — empty `connect_args`, no-op `on_connect` — so an unregistered URL
behaves exactly as an unguarded engine does today. **A missing dialect is not an error:**
SQLAlchemy already supports every engine it ships; tuning is an optional refinement, so
failing closed here would break working databases to enforce a registry nobody needs.

### What Open/Closed does and does not buy here

`get_engine` becomes genuinely closed: adding an engine never touches it, and the
`if _is_sqlite(...)` chain that would otherwise grow disappears.

`registry.py` stays open — a new engine appends one entry to `_TUNINGS`. That is
deliberate. Self-registration through `__init_subclass__` or entry points would remove
the edit, but it makes import order decide whether a dialect exists: forget the import and
tuning silently vanishes, with no error. An explicit tuple is greppable, ordered
(`DefaultTuning` must stay last), and reviewable in a diff.

The distinction that matters is that OCP protects *logic*, not lists. Appending to a
declarative tuple changes no behaviour; editing a conditional does.

### Why a Protocol and not an ABC

The project's `domain/repositories/` package uses `Protocol` for every port
(`IJobRepository`, `IClassificationRecordRepository`). Following that convention keeps one
idiom for "a seam with swappable implementations", and structural typing means a test can
supply a stub without importing a base class.

### Why not a `providers.Factory` in the DI container

`get_engine` is `lru_cache`d and called during `create_app()`, before the container is
wired; `_get_session_factory` depends on it. Routing it through dependency-injector would
invert that order for no gain — the engine is process-wide, not per-request, which is
exactly what `injections/production.py:48` already documents about `db_session`.

## Consequences

**Adding a dialect** becomes: write a class, add it to the registry tuple. `get_engine`
is not edited.

**The conditional disappears.** `_is_sqlite` and its two branches collapse into one
polymorphic call — the Strategy pattern's usual payoff.

**Testing improves.** Today the SQLite pragmas are only reachable by constructing a real
file-backed engine (`tests/shared/test_database_concurrency.py`). Behind this seam, a
stub tuning asserts that `connect_args` reached `create_async_engine` and that
`on_connect` fired, with no file and no PostgreSQL server.

**Cost.** One new module, ~50 lines, plus an indirection between `get_engine` and the
pragmas it runs. A reader tracing "why is WAL on?" now follows one hop.

## Rejected alternatives

**Leave it as is.** Defensible: the deletion test says both branches earn their keep, and
one adapter is a hypothetical seam. Rejected because the user has stated the intent to
support more engines, which converts the hypothetical into a stated requirement — and the
change is small enough that doing it before the second dialect is cheaper than during.

**Subclass `AsyncEngine` per dialect.** Rejected: SQLAlchemy constructs engines through
`create_async_engine`, so a subclass would fight the factory it must call. Composition
over inheritance, and the dialect varies independently of the engine.

**Abstract Factory over the whole persistence layer** (engine + session + repositories per
dialect). Rejected as speculative generality: repositories are already dialect-agnostic,
so the extra families would each have exactly one member.

**Push tuning into `Settings`.** Rejected: settings is a value object read by many
modules; putting `event.listen` behaviour there would give configuration a runtime side
effect and couple it to SQLAlchemy.

**A single flat `dialects.py`.** Two classes and a registry fit in one ~50-line module,
and four files to hold that is more structure than content. Rejected because the flat
file hides what varies: nothing in the directory listing says SQLite is specialized, so a
reader has to open the module to find out, and the second engine turns it into a grab
bag. The package makes the extension point visible at the cost of three small files.

**Self-registering dialects** (`__init_subclass__`, entry points, or auto-import of every
module in the package). Rejected: all three make import order decide whether a dialect is
active, and a forgotten import disables tuning silently rather than loudly. See the
Open/Closed note above.

## Open question

`SQLITE_BUSY_TIMEOUT_SECONDS` lives in `Settings` and is read inside the tuning class. A
second dialect would add `POSTGRES_*` keys beside it, growing a flat namespace with
per-dialect entries. Leaving it flat for now — one dialect is not a naming problem, and
guessing at PostgreSQL's knobs before needing them is what this spec calls speculative
elsewhere.
